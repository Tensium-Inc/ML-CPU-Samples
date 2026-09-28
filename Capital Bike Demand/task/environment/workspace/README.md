# Capital Bike release incident

This workspace contains the editable candidate for a September through December 2012 hourly
demand forecast. Read `data/DATA_CARD.md`, `data/FORECAST_CONTRACT.md`, and
`data/schema_registry.json`, then use `python3 env_cli.py help`.

The history exports deliberately differ in delimiter, names, units, and duplicate behavior. The
starter pipeline runs, but its profile is not a trustworthy production forecast. Operations must
be performed through `env_cli.py`; the service state is outside this workspace.

Useful local commands after the investigation commitment are:

```bash
python3 -m unittest discover -s tests
python3 scripts/run_backtest.py
```

Do not create the final CSV yourself. `submit` writes the environment-owned terminal artifact.
