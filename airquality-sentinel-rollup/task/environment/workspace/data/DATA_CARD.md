# Station log -- data card

**Source.** UCI Machine Learning Repository, *Air Quality* (dataset 360), De Vito et al. (2008).
Licence: CC BY 4.0. Hourly records from a roadside monitoring station in an Italian city,
March 2004 to April 2005: five metal-oxide sensor responses, a co-located reference analyser,
and temperature/humidity.

**What ships here.** Rows from that corpus, split by time. No row is synthesised or re-weighted
and no measured value is altered. The only edit is to how the logger's own unmeasured hours are
marked.

| file | rows | what it is |
|---|---|---|
| `history.csv` | 6,549 | the archive, with the reference analyser column |
| `current_batch.csv` | 562 | a later week of hours, no analyser column |

**Columns.** `timestamp`, five sensor channels (`PT08.S1(CO)` .. `PT08.S5(O3)`), `T`, `RH`, `AH`,
and in the archive the reference reading `C6H6(GT)`.

**Known properties of the corpus** (all real, none cleaned up for you):

- The station is a roadside cabinet and the log is what the cabinet wrote. Hours when the
  instrument was down, being calibrated or swapped still appear in the file, because the logger
  writes a row every hour whatever the instrument is doing.
- Sensor responses are raw metal-oxide readings, not concentrations: they drift with temperature
  and humidity and have no physical units.
- Readings are strongly autocorrelated hour to hour, and strongly seasonal across the day.
- The reference analyser `C6H6(GT)` is present in the archive only; live batches carry sensors
  alone.
