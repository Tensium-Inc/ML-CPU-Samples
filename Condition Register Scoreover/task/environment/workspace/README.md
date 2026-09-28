# Readmission scoring: condition register export

Scores every inpatient discharge in a batch for a 30-day readmission and exports, per encounter,
the score and the condition register that goes to the ward alongside it.

    python3 scripts/score_batch.py --batch data/serving_batch.csv --out results/scores.csv
    python3 scripts/run_backtest.py
    python3 -m unittest discover -s tests

`config.yaml` is the policy the analytics team owns; the pipeline is expected to honour it.
`data/DATA_CARD.md` describes the corpus. `var/ops_log.jsonl` is what the scheduled jobs recorded.

    src/config.py     reads the policy and checks the keys the contract depends on
    src/codes.py      the diagnosis codes recorded on an encounter
    src/register.py   the condition register, in long form
    src/features.py   the feature frame the model is fitted on
    src/model.py      training and scoring
    src/serve.py      assembling the export

Releases go out through the gated release service, not by copying files:

    python3 env_cli.py status
