"""The gated incident. Root-side; the agent reaches it only through the daemon.

Everything authoritative lives here: the action log, the budgets, the trusted
copy of the dump, the reference rebuild, and the policy notes. The agent's
workspace holds a harness and a thin client, and nothing it writes there is read
as evidence of anything.

Three properties the gates are built to have:

  A wrong repair costs a call and a fresh diagnosis, not a turn. `recovery.apply`
  with a family that does not match spends one of two budgeted repairs and puts
  the incident back to needing `diagnostics.read`. If a wrong family merely
  errored, "try each family" would be a two-line loop and the diagnosis step
  would be decoration; if it ended the run, a documented flag typed once from
  memory would end it, which grades typing.

  The feedback cannot be brute-forced. `validate` returns one bit against a
  reference the agent cannot see, three times, and `validate.release` twice
  more. That is enough to confirm a reading already believed and nowhere near
  enough to search the space of readings -- there are four kinds in the incident
  question alone and one in the population question, so the readings outnumber
  the verdicts by an order of magnitude.

  The build is exercised as a build. `validate` runs the entry point end to end,
  which is the only path a single inlined file has to satisfy. The release steps
  therefore call modules directly, the way anything downstream of a build does:
  `stage.release` asks `places.audit` for its account of the place keys,
  `validate.release` asks `schema.contract()` what shape it writes. Both assert
  on the VALUE that comes back and never on how the build is laid out -- no file
  names, no counts of files, no hashes. Reward that depended on which files
  changed would be grading a shape, and would floor an alternate for being
  written differently.
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import corpus  # noqa: E402
import grading  # noqa: E402
import policies  # noqa: E402
import reference  # noqa: E402
import sandbox  # noqa: E402

# The record has to survive into whatever container grades it, and the verifier
# does not always run in the one the episode ran in. The primary copy stays in
# /var/lib/fundops; these are mirrors of it. /logs/verifier is where the reward
# is delivered. The agent's workspace is the one thing the platform is
# guaranteed to carry from the episode to grading -- output_path lives there --
# and the mirror inside it is root-owned, so the agent still cannot write a byte
# of the record. The workspace itself is sticky, so it cannot be renamed aside.
MIRROR_ROOTS = (Path("/logs/verifier/ops"), Path("/workspace/target/.ops"))

WORKSPACE = Path("/workspace/target")

# What `deploy` snapshots. The deliverable named in task.toml is the entry
# point; the package beside it is the rest of the build and travels with it.
ENTRY = "harness.py"
PACKAGE = "src"

# Three. Two are structural -- one validate to meet the fault, one to confirm
# the repair -- which leaves exactly one to spend on being right about the
# judgements. That is deliberate: the verdicts are for confirming a reading, not
# for finding one, and the oracle is where findings are supposed to come from.
V_BUDGET = 6
R_BUDGET = 2
# The oracle. One request per call, and the ration is what stops the label
# being brute-forced request by request instead of reasoned about as a rule.
A_BUDGET = 12
CANDIDATE_TIMEOUT_SEC = 600
PROBE_TIMEOUT_SEC = 300
FAULT_FAMILY = "stale_applicant_cache"
FAULT_SYMPTOM = "feature_cache_predates_the_deployed_applicant_key"

DELIVERABLE_COLUMNS = ["funding_request_number", "label", "applicant_key",
                       "committed_cents", "filed_months",
                       "filed_commitment_cents", "filed_pre_discount_cents",
                       "filed_discount_pct"]
AUDIT_STRIDE = 7

# The two release steps exercise the build the way anything downstream of it
# does -- by importing a module and calling it -- rather than by running the
# entry point again. These drivers are ours, the modules they import are the
# agent's, and both run through `sandbox.probe`: subprocess, demoted, throwaway
# copy of the dump, never imported into the service.
SCHEMA_CONTRACT_PROBE = '''
import argparse
import json

ap = argparse.ArgumentParser()
ap.add_argument("--data-root", required=True)
ap.parse_args()

from src import schema

print(json.dumps({"contract": schema.contract()}))
'''

REQUEST_AUDIT_PROBE = '''
import argparse
import json

ap = argparse.ArgumentParser()
ap.add_argument("--data-root", required=True)
ap.add_argument("--stride", type=int, required=True)
opts = ap.parse_args()

from src import loading, requests

rows = loading.read_rows(opts.data_root)

print(json.dumps({"full": requests.audit(rows),
                  "sample": requests.audit(rows[::opts.stride])}))
'''

OBSERVATION = {"status", "inspect", "profile", "sample_rows", "policy.list",
               "policy.read", "adjudicate"}
GATED = {"reproduce", "deploy", "validate", "diagnostics.read", "recovery.apply",
         "check.release", "submit"}
# Eight steps, not ten. Every step here is one a release actually needs, and a
# walk long enough to run a competent agent out of turns floors the run before
# it reaches the difficulty -- which is the finding that retired the previous
# task in this family. `stage`, a second release validate and `promote` were
# three separate acknowledgements of the same clean result; they are one now.
REQUIRED_WALK = ["reproduce", "deploy", "validate", "diagnostics.read",
                 "recovery.apply", "validate", "check.release", "submit"]


class Refused(Exception):
    def __init__(self, msg: str):
        super().__init__(msg)
        self.msg = msg


def _read_table(path) -> dict[str, dict]:
    """The deliverable: six columns, all of them strings.

    Read without pandas -- money is carried as an integer count of cents on
    purpose, and letting a csv reader infer types is exactly how it would stop
    being one.
    """
    import csv
    with open(path, newline="", encoding="utf-8") as fh:
        rows = list(csv.reader(fh))
    if not rows:
        return {}
    start = 1 if [c.strip() for c in rows[0][:8]] == DELIVERABLE_COLUMNS else 0
    out: dict[str, dict] = {}
    for r in rows[start:]:
        if len(r) < 8:
            continue
        out[r[0].strip()] = {name: r[i].strip()
                             for i, name in enumerate(DELIVERABLE_COLUMNS[1:], start=1)}
    return out


class Broker:
    def __init__(self, state_dir: str, trusted_data: str):
        self.state_dir = Path(state_dir)
        self.trusted = Path(trusted_data)
        self.state_dir.mkdir(parents=True, exist_ok=True)
        self.state_path = self.state_dir / "state.json"
        self.log_path = self.state_dir / "actions.jsonl"
        self.candidate_dir = self.state_dir / "candidate"
        self.session_key = hashlib.sha256(
            str(self.state_dir.resolve()).encode()).hexdigest()[:16]
        self._reference_cache = None
        self._corpus_cache = None
        self._shape_cache = None
        self.mirrors = [m for m in MIRROR_ROOTS if m != self.state_dir]
        if not self.state_path.exists():
            self._save({
                "reproduced": False, "deploys": 0, "deployed": False,
                "fault_active": False, "fault_seen": False,
                "diagnosed": False, "recovered": False,
                "v_budget": V_BUDGET, "r_budget": R_BUDGET, "a_budget": A_BUDGET,
                "adjudicated": [],
                "clean_after_recovery": False, "released": False, "submitted": False,
                "policies_read": [], "seq": 0, "receipt": None,
            })

    # ---------------------------------------------------------------- state
    def _load(self) -> dict[str, Any]:
        return json.loads(self.state_path.read_text())

    def _save(self, s: dict[str, Any]) -> None:
        self.state_path.write_text(json.dumps(s, indent=2))

    def _log(self, op: str, args: dict, accepted: bool, info: dict) -> None:
        s = self._load()
        s["seq"] += 1
        self._save(s)
        rec = {"seq": s["seq"], "ts": time.time(), "op": op, "args": args,
               "accepted": bool(accepted),
               "op_class": "observation" if op in OBSERVATION else "gated",
               "info_keys": sorted(info.keys())}
        with self.log_path.open("a") as f:
            f.write(json.dumps(rec) + "\n")
        self._mirror()

    def _mirror(self) -> None:
        """Replicate the record to every place a verifier might look for it.

        A mirror that cannot be written is not a reason to refuse an op -- the
        primary copy is still authoritative, and offline calibration has none of
        these paths at all.
        """
        for root in self.mirrors:
            try:
                root.mkdir(parents=True, exist_ok=True)
                # Readable, not writable. A copy taken as anyone but root cannot
                # read a 0700 directory -- it is skipped in silence and the run
                # grades as though it never happened. Reading it costs nothing: it
                # holds operation names, sequence numbers and the agent's own
                # deployed code, never a policy note and never an expected value.
                # Forging it is still impossible: the directory is root-owned so
                # the agent cannot create, delete or rename anything inside it,
                # and the workspace is sticky so it cannot be moved aside.
                os.chmod(root, 0o755)
                shutil.copy2(self.state_path, root / "state.json")
                if self.log_path.exists():
                    shutil.copy2(self.log_path, root / "actions.jsonl")
                if self.candidate_dir.exists():
                    dst = root / "candidate"
                    shutil.rmtree(dst, ignore_errors=True)
                    shutil.copytree(self.candidate_dir, dst)
                    os.chmod(dst, 0o755)
                    for path in dst.rglob("*"):
                        os.chmod(path, 0o755 if path.is_dir() else 0o644)
            except OSError:
                continue

    # ------------------------------------------------------------- helpers
    def _corpus(self) -> list[dict]:
        if self._corpus_cache is None:
            self._corpus_cache = corpus.load(self.trusted)
        return self._corpus_cache

    def _reference(self):
        # Memoised for the life of the process. The trusted extract is read-only
        # and root-owned, so the reference cannot change under us.
        if self._reference_cache is None:
            self._reference_cache = reference.build_reference(self._corpus())
        return self._reference_cache

    def _shape(self) -> dict[str, int]:
        """Shape of the extract. Counts only -- never a field, never a rule.

        Every one of these is a number the agent can recompute from its own copy;
        they are here to save the pass, not to tell it anything the data does not.
        """
        if self._shape_cache is not None:
            return self._shape_cache
        rows = self._corpus()
        versions: dict[str, set] = {}
        names: dict[str, set] = {}
        for row in rows:
            frn = row["funding_request_number"]
            if frn:
                versions.setdefault(frn, set()).add(row["form_version"])
            names.setdefault(row["organization_name"], set()).add(row["ben"])
        self._shape_cache = {
            "rows": len(rows),
            "distinct_requests": len(versions),
            "requests_carrying_both_versions": sum(1 for v in versions.values() if len(v) > 1),
            "requests_as_filed_only": sum(1 for v in versions.values() if v == {"Original"}),
            "requests_as_adjudicated_only": sum(1 for v in versions.values() if v == {"Current"}),
            "distinct_billed_entities": len({r["ben"] for r in rows}),
            "distinct_organisation_names": len(names),
            "names_used_by_more_than_one_billed_entity":
                sum(1 for v in names.values() if len(v) > 1),
        }
        return self._shape_cache

    def _run_candidate(self) -> Any:
        """Execute the deployed harness in a subprocess, demoted.

        Never imported: it is untrusted code, and a hang or a crash has to yield a
        verdict rather than take the service down with it. `sandbox` owns how that
        run is isolated -- the verifier grades through the same helper, so a build
        that validates here cannot behave differently there.
        """
        if not (self.candidate_dir / ENTRY).exists():
            raise Refused("no deployed harness")
        try:
            proc, out_file, work = sandbox.run(
                self.candidate_dir, self.trusted, CANDIDATE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            raise Refused("the deployed harness exceeded its time budget") from None
        try:
            if proc.returncode != 0:
                raise Refused(f"the deployed harness exited {proc.returncode}")
            if not out_file.exists():
                raise Refused("the deployed harness produced no output file")
            return _read_table(out_file)
        finally:
            shutil.rmtree(work, ignore_errors=True)

    def _probe(self, name: str, source: str, args: list[str]) -> dict:
        """Ask the deployed build a question by calling one of its modules."""
        if not (self.candidate_dir / ENTRY).exists():
            raise Refused("no deployed harness")
        try:
            proc = sandbox.probe(self.candidate_dir, self.trusted, name, source,
                                 args, PROBE_TIMEOUT_SEC)
        except subprocess.TimeoutExpired:
            raise Refused("the deployed build did not answer this step inside its "
                          "time budget") from None
        if proc.returncode != 0:
            tail = [ln for ln in (proc.stderr or "").strip().splitlines() if ln.strip()]
            raise Refused("this step calls the deployed build's own modules and the call "
                          f"failed: {tail[-1] if tail else 'exit ' + str(proc.returncode)}")
        try:
            return json.loads((proc.stdout or "").strip().splitlines()[-1])
        except (ValueError, IndexError):
            raise Refused("the deployed build answered this step with something that is "
                          "not the value it was asked for") from None

    def _next(self, s: dict) -> str:
        if not s["reproduced"]:
            return "reproduce"
        if not s["deployed"]:
            return "deploy"
        if s["fault_active"] and not s["fault_seen"]:
            return "validate"
        if s["fault_active"] and not s["diagnosed"]:
            return "diagnostics.read"
        if s["fault_active"] and not s["recovered"]:
            return "recovery.apply"
        if not s["clean_after_recovery"]:
            return "validate"
        if not s["released"]:
            return "check.release"
        return "submit"

    def _next_command(self, s: dict) -> str:
        """The exact command line for the next step, receipt included.

        Printed by `status` on purpose. Nothing about working out which op comes
        next is part of the difficulty here -- the difficulty is the table -- and a
        walk that costs turns to navigate spends the run before it reaches that.
        """
        op = self._next(s)
        flags = ""
        if op == "recovery.apply":
            flags = f" --family {FAULT_FAMILY}"
        if s.get("receipt"):
            flags += f" --receipt {s['receipt']}"
        return f"python3 env_cli.py {op}{flags}"

    # ---------------------------------------------------------------- entry
    def handle(self, argv: list[str]) -> dict[str, Any]:
        if not argv:
            return {"ok": False, "error": "no op"}
        op, args = argv[0], self._parse(argv[1:])
        try:
            info = self._dispatch(op, args)
            if op in GATED:
                info = {**info, "receipt": self._issue_receipt(op)}
                info = {**info, "next_command": self._next_command(self._load())}
            self._log(op, args, True, info)
            return {"ok": True, "op": op, **info}
        except Refused as exc:
            self._log(op, args, False, {"error": exc.msg})
            return {"ok": False, "op": op, "error": exc.msg}

    @staticmethod
    def _parse(rest: list[str]) -> dict[str, Any]:
        args: dict[str, Any] = {}
        i = 0
        while i < len(rest):
            if rest[i].startswith("--"):
                key = rest[i][2:]
                value = "true"
                if i + 1 < len(rest) and not rest[i + 1].startswith("--"):
                    value = rest[i + 1]
                    i += 1
                args[key] = value
            i += 1
        return args

    def _issue_receipt(self, op: str) -> str:
        """The token the next gated op has to carry.

        Keyed to the sequence number, so a receipt is good exactly once and only
        for the step that follows the one that issued it. The point is not secrecy
        -- the agent is meant to read it, and `status` prints the whole command
        line with it already filled in -- but that each gated step has to be taken
        after observing the one before it. Without this the walk collapses into a
        single shell line.
        """
        s = self._load()
        token = hashlib.sha256(
            f"{self.session_key}:{s['seq']}:{op}".encode()).hexdigest()[:16]
        s["receipt"] = token
        self._save(s)
        return token

    def _dispatch(self, op: str, args: dict) -> dict[str, Any]:
        s = self._load()
        if op not in OBSERVATION and op not in GATED:
            raise Refused(f"unknown op {op!r}")
        if op in GATED and s.get("receipt"):
            if args.get("receipt") != s["receipt"]:
                raise Refused(
                    "this op needs the receipt the previous one returned. `status` "
                    "prints the whole command line under `next_command`")
        handler = getattr(self, "_op_" + op.replace(".", "_"), None)
        if handler is None:
            raise Refused(f"unknown op {op!r}")
        return handler(s, args)

    # --------------------------------------------------------- observation
    def _op_status(self, s: dict, _args: dict) -> dict:
        return {"next_expected": self._next(s),
                "next_command": self._next_command(s),
                "receipt": s.get("receipt"),
                "validate_budget": s["v_budget"], "repair_budget": s["r_budget"],
                "adjudicate_budget": s.get("a_budget", A_BUDGET),
                "fault_active": s["fault_active"], "recovered": s["recovered"],
                "released": s["released"], "submitted": s["submitted"],
                "policies_read": sorted(s["policies_read"]),
                "notes_outstanding": sorted(policies.REQUIRED - set(s["policies_read"]))}

    def _op_inspect(self, s: dict, _args: dict) -> dict:
        return {
            "objective": ("rebuild the funding-request table. deliverable: "
                          "workspace/harness.py, run as "
                          "`python3 harness.py --data-root <DIR> --out <FILE>`, writing csv "
                          "with columns " + ", ".join(DELIVERABLE_COLUMNS) +
                          " -- one row for every distinct funding request"),
            "where_the_rules_are": ("the ops notes. they pose every question the "
                                    "deliverable is graded on and they answer most of them. "
                                    "`policy.list` shows what has been written up; all of "
                                    "them must be read before submit"),
            "adjudicate": (f"ground truth on the label of ONE request: "
                           f"`adjudicate --request <FRN>`. {A_BUDGET} calls for the whole "
                           "incident and no way to earn more. it answers about a case and "
                           "never about a rule"),
            "validate": f"one clean/dirty verdict on the whole extract, {V_BUDGET} calls total",
            "recovery": (f"recovery.apply takes --family; diagnostics.read names the value "
                         f"and prints the command. {R_BUDGET} repairs are budgeted and a "
                         "family that does not match spends one"),
            "receipts": ("every gated op returns a receipt and the next one must carry it; "
                         "`status` prints the whole next command line under `next_command`"),
            "check_release": ("calls the build's own modules rather than the entry point: "
                              "src.requests.audit(rows) for its account of the extract, and "
                              "src.schema.contract() for the shape it declares"),
            "your_data": "the whole extract. what it does not contain is the corrected table",
        }

    def _op_profile(self, s: dict, _args: dict) -> dict:
        return {
            **self._shape(),
            "note": ("your workspace holds this same extract in full, so every count here is "
                     "one you can recompute -- they are here to save you the pass. rows and "
                     "distinct_requests are different numbers because the extract records "
                     "FORM VERSIONS: a request appears once per version of the form that "
                     "carries it, which the requests note explains. the name/entity counts "
                     "are what the applicant note is about."),
        }

    def _op_adjudicate(self, s: dict, args: dict) -> dict:
        """Ground truth on the label of exactly ONE request, rationed.

        It reads the reference, so it cannot drift from what the deliverable is
        scored against. It answers about a CASE and never about a rule: the
        generalisation is the agent's to make and the budget is what stops it
        being bought one request at a time.
        """
        question = args.get("question", "funded")
        if question != "funded":
            raise Refused("the only question this oracle answers is 'funded'; "
                          "the field provenance is not a judgement it can settle, "
                          "and the extract carries everything that decides it")
        frn = args.get("request")
        if isinstance(frn, list):
            raise Refused("one request per call")
        if not frn:
            raise Refused("adjudicate takes --request <FRN>")
        table = self._reference()
        if frn not in table:
            raise Refused(f"not a funding request number in this extract: {frn!r}")
        if s.get("a_budget", A_BUDGET) <= 0:
            raise Refused(f"adjudicate budget is spent ({A_BUDGET} calls). "
                          "the rule has to come from the answers you already have")
        s["a_budget"] = s.get("a_budget", A_BUDGET) - 1
        s.setdefault("adjudicated", []).append(frn)
        self._save(s)
        return {"request": frn, "label": table[frn]["label"],
                "adjudicate_budget_left": s["a_budget"],
                "note": "one request. the rule behind it is yours to work out"}

    def _op_sample_rows(self, s: dict, _args: dict) -> dict:
        """A few real rows, so the format is never in doubt.

        Both versions of one request, side by side, because the shape of this
        extract is the thing most easily missed and no note substitutes for
        seeing it.
        """
        rows = self._corpus()
        by_frn: dict[str, list[dict]] = {}
        for row in rows:
            by_frn.setdefault(row["funding_request_number"], []).append(row)
        paired = next((v for v in by_frn.values() if len(v) > 1), rows[:2])
        return {"rows": paired[:2],
                "note": "these two rows are the same funding request"}

    def _op_policy_list(self, s: dict, _args: dict) -> dict:
        return {"topics": sorted(policies.TOPICS),
                "read": sorted(s["policies_read"]),
                "note": "each is a separate write-up; pull them individually. all of them "
                        "must be read before submit is accepted"}

    def _op_policy_read(self, s: dict, args: dict) -> dict:
        topic = args.get("topic", "")
        if topic not in policies.TOPICS:
            raise Refused(f"no note filed under {topic!r}; try policy.list")
        if topic not in s["policies_read"]:
            s["policies_read"].append(topic)
            self._save(s)
        note = policies.TOPICS[topic].replace("ADJUDICATE_BUDGET", str(A_BUDGET))
        return {"topic": topic, "note": note}

    # -------------------------------------------------------------- gated
    def _op_reproduce(self, s: dict, _args: dict) -> dict:
        s["reproduced"] = True
        self._save(s)
        return {"note": "current harness recorded as the starting point"}

    def _op_deploy(self, s: dict, _args: dict) -> dict:
        if not s["reproduced"]:
            raise Refused("reproduce first")
        entry = WORKSPACE / ENTRY
        if not entry.exists():
            raise Refused(f"no workspace/{ENTRY} to deploy")
        # A snapshot of the whole build, not of one file. Rebuilt rather than
        # merged into: a module the agent deleted between deploys has to be gone
        # from what gets validated too, otherwise the candidate is a mixture of
        # two builds and neither one is what was run.
        shutil.rmtree(self.candidate_dir, ignore_errors=True)
        self.candidate_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry, self.candidate_dir / ENTRY)
        package = WORKSPACE / PACKAGE
        if package.is_dir():
            shutil.copytree(package, self.candidate_dir / PACKAGE,
                            ignore=shutil.ignore_patterns("__pycache__"))
        s.update({"deployed": True, "deploys": s["deploys"] + 1,
                  "clean_after_recovery": False, "released": False})
        if s["deploys"] == 1:
            s["fault_active"] = True
        self._save(s)
        return {"deploys": s["deploys"], "note": "candidate registered"}

    def _op_validate(self, s: dict, _args: dict) -> dict:
        if not s["deployed"]:
            raise Refused("deploy first")
        # The injected fault is NOT charged. A verdict of "the serving cache is
        # stale" is this environment reporting its own fault; it says nothing
        # about the agent's build, and billing a third of the ration for it
        # floored four runs out of four that had already produced a correct
        # table. The budget exists to stop a clean/dirty bit being used to
        # search for a rule, and a fault verdict cannot be used for that.
        if s["fault_active"]:
            s["fault_seen"] = True
            self._save(s)
            return {"status": "dirty",
                    "reason": "scoring did not run against the deployed build",
                    "remaining": s["v_budget"],
                    "note": "this verdict is about the serving cache and not about your "
                            "build, so it has not been charged"}

        if s["v_budget"] <= 0:
            raise Refused("validate budget exhausted")
        s["v_budget"] -= 1
        self._save(s)
        result = grading.compare(self._run_candidate(), self._reference())
        clean = grading.is_clean(result)
        if clean and s["recovered"]:
            s["clean_after_recovery"] = True
        self._save(s)
        return {"status": "clean" if clean else "dirty", "remaining": s["v_budget"]}

    def _op_diagnostics_read(self, s: dict, _args: dict) -> dict:
        if not s["fault_seen"]:
            raise Refused("nothing to diagnose until a validate comes back dirty")
        s["diagnosed"] = True
        self._save(s)
        return {"family": FAULT_FAMILY, "symptom": FAULT_SYMPTOM,
                "detail": ("the serving feature cache is keyed by applicant and was built by "
                           "the harness that was live before this deploy, so scoring never "
                           "reached your build"),
                "repair": f"recovery.apply --family {FAULT_FAMILY}"}

    def _op_recovery_apply(self, s: dict, args: dict) -> dict:
        """Clear the fault, quoting the family the diagnosis named.

        A family that does not match spends one of the budgeted repairs and sends
        the incident back to needing a fresh diagnosis. It does not end the run:
        the value is printed by `diagnostics.read`, named again by `inspect`, and
        filled into the command line `status` prints, so getting it wrong is a
        transcription slip rather than a judgement and flooring a run on one would
        be grading typing.
        """
        if not s["diagnosed"]:
            raise Refused("diagnose before repairing")
        if s["r_budget"] <= 0:
            raise Refused("repair budget exhausted; both budgeted repairs are spent")
        family = args.get("family", "")
        if family != FAULT_FAMILY:
            s["r_budget"] -= 1
            s["diagnosed"] = False
            self._save(s)
            raise Refused(f"{family!r} does not match the diagnosis. one repair spent, "
                          f"{s['r_budget']} left; read diagnostics again before the next one")
        s.update({"recovered": True, "fault_active": False})
        self._save(s)
        return {"family": family,
                "note": "cache cleared; the next scoring run reaches your build"}

    def _op_check_release(self, s: dict, _args: dict) -> dict:
        """The release check: ask the build itself what it sees and what it writes.

        `validate` runs the entry point, which is the only path a single inlined
        file has to satisfy. This calls two of the build's own modules the way
        anything downstream of it would -- `requests.audit` for its account of the
        extract and `schema.contract` for the shape it declares -- and asserts on
        the VALUES that come back, never on how the build is laid out. A build
        free to answer any way it likes is free to be written any way it likes.

        The audit is asked about two sets of rows, all of them and every seventh,
        because a constant can be right about one and cannot be right about both.
        """
        if not s["clean_after_recovery"]:
            raise Refused("check.release needs a clean validate after the repair")

        declared = self._probe("_contract.py", SCHEMA_CONTRACT_PROBE, []).get("contract")
        if not isinstance(declared, dict):
            raise Refused("check.release asks src.schema.contract() what the file this build "
                          "writes looks like, and got nothing back")
        if list(declared.get("columns") or []) != DELIVERABLE_COLUMNS:
            raise Refused(f"src.schema.contract() declares columns "
                          f"{declared.get('columns')!r}; the deliverable is "
                          f"{DELIVERABLE_COLUMNS}, in that order")
        if declared.get("rows_per_request") != 1:
            raise Refused("src.schema.contract() has to declare exactly one row per request; "
                          f"it declares {declared.get('rows_per_request')!r}")

        reported = self._probe("_audit.py", REQUEST_AUDIT_PROBE, ["--stride", str(AUDIT_STRIDE)])
        rows = self._corpus()
        for which, subset in (("full", rows), ("sample", rows[::AUDIT_STRIDE])):
            got = reported.get(which)
            if not isinstance(got, dict):
                raise Refused("check.release asks src.requests.audit(rows) for its account of "
                              f"the extract and got nothing back for the {which} set")
            versions: dict[str, set] = {}
            for row in subset:
                if row["funding_request_number"]:
                    versions.setdefault(row["funding_request_number"], set()).add(
                        row["form_version"])
            expected = {"rows": len(subset), "requests": len(versions),
                        "carrying_both_versions": sum(1 for v in versions.values()
                                                      if len(v) > 1)}
            for key, want in expected.items():
                if got.get(key) != want:
                    # The number it should have reported is deliberately not
                    # named: the extract in the workspace is the same bytes, so
                    # this is something the build can check for itself.
                    raise Refused(
                        f"src.requests.audit does not match the extract on {key!r} over the "
                        f"{which} set: it reports {got.get(key)!r}")

        s["released"] = True
        self._save(s)
        return {"note": "released; the build's own account of the extract matches it"}

    def _op_submit(self, s: dict, _args: dict) -> dict:
        if not s["released"]:
            raise Refused("check.release first")
        missing = policies.REQUIRED - set(s["policies_read"])
        if missing:
            raise Refused(f"{len(missing)} ops note(s) never pulled ({sorted(missing)}); "
                          "submit refused")
        s["submitted"] = True
        self._save(s)
        return {"note": "submitted; the environment recomputes the outcome from the "
                        "deployed build"}
