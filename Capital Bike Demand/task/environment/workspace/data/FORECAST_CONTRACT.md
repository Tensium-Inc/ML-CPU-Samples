# Forecast contract

Normalize every visible history export according to `schema_registry.json`. Apply its delimiter,
column rename, and scale rules, concatenate the canonical columns, deduplicate by integer
`instant`, and sort by `instant`. The result has 11,539 unique rows. Weather values return to the
source scale from 0 through 1.

The runtime calls:

```bash
python3 scripts/predict.py --history HISTORY.csv --requests REQUESTS.csv --output OUTPUT.csv --seed 2026
```

Keep this command and output contract. History is a canonical labeled CSV. Requests contain the
same issue-time fields but omit `cnt`, `casual`, and `registered`. Output must be deterministic,
ASCII, and contain exactly these columns in this order:

`instant,predicted_cnt,lower_80,upper_80`

Every request identity appears exactly once. Values are finite and nonnegative, with
`lower_80 <= predicted_cnt <= upper_80`. The implementation must be invariant to independent
history and request row permutations.

Use chronological validation only. All training dates must precede the evaluation dates. The
public March and April folds are rehearsal evidence, not the production discriminator. The
protected runtime adds later waves after the forced cache recovery. Calibrate the 80 percent
interval from forward residuals without terminal labels.
