#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
import os
import pwd
import shutil
import socket
import socketserver
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# --------------------------------------------------------------------------- config
DEV = os.environ.get("ENVD_DEV") == "1"
WORKSPACE = Path(os.environ.get("WORKSPACE_DIR", "/workspace/target")).resolve()
STATE_DIR = Path(os.environ.get("ENVD_STATE", "/var/lib/envstate")).resolve()
HIDDEN = Path(os.environ.get("ENVD_HIDDEN", "/opt/task/hidden")).resolve()
SOCK = Path(os.environ.get("ENVD_SOCK", "/run/envd/envd.sock"))
RUN_USER = os.environ.get("ENVD_RUN_USER", "envrun")

ACTIONS = STATE_DIR / "actions.jsonl"
STATE = STATE_DIR / "state.json"
BUNDLE = STATE_DIR / "bundle"
FROZEN = STATE_DIR / "frozen"

BUNDLE_PATHS = ["src", "scripts", "config.yaml"]
BUNDLE_SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
BUNDLE_MAX_FILE_BYTES = 64 * 1024        # generous for source; far under a vendored table
BUNDLE_MAX_TOTAL_BYTES = 512 * 1024

VALIDATE_LIMIT = 4           # rate-limited, lossy: confirms a hypothesis, cannot enumerate
RECOVERY_ATTEMPTS = 2        # per deploy cycle; a wrong family burns one (not a free retry)
RUN_TIMEOUT = 900

INJECT_FAMILY = "stale_config"
INJECT_TARGET = "config.yaml"
INJECT_KEY = "threshold"
RECOVERY_FAMILIES = ["stale_config", "partial_rollout", "clock_skew", "quality_regression"]

SANITY_BATCH = HIDDEN / "sanity_batch.csv"
SANITY_LABELS = HIDDEN / "sanity_labels.csv"
SANITY_AUC_FLOOR = 0.85          # anti-degeneracy guard; an honest pipeline sits near 0.95
SANITY_COVERAGE_FLOOR = 0.95


# --------------------------------------------------------------------------- state
def _fresh() -> Dict[str, Any]:
    return {
        "reproduced": False, "deployed": False, "deploy_count": 0,
        "validate_count": 0, "last_validate": None, "last_signal": None,
        "clean_after_recovery": 0,
        "diagnosed": False, "diagnosis_family": None,
        "inject_active": False, "recovered": False, "recovery_family": None,
        "recovery_attempts_left": RECOVERY_ATTEMPTS, "wrong_recoveries": 0,
        "promoted": False, "submitted": False,
        "bundle_digest": None, "frozen_digest": None,
        "gate_log": [], "obs_count": 0,
    }


def load_state() -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE.exists():
        save_state(_fresh())
    return json.loads(STATE.read_text())


def save_state(state: Dict[str, Any]) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE)


def log_action(op: str, payload: Dict[str, Any], accepted: bool, op_class: str) -> None:
    rec = {"seq": _next_seq(), "ts": round(time.time(), 3), "op": op,
           "op_class": op_class, "accepted": accepted, "payload": payload}
    with ACTIONS.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def _next_seq() -> int:
    if not ACTIONS.exists():
        return 1
    return sum(1 for line in ACTIONS.read_text().splitlines() if line.strip()) + 1


def digest_tree(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


# --------------------------------------------------------------------------- sandboxed runs
def _run_uid() -> Tuple[int, int]:
    if DEV:
        return os.getuid(), os.getgid()
    ent = pwd.getpwnam(RUN_USER)
    return ent.pw_uid, ent.pw_gid


def safe_copy_tree(src: Path, dst: Path) -> List[str]:
    dropped: List[str] = []
    src = src.resolve()
    dst.mkdir(parents=True, exist_ok=True)
    for path in sorted(src.rglob("*")):
        rel = path.relative_to(src)
        if "__pycache__" in rel.parts or rel.parts[:1] == (".git",):
            continue
        target = dst / rel
        if path.is_symlink():
            try:
                resolved = path.resolve(strict=True)
                resolved.relative_to(src)
            except (OSError, ValueError):
                dropped.append(rel.as_posix())
                continue
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "rb", opener=lambda p, f: os.open(p, f | os.O_NOFOLLOW)) as fh:
                target.write_bytes(fh.read())
    return dropped


