"""Run an untrusted candidate pipeline. One owner for the isolation rules.

Two callers execute the agent's build: the ops service, on every `validate`,
and the verifier, when it grades. Both have to do it the same way -- never
imported, always demoted, never able to reach the authoritative data -- so the
rule lives here rather than twice.

It was twice, and the two copies had drifted in opposite directions. The
service demoted the candidate but handed it a data root only root can read, so
every validate failed with a permission error. The verifier could read the data
because it never demoted at all, which left untrusted code running as root
beside the file it was about to be compared against.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

AGENT_UID = 1000
AGENT_GID = 1000

# The deployed build is a package: an entry point plus the modules it imports.
# Both have to be staged together or the entry point imports nothing.
ENTRY = "harness.py"
PACKAGE = "src"


def _can_demote() -> bool:
    """Only root can drop privileges, and only with a tool to do it."""
    return bool(shutil.which("setpriv")) and getattr(os, "geteuid", lambda: -1)() == 0


def _stage_build(candidate: Path, work: Path) -> Path:
    """Copy the deployed build into `work` and return the entry point there.

    The package is staged NEXT TO the entry point, because that is what puts it
    on the import path: python prepends the script's own directory to sys.path,
    so `import src...` resolves to this copy and never reaches back into the
    service's state directory -- which a demoted process could not open anyway.
    """
    run_script = work / ENTRY
    shutil.copyfile(candidate / ENTRY, run_script)
    package = candidate / PACKAGE
    if package.is_dir():
        shutil.copytree(package, work / PACKAGE,
                        ignore=shutil.ignore_patterns("__pycache__"))
    return run_script


def _open_up(work: Path, scripts: list[Path]) -> None:
    """Make everything staged readable by the uid the run is demoted to.

    Everything the demoted process touches has to be staged out of the root-only
    tree and opened up, and that includes the build itself: it lives under the
    service's 0700 state directory, where uid 1000 cannot even open it. Python
    exits 2 on a script it cannot read, which reads like a usage error and sent
    the first hunt for this bug in the wrong direction entirely.
    """
    os.chmod(work, 0o777)              # the demoted process writes its output here
    for script in scripts:
        os.chmod(script, 0o644)
    for top in (work / "data", work / PACKAGE):
        if not top.is_dir():
            continue
        for path in (top, *top.rglob("*")):
            os.chmod(path, 0o755 if path.is_dir() else 0o644)


def _argv(script: Path, args: list[str], demote: bool) -> list[str]:
    """The command line, with the privilege drop in front of it when we are root."""
    argv = [sys.executable, str(script), *args]
    if demote:
        return ["setpriv", f"--reuid={AGENT_UID}", f"--regid={AGENT_GID}",
                "--clear-groups", *argv]
    return argv


def run(candidate: Path, trusted: Path, timeout_sec: int):
    """Execute the build deployed in `candidate` against a copy of `trusted`.

    `candidate` is a directory holding the entry point and, beside it, the
    package it imports -- the same two things `deploy` snapshots out of the
    workspace. Returns `(completed_process, out_file, work_dir)`. The caller
    owns `work_dir` and must remove it.

    The candidate is demoted to the agent's own uid whenever we are root, which
    means it cannot read the authoritative data -- that copy is 0700 root-only
    by design -- so it gets a per-run copy instead. The data was never the
    secret: the agent starts with the same extract in its workspace, and what
    is withheld is which rows are one request and which version each field is read from. Only the data's INTEGRITY
    matters here, and a throwaway copy protects that without handing untrusted
    code the root privileges it would need to rewrite the original.
    """
    candidate = Path(candidate)
    work = Path(tempfile.mkdtemp(prefix="cand-"))
    out_file = work / "request_table.csv"
    data_root = trusted
    run_script = candidate / ENTRY

    demote = _can_demote()
    if demote:
        run_script = _stage_build(candidate, work)
        data_root = work / "data"
        shutil.copytree(trusted, data_root)
        _open_up(work, [run_script])

    proc = subprocess.run(
        _argv(run_script, ["--data-root", str(data_root), "--out", str(out_file)], demote),
        capture_output=True, text=True, timeout=timeout_sec, check=False, cwd=str(work))
    return proc, out_file, work


def probe(candidate: Path, trusted: Path, name: str, source: str,
          args: list[str], timeout_sec: int):
    """Run a short driver of OUR OWN beside the deployed build and hand back what
    it printed.

    The entry point is not the only way a build gets used, and `run` measures
    only that one path -- so a build that answers `resolve.py` and nothing else
    looks complete to it. This executes a module of the build directly, the way
    anything downstream of it would, and returns the finished process for the
    caller to read.

    Same isolation as `run` and for the same reason: the driver is ours but the
    module it imports is not, so it is never imported into the service, always
    demoted when we are root, and given a throwaway copy of the data. The work
    directory is removed here rather than by the caller -- there is no output
    file to keep, only stdout.
    """
    candidate = Path(candidate)
    work = Path(tempfile.mkdtemp(prefix="probe-"))
    try:
        demote = _can_demote()
        # Staged whether or not we are root: the driver has to sit beside the
        # package for `import src` to find it at all.
        _stage_build(candidate, work)
        script = work / name
        script.write_text(source, encoding="utf-8")
        data_root = Path(trusted)
        if demote:
            data_root = work / "data"
            shutil.copytree(trusted, data_root)
            _open_up(work, [script, work / ENTRY])
        return subprocess.run(
            _argv(script, ["--data-root", str(data_root), *args], demote),
            capture_output=True, text=True, timeout=timeout_sec, check=False,
            cwd=str(work))
    finally:
        shutil.rmtree(work, ignore_errors=True)
