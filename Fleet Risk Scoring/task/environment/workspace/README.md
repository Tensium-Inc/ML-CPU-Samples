# Fleet grounding risk service

Maintenance control runs this against the overnight operations export. It puts a number on
every leg that flew: how likely is it that this airframe gets grounded in the next few days.
Anything over the watch threshold gets pulled forward for a check before it strands a crew.

    python3 run_scoring.py --config configs/reference.yaml --out out/reference

## Layout

    run_scoring.py        nightly entry point
    SPEC.md               what the service computes, and what each quantity means
    configs/              run configuration, one file per scheduled run
    data/                 the overnight export
    src/fleetrisk/        the service
    reference/            the published output from the accepted backtest
    tools/                helper for comparing two runs

## The export

Two feeds, and they do not overlap.

`data/flights.csv.gz` is the flight log: one row per leg that actually operated, with the
schedule, the delays and the airframe that flew it.

`data/groundings.csv.gz` comes off the ops system instead. It records cancellations, with
the tail number and the time. A cancelled leg never operated, so it is not in the flight log
at all, and the two feeds have to be matched up before you can say which flights turned out
badly.

`data/fleet.csv` is the airframe register and `data/stations.csv` the airport reference.
Both are slow moving.

The export is a rolling pull. It starts at a fixed date and stops on whichever day it was
taken, which is worth keeping in mind when reading anything derived from it.

Airframes join and leave the fleet and stations come and go, so a live run will always
carry legs whose aircraft or departure station the history has never seen. `SPEC.md` says
what the desk does with those.

## The two scheduled runs

The backtest, `configs/reference.yaml`, is the one that has been signed off. What it
produced last time is under `reference/`: the scores themselves and the run summary.

The live run, `configs/current.yaml`, fits on the same history and scores a stretch of flying
from well after the end of it. Nothing is published for it, so the only run you can check
yourself is the backtest.