def chown_tree(root: Path, uid: int, gid: int) -> None:
    if DEV:
        return
    os.chown(root, uid, gid)
    for p in root.rglob("*"):
        os.chown(p, uid, gid, follow_symlinks=False)


def run_candidate(code_root: Path, argv: List[str], timeout: int = RUN_TIMEOUT,
                  extra_inputs: Dict[str, Path] | None = None) -> Dict[str, Any]:
    uid, gid = _run_uid()
    tmp = Path(tempfile.mkdtemp(prefix="envrun-"))
    run = tmp / "run"
    try:
        safe_copy_tree(WORKSPACE, run)                     # full agent environment
        for rel in BUNDLE_PATHS:                            # overlay the artifact under test
            s, d = code_root / rel, run / rel
            if not s.exists():
                continue
            if d.is_dir():
                shutil.rmtree(d)
            elif d.exists():
                d.unlink()
            if s.is_dir():
                safe_copy_tree(s, d)
            else:
                shutil.copy2(s, d)
        for name, path in (extra_inputs or {}).items():     # hidden INPUTS only, never labels
            dest = run / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        os.chmod(tmp, 0o755)
        os.chmod(run, 0o700)
        chown_tree(run, uid, gid)

        # A private scratch dir inside the (0700, envrun-owned) run tree, so the default temp
        # path for candidate code is not the world-readable /tmp the agent can also read. See
        # the residual noted in DEV_NOTES: this redirects the default, it cannot stop code that
        # writes to an absolute path, so anything envrun leaves in /tmp is scrubbed after.
        scratch = run / ".scratch"
        scratch.mkdir(exist_ok=True)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(run),
               "TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch),
               "PYTHONDONTWRITEBYTECODE": "1", "OMP_NUM_THREADS": "1",
               "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1", "PYTHONHASHSEED": "0"}
        if DEV:      # dev box: the interpreter's libraries are not on the system path
            env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
            env["HOME"] = os.environ.get("HOME", str(run))
        kwargs: Dict[str, Any] = {}
        if not DEV:
            kwargs.update(user=uid, group=gid)
        started = time.time()
        proc = subprocess.run([sys.executable, *argv], cwd=str(run), env=env,
                              capture_output=True, text=True, timeout=timeout, **kwargs)
        out = {"rc": proc.returncode, "seconds": round(time.time() - started, 2),
               "stderr_tail": proc.stderr[-600:], "stdout_tail": proc.stdout[-600:],
               "run_dir": str(run)}
        out["_keep"] = tmp
        _scrub_world_tmp(uid)
        return out
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp, ignore_errors=True)
        return {"rc": -9, "seconds": timeout, "stderr_tail": "timeout", "stdout_tail": "", "run_dir": None}
    except Exception as exc:                                # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        return {"rc": -1, "seconds": 0.0, "stderr_tail": f"harness_error:{exc}", "stdout_tail": "", "run_dir": None}


def _scrub_world_tmp(uid: int) -> None:
    if DEV:
        return
    for entry in Path("/tmp").iterdir():
        try:
            if entry.stat().st_uid != uid:
                continue
            if entry.is_dir() and not entry.is_symlink():
                shutil.rmtree(entry, ignore_errors=True)
            else:
                entry.unlink(missing_ok=True)
        except OSError:
            continue


def auc(labels: List[int], scores: List[float]) -> float:
    pairs = sorted(zip(scores, labels))
    ranks: Dict[int, float] = {}
    i = 0
    while i < len(pairs):
        j = i
        while j + 1 < len(pairs) and pairs[j + 1][0] == pairs[i][0]:
            j += 1
        avg = (i + j) / 2.0 + 1.0
        for k in range(i, j + 1):
            ranks[k] = avg
        i = j + 1
    pos = sum(1 for _, y in pairs if y == 1)
    neg = len(pairs) - pos
    if pos == 0 or neg == 0:
        return float("nan")
    s = sum(ranks[k] for k, (_, y) in enumerate(pairs) if y == 1)
    return (s - pos * (pos + 1) / 2.0) / (pos * neg)


