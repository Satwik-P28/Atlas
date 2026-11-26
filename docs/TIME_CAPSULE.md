# Atlas Time Capsule v1

A Time Capsule is the complete stored context required to inspect and replay a Quant Lab
run. It is assembled from the immutable `quant_run`, its strategy and experiment objects,
source/evidence references and archive status.

## Contents

* research question and hypothesis (from the experiment);
* instrument identity and MIC;
* raw data source ids, retrieval metadata and first/last session;
* information cutoff and feature definitions/fingerprint;
* strategy document, semver, content hash and model fingerprint;
* simulation configuration: dates, capital, commission, slippage, signal/fill timing,
  benchmark, risk-free rate;
* engine version (`atlas.quant.reference.v1`);
* portfolio ledger, trades, equity curve, drawdown curve and metrics;
* independent accounting reconciliation;
* result fingerprint;
* source archive status: `archived`, `external_provider_only` or `no_evidence`;
* reproducibility status and unresolved limitations.

## Reproduction statuses

| Status | Meaning |
|---|---|
| `fully_reproducible` | all required source bytes are archived and verified by SHA-256 |
| `provider_dependent` | the provider is reachable but exact source bytes are not archived |
| `numerically_reproducible` | stored processed inputs can reproduce numbers, but original bytes cannot be checked |
| `limited` | data, actions or archive coverage are incomplete |

The current real IBM dataset is `provider_dependent` / `external_provider_only`: no vendor
bytes are bundled, and the raw Alpha Vantage rows do not prove their 2015 display vintage.
The capsule says this instead of claiming full historical reproducibility.

## Replay

`POST /api/quant/runs/{run_id}/replay` reloads the persisted strategy and config, executes
the reference engine again against the same database, and compares the SHA-256 result
fingerprint. A mismatch is a failure, not a warning. Replay does not use the browser and
does not re-fetch the vendor.

## Inspecting a decision

The run stores each trade with decision date, fill date, reference and fill price, quantity,
commission and reason. The signal series and equity curve are exposed in the Lab’s advanced
diagnostics. If a fill has no valid next open, the trade is skipped with the reason and the
capsule discloses the affected session; the engine never substitutes a same-close fill.

## Comparison

`GET /api/quant/compare?run_ids=…` returns aligned metrics, costs, trade counts and
fingerprints. Comparing two runs with different strategy versions or costs is allowed, but
the response labels the differing configuration rather than implying a controlled
experiment. A true parameter experiment must store the parameter variation and attempt
count on the experiment object.

## Limits

No bitemporal replay of vendor UI values, no order-book replay, no live venue state. A
capsule reproduces the Atlas computation on stored inputs; it does not recreate the market.
