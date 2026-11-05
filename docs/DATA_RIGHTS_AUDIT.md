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