# --------------------------------------------------------------------------- observations
def _read_log(path: Path, **kw):
    import pandas as pd
    frame = pd.read_csv(path, low_memory=False, **kw)
    if "timestamp" in frame.columns:
        frame["timestamp"] = pd.to_datetime(frame["timestamp"])
    return frame


def obs_inspect(args: Dict[str, Any]) -> Dict[str, Any]:
    import pandas as pd
    import yaml
    cfg = yaml.safe_load((WORKSPACE / "config.yaml").read_text())
    data = {}
    for f in sorted((WORKSPACE / "data").glob("*.csv")):
        with f.open() as fh:
            rows = sum(1 for _ in fh) - 1
        head = pd.read_csv(f, nrows=200, low_memory=False)
        span = None
        if "timestamp" in head.columns:
            full = pd.read_csv(f, usecols=["timestamp"])
            span = [str(full.timestamp.min()), str(full.timestamp.max())]
        data[f"data/{f.name}"] = {"rows": rows, "columns": list(head.columns), "span": span}
    return {
        "config": cfg,
        "data_files": data,
        "scoring_contract": {
            "entry_point": "scripts/score_hours.py --batch <csv> --out <csv>",
            "output_columns": ["timestamp", "alert_probability", "rollup_24h"],
            "rule": ("one row per hour in the batch; rollup_24h is the number the operator "
                     "display shows beside the alert"),
        },
        "bundle": {"deployed": _bundle_deployed(), "digest": load_state().get("bundle_digest")},
        "gates": _gate_summary(load_state()),
    }


def obs_profile(args: Dict[str, Any]) -> Dict[str, Any]:
    import yaml
    cfg = yaml.safe_load((WORKSPACE / "config.yaml").read_text())
    log = _read_log(WORKSPACE / cfg["paths"]["history"])
    batch = _read_log(WORKSPACE / cfg["paths"]["current_batch"])
    numeric = log.select_dtypes("number")

    stats = []
    for column in numeric.columns:
        series = numeric[column]
        stats.append({
            "channel": column,
            "median": round(float(series.median()), 2),
            "distinct_values": int(series.nunique()),
        })
    jobs = []
    joblog = WORKSPACE / "var" / "ops_log.jsonl"
    if joblog.exists():
        jobs = [json.loads(l) for l in joblog.read_text().splitlines() if l.strip()][-8:]
    st = load_state()
    return {
        "archive_hours": int(len(log)),
        "archive_span": [str(log.timestamp.min()), str(log.timestamp.max())],
        "batch_hours": int(len(batch)),
        "channels": stats,
        "recent_jobs": jobs,
        "last_validate": {"status": st.get("last_validate"), "signal": st.get("last_signal")},
        "validate_budget": {"used": st.get("validate_count", 0), "limit": VALIDATE_LIMIT},
    }


def obs_sample_records(args: Dict[str, Any]) -> Dict[str, Any]:
    import yaml
    cfg = yaml.safe_load((WORKSPACE / "config.yaml").read_text())
    name = args.get("file") or cfg["paths"]["current_batch"]
    path = (WORKSPACE / name).resolve()
    if WORKSPACE not in path.parents or not path.exists():
        return {"error": "unknown_file", "file": name}
    log = _read_log(path)
    if args.get("at"):
        import pandas as pd
        centre = (log["timestamp"] - pd.Timestamp(args["at"])).abs().idxmin()
    else:
        centre = len(log) // 2
    lo = max(0, centre - 12)
    rows = log.iloc[lo:lo + 30]
    return {"file": name, "hours_shown": int(len(rows)),
            "rows": json.loads(rows.to_json(orient="records", date_format="iso")),
            "note": "raw logger rows, exactly as stored; nothing here is filtered or derived"}


