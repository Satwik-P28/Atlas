# Third-party notices

Atlas is licensed under the Apache License, Version 2.0 (see [LICENSE](LICENSE)). That licence
covers Atlas-authored material only. This file reproduces the attribution obligations that travel
with a distributed Atlas artifact (the wheel, the source distribution and this repository).

The machine-readable inventory is [docs/DEPENDENCY_LICENSES.json](docs/DEPENDENCY_LICENSES.json);
the per-obligation discussion is [docs/THIRD_PARTY_ATTRIBUTION.md](docs/THIRD_PARTY_ATTRIBUTION.md).
Regenerate the inventory with `.venv/bin/python scripts/inventory_dependency_licenses.py`.

## 1. Python dependencies

Python packages are installed by the user's package manager, not vendored into the Atlas wheel.
They keep their own licences; the inventory records the licence each package reports about itself.

| Package | Version at certification | Licence |
| --- | --- | --- |
| numpy | 2.5.5 | BSD-3-Clause AND 0BSD AND MIT AND Zlib AND CC0-1.0 |
| tzdata | 2026.6 | Apache-2.0 |
| httpx (dev) | 0.29.0 | BSD-3-Clause |
| hypothesis (dev) | 6.170.17 | MPL-2.0 |
| scipy (optional) | 1.18.1 | BSD-3-Clause |
| scikit-learn (optional) | 1.9.1 | BSD-3-Clause |
| pyarrow (optional) | 26.0.1 | Apache-2.0 |
| duckdb (optional) | 1.5.6 | MIT |
| zstandard (optional) | 0.25.0 | BSD-3-Clause |
| osqp (optional) | 1.1.3 | Apache-2.0 |
| clarabel (optional) | 0.11.1 | Apache-2.0 |
| fastapi (optional) | 0.165.0 | MIT |
| uvicorn (optional) | 0.54.0 | BSD-3-Clause |

`hypothesis` is MPL-2.0 and is a development/test dependency only; it is not imported by Atlas at
runtime and is not present in a user installation that installs the wheel.

No dependency is relicensed by Atlas, and listing a licence here is an inventory, not a legal
review. Re-check every dependency's own licence text before redistributing it yourself.

## 2. Frontend packages compiled into the wheel

The terminal UI under `web/` is built with Vite and the built assets are packaged inside the wheel.
These production dependencies are compiled into that bundle:

| Package | Version at certification | Licence |
| --- | --- | --- |
| react | 19.3.1 | MIT |
| react-dom | 19.3.1 | MIT |
| scheduler | 0.28.0 | MIT |
| react-router | 7.18.5 | MIT |
| react-router-dom | 7.18.5 | MIT |
| cookie | 1.1.1 | MIT |
| set-cookie-parser | 2.7.3 | MIT |
| lightweight-charts | 5.2.1 | Apache-2.0 |
| fancy-canvas | 2.1.0 | MIT |

Development-only npm packages (build tooling, test runners, type definitions) are not shipped in
any artifact. The inventory lists them separately so the difference is auditable.

No web font or icon set is bundled: the interface uses system font stacks. No MPL-2.0 package is
in the production bundle; if a future dependency introduces one, the file-level copyleft
obligation (publish the licence and make the covered files' source available) applies, as
[docs/THIRD_PARTY_ATTRIBUTION.md](docs/THIRD_PARTY_ATTRIBUTION.md) records.

## 3. Data and documents are not covered by the software licence

The Apache-2.0 grant does not extend to third-party data. In particular:

- **SEC-derived financial facts** are stored as derived figures, identifiers, accession numbers,
  URLs and digests. Issuer-prepared filing content is not a U.S. Government work and is not
  relicensed here; SEC access terms apply.
- **Synthetic market fixtures** are project-authored and covered by the software licence.
- **U.S. Government data** (Treasury, EIA, NOAA, FFIEC, FDIC) is treated as public domain with
  attribution retained.
- **No licensed vendor market data ships in any artifact.** Nine Nasdaq/Alpha Vantage files
  existed in this repository's earlier development history and were removed from the tree; they
  are not in the wheel, the sdist or the sanitized source archive, and they may not be
  redistributed. See [docs/DATA_RIGHTS_AND_DISTRIBUTION.md](docs/DATA_RIGHTS_AND_DISTRIBUTION.md).

Per-source rights are inventoried in [docs/DATA_RIGHTS_INVENTORY.json](docs/DATA_RIGHTS_INVENTORY.json).
