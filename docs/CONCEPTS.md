# Canonical concepts and mapping policy

Atlas maps XBRL to a **closed registry** of 32 canonical concepts. Mapping is exact and
auditable; nothing is inferred from name similarity.

## 1. Policy

1. Each concept lists acceptable source elements **in priority order**. The first element
   the issuer actually reports wins.
2. Resolution is per issuer across the whole `companyfacts` payload, so one issuer always
   maps a concept to one element (consistency across periods).
3. The original element is stored on every record (`taxonomy` + `source_concept`) and
   shown by the CLI and provenance report.
4. A unit of the wrong **kind** is rejected and counted. A different **currency** is a
   separate fact; currencies are never converted or combined.
5. Elements outside the registry are counted and listed (`unmapped_tags`). Apple's
   payload has 505 elements; 31 are mapped, 474 reported as unmapped.
6. Issuer overrides exist but must name an element the issuer reports, otherwise the
   concept is treated as missing — no silent fallback to a different definition.

## 2. Coverage against Apple Inc. (CIK 0000320193)

Measured from the archived `companyfacts` payload (`fixtures/sec/`):

| Metric | Value |
|---|---|
| XBRL elements available | 505 |
| Elements mapped | 31 |
| Canonical concepts populated | **31 of 32** |
| Observations ingested as evidence | 5,737 |
| Availability `exact` (acceptance timestamp) | 3,740 |
| Availability `date` (filed date, end-of-day UTC) | 1,997 |
| Availability `unknown` | 0 |

Unpopulated: `net_income_common` (`NetIncomeLossAvailableToCommonStockholdersBasic`).
Apple reports `NetIncomeLoss`, which maps to `net_income`; Atlas does not substitute it.

## 3. Registry

### Income statement

| Concept | Unit | Period | Source elements (priority order) |
|---|---|---|---|
| `revenue` | monetary | duration | `RevenueFromContractWithCustomerExcludingAssessedTax`, `…IncludingAssessedTax`, `Revenues`, `SalesRevenueNet`, `SalesRevenueGoodsNet` |
| `cost_of_revenue` | monetary | duration | `CostOfRevenue`, `CostOfGoodsAndServicesSold`, `CostOfGoodsSold`, `CostOfServices` |
| `gross_profit` | monetary | duration | `GrossProfit` |
| `operating_expenses` | monetary | duration | `OperatingExpenses` |
| `research_and_development` | monetary | duration | `ResearchAndDevelopmentExpense` |
| `selling_general_administrative` | monetary | duration | `SellingGeneralAndAdministrativeExpense` |
| `operating_income` | monetary | duration | `OperatingIncomeLoss` |
| `pretax_income` | monetary | duration | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`, `…MinorityInterestAndIncomeLossFromEquityMethodInvestments` |
| `income_tax_expense` | monetary | duration | `IncomeTaxExpenseBenefit` |
| `net_income` | monetary | duration | `NetIncomeLoss`, `ProfitLoss` |
| `net_income_common` | monetary | duration | `NetIncomeLossAvailableToCommonStockholdersBasic` |
| `eps_basic` | per-share | duration | `EarningsPerShareBasic` |
| `eps_diluted` | per-share | duration | `EarningsPerShareDiluted` |
| `weighted_average_shares_diluted` | shares | duration | `WeightedAverageNumberOfDilutedSharesOutstanding` |
| `interest_expense` | monetary | duration | `InterestExpenseNonoperating`, `InterestExpense` |

### Balance sheet

| Concept | Unit | Period | Source elements |
|---|---|---|---|
| `assets` | monetary | instant | `Assets` |
| `liabilities` | monetary | instant | `Liabilities` |
| `equity` | monetary | instant | `StockholdersEquity`, `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` |
| `cash_and_equivalents` | monetary | instant | `CashAndCashEquivalentsAtCarryingValue`, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` |
| `short_term_investments` | monetary | instant | `ShortTermInvestments`, `MarketableSecuritiesCurrent`, `AvailableForSaleSecuritiesDebtSecuritiesCurrent` |
| `receivables` | monetary | instant | `AccountsReceivableNetCurrent`, `ReceivablesNetCurrent` |
| `inventory` | monetary | instant | `InventoryNet` |
| `long_term_debt` | monetary | instant | `LongTermDebtNoncurrent`, `LongTermDebt` |
| `short_term_debt` | monetary | instant | `LongTermDebtCurrent`, `OtherShortTermBorrowings`, `ShortTermBorrowings`, `CommercialPaper` |
| `shares_outstanding` | shares | instant | `dei:EntityCommonStockSharesOutstanding` |

