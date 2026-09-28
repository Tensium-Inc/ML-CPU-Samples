Maintenance control wants the grounding risk scorer back. A migration stripped five modules
out of `src/fleetrisk/` and never restored them, so every function in those five raises
`NotImplementedError` and nothing runs.

Rebuild them. The service has to reproduce its last accepted run to the last decimal, on
both of the scheduled configurations:

    python3 run_scoring.py --config configs/reference.yaml --out out/reference
    python3 run_scoring.py --config configs/current.yaml   --out out/current

`configs/reference.yaml` is the accepted backtest and the only one you can check yourself
against. What it produced before the migration is in `reference/`: the score for every
flight it touched, and the summary the run wrote beside them. `tools/compare_scores.py`
diffs a pair of score files.

`configs/current.yaml` runs the live scoring period off the same history. It scores flying
from well after the end of that history, and nothing is published for it, so nothing will
tell you whether you have that one right.

`SPEC.md` is the contract the desk signed off. It describes every published quantity in the
terms operations uses and deliberately carries no formulas, so where a definition could go
more than one way, the published run decides it.

The other modules, the configs and the export are not part of the job. Leave them alone.
