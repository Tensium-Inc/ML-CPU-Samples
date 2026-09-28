# Fleet grounding risk: specification

This says what the service is for and what each published quantity means. It is written
the way the operations desk describes its own model, in business terms.

**It gives no formulas.** Where a definition could reasonably be written more than one way,
the published backtest settles it: `reference/scores_reference.csv` is what the service
produced on that run and `reference/run_report.json` is the summary it wrote beside it. A
correct rebuild reproduces both.

---

## 1. Run shape

A run reads the export, fits on the **fit window** and scores the **score window**, both
named in the run configuration and inclusive of the last second of their end date.

Flights are processed in `flight_id` order. Everything the service knows about an aircraft,
a station, a route or an operator is learned from the **fit window only**.

## 2. What the service is predicting

A flight is **at risk** if the aircraft that flew it is grounded within
`labelling.window_days` days of leaving. Groundings are exported separately, in
`data/groundings.csv.gz`; they are not in the flight log, because a grounded flight never
operated.

## 3. What the service fits on

The service does not fit on every flight in the fit window.

A flight is only usable for fitting if its outcome is already settled by the history the
service is allowed to read. Which flights that leaves out, and on what grounds, is part of
the rebuild.

## 4. What the features mean

Thirty-eight quantities are published, in the order `src/fleetrisk/assemble.py` declares them.

**Departure.** When the flight was scheduled out: hour, day of week, month, week of year,
whether it fell at a weekend, and how far into the exported period it sits.

**The leg.** What the flight looks like on paper and how it actually ran: distance, block
time, taxi out, departure and arrival delay, whether it was diverted, and the average speed
its block time implies.

**The aircraft on paper.** From the fleet register: which operator it belongs to, whether it
left from its home station, and how many aircraft that operator runs.

**The stations.** From the station reference: the state at each end and whether both ends
sit in the same state.

**Aircraft record.** What the fit window knows about the airframe: how much it flew, how
often it was grounded, how often that was per flight, how long since the last grounding,
how long it has been in the exported fleet, and its usual departure delay.

**Station record.** The same idea for the airports at each end: how much flew from there and
how often aircraft based there were grounded.

**Reliability.** How often flights of this operator, this route and this departure station
turned out to be at risk. A rate over thin history is unreliable, so it is pulled toward the
fleet rate in proportion to how little history stands behind it; `encoding.smoothing` sets
how hard.

**Recent form.** How the aircraft has been behaving lately rather than over the whole
window: its grounding rate over the last fortnight, how long since it last flew, and its
departure delay over its last `recent.flights` legs.

**Against the fleet.** How the aircraft, its departure station and its operator sit against
the fleet rate.

## 5. Rows with no history behind them

Plenty of airframes go the whole fit window without being grounded once. Their "how long
since the last grounding" is not a large number and it is not zero; there is no such date to
measure from. The service marks those with **-1** rather than inventing a gap.

A live run also carries legs the fit window has nothing at all on: an airframe that joined
after the history ends, a station or a route that never appears in it. Those legs are still
scored. Wherever a quantity is a rate, an average or a span taken over history the leg does
not have, the service puts the fleet-wide level for that quantity in its place, so the leg
sits at the fleet average rather than at zero. Counts are the exception. An aircraft the
history has never seen has flown no flights and been grounded no times, and those are
recorded as such. Time since the last grounding follows the paragraph above.

## 6. Model

Gradient boosting over the thirty-eight features, fitted on the fit window against the label, using
`model.seed`, `model.max_iter`, `model.learning_rate` and `model.max_depth`. Values that are
not finite are treated as zero before fitting.

## 7. Output

One row per scored flight, in `flight_id` order, carrying `flight_id`, `tail_number`,
`departed_at`, `risk_score` and `watch`.

`risk_score` is the modelled probability that the flight is at risk, rounded to six decimal
places. `watch` is 1 when the unrounded score is at least `scoring.watch_threshold`.

A run also writes a summary beside the scores. The summary is not graded.