### Cash flow statement

| Concept | Unit | Period | Source elements |
|---|---|---|---|
| `operating_cash_flow` | monetary | duration | `NetCashProvidedByUsedInOperatingActivities`, `…ContinuingOperations` |
| `investing_cash_flow` | monetary | duration | `NetCashProvidedByUsedInInvestingActivities`, `…ContinuingOperations` |
| `financing_cash_flow` | monetary | duration | `NetCashProvidedByUsedInFinancingActivities`, `…ContinuingOperations` |
| `capex` | monetary | duration | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets`, `PaymentsForCapitalImprovements` |
| `depreciation_amortization` | monetary | duration | `DepreciationDepletionAndAmortization`, `DepreciationAmortizationAndAccretionNet`, `Depreciation` |
| `dividends_paid` | monetary | duration | `PaymentsOfDividends`, `PaymentsOfDividendsCommonStock` |
| `share_repurchases` | monetary | duration | `PaymentsForRepurchaseOfCommonStock` |

## 4. Sign conventions

| Policy | Concepts | Meaning |
|---|---|---|
| `as_reported` | all except below | value used unchanged |
| `magnitude_outflow` | `capex`, `dividends_paid`, `share_repurchases` | concept is a **positive outflow magnitude**; XBRL `Payments*` elements are positive, so no arithmetic is applied. A negative source value is preserved and flagged `suspect` rather than flipped silently. |

## 5. Derivations

| Concept | Rule id | Inputs | Definition |
|---|---|---|---|
| `gross_profit` | `atlas.derived.gross_profit.v1` | `revenue`, `cost_of_revenue` | `revenue − cost_of_revenue`, same unit and period only |
| `total_debt` | `atlas.derived.total_debt.v1` | `long_term_debt`, `short_term_debt` | sum at the same instant; a partial sum is never labelled total debt |
| `free_cash_flow` | `atlas.derived.free_cash_flow.v1` | `operating_cash_flow`, `capex` | `operating_cash_flow − capex` (simple definition, not universal) |

Derived values carry `derivation_kind = derived_calculation`, the rule id, and the input
`evidence_id`s. They sit at basis tier 2, so an observed value for the same concept and
period always outranks them.

> Note: the derivation functions are defined and their rules are recorded, but the
> Phase 1 SEC pipeline does **not** automatically synthesise derived facts; a derived
> record is created explicitly (see the provenance test and the API). Automatic
> derivation belongs to the Phase 2 model layer, where dependency tracking is owned.

## 6. Known semantic caveats (recorded on the concept, surfaced in provenance)

* **Revenue** — gross vs net presentation differs by issuer; four ASC 606 / legacy
  elements are accepted in priority order and the chosen element is always reported.
* **Net income** — `NetIncomeLoss` is attributable to the parent; `ProfitLoss` includes
  non-controlling interests. Not interchangeable.
* **Equity** — the primary element excludes non-controlling interests; the fallback
  includes them. `assets = liabilities + equity` holds only for the matching variant.
* **Cash** — the fallback element includes restricted cash.
* **Debt** — the least comparable balance-sheet concept. `LongTermDebtNoncurrent`
  excludes current maturities; `LongTermDebt` may be total. Short-term components are
  heterogeneous (`LongTermDebtCurrent`, `OtherShortTermBorrowings`, `CommercialPaper`).
* **Shares outstanding** — `dei:` cover-page figure dated at the filing date, not a
  balance-sheet share count.

These are why every normalised value carries its source element: a researcher can see
which definition produced the number.
