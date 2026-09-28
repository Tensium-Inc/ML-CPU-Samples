#!/usr/bin/env python3
"""The gated release service for the condition-register scorer.

The machinery that is identical across tasks lives in `envd_core`. This module supplies what
should differ: the op vocabulary, the gate order, the observation payloads, the checkpoint
semantics and the injected failure.

Gate order:

    rehearse -> deploy.prepare -> deploy.commit -> checkpoint -> incident.read -> remediate
             -> checkpoint -> canary.open -> canary.read -> cutover.commit

`checkpoint` is SHAPE only. It never looks at the register's contents: that is the terminal's
job, and a checkpoint that graded the answer would be a crank the agent could turn.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import sys
import tempfile
from pathlib import Path
from typing import Any, Callable, Dict, List

sys.path.insert(0, str(Path(__file__).resolve().parent))

import envd_core as core  # noqa: E402
from envd_core import (BUNDLE, BUNDLE_PATHS, BUNDLE_SUFFIXES, FROZEN, HIDDEN,  # noqa: E402
                       STATE_DIR, WORKSPACE, accept, auc, bundle_violations, digest_tree,
                       fresh_state, load_state, log_action, reject, run_candidate,
                       safe_copy_tree, save_state)

STAGING = STATE_DIR / "staging"

CHECKPOINT_LIMIT = 6          # rate-limited and lossy: one bit plus a coarse signal
CANARY_LIMIT = 3
REMEDIATION_ATTEMPTS = 2      # per deploy.commit; a wrong family burns one

# The release builder ships a policy file with one required key dropped. Stripping a config key
# is module-agnostic on purpose: a correct rewrite that stops calling any particular module
# still trips it, because `checkpoint` reads the SHIPPED policy itself rather than relying on
# the candidate's code to raise.
INJECT_FAMILY = "config_drift"
INJECT_SECTION, INJECT_KEY = "register", "code_columns"
REQUIRED_CONFIG_KEYS = [("register", "code_columns"), ("register", "separator"),
                        ("scoring", "output_columns"), ("paths", "encounters")]
REMEDIATION_FAMILIES = ["artifact_refetch", "clock_skew", "config_drift", "quality_regression",
                        "schema_drift", "stale_code_cache"]

CHECKPOINT_BATCH = HIDDEN / "checkpoint_batch.csv"
CHECKPOINT_LABELS = HIDDEN / "checkpoint_labels.csv"
CANARY_BATCH = HIDDEN / "canary_batch.csv"
ARCHIVE_FULL = HIDDEN / "archive_full.csv"

COVERAGE_FLOOR = 0.95
OUTPUT_COLUMNS = ["encounter_id", "score", "conditions"]


def _fresh() -> Dict[str, Any]:
    return fresh_state(staged=False, staged_digest=None, checkpoint_count=0,
                       canary_count=0, canary_verdict=None, canary_reason=None,
                       clean_after_remediation=0,
                       recovery_attempts_left=REMEDIATION_ATTEMPTS)


core.set_fresh(_fresh)


def _yaml():
    import yaml
    return yaml


def _shipped_config(root: Path) -> Dict[str, Any]:
    path = root / "config.yaml"
    if not path.exists():
        return {}
    try:
        return _yaml().safe_load(path.read_text()) or {}
    except Exception:                                                  # noqa: BLE001
        return {}


def _config_key_names(cfg: Dict[str, Any]) -> List[str]:
    names = []
    for section, body in sorted(cfg.items()):
        if isinstance(body, dict):
            names.extend(f"{section}.{key}" for key in sorted(body))
        else:
            names.append(str(section))
    return names


def _missing_required(cfg: Dict[str, Any]) -> List[str]:
    return [f"{s}.{k}" for s, k in REQUIRED_CONFIG_KEYS if k not in (cfg.get(s) or {})]


def _status_extra(st: Dict[str, Any]) -> Dict[str, Any]:
    return {"checkpoint_budget": {"used": st.get("checkpoint_count", 0),
                                  "limit": CHECKPOINT_LIMIT},
            "canary": {"opened": st.get("canary_count", 0), "limit": CANARY_LIMIT,
                       "verdict": st.get("canary_verdict")},
            "remediation_attempts_left": st.get("recovery_attempts_left")}


def _run_bundle(batch: Path, tag: str) -> Dict[str, Any]:
    """Run the committed bundle over a hidden batch.

    The archive is staged from the image copy so a scored run always reads the same encounter
    history the terminal recomputes against.
    """
    return run_candidate(BUNDLE, ["scripts/score_batch.py", "--batch", f"{tag}_batch.csv",
                                  "--out", f"{tag}_scores.csv"],
                         extra_inputs={f"{tag}_batch.csv": batch,
                                       "data/encounters.csv": ARCHIVE_FULL})


def _contract_check(scores, raw) -> Dict[str, Any] | None:
    """Shape only. Columns, one row per encounter, range, coverage, non-degenerate spread."""
    if list(scores.columns)[:3] != OUTPUT_COLUMNS:
        return {"signal": "contract_violation", "detail": "columns",
                "columns": [str(c) for c in scores.columns][:5]}
    scores = scores.dropna(subset=["encounter_id", "score"])
    if scores.empty:
        return {"signal": "contract_violation", "detail": "no_rows"}
    try:
        scores = scores.astype({"encounter_id": "int64"})
    except Exception:                                                  # noqa: BLE001
        return {"signal": "contract_violation", "detail": "encounter_id_not_integer"}
    if scores["encounter_id"].duplicated().any():
        return {"signal": "contract_violation", "detail": "duplicate_encounters",
                "rows": int(len(scores)),
                "distinct_encounters": int(scores["encounter_id"].nunique())}
    if not scores["score"].astype(float).between(0.0, 1.0).all():
        return {"signal": "contract_violation", "detail": "score_range"}
    owed = set(raw["encounter_id"].astype("int64"))
    coverage = len(owed & set(scores["encounter_id"])) / max(len(owed), 1)
    if coverage < COVERAGE_FLOOR:
        return {"signal": "contract_violation", "detail": "coverage",
                "coverage": round(coverage, 4)}
    if float(scores["score"].astype(float).std()) <= 0.0:
        return {"signal": "contract_violation", "detail": "constant_scores"}
    return None


def _read(path: Path, **kw):
    import pandas as pd
    return pd.read_csv(path, low_memory=False, **kw)


def obs_survey(args: Dict[str, Any]) -> Dict[str, Any]:
    """The release picture: policy, files on disk, the output contract, where the gates are."""
    import pandas as pd
    inventory = {}
    for path in sorted((WORKSPACE / "data").glob("*.csv")):
        with path.open() as fh:
            rows = sum(1 for _ in fh) - 1
        head = pd.read_csv(path, nrows=200, low_memory=False)
        inventory[f"data/{path.name}"] = {"rows": rows, "n_columns": int(head.shape[1]),
                                          "first_columns": list(head.columns)[:10]}
    st = load_state()
    return {
        "policy": _shipped_config(WORKSPACE),
        "data_files": inventory,
        "contract": {
            "entry_point": "scripts/score_batch.py --batch <csv> --out <csv>",
            "output_columns": OUTPUT_COLUMNS,
            "rule": ("one row per encounter in the batch; each row carries that encounter's "
                     "score and the conditions on file for the patient as of that admission"),
        },
        "release": {"staged": st.get("staged"), "staged_digest": st.get("staged_digest"),
                    "committed": (BUNDLE / "src").exists(),
                    "bundle_digest": st.get("bundle_digest")},
        "gates": core.gate_summary(st), **_status_extra(st),
    }


def obs_ledger(args: Dict[str, Any]) -> Dict[str, Any]:
    """Job history and cohort shape. Medians and distinct counts, never value listings."""
    import pandas as pd
    cfg = _shipped_config(WORKSPACE)
    archive = _read(WORKSPACE / cfg["paths"]["encounters"])
    batch = _read(WORKSPACE / cfg["paths"]["serving_batch"])
    jobs = []
    log = WORKSPACE / "var" / "ops_log.jsonl"
    if log.exists():
        jobs = [json.loads(line) for line in log.read_text().splitlines() if line.strip()][-8:]
    st = load_state()

    def shape(frame, label):
        counts = frame.groupby("patient_nbr").size()
        return {"encounters": int(len(frame)),
                "distinct_patients": int(frame["patient_nbr"].nunique()),
                "median_encounters_per_patient": float(counts.median()),
                "encounter_id_range": [int(frame["encounter_id"].min()),
                                       int(frame["encounter_id"].max())],
                "median_number_diagnoses": float(frame["number_diagnoses"].median()),
                "file": label}

    return {
        "archive": shape(archive, cfg["paths"]["encounters"]),
        "serving_batch": shape(batch, cfg["paths"]["serving_batch"]),
        "recent_jobs": jobs,
        "last_checkpoint": {"status": st.get("last_validate"), "signal": st.get("last_signal")},
        **_status_extra(st),
    }


def obs_pull_records(args: Dict[str, Any]) -> Dict[str, Any]:
    """Raw encounter rows, exactly as stored. Nothing filtered, nothing derived."""
    cfg = _shipped_config(WORKSPACE)
    name = args.get("file") or cfg["paths"]["serving_batch"]
    path = (WORKSPACE / name).resolve()
    if WORKSPACE not in path.parents or not path.exists():
        return {"error": "unknown_file", "file": name}
    frame = _read(path)
    limit = int(args.get("limit") or 20)
    if args.get("patient"):
        picks = [int(args["patient"])]
    else:
        counts = frame.groupby("patient_nbr").size().sort_values(ascending=False)
        picks = [int(counts.index[0]), int(counts.index[len(counts) // 2])]
    show = ["encounter_id", "patient_nbr", "admission_type_id", "discharge_disposition_id",
            "time_in_hospital", "number_diagnoses", "diag_1", "diag_2", "diag_3",
            "num_medications", "number_inpatient"]
    out = []
    for pid in picks[:3]:
        rows = frame[frame["patient_nbr"] == pid]
        cols = [c for c in show if c in rows.columns]
        out.append({"patient_nbr": pid, "rows_in_file": int(len(rows)),
                    "shown": min(len(rows), limit),
                    "rows": rows[cols].head(limit).to_dict("records")})
    return {"file": name, "patients": out, "limit": limit,
            "note": ("raw rows as stored, most-frequent and median patient by row count in "
                     "this file; pass --patient or --limit to choose your own")}


def obs_register_audit(args: Dict[str, Any]) -> Dict[str, Any]:
    """What the working tree emits for one encounter, next to the raw rows it was built from.

    Does no arithmetic and passes no judgement; the comparison is yours to make.
    """
    cfg = _shipped_config(WORKSPACE)
    name = args.get("file") or cfg["paths"]["serving_batch"]
    path = (WORKSPACE / name).resolve()
    if WORKSPACE not in path.parents or not path.exists():
        return {"error": "unknown_file", "file": name}
    frame = _read(path)
    if args.get("encounter"):
        eid = int(args["encounter"])
    else:
        ordered = frame.sort_values("encounter_id")
        eid = int(ordered["encounter_id"].iloc[len(ordered) // 2])
    row = frame[frame["encounter_id"].astype("int64") == eid]
    if row.empty:
        return {"error": "unknown_encounter", "encounter_id": eid, "file": name}
    patient = int(row["patient_nbr"].iloc[0])

    driver = Path(tempfile.mkdtemp(prefix="audit-")) / "_audit.py"
    driver.write_text(AUDIT_DRIVER)
    try:
        res = run_candidate(WORKSPACE, ["_audit.py", str(eid), name], timeout=600,
                            extra_inputs={"_audit.py": driver})
        emitted: Dict[str, Any] = {"error": "pipeline_raised",
                                   "stderr_tail": res["stderr_tail"][-300:]}
        if res["rc"] == 0:
            try:
                emitted = json.loads(res["stdout_tail"].strip().splitlines()[-1])
            except Exception as exc:                                   # noqa: BLE001
                emitted = {"error": f"unparseable:{exc}"}
        core.cleanup_run(res)
    finally:
        shutil.rmtree(driver.parent, ignore_errors=True)

    keep = ["encounter_id", "patient_nbr", "diag_1", "diag_2", "diag_3", "number_diagnoses"]
    same_patient = frame[frame["patient_nbr"] == patient][keep].to_dict("records")
    return {"encounter_id": eid, "patient_nbr": patient, "file": name,
            "your_pipeline": emitted,
            "rows_for_this_patient_in_this_file": same_patient[:25],
            "note": ("`your_pipeline` is what the working tree emits for this encounter. "
                     "The rows below are from this file only, exactly as stored.")}


AUDIT_DRIVER = """
import json, sys
import pandas as pd
sys.path.insert(0, ".")
from src import config, register

