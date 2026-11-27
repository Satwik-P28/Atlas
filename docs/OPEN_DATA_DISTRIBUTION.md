# Open data distribution

Atlas separates four things that are often conflated:

1. a **dataset discovered** in the registry;
2. a **snapshot acquired** into the content-addressed store;
3. an **observation integrated** into a queryable index;
4. a **package published** under a verified licence.

Only step 4 creates a redistribution obligation, and it is the only step gated by the
rights policy.

## Channels and verified limits (checked 2026-11-24)

| Channel | Limit relevant to Atlas | Retention | Cost | Decision |
| --- | --- | --- | --- | --- |
| Git history | Practical repo limits; no bulk binaries | permanent | free | Small reference datasets and manifests only. Never multi-GB archives. |
| GitHub Releases | Each asset **< 2 GiB**; up to **1000 assets per release**; no total size or bandwidth limit | permanent while release exists | free | **Primary channel** for versioned archives, split at < 2 GiB. |
| GitHub Actions artifacts | Per-artifact limits; repository retention configurable | default **90 days**, max 90 for public repos | free (within plan) | Build evidence, validation reports and short-lived smoke outputs. Never the long-term distribution channel. |
| Hugging Face datasets | Free public storage is **best effort**; recommended < 100k files and < 200 GB per file; no per-repo hard cap, quota is account-wide | while hosted | free tier | Optional mirror for a package that exceeds a practical Release layout, only with explicit approval. |
| External object storage | Provider-specific | provider-specific | may incur charges | Not used; requires approval. |

No paid infrastructure is created by any workflow in this repository.

## Selected design

**Local-first archives, published as GitHub Release assets.**

A package is a single `tar.zst` built by `scripts/build_open_data_package.py`:

```
PACKAGE_MANIFEST.json     datasets, licences, attribution, file hashes, raw bytes
ATTRIBUTION.md            human-readable attribution
registry.json             the reviewed registry used to build the package
datasets/<id>/<snapshot>/ files + manifest.json + manifest.sha256
```

The builder:

* verifies every stored file hash before packaging;
* includes only `public_domain`, `permissive` and `redistributable_conditions` entries;
* refuses an entry unless `redistribution`, `commercial_use`, a current review and
  cleared exclusions all hold;
* copies exact source bytes, never a transformed substitute;
* writes a `.sha256` sidecar for the package;
* uploads nothing.

Packages are built **one dataset per asset**, because a multi-GB selection can exceed the
2 GiB GitHub asset limit even when each dataset is smaller. `data/open_data/releases/index.json`
records each asset's snapshot, source manifest hash, package hash and rights decision.

```bash
python scripts/build_open_data_package.py \
  --dataset sec.companyfacts \
  --out dist/sec.companyfacts.tar.zst \
  --index dist/sec.companyfacts.index.json \
  --level 3
python scripts/index_open_data_release.py --packages dist \
  --out data/open_data/releases/index.json --release-tag open-data-2026-11
```

A snapshot manifest records the rights class it had when the bytes were fetched; the
registry decision supersedes it. After a reclassification, re-derive the rights fields of
the published index (and of the measured artifact) from the registry without rebuilding or
re-acquiring anything:

```bash
python scripts/index_open_data_release.py --refresh-rights
python scripts/open_data_phase2_metrics.py --refresh-rights
```

Both keep the superseded class as `manifest_rights_class` next to the current
`rights_class`; package and manifest hashes are untouched.

## Clean-install lifecycle

A downloaded asset is untrusted input. `atlas data install` resolves the asset from the
release index (or the GitHub API with `--online`), refuses a dataset whose *current*
registry decision denies public distribution, reports the required space before the first
byte, downloads only what is missing, resumes a partial file, re-hashes it, and only then
restores it. Restore verifies the package checksum, the embedded `PACKAGE_MANIFEST.json`,
every file hash and the stored manifest before publishing a snapshot. The original
snapshot id is preserved, so the restore is byte-identifiable, and restoring the same
package twice reports `already_present` instead of replacing it.

```bash
atlas data releases                     # discovered / approved / acquired / packaged / uploaded / verified / restored / integrated
atlas data releases --online            # add what the GitHub API actually returns
atlas data install sec.company_tickers  # download, verify, restore
atlas data install treasury --index data/open_data/releases/index.json
atlas data install sec.financial_statement_data_sets --period 2024q1   # one quarter only
atlas data install --all-open           # every approved dataset with a published asset
atlas data inventory                    # committed manifest vs stored bytes
atlas data verify                       # deep hash check of every snapshot
atlas data repair                       # recover staging, reinstall from a release
atlas data update                       # published snapshots newer than local
atlas data storage                      # blob bytes, deduplication, quarantine
```

