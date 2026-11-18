# Real-time vintage dataset (generated)

Built by `scripts/research/rtds_build.py`. Do not hand-edit.

## Cohort A: BEA quarterly expenditure components

* series: GDPC1, GPDIC1, GCEC1, EXPGSC1
* source: BEA via ALFRED/FRED (Federal Reserve Bank of St. Louis)
* vintage files fetched: 1338 (1338 from cache, 6.5 MB)
* manifest digest: `fb7fd332f7614dc00155f1aebc16e1f4829d70150e230e2c467493c6217cfb08`

| split | events | with a changed input | median changed inputs |
|---|---|---|---|
| train | 52 | 52 | 4 |
| pilot | 8 | 8 | 4 |
| test | 38 | 38 | 4 |
| holdout | 4 | 4 | 4 |

| category | test events |
|---|---|
| annual_benchmark_window | 10 |
| later_estimate | 28 |

## Cohort B: BLS monthly payroll employment

* series: PAYEMS, MANEMP, USCONS
* source: BLS via ALFRED/FRED (Federal Reserve Bank of St. Louis)
* vintage files fetched: 1009 (1009 from cache, 15.0 MB)
* manifest digest: `ce2eca6a224a94c254d2aee19b30dbaeffac107cc94bb635e736d4fec2e2f728`

| split | events | with a changed input | median changed inputs |
|---|---|---|---|
| train | 156 | 156 | 3 |
| pilot | 24 | 24 | 3 |
| test | 114 | 114 | 3 |
| holdout | 12 | 12 | 3 |

| category | test events |
|---|---|
| annual_benchmark_window | 10 |
| later_print | 104 |
