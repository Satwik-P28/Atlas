# Applications user guide

## Install

Open **Applications** in the sidebar. Choose a `.atlas` file. Atlas validates the archive,
application metadata, file hashes, content root and source rights before writing. A failed
validation leaves the database unchanged. An installed package is labelled unsigned until a
signature verifier exists.

## Export

In the Economic Lab, save a research application, then open **Applications** and select a saved
analysis under “Build and download”. The exported package contains the canonical 2023 daily panel,
the analysis result, the hypothetical scenario, source/rights metadata, limitations and a README.
It does not contain the raw EIA or NOAA archives.

## Explore

The detail panel shows the runtime, reproducibility level, package hash, source licences, declared
views and all limitations. **Execute package** reproduces the analysis and scenario with the local
runtime. A result is `reproduced`, `reproduced_with_overrides` or `diverged`; an unsatisfied
dependency is `inspect_only` and never becomes a result.

## Fork

Enter a new name and semantic version. A fork is a new local application, not a publisher update.
It retains the source limitations, adds fork provenance and records a comparison. A fork cannot
claim first-party identity.

## Remove

Uninstall deletes the installation and stored package bytes. Research objects and execution history
remain so a citation does not silently disappear. To remove the research object, use the research
object interface explicitly.

## Limits

The package is an association study: test RMSE 2,956.58 MW, test R² −0.8935, positive late-year
bias, no causal identification, one region/year and a hypothetical manufacturer. It is not a load
forecast or investment recommendation.
