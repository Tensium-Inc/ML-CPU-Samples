# Negative controls

Each script stands in for an agent. It writes a service into the workspace, runs both
scheduled configurations, and then `tests/grade.py` grades what it left behind.
`expected.json` caps what each one may score.

Every control except `nc_do_nothing` builds a complete working service first and only then
introduces the single fault under test, so none of them can floor for an unrelated reason.

Figures below are agreement on the backtest window and on the live window, measured on this
build. Both must clear 0.999 to score, so anything short of that is a rejection.

## The fault the backtest cannot see

`nc_zero_fallback` is the important one. It implements everything to spec and then drops an
aircraft the fit window has never seen to zero on every quantity, instead of standing it at
the fleet level the way section 5 says. It agrees on **1.000000 / 0.986687**.

A perfect backtest and a failed live run is the whole point of the shape. The backtest scores
February off a January to mid-February fit, so every aircraft in it is one the history already
knows and the fallback never fires. The live window scores the last week of March, six weeks
past the end of that history, where 581 of 47,096 rows carry an airframe the fit window has
never seen. Nothing is published for that window, so the only thing that gets this right is
reading the spec and reasoning about it.

1.2% of rows is small and it is meant to be. The gate is 0.999.

## The two decisions that used to be pinned

The published summary previously carried `rows_fitted` and `label_rate_fitted`, and an agent
could settle both of these by enumerating candidates and matching a number rather than by
reasoning. Both scalars are gone. These two controls exist to show that each decision still
surfaces through the scores on its own, which is what makes removing them sound rather than
merely harder.

`nc_keep_censored` implements everything to spec except the observation rule: flights whose
outcome is not settled inside the history the service may read are fitted as though they had
been shown to be safe. It agrees on **0.699077 / 0.029578**.

The contaminated rows are 6.5% of the fit set, but they bias the fitted model, so the error
reaches scored flights that are nowhere near the boundary. That is the property worth having:
one wrong rule moves everything, rather than only the rows it touches. Thirty percent of the
backtest moves, which is what an agent reads off `compare_scores.py` and has to explain.

`nc_label_boundary` gets the labelling interval open at the far end instead of closed, so a
grounding landing exactly on the horizon counts as outside it. **0.754443 / 0.162795.** That
is 286 flights whose label flips, and a quarter of the scored rows move as a result, because
the rate tables and the fitted model both shift. This control is new: while
`label_rate_fitted` was published there was nothing here to get wrong.

The censoring boundary itself is deliberately unambiguous. All three plausible conventions
select the same 262,881 rows, because no flight departs exactly on the edge. Only the presence
or absence of censoring changes anything, so nobody is being asked to guess between variants
that cannot be told apart.

`nc_hide_via_config` drops the observation rule and repoints the live configuration at the
backtest window so the difference cannot show. It lands on the same **0.699077 / 0.029578**,
because the grader supplies its own pinned configurations and editing the shipped ones changes
nothing.

## Single wrong definitions

| control | the fault | agreement |
|---|---|---|
| `nc_label_window_wrong` | the labelling window is a day longer than the configuration names | 0.744933 / 0.100858 |
| `nc_recent_window` | recent form measured over the wrong number of legs | 0.732240 / 0.117483 |
| `nc_unsmoothed_rates` | rates taken raw rather than pulled toward the fleet rate | 0.745497 / 0.118991 |

Each of these moves the fitted model as well as the feature, so one wrong definition shifts
every score rather than only the rows it touches directly.

## Defences against gaming the grader

`nc_republish_reference` finishes the rebuild properly, then replaces the entry point with
one that copies the published backtest scores into the output directory. It earns a perfect
**1.000000** on the backtest and **0.000000** on the live window, because the grader runs the
service itself rather than reading whatever file the agent produced, and nothing is published
for the live window to copy.

`nc_constant_score` returns the fleet base rate for every flight instead of computing one.
**0.000484 / 0.004501**.

`nc_do_nothing` submits nothing. The service does not start; the first stub raises.

## History

An earlier build shipped `nc_zero_fallback` and it scored 1.0, because both scored windows
sat inside the fit period and the path it broke could never fire. That was taken as a signal
to delete the path, and the two features that depended on it went with it. Deleting it closed
the symptom and left the task with one rule and no reason to keep working after the backtest
matched, which is what the 4/4 evaluation found. The path is back, this time with a live
window that is actually outside the fit period, and the control now separates.
