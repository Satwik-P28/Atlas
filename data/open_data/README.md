# Atlas open data

Two layers live here:

1. **`registry.json`** — the reviewed, machine-readable acquisition registry used by
   `atlas data`. It records licence, rights class, verification date, permissions,
   third-party exclusions, endpoints, adapters and coverage for every dataset.
2. **`catalog.json` and `scripts/fetch_open_data.py`** — the original minimal
   allowlist downloader. It is retained for compatibility; its 25 URLs were re-verified
   against their official sources on 2026-11-24 and all resolved.

`PACKAGE_MANIFEST.json` files and snapshot manifests under `manifests/` are small,
redistributable provenance records. Bulk provider bytes are never committed to Git.

## Quick start

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev,columnar]' zstandard duckdb

atlas data list
atlas data audit-rights
atlas data sync sec.company_tickers treasury.nominal_yields
atlas data verify
atlas data coverage
atlas data dashboard --out artifacts/open_data_dashboard.html
```

Use `atlas data sync <group>` with `sec`, `treasury`, `macro`, `banking`, `energy`,
`cftc` or `identifiers`. Add `--automated` in CI so unverified or stale entries are
skipped. Add `--max-bytes` to bound a smoke run.

## Verification

```bash
python scripts/build_open_data_registry.py --check
python scripts/audit_open_data.py --strict
python scripts/audit_open_data.py --live --samples --strict
python -m pytest tests/test_open_data_engine.py tests/test_open_data_bootstrap.py
```

The live audit checks every official endpoint and compares all three checked-in
Treasury samples with the providers' current official responses. See
`docs/OPEN_DATA_ENGINE.md`, `docs/OPEN_DATA_DISTRIBUTION.md` and
`docs/OPEN_DATA_ACQUISITION_REPORT.md`.

## Rights

Default deny. Only `public_domain`, `permissive` and `redistributable_conditions`
entries may enter a public package, and only with a current review, commercial-use and
redistribution permission, and no uncleared third-party exclusions. Unverified entries
are never acquired by automated public-distribution jobs. `FRED` is local-use only.
Vendor and FINRA entries are retained as auditable negative results.

## Samples

The checked-in samples are three source-backed Treasury observations (two debt rows and
21 January 1990 yield-curve dates, 189 numeric yields), not full datasets and not a
historical vintage. They are re-verified upstream by the live audit.