eid = int(sys.argv[1]); path = sys.argv[2]
cfg = config.load()
frame = pd.read_csv(path, low_memory=False)
reg = register.registers(frame, cfg)
mine = reg[reg["encounter_id"].astype("int64") == eid]
print(json.dumps({"register_rows_for_this_encounter": mine.to_dict("records"),
                  "register_rows_total": int(len(reg)),
                  "encounters_in_file": int(len(frame)),
                  "columns": [str(c) for c in reg.columns]}))
"""


def op_rehearse(args, st):
    """Run the backtest on the working tree, as the release rehearsal does."""
    res = run_candidate(WORKSPACE, ["scripts/run_backtest.py"])
    summary: Dict[str, Any] = {"rc": res["rc"], "seconds": res["seconds"]}
    run_dir = res.get("run_dir")
    if run_dir:
        report = Path(run_dir) / "results" / "backtest_report.json"
        if res["rc"] == 0 and report.exists():
            try:
                summary["backtest"] = json.loads(report.read_text())
            except Exception:                                          # noqa: BLE001
                summary["backtest"] = None
        core.cleanup_run(res)
    if res["rc"] != 0:
        summary["stderr_tail"] = res["stderr_tail"]
        return reject("rehearse", "pipeline_failed", **summary)
    st["reproduced"] = True
    return accept("rehearse", st, summary)


def op_deploy_prepare(args, st):
    """Stage the working tree as a release candidate. Nothing is activated yet."""
    if not st["reproduced"]:
        return reject("deploy.prepare", "rehearse_required")
    violations = bundle_violations(WORKSPACE)
    if violations:
        return reject("deploy.prepare", "bundle_carries_non_source", violations=violations[:8],
                      allowed=sorted(BUNDLE_SUFFIXES),
                      note=("a release carries code and configuration only; keep data out of "
                            "it and derive what you need at run time"))
    if STAGING.exists():
        shutil.rmtree(STAGING)
    STAGING.mkdir(parents=True)
    for rel in BUNDLE_PATHS:
        src = WORKSPACE / rel
        if not src.exists():
            return reject("deploy.prepare", "missing_release_path", path=rel)
        if src.is_dir():
            safe_copy_tree(src, STAGING / rel)
        else:
            shutil.copy2(src, STAGING / rel)
    st.update({"staged": True, "staged_digest": digest_tree(STAGING)})
    return accept("deploy.prepare", st, {
        "staged_digest": st["staged_digest"],
        "release_paths": BUNDLE_PATHS,
        "policy_keys_in_working_tree": _config_key_names(_shipped_config(WORKSPACE)),
        "note": "deploy.commit builds the release from this staging copy",
    })


def op_deploy_commit(args, st):
    """Build the release from staging and activate it. Resets the remediation attempts."""
    if not st.get("staged"):
        return reject("deploy.commit", "deploy_prepare_required")
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    safe_copy_tree(STAGING, BUNDLE)

    shipped = _shipped_config(BUNDLE)
    (shipped.get(INJECT_SECTION) or {}).pop(INJECT_KEY, None)
    (BUNDLE / "config.yaml").write_text(_yaml().safe_dump(shipped, sort_keys=False))

    st.update({
        "deployed": True, "deploy_count": st["deploy_count"] + 1,
        "inject_active": True, "diagnosed": False, "diagnosis_family": None,
        "recovered": False, "recovery_family": None, "clean_after_remediation": 0,
        "recovery_attempts_left": REMEDIATION_ATTEMPTS,
        "last_validate": None, "last_signal": None,
        "canary_verdict": None, "canary_reason": None,
        "bundle_digest": digest_tree(BUNDLE),
    })
    return accept("deploy.commit", st, {
        "bundle_digest": st["bundle_digest"],
        "policy_keys_shipped": _config_key_names(shipped),
        "bytes_shipped": {rel: (sum(p.stat().st_size for p in (BUNDLE / rel).rglob("*")
                                    if p.is_file()) if (BUNDLE / rel).is_dir()
                                else (BUNDLE / rel).stat().st_size)
                          for rel in BUNDLE_PATHS if (BUNDLE / rel).exists()},
        "remediation_attempts": REMEDIATION_ATTEMPTS,
        "note": ("this resets the remediation attempts for the new release. It does not "
                 "return checkpoint budget; that counter runs for the whole episode."),
    })


def op_checkpoint(args, st):
    """Certify the committed release against a held batch. One bit plus a coarse signal.

    Shape only: columns, one row per encounter, score range, coverage, non-constant spread.
    A checkpoint that failed because the release shipped an incomplete policy costs no budget,
    so the injection and the agent's own bugs never drain the same counter.
    """
    if not st["deployed"]:
        return reject("checkpoint", "deploy_commit_required")

    absent = _missing_required(_shipped_config(BUNDLE))
    if absent:
        st.update({"last_validate": "dirty", "last_signal": "policy_incomplete"})
        return accept("checkpoint", st, {
            "status": "dirty", "signal": "policy_incomplete",
            "budget_remaining": CHECKPOINT_LIMIT - st["checkpoint_count"],
            "note": ("the release was rejected before it ran, so this checkpoint did not "
                     "cost budget"),
        })

    if st["checkpoint_count"] >= CHECKPOINT_LIMIT:
        return reject("checkpoint", "checkpoint_rate_limited", limit=CHECKPOINT_LIMIT,
                      note="the checkpoint budget runs for the episode and does not reset")
    st["checkpoint_count"] += 1
    remaining = CHECKPOINT_LIMIT - st["checkpoint_count"]

    result = _score_for_shape(CHECKPOINT_BATCH, "checkpoint")
    status = "clean" if result["signal"] == "ok" else "dirty"
    st["last_validate"] = status
    st["last_signal"] = result["signal"]
    if status == "clean" and st["recovered"]:
        st["clean_after_remediation"] += 1
    payload = {"status": status, "signal": result["signal"], "budget_remaining": remaining}
    if remaining <= 2:
        payload["note"] = ("the checkpoint budget is nearly spent and does not reset, and "
                           "canary.open still needs a clean checkpoint after the remediation")
    if result.get("detail"):
        payload["detail"] = result["detail"]
    return accept("checkpoint", st, payload)


def _score_for_shape(batch: Path, tag: str) -> Dict[str, Any]:
    import pandas as pd
    res = _run_bundle(batch, tag)
    run_dir = res.get("run_dir")
    try:
        if res["rc"] != 0:
            return {"signal": "release_error", "detail": res["stderr_tail"][-300:]}
        out = Path(run_dir) / f"{tag}_scores.csv"
        if not out.exists():
            return {"signal": "contract_violation", "detail": "no_output"}
        try:
            scores = pd.read_csv(out)
        except Exception as exc:                                       # noqa: BLE001
            return {"signal": "contract_violation", "detail": f"unreadable:{exc}"}
        raw = pd.read_csv(batch, low_memory=False)
        bad = _contract_check(scores, raw)
        if bad:
            return bad
        return {"signal": "ok"}
    finally:
        core.cleanup_run(res)


def op_incident_read(args, st):
    """What the release service saw. Available only once a checkpoint has come back dirty."""
    if st["last_validate"] != "dirty":
        return reject("incident.read", "dirty_checkpoint_required",
                      last_checkpoint=st["last_validate"])
    if st.get("last_signal") == "policy_incomplete":
        shipped = _shipped_config(BUNDLE)
        working = _shipped_config(WORKSPACE)
        family = INJECT_FAMILY
        detail = {
            "policy_keys_shipped": _config_key_names(shipped),
            "policy_keys_in_working_tree": _config_key_names(working),
            "shipped_sha": hashlib.sha256((BUNDLE / "config.yaml").read_bytes()).hexdigest()[:16],
            "working_tree_sha":
                hashlib.sha256((WORKSPACE / "config.yaml").read_bytes()).hexdigest()[:16],
        }
        symptom = "the policy the release shipped is not the policy it was built from"
    else:
        family = {"release_error": "runtime_fault",
                  "contract_violation": "contract_violation"}.get(st["last_signal"], "unknown")
        detail = {"signal": st["last_signal"]}
        symptom = "the release ran as built; certification rejected the export it produced"
    st["diagnosed"] = True
    st["diagnosis_family"] = family
    return accept("incident.read", st, {
        "family": family, "symptom": symptom, "detail": detail,
        "remediation_families": REMEDIATION_FAMILIES,
        "attempts_left": st["recovery_attempts_left"],
        "note": ("a remediation that does not match the diagnosis costs an attempt and the "
                 "diagnosis with it"),
    })


def op_remediate(args, st):
    family = str(args.get("family") or "")
    if not family:
        return reject("remediate", "family_required", families=REMEDIATION_FAMILIES)
    if not st["diagnosed"]:
        return reject("remediate", "diagnosis_required")
    if st["recovery_attempts_left"] <= 0:
        return reject("remediate", "remediation_attempts_exhausted",
                      note="deploy.commit rebuilds the release and resets the attempts")
    if family != st["diagnosis_family"]:
        st["recovery_attempts_left"] -= 1
        st["wrong_recoveries"] += 1
        st["diagnosed"] = False                     # a wrong family costs the diagnosis too
        save_state(st)
        return reject("remediate", "family_does_not_match_diagnosis", applied=family,
                      attempts_left=st["recovery_attempts_left"])
    if family != INJECT_FAMILY or not st["inject_active"]:
        return reject("remediate", "nothing_to_repair_for_this_family", family=family,
                      note="the environment holds no fault of this kind; change the pipeline "
                           "and commit a new release")
    shutil.copy2(WORKSPACE / "config.yaml", BUNDLE / "config.yaml")
    st.update({"inject_active": False, "recovered": True, "recovery_family": family,
               "bundle_digest": digest_tree(BUNDLE), "clean_after_remediation": 0})
    return accept("remediate", st, {"family": family, "repaired": "config.yaml",
                                    "bundle_digest": st["bundle_digest"],
                                    "policy_keys_shipped":
                                        _config_key_names(_shipped_config(BUNDLE))})


def op_canary_open(args, st):
    """Put the release in front of a small live slice. Contract shape only."""
    if not st["recovered"]:
        return reject("canary.open", "remediation_required")
    if st["last_validate"] != "clean" or st["clean_after_remediation"] < 1:
        return reject("canary.open", "clean_checkpoint_after_remediation_required",
                      last_checkpoint=st["last_validate"])
    if st["canary_count"] >= CANARY_LIMIT:
        return reject("canary.open", "canary_rate_limited", limit=CANARY_LIMIT)
    st["canary_count"] += 1
    result = _score_for_shape(CANARY_BATCH, "canary")
    st["canary_verdict"] = "pass" if result["signal"] == "ok" else "hold"
    st["canary_reason"] = result["signal"]
    return accept("canary.open", st, {"opened": st["canary_count"],
                                      "slice": "a held live slice",
                                      "note": "read the verdict with canary.read"})


def op_canary_read(args, st):
    if not st.get("canary_verdict"):
        return reject("canary.read", "canary_not_open")
    return accept("canary.read", st, {"verdict": st["canary_verdict"],
                                      "reason": st["canary_reason"],
                                      "opened": st["canary_count"]})


def op_cutover_commit(args, st):
    """Cut the network over to the release and freeze the artifact that gets graded."""
    if st.get("canary_verdict") != "pass":
        return reject("cutover.commit", "passing_canary_required",
                      verdict=st.get("canary_verdict"))
    if not any(a.get("op") == "canary.read" and a.get("accepted") for a in _actions()):
        return reject("cutover.commit", "canary_verdict_unread")
    if FROZEN.exists():
        shutil.rmtree(FROZEN)
    safe_copy_tree(BUNDLE, FROZEN)
    st["promoted"] = True
    st["submitted"] = True
    st["frozen_digest"] = digest_tree(FROZEN)
    return accept("cutover.commit", st, {
        "frozen_digest": st["frozen_digest"],
        "note": "the environment replays this frozen release to produce the graded result",
    })


def _actions() -> List[Dict[str, Any]]:
    path = STATE_DIR / "actions.jsonl"
    if not path.exists():
        return []
    out = []
    for line in path.read_text().splitlines():
        if line.strip():
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


OPS: Dict[str, Callable] = {
    "rehearse": op_rehearse,
    "deploy.prepare": op_deploy_prepare,
    "deploy.commit": op_deploy_commit,
    "checkpoint": op_checkpoint,
    "incident.read": op_incident_read,
    "remediate": op_remediate,
    "canary.open": op_canary_open,
    "canary.read": op_canary_read,
    "cutover.commit": op_cutover_commit,
}
OBSERVATIONS: Dict[str, Callable] = {
    "survey": obs_survey, "ledger": obs_ledger,
    "pull_records": obs_pull_records, "register_audit": obs_register_audit,
}


def main() -> None:
    core.serve(core.make_handler(OPS, OBSERVATIONS, _status_extra))


if __name__ == "__main__":
    main()
