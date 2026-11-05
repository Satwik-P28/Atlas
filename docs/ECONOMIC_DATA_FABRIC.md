# Economic data fabric

Status: implemented for two public source families on schema 9. It extends, rather than
replaces, the Temporal Evidence Kernel and source registry.

## Sources

| Source | Role | Data | Rights |
|---|---|---|---|
| `eia-930` | Regional electricity | Hourly ERCOT `Demand` (MW) from six-month balance files | U.S. Government public domain; redistribution permitted |
| `noaa-ghcn` | Weather observations | GHCN-Daily `TMAX`, `TMIN`, precipitation for two Dallas stations | U.S. Government public domain; redistribution permitted |
| `atlas-assumption` | Non-evidence parameters | Hypothetical company/facility/exposure labels | Internal research assumption; never evidence |

Raw archives are downloaded by `scripts/fetch_phase7_data.py` into ignored `var/phase7/raw/`.
The committed result is a compact derived fixture, `fixtures/phase7/weather_demand_2023.csv`,
with SHA-256 `987feb4933df29c119d5d2d9f1f5e49c1439fe9d10c33e899a78179e0963314f`.

## Declared series

| Series | Unit | Frequency | Geography | Class |
|---|---|---|---|---|
| `ECON-EIA-ERCO-DEMAND-D` | MW (daily mean) | daily | ERCO | observed |
| `ECON-NOAA-DFW-TMAX-D` | °C (daily mean of TMAX/TMIN) | daily | Dallas–Fort Worth | observed |
| `ECON-NOAA-REDBIRD-TMAX-D` | °C (daily mean of TMAX/TMIN) | daily | Dallas–Fort Worth | observed |

Every series records source, canonical URL, unit, time zone convention, rights,
redistribution, vintage policy and update cadence.

## Unit and time conventions

* EIA `Demand` is reported in MW. The panel retains daily mean, peak, minimum and summed MWh.
* NOAA tenths of degrees Celsius are converted to °C by division by 10.
* NOAA daily mean is `(TMAX + TMIN) / 2`; no infilling is performed.
* EIA `Data Date` is treated as the local operating day. NOAA `DATE` is the station local day.
* DST days keep 23/24/25 hourly EIA observations; demand is an average, not a fixed 24-hour sum.
* Missing station measurements do not become zero. A day without the required demand and
  station fields is reported as partial and excluded from the model panel.
* Megawatts, megawatt-hours, °C, dollars and rates are never silently interchanged. The
  scenario uses explicit conversion through compiler operators.

## Availability semantics

Every observation records:

* `period_start` / `period_end` — the observed interval, not the retrieval time;
* `observed_at` — when Atlas received the archive;
* `availability_time` — the evidenced availability instant;
* `availability_precision` — `exact`, `date` or `unknown`;
* `availability_basis` — a human-readable statement of what the timestamp means;
* `published_at` — null when the source does not expose a historical publication time;
* `vintage` and `revision_seq`.

For this slice, availability is the **exact archive retrieval instant** with basis
`archive retrieval instant; not a historical publication vintage`. This is a retrieval proxy.
It is not evidence that a researcher could have seen the value on the operating date.

`public_available` excludes observations whose evidenced availability exceeds the cutoff.
`atlas_ingested` uses the ingestion time and is only for internal reconstruction. If no
complete rows remain, the API raises a `MissingDataError` with the cutoff, excluded count and
a correction hint. It never fills the interval with later data.

## As-of behavior

A query at `2023-12-31T23:59:59Z` returns **no** complete observations because the archive was
retrieved in 2026. This is correct under the declared semantics. A query after the retrieval
instant reproduces 365 rows. Replay with the 2023 cutoff returns
`status: insufficient_evidence` and explicitly states that no validated vintage is present.

## Quality checks

The builder and panel loader verify:

* 365 expected dates and 8,760 EIA hourly records for ERCO;
* no duplicate series/day pair beyond intentional revisions;
* TMAX ≥ TMIN;
* positive demand;
* peak ≥ mean ≥ minimum;
* required fields present for a complete model row;
* station disagreement is recorded, not automatically resolved.

The panel reports 0 daily anomalies and 1 preserved metro-scale station conflict.

## Retention and rights

Public-domain source bytes are not needed in Git; only the derived fixture and its manifest
are committed. The manifest preserves provider names, official URLs, file hashes, transforms,
rights and limitations. Restricted data is not introduced by this phase.

## Not implemented

ALFRED vintage histories, EIA API v2 scheduled retrieval, SEC filing text extraction, GDELT,
trade/logistics series, facility registries, demographic panels, environmental hazards and
real-estate parcel data. These require their own rights and timing contracts and were not
added merely to increase a source count.
