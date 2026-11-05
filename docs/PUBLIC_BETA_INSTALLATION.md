# Public beta installation

## From a checkout

```bash
python3 -m venv .venv
.venv/bin/pip install -e .
.venv/bin/python scripts/build_phase9_db.py --db var/phase9.db
.venv/bin/python -m atlas.terminal.api          # API + built SPA on 127.0.0.1:8000
```

Frontend development:

```bash
npm --prefix web install
npm --prefix web run dev                        # Vite dev server
npm --prefix web run build                      # production bundle served by the API
```

## Verification after install

```bash
.venv/bin/python -m pytest -o addopts='' -q -p no:warnings
.venv/bin/python scripts/audit_phase9_financials.py --db var/phase9.db
.venv/bin/python scripts/benchmark_phase9_equity.py --db var/phase9.db
```

The audit must print `"status": "pass"` before you treat the database as reconciled.

## What the beta includes

- The 20-company SEC fixture and the terminal.
- Deterministic equity research, DCF audit and a portable research package.
- Existing markets, screener, studio, quant lab, learning, economic and applications
  surfaces.

## What it does not include

- Market prices. Anything price-dependent reports a missing input.
- Financial-institution valuation.
- Signatures, a marketplace or executable plug-ins.
- A server deployment story: no authentication, no multi-tenant isolation.

## Troubleshooting

- `database_missing`: run the builder or point `ATLAS_DB` at an existing database.
- `database_needs_migration`: run `atlas --db <path> init`.
- Package import says `inspect_only`: the runtime, compiler or an operator version does not
  match the package. It is not executed.