Everything above works offline after installation: the store is on local disk and queries
never reach a provider.

Publication is `.github/workflows/open-data-release.yml`. Packaging runs read-only;
publication runs in a separate job inside the protected `open-data-release` environment
with `contents: write`, creates a draft release, and publishes only on an explicit
`mode: public` dispatch. Ordinary CI never uploads data. The full audit is in
[`OPEN_DATA_RELEASE_SECURITY.md`](OPEN_DATA_RELEASE_SECURITY.md).

## Phase I package command (single archive)

```bash
python scripts/build_open_data_package.py \
  --out dist/atlas-open-data-2026-11-24.tar.zst \
  --max-bytes 2000000000
sha256sum -c dist/atlas-open-data-2026-11-24.tar.zst.sha256
```

## Multipart packages

A dataset too large for one 1.9 GB asset is packaged natively, not with a generic `split`.
`atlas.open_data.multipart` writes an index with a per-part SHA-256 and the whole-source
SHA-256, and supports two modes:

```bash
# exact reconstruction: deterministic byte slices of the original provider archive
python scripts/build_open_data_multipart.py \
  --dataset sec.financial_statement_data_sets --mode bytes --out dist

# selective install: one package per reporting period (2024q1, 2023q4, ...)
python scripts/build_open_data_multipart.py \
  --dataset sec.financial_statement_data_sets --mode period --out dist
```

`bytes` mode reassembles to the original file byte for byte. `period` mode preserves each
archive member exactly and lets a user install one quarter, so an install of one quarter
downloads one quarter's package. Missing parts are rejected before anything is written;
a corrupt part fails its own hash; a restore is staged and renamed atomically, so an
interrupted run leaves nothing installed.

## Publication procedure (explicit authorization required)

1. Build the package and verify its SHA-256.
2. Run `python scripts/audit_open_data.py --live --samples --strict`.
3. Confirm every included dataset's `rights_verified_at` is within 365 days and that
   `third_party_exclusions` is empty or explicitly cleared.
4. Obtain the repository owner's explicit approval for the specific package.
5. Create a **draft** GitHub Release and attach the assets; attach
   `PACKAGE_MANIFEST.json` and the `.sha256` sidecar.
6. Publish the release only after step 4.

The packaging job uploads `dist/` as a workflow artifact for review. Only the `publish`
job can create or publish a Release, and it runs in the `open-data-release` environment,
which must be configured with required reviewers.

## Reproducibility contract

A consumer can:

1. read `PACKAGE_MANIFEST.json` to see the exact snapshots, source endpoints, licences,
   byte counts and SHA-256 values;
2. verify every file with `atlas data verify` after placing the package under a store
   root;
3. re-acquire the same dataset with `atlas data sync <id>`, receiving either the same
   bytes (if the provider has not revised the resource) or a new immutable snapshot with
   its own manifest.

Provider revisions are expected. A new snapshot never overwrites the old one; the
manifest records the ETag / Last-Modified and retrieval time that distinguish them.

## What is never distributed

* FRED series (local-use only).
* FINRA market data.
* Vendor OHLCV (Yahoo, Nasdaq, Alpha Vantage, Stooq, exchange feeds).
* Crypto exchange data with unconfirmed redistribution terms.
* Any dataset whose licence review is missing, stale or inconclusive.
* Personal data or third-party content excluded by a provider's terms.

These exclusions are visible in `data/open_data/registry.json` and in
`atlas data audit-rights`, not hidden in prose.

## Integration checkpoints are bound to the destination database

Bulk SEC integration is resumable, and the thing that decides where to resume is the
destination database — not a JSON file beside the store.

* Every Atlas database carries an immutable UUID (`database_identity`).
* Each archive's progress is written inside the same transaction as the evidence it
  describes (`open_data_integration`, `open_data_integration_member`), so a crash
  cannot leave a "processed issuer" with no evidence or evidence with no progress.
* A checkpoint records the database UUID, the integration schema, the snapshot id,
  the manifest hash and the archive hash. On resume all five must still agree.
* A deleted or recreated database has a new UUID and no progress rows, so the
  external checkpoint is ignored and issuers are re-parsed rather than skipped.
* A replaced database with a different UUID is treated the same way.
* A rolled-back database (fewer members than the checkpoint claims) is detected and
  the missing issuers are re-integrated.
* A progress row that claims an issuer whose evidence is absent is detected and that
  issuer is re-parsed.

The JSON checkpoint remains as an operator mirror and for reporting; its
`authority` field is `destination_database`, and every disagreement is reported in
`progress.events` on the integration result. Verification of claimed evidence scans
`evidence.source_url` for the snapshot id, which is why a resume takes longer than a
fresh start; `--no-verify-progress` is available when the operator has already
established that the database is intact.
