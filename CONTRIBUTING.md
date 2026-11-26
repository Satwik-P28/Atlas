# Contributing to Atlas

Atlas is a research system whose value is that a claim can be checked. Contributions are judged on
the same principle: can a reviewer reproduce what you assert?

## Before you start

- Read [`docs/ARCHITECTURE.md`](docs/ARCHITECTURE.md) and [`docs/CONCEPTS.md`](docs/CONCEPTS.md).
  Most "wrong number" reports are concept-scope questions, not parser bugs.
- Check [`docs/KNOWN_LIMITATIONS.md`](docs/KNOWN_LIMITATIONS.md): refusals on unparsed filings and
  ambiguous column labels are documented behaviour, not defects.
- For anything security-relevant, do not open a public issue with an exploit; open a minimal private
  report to the maintainer first.

## Development setup

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev,terminal,learning,columnar,optimization]"
python -m pytest -o addopts='' -q tests        # ~190 s
cd web && npm ci && npm test -- --run && npm run typecheck && npm run build
```

Browser journeys live in `web/e2e/`; the release journey is
`web/e2e/phase10_5_certification.mjs` and needs a running `atlas serve` and a demo database.

## What a good change looks like

1. **One claim per pull request.** Say what was wrong, what the evidence was, and what now holds.
2. **A test that fails before the fix.** For resolution or arithmetic changes, include the filing
   shape that provoked it (a synthetic fixture is fine; do not commit licensed filings).
3. **No silent behaviour changes.** If an answer becomes possible where it was refused, or a refusal
   becomes an answer, that is a semantic change and needs a rationale plus updated documentation.
4. **No fabricated data.** Fixtures must be project-authored, public-domain, or derived facts with
   an entry in [`docs/DATA_RIGHTS_INVENTORY.json`](docs/DATA_RIGHTS_INVENTORY.json).
5. **Honest labels.** If a capability is partial, document it. "Supported" means tested.

## Gates that must stay green

- `python -m pytest` (full suite), `npm test`, `npm run typecheck`, `npm run build`.
- `python scripts/scan_dependencies.py`, `python scripts/audit_distribution.py`.
- `python scripts/verify_test_inventory.py` when adding or removing tests.

## Commit messages

Describe the reason, not the diff: what was wrong, what changed, what evidence supports it. If the
change affects a release gate, name the gate.

## Code of conduct

Be specific, be kind, assume the other person has read the same filing you have. Disagreements about
resolution policy are welcome and should be argued with examples.
