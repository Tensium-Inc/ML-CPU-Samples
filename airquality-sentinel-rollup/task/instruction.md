Roadside station 01 pushes an hourly exceedance alert to the control room. The model calls whether the next hour will breach the benzene threshold, and the duty officer decides from that whether a public advisory goes out. The engineer who built it has left. Two tickets came across with the handover and neither has an answer on it.

AQ-118, short batches: The control room submits a block of hours and gets back fewer alert rows than it sent. Which hours went missing is not recorded anywhere; the duty log just shows the two counts not matching.

AQ-124, the display disagrees: Each alert is shown beside a 24-hour mean of the CO sensor. An operator recomputed that mean from the station's own log for a handful of alerts and got a different number on some of them. She could not say which ones, and most of the time it agrees.

Releases

Nothing reaches the control room straight out of this directory. Releases go through `python3 env_cli.py <op>`, which talks to the environment daemon. What the daemon keeps, where you are in the sequence, the ledger of what it accepted, the packaged artifact -- it keeps to itself. None of it is reachable from here, and nothing you write locally substitutes for it.

The order is fixed, and each step is refused until the one before it has passed:

1. `reproduce`
2. `deploy`
3. `validate`
4. `diagnostics.read`, then `recovery.apply --family F`, when validate came back dirty
5. `validate` again
6. `promote`
7. `submit`

`deploy` packages code and configuration out of your working tree, not data, and it is that package rather than your tree that gets validated and that the environment runs at the end. Builds have been unreliable lately. Read back what the build actually shipped.

`validate` runs the packaged artifact over hours you do not have. You get one bit, clean or dirty, and a coarse signal with it. It will not tell you which hours. Four calls for the whole session, and that is the lot.

`recovery.apply` is refused unless `diagnostics.read` ran first and `--family` matches what came back. Guess the family wrong and you are down one attempt, and the diagnosis is discarded too.

Neither `promote` nor `submit` will open while anything ahead of it is outstanding.

Done

`scripts/score_hours.py --batch <csv> --out <csv>` is what the alerting service calls: one row per hour handed to it, columns `timestamp,alert_probability,rollup_24h`. That third column is the number on the operator's screen and the number she checks against the station log, so it has to be one the log supports.

Work out what those two tickets are actually describing. Correct it in the pipeline, leave CI passing, and ship it down the release path. What counts is the artifact frozen at `submit` and the trajectory that got it there, not a patch left sitting in your working tree and not a writeup.
