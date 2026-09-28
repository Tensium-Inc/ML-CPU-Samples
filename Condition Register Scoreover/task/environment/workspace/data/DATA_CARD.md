# Encounters - data card

**Source.** UCI Machine Learning Repository, *Diabetes 130-US hospitals for years 1999-2008*
(dataset 296), Strack et al. (2014). Licence: CC BY 4.0. Ten years of real inpatient encounters
for diabetic patients across 130 US hospitals.

**What ships here.** Verbatim rows from that corpus, split by position in the corpus's own
encounter ordering - no rows are synthesised, edited or re-weighted.

| file | rows | what it is |
|---|---|---|
| `encounters.csv` | 42,741 | the encounter archive, with the `readmitted` outcome |
| `serving_batch.csv` | 8,548 | a later batch as the ward system cuts it, no outcome column |
| `patient_conditions.csv` | 112,493 | the condition index the refresh job delivers, with its manifest |
| `code_groups.csv` | 867 | the code table the refresh job keys the register on |

**The delivered artifacts.** `patient_conditions.csv` and `code_groups.csv` are not part of the
UCI corpus. They are what the register-refresh job writes, and they are described by
`patient_conditions.manifest.json` and by the `register_refresh` entries in `var/ops_log.jsonl`.
Both are derived from the encounter columns below, so anything either of them asserts can be
checked against those columns.

**Columns.** 50 per encounter: identifiers (`encounter_id`, `patient_nbr`), demographics,
administrative ids (`admission_type_id`, `discharge_disposition_id`, `admission_source_id`),
utilisation counts (`time_in_hospital`, `num_lab_procedures`, `number_inpatient`, ...),
`diag_1`/`diag_2`/`diag_3`, `number_diagnoses`, 24 medication columns, and `readmitted` in the
archive only.

**Known properties of the corpus** (all real, none cleaned up for you):

- `encounter_id` increases with time. The corpus carries no timestamps, so the encounter
  number is the only chronology there is.
- `?` is the missing-value marker. It is common in `weight`, `payer_code` and
  `medical_specialty`, and rare in `race` and the three diagnosis columns (0.03%, 0.44%, 1.75%).
- `diag_1`, `diag_2` and `diag_3` hold the conditions recorded at that admission: at most
  three per encounter, most specific first, as ICD-9 codes. The corpus uses the numeric
  series, the supplementary V and E series, and decimal subdivisions (`250.83` and `250.8`
  are different codes).
- `number_diagnoses` is the count the coder entered on the chart. It is not the number of
  codes in the three diagnosis columns and it is frequently larger.
- `number_inpatient`, `number_outpatient` and `number_emergency` count visits in the year
  preceding the encounter. They are counts of visits; they say nothing about what was
  diagnosed.
- `readmitted` has three values: `<30`, `>30` and `NO`. Only `<30` is a 30-day readmission.
- Class balance is uneven: about 11% of encounters are followed by a readmission within 30
  days.
- A patient number is stable across the whole corpus. `encounter_id` is unique; `patient_nbr`
  is not.
