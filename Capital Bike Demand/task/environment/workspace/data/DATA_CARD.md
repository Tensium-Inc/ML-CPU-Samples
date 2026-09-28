# Data card

The records come from the hourly table of the UCI Bike Sharing dataset.

- Source page: https://archive.ics.uci.edu/dataset/275/bike+sharing+dataset
- DOI: 10.24432/C5W894
- License: Creative Commons Attribution 4.0 International
- Source SHA256: e03de4ee4ef4dc376ac6e04bf829673c6269e8eba5c60fa121640fa2f829504f
- Full source: 17,379 hourly records from 2011-01-01 through 2012-12-31
- Visible labeled history: 11,539 unique records through 2012-04-30
- Runtime validation advances: May through August 2012
- Terminal horizon: 2,888 records from 2012-09-01 through 2012-12-31

`cnt` is total hourly rentals and equals `casual + registered`. All three columns are outcomes.
They are available in labeled history but unavailable at issue time and forbidden as predictors.
The normalized weather observations in a request are available at the hourly issue time. Missing
clock hours are source gaps and must not be invented. `instant` is the stable row identity.
