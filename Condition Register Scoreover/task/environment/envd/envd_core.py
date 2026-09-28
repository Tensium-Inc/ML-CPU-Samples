#!/usr/bin/env python3
"""The parts of the gated-ops daemon that are identical across tasks.

The task's own `envd.py` supplies the OPS and OBSERVATIONS dicts and the injection. Everything
here is the machinery where a bug is fatal and silent: the root-owned action log, symlink-safe
staging, unprivileged candidate execution, the bundle content restriction, and a tie-aware AUC.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import socketserver
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Callable, Dict, List, Tuple

# Unix-only, and only needed when actually dropping privilege. Guarded so the module imports on
# a Windows authoring box: ENVD_DEV=1 calibration and the terminal probe both import this and
# never drop privilege.
try:
    import pwd
except ImportError:                                                # pragma: no cover
    pwd = None                                                     # type: ignore[assignment]

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

# The deployed artifact carries CODE, not data. A candidate that vendors a snapshot of a derived
# table into src/ ships the very values it is supposed to recompute, and no invariance clause
# can see it: a baked-in copy is identical in both probe runs. Enforced at deploy and re-checked
# at the terminal.
BUNDLE_PATHS = ["src", "scripts", "config.yaml"]
BUNDLE_SUFFIXES = {".py", ".yaml", ".yml", ".toml", ".cfg", ".ini"}
BUNDLE_MAX_FILE_BYTES = 64 * 1024
BUNDLE_MAX_TOTAL_BYTES = 512 * 1024

RUN_TIMEOUT = int(os.environ.get("ENVD_RUN_TIMEOUT", "900"))


def fresh_state(**extra: Any) -> Dict[str, Any]:
    """The common gate flags. Add task-specific keys via **extra."""
    base = {
        "reproduced": False, "deployed": False, "deploy_count": 0,
        "validate_count": 0, "last_validate": None, "last_signal": None,
        "clean_after_recovery": 0,
        "diagnosed": False, "diagnosis_family": None,
        "inject_active": False, "recovered": False, "recovery_family": None,
        "recovery_attempts_left": 2, "wrong_recoveries": 0,
        "promoted": False, "submitted": False,
        "bundle_digest": None, "frozen_digest": None,
        "gate_log": [], "obs_count": 0,
    }
    base.update(extra)
    return base


_FRESH: Callable[[], Dict[str, Any]] = fresh_state


def set_fresh(fn: Callable[[], Dict[str, Any]]) -> None:
    """Let the task override the initial state."""
    global _FRESH
    _FRESH = fn


def load_state() -> Dict[str, Any]:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE.exists():
        save_state(_FRESH())
    return json.loads(STATE.read_text())


def save_state(state: Dict[str, Any]) -> None:
    tmp = STATE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=2))
    tmp.replace(STATE)                      # atomic; a torn state file loses the trajectory


def _next_seq() -> int:
    if not ACTIONS.exists():
        return 1
    return sum(1 for line in ACTIONS.read_text().splitlines() if line.strip()) + 1


def log_action(op: str, payload: Dict[str, Any], accepted: bool, op_class: str) -> None:
    """Append to the accepted-action log.

    This file lives under STATE_DIR (root 0700) and is written only by this daemon, which the
    agent cannot impersonate. That is what makes the gate walk trustworthy without a signing
    key: an in-container key the agent can read, or a keyless hash chain, are both forgeable.
    """
    rec = {"seq": _next_seq(), "ts": round(time.time(), 3), "op": op,
           "op_class": op_class, "accepted": accepted, "payload": payload}
    with ACTIONS.open("a") as fh:
        fh.write(json.dumps(rec) + "\n")
        fh.flush()
        os.fsync(fh.fileno())


def digest_tree(root: Path) -> str:
    h = hashlib.sha256()
    for p in sorted(root.rglob("*")):
        if p.is_file() and "__pycache__" not in p.parts:
            h.update(p.relative_to(root).as_posix().encode())
            h.update(p.read_bytes())
    return h.hexdigest()[:16]


def safe_copy_tree(src: Path, dst: Path) -> List[str]:
    """Copy `src` into `dst`, refusing to follow symlinks out of the tree.

    Escaping links are dropped and recorded, so a planted link cannot pull the hidden labels or
    anything else root-owned into a directory the candidate can read.
    """
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
                path.resolve(strict=True).relative_to(src)
            except (OSError, ValueError):
                dropped.append(rel.as_posix())
                continue
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        elif path.is_file():
            target.parent.mkdir(parents=True, exist_ok=True)
            with open(path, "rb", opener=_nofollow_opener) as fh:
                target.write_bytes(fh.read())
    return dropped


# O_NOFOLLOW is POSIX-only. In the container it is always present and is what stops a planted
# symlink being followed out of the tree; on a Windows authoring box it degrades to a plain
# open, which is acceptable because the privilege boundary only exists in the container.
_O_NOFOLLOW = getattr(os, "O_NOFOLLOW", 0)


def _nofollow_opener(path: str, flags: int) -> int:
    return os.open(path, flags | _O_NOFOLLOW)


def _run_uid() -> Tuple[int, int]:
    if DEV:
        return (os.getuid(), os.getgid()) if hasattr(os, "getuid") else (-1, -1)
    if pwd is None:
        raise RuntimeError("privilege drop requires a POSIX host; set ENVD_DEV=1 to calibrate")
    ent = pwd.getpwnam(RUN_USER)
    return ent.pw_uid, ent.pw_gid


def chown_tree(root: Path, uid: int, gid: int) -> None:
    if DEV:
        return
    os.chown(root, uid, gid)
    for p in root.rglob("*"):
        os.chown(p, uid, gid, follow_symlinks=False)


def _scrub_world_tmp(uid: int) -> None:
    """Remove anything the candidate uid left in the world-writable /tmp.

    Candidate code runs unprivileged, but /tmp is shared with the agent uid, so a bundle could
    copy a hidden validate input there for the agent to read. That leaks no labels, but it would
    let the agent reconstruct the validate cohort offline and route around the rate limit, which
    is a designed difficulty lever.
    """
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


def run_candidate(code_root: Path, argv: List[str], timeout: int = RUN_TIMEOUT,
                  extra_inputs: Dict[str, Path] | None = None) -> Dict[str, Any]:
    """Run candidate code unprivileged in a throwaway dir. Never raises into the daemon.

    `code_root` supplies the bundle paths; every other input the agent had is staged from the
    workspace, so a candidate that legitimately reads data/ or config finds it there. Staging a
    subset produces FileNotFoundError floors that read as wrong answers.

    `extra_inputs` is for hidden INPUTS only. Labels never enter a run dir: the verifier scores
    the candidate's output file against labels it holds itself.
    """
    uid, gid = _run_uid()
    tmp = Path(tempfile.mkdtemp(prefix="envrun-"))
    run = tmp / "run"
    try:
        safe_copy_tree(WORKSPACE, run)
        for rel in BUNDLE_PATHS:
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
        for name, path in (extra_inputs or {}).items():
            dest = run / name
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, dest)
        os.chmod(tmp, 0o755)
        os.chmod(run, 0o700)
        chown_tree(run, uid, gid)

        scratch = run / ".scratch"          # private TMPDIR inside the 0700 tree
        scratch.mkdir(exist_ok=True)
        env = {"PATH": "/usr/local/bin:/usr/bin:/bin", "HOME": str(run),
               "TMPDIR": str(scratch), "TEMP": str(scratch), "TMP": str(scratch),
               "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0",
               "OMP_NUM_THREADS": "1", "OPENBLAS_NUM_THREADS": "1", "MKL_NUM_THREADS": "1"}
        if DEV:
            env["PYTHONPATH"] = os.pathsep.join(p for p in sys.path if p)
            env["HOME"] = os.environ.get("HOME", str(run))
        kwargs: Dict[str, Any] = {} if DEV else {"user": uid, "group": gid}

        started = time.time()
        proc = subprocess.run([sys.executable, *argv], cwd=str(run), env=env,
                              capture_output=True, text=True, timeout=timeout, **kwargs)
        out = {"rc": proc.returncode, "seconds": round(time.time() - started, 2),
               "stderr_tail": proc.stderr[-600:], "stdout_tail": proc.stdout[-600:],
               "run_dir": str(run), "_keep": tmp}
        _scrub_world_tmp(uid)
        return out
    except subprocess.TimeoutExpired:
        shutil.rmtree(tmp, ignore_errors=True)
        return {"rc": -9, "seconds": timeout, "stderr_tail": "timeout",
                "stdout_tail": "", "run_dir": None}
    except Exception as exc:                                       # noqa: BLE001
        shutil.rmtree(tmp, ignore_errors=True)
        return {"rc": -1, "seconds": 0.0, "stderr_tail": f"harness_error:{exc}",
                "stdout_tail": "", "run_dir": None}


def cleanup_run(res: Dict[str, Any]) -> None:
    if res.get("run_dir"):
        shutil.rmtree(res.get("_keep", res["run_dir"]), ignore_errors=True)


def bundle_violations(root: Path) -> List[Dict[str, Any]]:
    """Files the artifact may not carry: data blobs, and anything too large for source."""
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


def stage_bundle(dest: Path = BUNDLE) -> Dict[str, Any] | None:
    """Copy BUNDLE_PATHS out of the workspace. Returns a rejection payload, or None on success."""
    violations = bundle_violations(WORKSPACE)
    if violations:
        return {"error": "bundle_carries_non_source", "violations": violations[:8],
                "allowed": sorted(BUNDLE_SUFFIXES),
                "note": ("the deployed artifact carries code and configuration only; keep data "
                         "out of it and derive what you need at run time")}
    if dest.exists():
        shutil.rmtree(dest)
    dest.mkdir(parents=True)
    for rel in BUNDLE_PATHS:
        src = WORKSPACE / rel
        if not src.exists():
            return {"error": "missing_bundle_path", "path": rel}
        if src.is_dir():
            safe_copy_tree(src, dest / rel)
        else:
            shutil.copy2(src, dest / rel)
    return None


def auc(labels: List[int], scores: List[float]) -> float:
    """Rank AUC with tie handling, so the daemon process needs no sklearn import."""
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


def gate_summary(st: Dict[str, Any]) -> Dict[str, Any]:
    keys = ("reproduced", "deployed", "deploy_count", "validate_count", "last_validate",
            "diagnosed", "diagnosis_family", "inject_active", "recovered",
            "recovery_attempts_left", "promoted", "submitted")
    return {k: st.get(k) for k in keys}


def reject(op: str, error: str, **extra: Any) -> Dict[str, Any]:
    payload = {"error": error, **extra}
    log_action(op, payload, False, "operational")
    return {"ok": False, "op": op, **payload}


def accept(op: str, state: Dict[str, Any], payload: Dict[str, Any]) -> Dict[str, Any]:
    state["gate_log"].append(op)
    save_state(state)
    log_action(op, payload, True, "operational")
    return {"ok": True, "op": op, **payload}


def make_handler(ops: Dict[str, Callable], observations: Dict[str, Callable],
                 status_extra: Callable[[Dict[str, Any]], Dict[str, Any]] | None = None):
    def handle(req: Dict[str, Any]) -> Dict[str, Any]:
        op = str(req.get("op", ""))
        args = req.get("args") or {}
        if op == "status":
            st = load_state()
            out = {"ok": True, "op": "status", "gates": gate_summary(st)}
            if status_extra:
                out.update(status_extra(st))
            return out
        if op in observations:
            st = load_state()
            try:
                payload = observations[op](args)
            except Exception as exc:                               # noqa: BLE001
                return {"ok": False, "op": op, "error": f"observation_failed:{exc}"}
            st["obs_count"] = st.get("obs_count", 0) + 1
            save_state(st)
            log_action(op, {"args": args}, True, "observation")
            return {"ok": True, "op": op, **payload}
        if op in ops:
            st = load_state()
            try:
                return ops[op](args, st)
            except Exception as exc:                               # noqa: BLE001
                return reject(op, f"op_failed:{exc}")
        return {"ok": False, "error": "unknown_op", "op": op,
                "known": sorted(list(ops) + list(observations))}
    return handle


def serve(handle: Callable[[Dict[str, Any]], Dict[str, Any]]) -> None:
    class Handler(socketserver.StreamRequestHandler):
        timeout = RUN_TIMEOUT + 60

        def handle(self) -> None:
            raw = self.rfile.readline()
            if not raw:
                return
            try:
                req = json.loads(raw.decode())
            except Exception as exc:                               # noqa: BLE001
                self.wfile.write(json.dumps({"ok": False,
                                             "error": f"bad_request:{exc}"}).encode() + b"\n")
                return
            self.wfile.write(json.dumps(handle(req), default=str).encode() + b"\n")

    if not hasattr(socketserver, "ThreadingUnixStreamServer"):     # pragma: no cover
        raise RuntimeError("the daemon serves over a unix socket; run it in the container")

    class Server(socketserver.ThreadingUnixStreamServer):
        allow_reuse_address = True
        daemon_threads = True

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    os.chmod(STATE_DIR, 0o700)
    load_state()
    SOCK.parent.mkdir(parents=True, exist_ok=True)
    if SOCK.exists():
        SOCK.unlink()
    with Server(str(SOCK), Handler) as server:
        os.chmod(SOCK, 0o666)          # anyone may ASK; the daemon decides
        print(f"envd listening on {SOCK} (workspace={WORKSPACE}, dev={DEV})", flush=True)
        server.serve_forever()
