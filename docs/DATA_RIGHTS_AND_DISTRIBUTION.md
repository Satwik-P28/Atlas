# Data rights and distribution

Rights are enforced in the backend before packaging, installation, export and sharing. A React
warning is not an enforcement boundary.

## Decision table

| Declared redistribution | Ingest | Local analysis | Package/export/share/host/redistribute |
| --- | --- | --- | --- |
| `public_domain` | yes | yes | yes |
| `permitted` | yes | yes | yes |
| `restricted` | yes | yes | no |
| `user_responsibility` | yes | yes | no, until a separate grant exists |
| `not_applicable` / unknown | yes | yes | no |

`DataRightsEngine.decisions_for_metadata` returns a decision per action with a reason.
`assert_packaging` fails closed. Installation re-evaluates the application's source declarations
and data-bearing file records; a forged manifest cannot turn restricted source bytes into an
allowed payload. Transforming or aggregating data does not remove contractual obligations.

## Source attribution

Every source entry records `source_id`, provider, licence, redistribution status, rights basis
and snapshot paths. The source document in the package repeats the decisions. A package with an
unknown source identity is rejected with `rights_violation`; Atlas does not guess a licence.

## First-party economic package

EIA-930 and NOAA GHCN-Daily are U.S. Government public-domain sources with redistribution
`permitted`. The flagship package includes a canonical daily panel and analysis/scenario outputs,
not the raw provider archives. It is therefore `computationally_reproducible`, not fully
reproducible from source bytes.

The `atlas-assumption` registry is used only for explicitly hypothetical company exposures and is
not packaged as observed evidence. No private-location, real-estate, vendor-licensed or
credentialed data is included.

## Historical exposure

Restricted vendor market files were removed from the current tree, but they remain
reachable in earlier commits (`6920d0a` nasdaq series, `d0e4540` Alpha Vantage manifest).
That is a distribution exposure for anyone with repository access. CI refuses newly tracked
files matching `nasdaq_*`/`alphavantage`, and the remediation options — retain-and-restrict
or rewrite history with full coordination — are recorded in
[HISTORICAL_DATA_REMEDIATION.md](HISTORICAL_DATA_REMEDIATION.md). No rewrite has been
authorized or attempted.
