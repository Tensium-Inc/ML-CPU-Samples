# Private authoring files

- `source/hour.csv` is the original UCI hourly table.
- `generate_workspace.py` deterministically creates visible mixed exports, protected runtime waves,
  terminal requests, and verifier labels.
- `calibrate.py` runs three independent direct positives, one bounded-revision positive,
  adversarial negatives, malformed output cases, repeatability checks, and the strict reward
  contract without paid model calls.
- `negative_controls/` contains trajectory, model, isolation, timeout, and tamper controls.
- `package.sh` stages the task in a temporary directory and excludes `_private`.
