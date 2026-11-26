# Market-data rights and redistribution

This document records what Phase 6 actually used, what it only catalogued, and what may be
committed. It is an engineering record, not legal advice.

## Policy

1. A provider is not “free” merely because its documentation shows an example request.
2. Credentials belong in environment variables or a local secret store, never in source,
   fixtures, logs or a commit.
3. Restricted vendor bytes are cached only under `var/`, which is ignored by Git.
4. The repository distributes code and public-domain fixtures, not a vendor history.
5. A user importing CSV/Parquet is responsible for the entitlement and must declare it.
6. When rights are unclear, the UI and API expose the limitation instead of implying a
   redistribution grant.

## Providers relevant to Phase 6

| Provider | Access assessed | What Phase 6 did | Rights / redistribution |
|---|---|---|---|
| EODHD demo | Documented demo token; five symbols resolved | Implemented adapter and local cache; 3,760 daily bars | Vendor demo terms; local research only; **restricted**, no redistribution asserted |
| SEC EDGAR | Public fair-access API with a User-Agent | Existing Phase 1 source, not re-ingested for the panel | U.S. federal government work; public domain |
| U.S. Treasury | Public CSV | Existing Phase 5 official 2024 curve | U.S. federal government work; public domain |
| FRED / ALFRED | Public observations; ALFRED vintages require API access | Catalogued, not used for OHLCV | Series-specific attribution/terms; treat as restricted until checked |
| Tiingo free tier | Personal token and terms | Not used | Do not assume redistribution |
| Alpha Vantage | Demo/free endpoints have limits | Existing Phase 2 IBM demo observation | Existing provenance retained; no new redistribution |
| User CSV/Parquet | User-supplied local file | Existing import boundary; Phase 6 adapter contract only | User responsibility; Atlas records the declaration |

No token is hard-coded. The demo builder uses the provider's documented `demo` token only
for the supported sample symbols, and refuses to continue when a symbol has fewer than 500
rows or the response is not a JSON array.

## What is committed

Committed:

* adapter code and request construction;
* source metadata, rights labels and coverage/quality algorithms;
* synthetic fixtures whose provenance is explicit;
* public-domain SEC and Treasury fixtures already present in the repository;
* aggregate results and hashes, not vendor bytes.

Not committed:

* `var/atlas-phase6.db`;
* `var/phase6-eodhd/*.json`;
* any vendor token, cookie, API key or downloaded bulk file;
* model artifacts that embed restricted observations beyond what the research object
  documents. The JSON artifact contains coefficients, not vendor rows.

The source hash lets a user detect a different local panel. It is not a redistribution
licence.

## Reproducing the local demo

```bash
.venv/bin/python scripts/build_phase6_db.py --db var/atlas-phase6.db --force --offline
```

`--offline` requires the already-cached files. A clean checkout without them has no vendor
rows; the Learning Lab then reports that no dataset is present rather than substituting
synthetic securities.

## Export and user responsibility

The research memory, audit and model artifacts are designed to be inspectable. Exporting a
panel or vendor-derived series is the user's responsibility. The application marks the
dataset `restricted` and the auditor emits `redistribution_restricted`. A UI export control
must not be read as a licence grant.

## Unresolved

* No legal review of a production redistribution agreement.
* No provider terms snapshot with a stable hash.
* No automatic entitlement check for user imports.
* No point-in-time vendor-vintage archive.
