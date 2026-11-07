# Data rights audit — Phase 9

## Sources

| Source | Kind | Licence | Redistribution | Used for |
| --- | --- | --- | --- | --- |
| SEC EDGAR (`sec-edgar`) | regulatory filings / XBRL | US government public domain | allowed | all financial facts, filing metadata, identity |
| Phase 9 coverage manifest (`phase9-coverage`) | curation metadata | Apache-2.0 | allowed | declared CIK → primary ticker/exchange mapping |

No licensed market data, consensus estimate, credit dataset, transcript or news feed is
included in this checkout. The fixture contains derived XBRL facts and source identifiers,
not a copy of a commercial database.

## Enforcement

- `atlas.applications.rights.DataRightsEngine` evaluates packaging, export, redistribution
  and analysis separately and fails closed: an unknown or restricted source cannot be
  packaged.
- `build_package` runs the rights decision before writing a single file, and
  `ApplicationService.install` re-checks the packaged rights manifest.
- The equity research package declares `sec-edgar` as a required dataset with its
  redistribution class and includes a `sources.json` rights manifest.
- Missing source metadata raises an error instead of producing an unlabelled package.

## Package content

The package contains a financial snapshot, the model spec, DCF outputs, the audit, the
report and the expected outputs. It does **not** contain the raw SEC archive, market
prices, personal data or executable code.

## Residual risk

- Public-domain status is asserted from the source's own terms, not re-verified at build
  time.
- The fixture's compact facts are a derived extract; downstream redistribution of a
  reconstructed database should still be reviewed against SEC terms.
- Ticker identity curation is Atlas metadata, not an SEC statement, and is labelled as such.

## Phase 9.2.2 remediation: vendor market history removed

**Finding.** `fixtures/market/` tracked five Nasdaq quote-history CSVs whose own manifest
recorded `redistribution: restricted`, plus three archived Alpha Vantage demo responses with
no established redistribution grant. They were used as ordinary CI fixtures, which made an
unlicensed vendor history a build dependency of a private repository.

**Action.** All eight files and the Alpha Vantage manifest were removed from the tracked
tree. `fixtures/market/` now contains only project-authored synthetic data with an explicit
`synthetic: true` / `contains_vendor_data: false` declaration and a SHA-256 hash manifest.
CI no longer requires any vendor history: the reference database is bootstrapped with the
synthetic fixture, and `scripts/verify_distributable_fixtures.py` fails if vendor files
reappear.

**Residual exposure.** The removed bytes remain reachable in earlier commits
(`ed327d1` and its ancestors). Removing them from history requires a coordinated rewrite of
published commits, which was not authorized for this checkpoint. Recommended remediation if
the maintainers want it: coordinate a `git filter-repo` rewrite with a published notice,
re-issue the affected branch, and rotate any credential that ever sat beside the data. Until
then, the exposure is limited to the repository's own readers, not to packaged artefacts:
research packages, reports and exports never contained these series.
