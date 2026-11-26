# Independent validation of normalized facts

`atlas reconcile` answers one question: **does every stored value appear in the original
SEC document, unchanged, for the period the source gave it?**

It does not call the ingestion parser. Re-running the parser would only prove that the
parser agrees with itself; a shared bug would pass. Instead it walks the raw
`companyfacts` payload with its own tag resolution, its own decimal conversion and its own
period extraction, then compares that expected set with the `evidence` table.

## Usage

```bash
# offline, against archived payloads
atlas --db var/atlas.db reconcile --cik 320193 --offline fixtures/sec

# live, against EDGAR (fair-access User-Agent required)
export ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'
atlas --db var/atlas.db reconcile --cik 320193

# only errors, machine-readable
atlas --db var/atlas.db --json reconcile --cik 320193 --offline fixtures/sec --errors-only
```

Exit status is `0` when there are no errors and `1` when any error is found, so it can gate
a publication step.

## What is checked

| Check | Severity | Meaning |
|---|---|---|
| `stored_value_differs_from_source` | error | stored decimal ≠ source decimal for the same concept/unit/period/accession |
| `source_observation_not_stored` | error | the source contains an observation Atlas did not store |
| `stored_fact_not_in_source` | error | Atlas stored a source-classified fact the document does not contain |
| `duplicate_stored_observations` | error | more than one stored record claims one source observation |
| `duration_without_period_start` | error | a flow fact lost its start date and became indistinguishable from an instant |
| `amendment_not_marked` | error | form `10-Q/A` (etc.) stored with `revision_kind != amendment` |
| `amendment_availability_not_exact` | error | an amendment has a known acceptance timestamp but date-precision availability |
| `availability_unknown_but_filing_known` | error | availability unevidenced although a filing with a filed date is stored |
| `exact_availability_differs_from_filing` | error | exact availability ≠ the filing's `acceptanceDateTime` |
| `date_availability_not_end_of_day` | error | date-precision availability is not the end of the filed day in UTC |
| `fiscal_period_differs_from_source` | warning | stored `fy`/`fp` differ from the source's |
| `period_end_differs_from_filing_report_date` | warning | XBRL period end ≠ the filing's cover-page `reportDate` |
| `source_asserts_two_values` | error | one accession asserts two values for the same period/unit |
| `unparsable_source_value` / `_unit` | error / warning | the source itself is malformed |

## Measured result

Apple Inc., CIK 0000320193, 5,737 facts:

```
coverage: 5737/5737 source observations verified
mismatched_values: 0    missing_from_store: 0    unexpected_in_store: 0
duplicate_keys: 0       availability_issues: 0    period_issues: 0    amendment_issues: 0
errors: 0               warnings: 3238
```

The 3,238 warnings are all `period_end_differs_from_filing_report_date`. They are expected:
the SEC cover-page `reportDate` is the period of the *filing as a document*, while a
`companyfacts` observation can describe a comparative period or an instant inside that
filing. The check is retained as a warning precisely because it is a heuristic — promoting
it to an error would generate false failures on correct data.

Each of the checks above is also exercised by a test that corrupts a stored row with direct
SQL and asserts that reconciliation notices (`tests/test_reconcile.py`). A validator that
has only ever seen correct data has not been tested.

## Limits

* **It compares against `companyfacts`, not the XBRL instance document.** SEC's
  `companyfacts` is itself a derived API view. A defect in SEC's derivation would be
  invisible here. Verifying against the `.xml` instance (and the `Financial Report` R-files)
  is the next level of assurance and is not implemented.
* **It does not check concept *mapping* choices.** Both sides use the same registry. A
  wrong registry entry would agree with itself. Mapping decisions are reviewed by hand and
  documented in `CONCEPTS.md`.
* **It does not check bar or action data.** Those have their own validators
  (`atlas bars validate`, `atlas validate`).
* **Currencies are compared as reported.** No conversion is applied, by design.
* **A missing filing archive can hide nothing here**, because the comparison is against the
  facts payload; but availability checks only run for accessions whose filing metadata is
  stored. `atlas sec history` reports that coverage separately.
