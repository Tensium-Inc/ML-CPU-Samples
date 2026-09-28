# The control battery

Every scenario is a shell script that drives the ops itself. There is no model in the loop and
nothing leaves the machine. A runner gives each scenario a throwaway copy of
`environment/workspace`, starts the real `environment/envd/envd.py` over a unix socket with
`ENVD_DEV=1`, runs the scenario as the driver, then runs the real `tests/grade.py` and reads
the number out of `reward.txt`: the file, not stdout.

The environment variables a scenario expects are `WORKSPACE_DIR`, `ENVD_SOCK`, `ENVD_STATE`,
`ENVD_HIDDEN`, `TERMINAL_HIDDEN`, `PROBE_IMPL`, `REWARD_PATH` and `PYTHON`. `oracle`,
`alt_solve` and `alt2_solve` are `solution/*.sh`; the rest are the `nc_*.sh` here.

Scoring 0 is not the bar. Each control must floor **for the reason `expected_detail.json`
predicts**, which is what separates "the task rejects bad work" from "the task rejects
everything". Where a scenario reaches the terminal, `expected_detail.json` also pins the value
it lands on, in `expect_register_agreement` and `expect_archive_agreement`, to be compared
against the terminal's own report within `agreement_tol` (5e-4 unless the scenario names one).
Assert those too: a reason on its own is not enough. `nc_codes_only` and `nc_shape_only` were
accidentally the same arm for a while, and matching reasons hid it.

## What each one is for

| control | asks |
|---|---|
| `oracle`, `alt_solve`, `alt2_solve` | three structurally different correct implementations all score exactly 1.0 |
| `nc_rank_alt` | positive despite the prefix: ranked scores and a differently-ordered register still score 1.0, so the terminal grades a value and not a clone of gold |
| `nc_shape_only` | fixing only what the checkpoint names reaches the terminal and dies there, the shape/value split demonstrated |
| `nc_partial_fix`, `nc_codes_only` | each half of the deciding fix is load-bearing on its own: the code table with the carry-forward already right, and the carry-forward with the codes already right |
| `nc_textbook` | the false summit must reach the **terminal** to floor; if it dies earlier the difficulty is mislocated |
| `nc_no_skill` | keeps the discrimination floor measured instead of asserted |
| `nc_stale_cache` | keeps the archive clause measured: correct logic reading a memoised archive must floor |
| `nc_vendored_snapshot` | a release carries code, not data |
| `nc_cheat_labels`, `nc_cheat_stdout` | neither the answer key nor candidate stdout is a channel to the score |
| `nc_one_shot`, `nc_no_recovery`, `nc_wrong_recovery` | the deliverable is the driven trajectory, and guessing a remediation family is not free |
| `nc_untouched`, `nc_do_nothing` | the delivered environment and a perfect protocol with no fix both floor |
| `nc_malformed_*` | the declared `output_path`, emptied / truncated / oversized / binary / misnamed, scores 0 **cleanly** |

Two things are deliberately not in this battery. Forging the action log only means anything
against the real root-owned state tree, and `nc_cheat_labels` only proves the path scores 0:
offline there is no privilege drop, so that the labels are unreadable from the candidate uid is
a property of the served image, not something calibration can show.

## Adding one

Derive the arm from `_arm.sh`, which materialises the gold fix out of `solution/solve.sh`. That
is the only copy of gold that exists; a second transcription drifts.