def obs_feature_audit(args: Dict[str, Any]) -> Dict[str, Any]:
    import pandas as pd
    import yaml
    cfg = yaml.safe_load((WORKSPACE / "config.yaml").read_text())
    name = args.get("file") or cfg["paths"]["current_batch"]
    path = (WORKSPACE / name).resolve()
    if WORKSPACE not in path.parents or not path.exists():
        return {"error": "unknown_file", "file": name}
    log = _read_log(path)
    at = pd.Timestamp(args["at"]) if args.get("at") else log["timestamp"].iloc[len(log) // 2]

    driver = Path(tempfile.mkdtemp(prefix="audit-")) / "_audit.py"
    driver.write_text(AUDIT_DRIVER)
    try:
        res = run_candidate(WORKSPACE, ["_audit.py", str(at), name], timeout=600,
                            extra_inputs={"_audit.py": driver})
        computed: Dict[str, Any] = {"error": "pipeline_raised",
                                    "stderr_tail": res["stderr_tail"][-300:]}
        if res["rc"] == 0:
            try:
                computed = json.loads(res["stdout_tail"].strip().splitlines()[-1])
            except Exception as exc:                              # noqa: BLE001
                computed = {"error": f"unparseable:{exc}"}
        if res.get("run_dir"):
            shutil.rmtree(res.get("_keep", res["run_dir"]), ignore_errors=True)
    finally:
        shutil.rmtree(driver.parent, ignore_errors=True)

    window = log[(log["timestamp"] <= at) & (log["timestamp"] > at - pd.Timedelta(hours=24))]
    return {
        "file": name, "hour": str(at),
        "your_pipeline": computed,
        "raw_rows_in_the_last_24h": json.loads(window.to_json(orient="records", date_format="iso")),
        "note": ("`your_pipeline` is what the working tree computes for this hour. The rows are "
                 "the logger's own, for the 24 hours ending at it, exactly as stored."),
    }


AUDIT_DRIVER = """
import json, sys
import pandas as pd
sys.path.insert(0, ".")
from src import channels, features

at = pd.Timestamp(sys.argv[1]); path = sys.argv[2]
log = channels.read_log(path)
frame = features.build_features(log)
row = None
if at in frame.index:
    row = {k: (None if pd.isna(v) else float(v)) for k, v in frame.loc[at].items()}
print(json.dumps({"feature_row": row, "hours_in_frame": int(len(frame)),
                  "columns": [str(c) for c in frame.columns]}))
"""


# --------------------------------------------------------------------------- gate helpers
def _bundle_deployed() -> bool:
    return (BUNDLE / "src").exists()


def _gate_summary(st: Dict[str, Any]) -> Dict[str, Any]:
    return {k: st.get(k) for k in
            ("reproduced", "deployed", "deploy_count", "validate_count", "last_validate",
             "diagnosed", "diagnosis_family", "inject_active", "recovered",
             "recovery_attempts_left", "promoted", "submitted")}


def _reject(op: str, error: str, **extra: Any) -> Dict[str, Any]:
    payload = {"error": error, **extra}
    log_action(op, payload, False, "operational")
    return {"ok": False, "op": op, **payload}


def _accept(op: str, state: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    state["gate_log"].append(op)
    save_state(state)
    log_action(op, payload, True, "operational")
    return {"ok": True, "op": op, **payload}


# --------------------------------------------------------------------------- gated ops
def op_reproduce(args, st):
    res = run_candidate(WORKSPACE, ["scripts/run_backtest.py"])
    summary: Dict[str, Any] = {"rc": res["rc"], "seconds": res["seconds"]}
    run_dir = res.get("run_dir")
    if run_dir:
        report = Path(run_dir) / "results" / "backtest_report.json"
        if res["rc"] == 0 and report.exists():
            try:
                summary["backtest"] = json.loads(report.read_text())
            except Exception:                                     # noqa: BLE001
                summary["backtest"] = None
        shutil.rmtree(res.get("_keep", run_dir), ignore_errors=True)
    if res["rc"] != 0:
        summary["stderr_tail"] = res["stderr_tail"]
        return _reject("reproduce", "pipeline_failed", **summary)
    st["reproduced"] = True
    return _accept("reproduce", st, summary)


def bundle_violations(root: Path) -> List[Dict[str, Any]]:
    bad: List[Dict[str, Any]] = []
    total = 0
    for rel in BUNDLE_PATHS:
        src = root / rel
        if not src.exists():
            continue
        files = [src] if src.is_file() else [f for f in src.rglob("*") if f.is_file()]
        for f in files:
            if "__pycache__" in f.parts:
                continue
            size = f.stat().st_size
            total += size
            name = f.relative_to(root).as_posix()
            if f.suffix.lower() not in BUNDLE_SUFFIXES:
                bad.append({"path": name, "reason": "not_source", "suffix": f.suffix})
            elif size > BUNDLE_MAX_FILE_BYTES:
                bad.append({"path": name, "reason": "file_too_large", "bytes": size})
    if total > BUNDLE_MAX_TOTAL_BYTES:
        bad.append({"path": "<bundle>", "reason": "bundle_too_large", "bytes": total})
    return bad


def op_deploy(args, st):
    if not st["reproduced"]:
        return _reject("deploy", "reproduce_required")
    violations = bundle_violations(WORKSPACE)
    if violations:
        return _reject("deploy", "bundle_carries_non_source", violations=violations[:8],
                       allowed=sorted(BUNDLE_SUFFIXES),
                       note=("the deployed artifact carries code and configuration only; keep "
                             "data out of it and derive what you need at run time"))
    if BUNDLE.exists():
        shutil.rmtree(BUNDLE)
    BUNDLE.mkdir(parents=True)
    for rel in BUNDLE_PATHS:
        src = WORKSPACE / rel
        if not src.exists():
            return _reject("deploy", "missing_bundle_path", path=rel)
        if src.is_dir():
            safe_copy_tree(src, BUNDLE / rel)
        else:
            shutil.copy2(src, BUNDLE / rel)

    import yaml as _yaml
    target = BUNDLE / INJECT_TARGET
    shipped = _yaml.safe_load(target.read_text()) or {}
    shipped.get("alerting", {}).pop(INJECT_KEY, None)
    target.write_text(_yaml.safe_dump(shipped, sort_keys=False))

    st.update({
        "deployed": True, "deploy_count": st["deploy_count"] + 1,
        "inject_active": True, "diagnosed": False, "diagnosis_family": None,
        "recovered": False, "recovery_family": None, "clean_after_recovery": 0,
        "recovery_attempts_left": RECOVERY_ATTEMPTS,
        "last_validate": None, "last_signal": None, "promoted": False,
        "bundle_digest": digest_tree(BUNDLE),
    })
    return _accept("deploy", st, {
        "bundle_digest": st["bundle_digest"],
        "bundle_paths": BUNDLE_PATHS,
        "bytes_staged": {rel: sum(p.stat().st_size for p in (BUNDLE / rel).rglob("*") if p.is_file())
                         if (BUNDLE / rel).is_dir() else (BUNDLE / rel).stat().st_size
                         for rel in BUNDLE_PATHS},
        "config_keys_shipped": sorted((shipped.get("alerting") or {}).keys()),
    })


def _score_bundle_on(batch: Path, labels_path: Path) -> Dict[str, Any]:
    import pandas as pd
    res = run_candidate(BUNDLE, ["scripts/score_hours.py", "--batch", "hidden_batch.csv",
                                 "--out", "hidden_scores.csv"],
                        extra_inputs={"hidden_batch.csv": batch})
    run_dir = res.get("run_dir")
    try:
        if res["rc"] != 0:
            return {"signal": "candidate_error", "rc": res["rc"], "stderr_tail": res["stderr_tail"]}
        out = Path(run_dir) / "hidden_scores.csv"
        if not out.exists():
            return {"signal": "contract_violation", "detail": "no_output"}
        try:
            scores = pd.read_csv(out)
        except Exception as exc:                                  # noqa: BLE001
            return {"signal": "contract_violation", "detail": f"unreadable:{exc}"}
        if list(scores.columns)[:2] != ["timestamp", "alert_probability"]:
            return {"signal": "contract_violation", "detail": "columns"}
        if "rollup_24h" not in scores.columns:
            return {"signal": "contract_violation", "detail": "missing_rollup_24h"}
        scores = scores.dropna(subset=["timestamp", "alert_probability"])
        if scores.empty or not scores["alert_probability"].between(0, 1).all():
            return {"signal": "contract_violation", "detail": "probability_range"}
        scores["timestamp"] = pd.to_datetime(scores["timestamp"])
        if scores["timestamp"].duplicated().any():
            return {"signal": "contract_violation", "detail": "duplicate_hours"}

        owed = pd.to_datetime(pd.read_csv(batch, low_memory=False)["timestamp"])
        labels = pd.read_csv(labels_path)
        labels["timestamp"] = pd.to_datetime(labels["timestamp"])
        merged = (pd.DataFrame({"timestamp": owed})
                  .merge(labels, on="timestamp", how="inner")
                  .merge(scores[["timestamp", "alert_probability"]], on="timestamp", how="left"))
        coverage = float(merged["alert_probability"].notna().mean())
        if coverage < SANITY_COVERAGE_FLOOR:
            return {"signal": "contract_violation", "detail": "coverage",
                    "coverage": round(coverage, 4)}
        merged = merged.dropna(subset=["alert_probability"])
        value = auc(merged["label"].astype(int).tolist(),
                    merged["alert_probability"].astype(float).tolist())
        if value != value:
            return {"signal": "contract_violation", "detail": "degenerate_scores"}
        return {"signal": "ok" if value >= SANITY_AUC_FLOOR else "below_floor",
                "auc": round(float(value), 4), "coverage": round(coverage, 4)}
    finally:
        if run_dir:
            shutil.rmtree(res.get("_keep", run_dir), ignore_errors=True)


def op_validate(args, st):
    if not st["deployed"]:
        return _reject("validate", "deploy_required")
    if st["validate_count"] >= VALIDATE_LIMIT:
        return _reject("validate", "validate_rate_limited", limit=VALIDATE_LIMIT)
    st["validate_count"] += 1
    result = _score_bundle_on(SANITY_BATCH, SANITY_LABELS)
    signal = result["signal"]
    status = "clean" if signal == "ok" else "dirty"
    st["last_validate"] = status
    st["last_signal"] = signal
    if status == "clean" and st["recovered"]:
        st["clean_after_recovery"] += 1
    # lossy on purpose: a one-bit verdict plus a coarse signal, never a per-row diff
    return _accept("validate", st, {"status": status, "signal": signal,
                                    "budget_remaining": VALIDATE_LIMIT - st["validate_count"]})


def op_diagnostics_read(args, st):
    if st["last_validate"] != "dirty":
        return _reject("diagnostics.read", "dirty_validate_required",
                       last_validate=st["last_validate"])
    if st["inject_active"]:
        import yaml as _yaml
        shipped_cfg = _yaml.safe_load((BUNDLE / INJECT_TARGET).read_text()) or {}
        tree_cfg = _yaml.safe_load((WORKSPACE / INJECT_TARGET).read_text()) or {}
        shipped_keys = sorted((shipped_cfg.get("alerting") or {}).keys())
        tree_keys = sorted((tree_cfg.get("alerting") or {}).keys())
        family = INJECT_FAMILY
        detail = {
            "file": INJECT_TARGET,
            "bundle_alerting_keys": shipped_keys,
            "working_tree_alerting_keys": tree_keys,
            "absent_from_bundle": [k for k in tree_keys if k not in shipped_keys],
        }
        symptom = "the deployed bundle was built with a configuration older than the working tree"
    else:
        family = {"candidate_error": "runtime_fault",
                  "contract_violation": "contract_violation",
                  "below_floor": "quality_regression"}.get(st["last_signal"], "unknown")
        detail = {"signal": st["last_signal"]}
        symptom = "the deployed bundle ran as built; validation rejected its behaviour"
    st["diagnosed"] = True
    st["diagnosis_family"] = family
    return _accept("diagnostics.read", st,
                   {"family": family, "symptom": symptom, "detail": detail,
                    "recovery_families": RECOVERY_FAMILIES,
                    "attempts_left": st["recovery_attempts_left"]})


def op_recovery_apply(args, st):
    family = str(args.get("family") or "")
    if not family:
        return _reject("recovery.apply", "family_required", families=RECOVERY_FAMILIES)
    if not st["diagnosed"]:
        return _reject("recovery.apply", "diagnosis_required")
    if st["recovery_attempts_left"] <= 0:
        return _reject("recovery.apply", "recovery_attempts_exhausted",
                       note="redeploy to rebuild the artifact and reset the attempt budget")
    if family != st["diagnosis_family"]:
        st["recovery_attempts_left"] -= 1
        st["wrong_recoveries"] += 1
        st["diagnosed"] = False                     # a wrong family costs the diagnosis too
        save_state(st)
        return _reject("recovery.apply", "family_does_not_match_diagnosis",
                       applied=family, attempts_left=st["recovery_attempts_left"])
    if family != INJECT_FAMILY or not st["inject_active"]:
        return _reject("recovery.apply", "no_recovery_for_this_family",
                       family=family,
                       note="nothing to repair in the environment; change the pipeline and redeploy")

    shutil.copy2(WORKSPACE / INJECT_TARGET, BUNDLE / INJECT_TARGET)
    st.update({"inject_active": False, "recovered": True, "recovery_family": family,
               "bundle_digest": digest_tree(BUNDLE), "clean_after_recovery": 0})
    return _accept("recovery.apply", st,
                   {"family": family, "repaired": INJECT_TARGET, "bundle_digest": st["bundle_digest"]})


def op_promote(args, st):
    if not st["recovered"]:
        return _reject("promote", "recovery_required")
    if st["last_validate"] != "clean" or st["clean_after_recovery"] < 1:
        return _reject("promote", "clean_validate_after_recovery_required",
                       last_validate=st["last_validate"])
    st["promoted"] = True
    return _accept("promote", st, {"bundle_digest": st["bundle_digest"]})


def op_submit(args, st):
    if not st["promoted"]:
        return _reject("submit", "promote_required")
    if FROZEN.exists():
        shutil.rmtree(FROZEN)
    safe_copy_tree(BUNDLE, FROZEN)
    st["submitted"] = True
    st["frozen_digest"] = digest_tree(FROZEN)
    return _accept("submit", st, {
        "frozen_digest": st["frozen_digest"],
        "note": "the environment recomputes the graded terminal from this frozen artifact",
    })


OPS: Dict[str, Callable[[Dict[str, Any], Dict[str, Any]], Dict[str, Any]]] = {
    "reproduce": op_reproduce, "deploy": op_deploy, "validate": op_validate,
    "diagnostics.read": op_diagnostics_read, "recovery.apply": op_recovery_apply,
    "promote": op_promote, "submit": op_submit,
}
OBSERVATIONS: Dict[str, Callable[[Dict[str, Any]], Dict[str, Any]]] = {
    "inspect": obs_inspect, "profile": obs_profile, "sample_records": obs_sample_records,
    "feature_audit": obs_feature_audit,
}


def handle(req: Dict[str, Any]) -> Dict[str, Any]:
    op = str(req.get("op", ""))
    args = req.get("args") or {}
    if op == "status":
        return {"ok": True, "op": "status", "gates": _gate_summary(load_state()),
                "validate_budget": {"used": load_state().get("validate_count", 0), "limit": VALIDATE_LIMIT}}
    if op in OBSERVATIONS:
        st = load_state()
        try:
            payload = OBSERVATIONS[op](args)
        except Exception as exc:                                  # noqa: BLE001
            return {"ok": False, "op": op, "error": f"observation_failed:{exc}"}
        st["obs_count"] = st.get("obs_count", 0) + 1
        save_state(st)
        log_action(op, {"args": args}, True, "observation")
        return {"ok": True, "op": op, **payload}
    if op in OPS:
        st = load_state()
        try:
            return OPS[op](args, st)
        except Exception as exc:                                  # noqa: BLE001
            return _reject(op, f"op_failed:{exc}")
    return {"ok": False, "error": "unknown_op", "op": op, "known": sorted(list(OPS) + list(OBSERVATIONS))}


class Handler(socketserver.StreamRequestHandler):
    timeout = RUN_TIMEOUT + 60

    def handle(self) -> None:
        raw = self.rfile.readline()
        if not raw:
            return
        try:
            req = json.loads(raw.decode())
        except Exception as exc:                                  # noqa: BLE001
            self.wfile.write(json.dumps({"ok": False, "error": f"bad_request:{exc}"}).encode() + b"\n")
            return
        resp = handle(req)
        self.wfile.write(json.dumps(resp, default=str).encode() + b"\n")


class Server(socketserver.ThreadingUnixStreamServer):
    allow_reuse_address = True
    daemon_threads = True


def main() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    load_state()
    SOCK.parent.mkdir(parents=True, exist_ok=True)
    if SOCK.exists():
        SOCK.unlink()
    with Server(str(SOCK), Handler) as server:
        os.chmod(SOCK, 0o666)                # anyone may ASK; the daemon decides
        print(f"envd listening on {SOCK} (workspace={WORKSPACE}, dev={DEV})", flush=True)
        server.serve_forever()


if __name__ == "__main__":
    main()
