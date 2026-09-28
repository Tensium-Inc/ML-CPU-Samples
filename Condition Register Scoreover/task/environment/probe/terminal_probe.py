#!/usr/bin/env python3
"""The graded terminal.

The environment replays the frozen release over a batch it has never seen and compares the
condition register it emits against a register the verifier recomputes for itself. Nothing the
candidate prints is read; the comparison is made here, in the privileged process, from labels
and fixtures the candidate never sees.

Clauses, in the order they are checked:

  contract              shape: columns, one row per encounter, range, coverage
  register_agreement    VALUE: exact set equality per encounter, against the recomputation
  archive_agreement     VALUE: the same, with the encounter archive cut short under it
  discrimination        an anti-degeneracy floor and nothing else. The over-correction
                        outranks the correct answer on every AUC measured, so no AUC bar
                        anywhere can separate correct from leaking.
"""
from __future__ import annotations

import importlib.util
import json
import os
import shutil
import sys
from pathlib import Path
from typing import Any, Dict, Set

_ROOT = os.geteuid() == 0 if hasattr(os, "geteuid") else False


def _pinned(var: str, literal: str) -> Path:
    return Path(literal) if _ROOT else Path(os.environ.get(var, literal))


HIDDEN = _pinned("TERMINAL_HIDDEN", "/opt/task/hidden")
STATE_DIR = _pinned("ENVD_STATE", "/var/lib/envstate")
FROZEN = STATE_DIR / "frozen"
ENVD_PATH = _pinned("ENVD_PATH", "/opt/envd/envd.py")

CODE_COLUMNS = ["diag_1", "diag_2", "diag_3"]
MISSING = "?"
DEFAULT_SEPARATOR = "|"

COVERAGE_FLOOR = 0.95
REGISTER_AGREEMENT_FLOOR = 0.99
ARCHIVE_AGREEMENT_FLOOR = 0.99
AUC_FLOOR = 0.56


