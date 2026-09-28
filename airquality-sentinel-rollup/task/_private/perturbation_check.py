#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from devenv import DevEnv                                          # noqa: E402

HERE = Path(__file__).resolve().parent
TASK = HERE.parent
SOLVE = TASK / "solution" / "solve.sh"


def gold_sources() -> tuple[str, str]:
    out = Path(tempfile.mkdtemp(prefix="goldsrc-"))
    subprocess.run(["bash", str(SOLVE), str(out)], env={**os.environ, "FIX_ONLY": "1"},
                   check=True, capture_output=True)
    return (out / "rollup.py").read_text(), (out / "serve.py").read_text()
GRADE = TASK / "tests" / "grade.py"


def whitespace(feat: str, serve: str):
    feat = ("# " + "-" * 70 + "\n# reformatted; behaviour untouched\n# " + "-" * 70 + "\n\n"
            + feat.replace("\ndef ", "\n\ndef ").replace("    return f", "    \n    return f"))
    return feat, serve + "\n\n# trailing comment\n"


def numeric_format(feat: str, serve: str):
    feat = (feat.replace('.astype(float)', '.astype("float64")')
                .replace('.astype(int)', '.astype("int64")'))
    serve = serve.replace('.astype(int)', '.astype("int64")')
    return feat, serve


def literal_style(feat: str, serve: str):
    return feat.replace("NOT_RECORDED = -200", "NOT_RECORDED = -200.0").replace(
        "min_periods=1", "min_periods=int(1)"), serve


VARIANTS = {"p1_whitespace": whitespace,
            "p2_numeric_format": numeric_format,
            "p3_literal_style": literal_style}


def run(name: str, transform) -> dict:
    fix = Path(tempfile.mkdtemp(prefix=f"perturb-{name}-"))
    feat, serve = transform(*gold_sources())
    (fix / "rollup.py").write_text(feat)
    (fix / "serve.py").write_text(serve)
    box = DevEnv().start()
    try:
        env = os.environ.copy()
        env.update({
            "WORKSPACE_DIR": str(box.workspace), "ENVD_SOCK": str(box.sock),
            "ENVD_STATE": str(box.state), "ENVD_DEV": "1",
            "ENVD_PATH": str(TASK / "environment/envd/envd.py"),
            "ENVD_HIDDEN": str(TASK / "environment/hidden"),
            "TERMINAL_HIDDEN": str(TASK / "environment/hidden"),
            "PROBE_IMPL": str(TASK / "environment/probe/terminal_probe.py"),
            "PYTHON": sys.executable, "FIX_DIR": str(fix),
            "REWARD_PATH": str(box.root / "reward.txt"),
        })
        subprocess.run(["bash", str(SOLVE)], env=env, cwd=str(box.workspace),
                       capture_output=True, text=True, timeout=3600)
        graded = subprocess.run([sys.executable, str(GRADE)], env=env, cwd=str(TASK),
                                capture_output=True, text=True, timeout=3600)
        rf = box.root / "reward.txt"
        reward = float(rf.read_text().strip()) if rf.exists() else -1.0
        try:
            info = json.loads(graded.stdout[graded.stdout.index("{"):])
        except Exception:                                          # noqa: BLE001
            info = {}
        term = info.get("terminal", {})
        return {"name": name, "reward": reward, "auc": term.get("auc"),
                "moved": term.get("customers_moved_by_future_rows"),
                "reason": info.get("terminal_reason")}
    finally:
        box.cleanup()


def main() -> int:
    print(f"{'perturbed gold':22s} {'reward':>7s}  detail")
    print("-" * 70)
    with ThreadPoolExecutor(max_workers=3) as pool:
        rows = list(pool.map(lambda kv: run(*kv), VARIANTS.items()))
    ok = True
    for r in sorted(rows, key=lambda r: r["name"]):
        exact = r["reward"] == 1.0
        ok &= exact
        print(f"{r['name']:22s} {r['reward']:>7.3f}  auc={r['auc']} moved={r['moved']} {r['reason']}")
    print(f"\nPERTURBATION {'GREEN - every perturbed gold still scores exactly 1.0' if ok else 'RED'}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
