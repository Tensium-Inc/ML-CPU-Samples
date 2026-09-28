We score every inpatient discharge for "will this patient be back inside 30 days", and the
export goes to the wards with a condition register alongside each score so the care team can see
what we think that patient is carrying. I inherited this pipeline from someone who moved on and
I can't put my name on the next release.

Two things came across with the handover and neither has an answer on it.

The ward administrator says our export shows the same admission on several lines. She has been
de-duplicating it by hand every week and nobody could tell her why it comes out like that.

And clinical audit pulled two patients last month who they say are carrying the same
conditions, and our scores for them were nowhere near each other. The consultant who raised it
could not say how many patients it happens to, and she said most of the time the numbers look
perfectly sensible, which is why it has sat in the queue since March.

The numbers look fine, for what that is worth. `python3 scripts/run_backtest.py` reports about
0.65 AUC on a holdout that keeps whole patients on one side, so it is not the usual row-shuffle
mistake, and `python3 -m unittest discover -s tests` is green.

## What is in the workspace

Everything is under `/workspace/target` and there is no internet.

- `config.yaml` - the policy the analytics team owns; the pipeline is expected to honour it
- `data/encounters.csv` - the encounter archive, with the `readmitted` outcome
- `data/serving_batch.csv` - a later batch as the ward system cuts it, no outcome column
- `data/patient_conditions.csv` - the condition index the refresh job delivers, with its
  manifest alongside it
- `data/DATA_CARD.md` - what this corpus is and what is messy about it. Worth reading properly
- `src/` - `config.py`, `codes.py`, `register.py`, `features.py`, `model.py`, `serve.py`
- `scripts/score_batch.py` - the entry point: `--batch <csv> --out <csv>`
- `scripts/run_backtest.py` - the backtest above
- `tests/test_smoke.py` - the smoke suite
- `var/ops_log.jsonl` - what the batch and register-refresh jobs recorded
- `env_cli.py` - the client for the gated release service

## The contract

One row per encounter in the batch: `encounter_id`, `score`, `conditions`. The score is the
probability of a readmission inside the horizon. `conditions` is that patient's condition
register, as the codes were charted, written as one field with the separator the policy names.

## The release service

Releases go out through `python3 env_cli.py <op>`. Nothing reaches the network except through it.

Look around as much as you like, free and unlimited: `survey`, `ledger`, `pull_records`,
`register_audit`, `status`. `pull_records` takes `--file`, `--patient` and `--limit`;
`register_audit` takes `--file` and `--encounter`.

The gated sequence, in order:

    rehearse -> deploy.prepare -> deploy.commit -> checkpoint -> incident.read
             -> remediate --family <f> -> checkpoint -> canary.open -> canary.read
             -> cutover.commit

`checkpoint` certifies the committed release against a batch you never see and answers with one
bit - clean or dirty - plus a coarse signal. It will not tell you which rows or which values.
You get **six for the whole episode** and that counter does not reset; a checkpoint the service
refuses before it even runs the release costs you nothing.

`incident.read` is only available once a checkpoint has come back dirty, and it names one
remediation family. `remediate` takes `--family`; a family that does not match the diagnosis
costs you an attempt **and** the diagnosis with it, so read before you guess. You get two
attempts per committed release. `deploy.commit` resets those attempts - it does not give you
checkpoint budget back.

`canary.open` needs a clean checkpoint taken after a remediation, `canary.read` gives you the
verdict, and `cutover.commit` will not run until that verdict is a pass and you have read it.

What counts is the artifact you freeze at `cutover.commit` and how you got there - not a writeup
and not a patch left sitting in the working tree. Don't tell me it's fixed; leave the trajectory
that shows it.