def _load_envd():
    spec = importlib.util.spec_from_file_location("envd_probe", ENVD_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules["envd_probe"] = module
    spec.loader.exec_module(module)                       # our code, not the agent's
    return module


def _codes_of_row(row) -> Set[str]:
    out = set()
    for column in CODE_COLUMNS:
        value = row.get(column)
        if value is None:
            continue
        text = str(value).strip()
        if text and text not in (MISSING, "nan", "None"):
            out.add(text)
    return out


def recompute(archive, batch) -> Dict[int, frozenset]:
    """The condition register owed for every encounter in `batch`.

    The universe is exactly what the release can see: the encounter archive on disk plus the
    batch it was handed. Codes accumulate per patient in encounter order, and an encounter's
    register is the union of everything recorded for that patient at or before it.
    """
    import pandas as pd
    columns = ["encounter_id", "patient_nbr", *CODE_COLUMNS]
    universe = pd.concat([archive[columns], batch[columns]], ignore_index=True)
    universe["encounter_id"] = universe["encounter_id"].astype("int64")
    universe = (universe.drop_duplicates(subset=["encounter_id"])
                .sort_values("encounter_id", kind="stable"))
    wanted = set(batch["encounter_id"].astype("int64"))
    accumulated: Dict[int, Set[str]] = {}
    owed: Dict[int, frozenset] = {}
    for record in universe.to_dict("records"):
        patient = record["patient_nbr"]
        seen = accumulated.setdefault(patient, set())
        seen |= _codes_of_row(record)
        eid = int(record["encounter_id"])
        if eid in wanted:
            owed[eid] = frozenset(seen)
    return owed


def parse_field(value: Any, separator: str) -> frozenset:
    if value is None:
        return frozenset()
    text = str(value).strip()
    if not text or text.lower() == "nan":
        return frozenset()
    return frozenset(part.strip() for part in text.split(separator) if part.strip())


def separator_of(root: Path) -> str:
    """The separator the frozen release declares. The contract says the field is joined."""
    path = root / "config.yaml"
    if not path.exists():
        return DEFAULT_SEPARATOR
    try:
        import yaml
        value = ((yaml.safe_load(path.read_text()) or {}).get("register") or {}).get("separator")
    except Exception:                                                  # noqa: BLE001
        return DEFAULT_SEPARATOR
    return value if isinstance(value, str) and len(value) == 1 else DEFAULT_SEPARATOR


def _score(envd, batch: Path, archive: Path, tag: str) -> Dict[str, Any]:
    res = envd.run_candidate(
        FROZEN,
        ["scripts/score_batch.py", "--batch", "terminal_batch.csv",
         "--out", f"terminal_scores_{tag}.csv"],
        extra_inputs={"terminal_batch.csv": batch, "data/encounters.csv": archive},
    )
    run_dir = res.get("run_dir")
    out: Dict[str, Any] = {"rc": res["rc"], "seconds": res["seconds"],
                           "stderr_tail": res["stderr_tail"], "scores": None}
    try:
        if run_dir and res["rc"] == 0:
            path = Path(run_dir) / f"terminal_scores_{tag}.csv"
            if path.exists():
                import pandas as pd
                out["scores"] = pd.read_csv(path)
    finally:
        if run_dir:
            shutil.rmtree(res.get("_keep", run_dir), ignore_errors=True)
    return out


def _agreement(scores, owed: Dict[int, frozenset], separator: str):
    """Exact set equality per encounter, over the encounters that have a defensible answer."""
    emitted = {int(row["encounter_id"]): parse_field(row.get("conditions"), separator)
               for row in scores.to_dict("records")}
    gradeable = [eid for eid, truth in owed.items() if truth and eid in emitted]
    if not gradeable:
        return 0.0, 0, 0
    hits = sum(1 for eid in gradeable if emitted[eid] == owed[eid])
    return hits / len(gradeable), len(gradeable), len(gradeable) - hits


def probe() -> Dict[str, Any]:
    import pandas as pd

    if not FROZEN.exists() or not (FROZEN / "src").exists():
        return {"healthy": False, "reason": "no_frozen_artifact",
                "detail": "nothing was cut over; the environment has no release to grade"}
    envd = _load_envd()

    # Re-checked here and not only at deploy: the graded artifact is verified in its own right.
    carried = envd.bundle_violations(FROZEN)
    if carried:
        return {"healthy": False, "reason": "artifact_carries_non_source", "detail": carried[:8]}

    separator = separator_of(FROZEN)
    batch = pd.read_csv(HIDDEN / "terminal_batch.csv", low_memory=False)
    labels = pd.read_csv(HIDDEN / "terminal_labels.csv")
    terminal: Dict[str, Any] = {"separator": separator}

    base = _score(envd, HIDDEN / "terminal_batch.csv", HIDDEN / "archive_full.csv", "base")
    if base["rc"] != 0 or base["scores"] is None:
        return {"healthy": False, "reason": "artifact_failed_to_score",
                "detail": base["stderr_tail"][-300:], "rc": base["rc"]}

    frame = base["scores"]
    if list(frame.columns)[:3] != ["encounter_id", "score", "conditions"]:
        return {"healthy": False, "reason": "contract_columns",
                "detail": [str(c) for c in frame.columns][:5]}
    frame = frame.dropna(subset=["encounter_id", "score"])
    if frame.empty:
        return {"healthy": False, "reason": "contract_no_rows"}
    try:
        frame = frame.astype({"encounter_id": "int64"})
    except Exception:                                                  # noqa: BLE001
        return {"healthy": False, "reason": "contract_encounter_id_not_integer"}
    if frame["encounter_id"].duplicated().any():
        return {"healthy": False, "reason": "contract_duplicate_encounters",
                "terminal": {**terminal, "rows": int(len(frame)),
                             "distinct_encounters": int(frame["encounter_id"].nunique())}}
    if not frame["score"].astype(float).between(0.0, 1.0).all():
        return {"healthy": False, "reason": "contract_score_range"}
    owed_ids = set(batch["encounter_id"].astype("int64"))
    coverage = len(owed_ids & set(frame["encounter_id"])) / max(len(owed_ids), 1)
    terminal.update({"encounters_in_batch": len(owed_ids), "rows_returned": int(len(frame)),
                     "coverage": round(coverage, 4)})
    if coverage < COVERAGE_FLOOR:
        return {"healthy": False, "reason": "contract_coverage", "terminal": terminal}

    archive = pd.read_csv(HIDDEN / "archive_full.csv", low_memory=False)
    owed = recompute(archive, batch)
    agreement, graded, wrong = _agreement(frame, owed, separator)
    terminal.update({"gradeable_encounters": graded, "registers_wrong": wrong,
                     "register_agreement": round(agreement, 4),
                     "mean_register_size": round(
                         float(sum(len(v) for v in owed.values()) / max(len(owed), 1)), 3)})
    if agreement < REGISTER_AGREEMENT_FLOOR:
        return {"healthy": False, "reason": "register_disagreement", "terminal": terminal,
                "detail": ("the conditions returned for an encounter are not the conditions on "
                           "file for that patient as of that admission")}

    trimmed_run = _score(envd, HIDDEN / "terminal_batch.csv",
                         HIDDEN / "archive_trimmed.csv", "trimmed")
    if trimmed_run["rc"] != 0 or trimmed_run["scores"] is None:
        return {"healthy": False, "reason": "artifact_failed_on_short_archive",
                "detail": trimmed_run["stderr_tail"][-300:], "terminal": terminal}
    short = trimmed_run["scores"].dropna(subset=["encounter_id", "score"])
    try:
        short = short.astype({"encounter_id": "int64"})
    except Exception:                                                  # noqa: BLE001
        return {"healthy": False, "reason": "artifact_failed_on_short_archive",
                "detail": "encounter_id not integer on the second run", "terminal": terminal}
    trimmed_archive = pd.read_csv(HIDDEN / "archive_trimmed.csv", low_memory=False)
    owed_short = recompute(trimmed_archive, batch)
    short_agreement, short_graded, short_wrong = _agreement(short, owed_short, separator)
    terminal.update({"short_archive_gradeable": short_graded,
                     "short_archive_wrong": short_wrong,
                     "archive_agreement": round(short_agreement, 4)})
    if short_agreement < ARCHIVE_AGREEMENT_FLOOR:
        return {"healthy": False, "reason": "archive_not_reread", "terminal": terminal,
                "detail": ("the registers did not follow the encounter archive when it "
                           "changed under the release; they came from somewhere else")}

    merged = labels.merge(frame[["encounter_id", "score"]], on="encounter_id", how="inner")
    value = envd.auc(merged["label"].astype(int).tolist(),
                     merged["score"].astype(float).tolist())
    terminal["auc"] = None if value != value else round(float(value), 4)
    terminal["score_std"] = round(float(frame["score"].astype(float).std()), 6)
    if value != value or value < AUC_FLOOR:
        return {"healthy": False, "reason": "discrimination_below_floor", "terminal": terminal}

    return {"healthy": True, "reason": "ok", "terminal": terminal}


if __name__ == "__main__":
    try:
        print(json.dumps(probe(), default=str))
    except Exception as exc:                                           # noqa: BLE001
        print(json.dumps({"healthy": False,
                          "reason": f"probe_error:{type(exc).__name__}:{exc}"}))
        sys.exit(0)
