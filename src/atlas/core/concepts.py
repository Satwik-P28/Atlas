"""Canonical financial concepts and their explicit source-tag mappings.

Atlas never guesses that two similarly named facts are the same economic quantity.
Each canonical concept lists the XBRL tags it is willing to accept, **in priority
order**, plus a note on what the mapping does and does not cover. A tag absent from
this registry is not silently coerced into a canonical concept; it stays in the raw
document and is reported as unmapped.

Sign conventions are declared per concept:

``as_reported``
    The source value is used unchanged.
``magnitude_outflow``
    The concept is defined as a positive magnitude of an outflow (e.g. capital
    expenditure). XBRL reports ``Payments*`` elements as positive numbers, so this
    asserts rather than transforms; a negative source value is flagged as suspect.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable, Mapping

from .units import Unit, UnitKind, parse_unit


class Statement(str):
    INCOME = "income"
    BALANCE = "balance"
    CASHFLOW = "cashflow"


@dataclass(frozen=True, slots=True)
class ConceptDef:
    """A canonical financial concept."""

    key: str
    statement: str
    label: str
    unit_kind: UnitKind
    period_type: str  # "duration" | "instant"
    source_tags: tuple[tuple[str, str], ...]
    sign_policy: str = "as_reported"
    note: str = ""

    @property
    def primary_tag(self) -> tuple[str, str] | None:
        return self.source_tags[0] if self.source_tags else None

    def unit(self) -> Unit:
        if self.unit_kind is UnitKind.MONETARY:
            return parse_unit("USD")
        if self.unit_kind is UnitKind.SHARES:
            return parse_unit("shares")
        if self.unit_kind is UnitKind.PER_SHARE:
            return parse_unit("USD/shares")
        return parse_unit("pure")


@dataclass(frozen=True, slots=True)
class DerivationDef:
    """A declared derivation rule (derived values are never presented as source facts)."""

    key: str
    statement: str
    label: str
    rule_id: str
    requires: tuple[str, ...]
    unit_kind: UnitKind
    period_type: str
    description: str


def _c(
    key: str,
    statement: str,
    label: str,
    unit_kind: UnitKind,
    period_type: str,
    tags: Iterable[tuple[str, str] | str],
    *,
    sign_policy: str = "as_reported",
    note: str = "",
) -> ConceptDef:
    parsed: list[tuple[str, str]] = []
    for tag in tags:
        if isinstance(tag, str):
            namespace, _, name = tag.partition(":")
            parsed.append((namespace, name))
        else:
            parsed.append(tag)
    return ConceptDef(
        key=key,
        statement=statement,
        label=label,
        unit_kind=unit_kind,
        period_type=period_type,
        source_tags=tuple(parsed),
        sign_policy=sign_policy,
        note=note,
    )


_CONCEPTS: tuple[ConceptDef, ...] = (
    # ------------------------------------------------------------------ income
    _c(
        "revenue",
        Statement.INCOME,
        "Revenue",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "RevenueFromContractWithCustomerExcludingAssessedTax"),
            ("us-gaap", "RevenueFromContractWithCustomerIncludingAssessedTax"),
            ("us-gaap", "Revenues"),
            ("us-gaap", "SalesRevenueNet"),
            ("us-gaap", "SalesRevenueGoodsNet"),
        ],
        note=(
            "Issuers report revenue under different elements; the order above prefers the "
            "ASC 606 net-of-tax element. Gross vs net presentation can differ by issuer, so "
            "the chosen source concept is always exposed with the value."
        ),
    ),
    _c(
        "cost_of_revenue",
        Statement.INCOME,
        "Cost of revenue",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "CostOfRevenue"),
            ("us-gaap", "CostOfGoodsAndServicesSold"),
            ("us-gaap", "CostOfGoodsSold"),
            ("us-gaap", "CostOfServices"),
        ],
    ),
    _c(
        "gross_profit",
        Statement.INCOME,
        "Gross profit",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "GrossProfit")],
        note="Falls back to the declared derivation gross_profit when the issuer omits it.",
    ),
    _c(
        "operating_expenses",
        Statement.INCOME,
        "Operating expenses",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "OperatingExpenses")],
    ),
    _c(
        "research_and_development",
        Statement.INCOME,
        "Research and development expense",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "ResearchAndDevelopmentExpense")],
    ),
    _c(
        "selling_general_administrative",
        Statement.INCOME,
        "Selling, general and administrative expense",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "SellingGeneralAndAdministrativeExpense")],
    ),
    _c(
        "operating_income",
        Statement.INCOME,
        "Operating income",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "OperatingIncomeLoss")],
    ),
    _c(
        "pretax_income",
        Statement.INCOME,
        "Income before income taxes",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"),
            ("us-gaap", "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"),
        ],
    ),
    _c(
        "income_tax_expense",
        Statement.INCOME,
        "Income tax expense",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "IncomeTaxExpenseBenefit")],
    ),
    _c(
        "net_income",
        Statement.INCOME,
        "Net income",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "NetIncomeLoss"), ("us-gaap", "ProfitLoss")],
        note=(
            "NetIncomeLoss is attributable to the parent; ProfitLoss includes "
            "non-controlling interests. They are not interchangeable and the source tag is "
            "always reported."
        ),
    ),
    _c(
        "net_income_common",
        Statement.INCOME,
        "Net income available to common shareholders",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "NetIncomeLossAvailableToCommonStockholdersBasic")],
    ),
    _c(
        "eps_basic",
        Statement.INCOME,
        "Basic earnings per share",
        UnitKind.PER_SHARE,
        "duration",
        [("us-gaap", "EarningsPerShareBasic")],
    ),
    _c(
        "eps_diluted",
        Statement.INCOME,
        "Diluted earnings per share",
        UnitKind.PER_SHARE,
        "duration",
        [("us-gaap", "EarningsPerShareDiluted")],
    ),
    _c(
        "weighted_average_shares_diluted",
        Statement.INCOME,
        "Weighted average diluted shares",
        UnitKind.SHARES,
        "duration",
        [("us-gaap", "WeightedAverageNumberOfDilutedSharesOutstanding")],
    ),
    _c(
        "interest_expense",
        Statement.INCOME,
        "Interest expense",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "InterestExpenseNonoperating"), ("us-gaap", "InterestExpense")],
    ),
    # ----------------------------------------------------------------- balance
    _c(
        "assets",
        Statement.BALANCE,
        "Total assets",
        UnitKind.MONETARY,
        "instant",
        [("us-gaap", "Assets")],
    ),
    _c(
        "liabilities",
        Statement.BALANCE,
        "Total liabilities",
        UnitKind.MONETARY,
        "instant",
        [("us-gaap", "Liabilities")],
    ),
    _c(
        "equity",
        Statement.BALANCE,
        "Shareholders' equity",
        UnitKind.MONETARY,
        "instant",
        [
            ("us-gaap", "StockholdersEquity"),
            ("us-gaap", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"),
        ],
        note=(
            "The first element excludes non-controlling interests; the fallback includes "
            "them. Assets = liabilities + equity only holds for the matching variant."
        ),
    ),
    _c(
        "preferred_stock",
        Statement.BALANCE,
        "Preferred stock",
        UnitKind.MONETARY,
        "instant",
        [
            ("us-gaap", "PreferredStockValue"),
            ("us-gaap", "PreferredStockIncludingAdditionalPaidInCapitalNetOfDiscount"),
        ],
        note=(
            "Issuers use different preferred-stock elements. The fallback includes additional "
            "paid-in capital net of discount; the source tag is always reported so a total "
            "equity less preferred reconciliation can be audited."
        ),
    ),
    _c(
        "cash_and_equivalents",
        Statement.BALANCE,
        "Cash and cash equivalents",
        UnitKind.MONETARY,
        "instant",
        [
            ("us-gaap", "CashAndCashEquivalentsAtCarryingValue"),
            ("us-gaap", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents"),
        ],
        note="The fallback element includes restricted cash; the variant used is always reported.",
    ),
    _c(
        "short_term_investments",
        Statement.BALANCE,
        "Short-term investments",
        UnitKind.MONETARY,
        "instant",
        [
            ("us-gaap", "ShortTermInvestments"),
            ("us-gaap", "MarketableSecuritiesCurrent"),
            ("us-gaap", "AvailableForSaleSecuritiesDebtSecuritiesCurrent"),
        ],
    ),
    _c(
        "receivables",
        Statement.BALANCE,
        "Accounts receivable, net",
        UnitKind.MONETARY,
        "instant",
        [("us-gaap", "AccountsReceivableNetCurrent"), ("us-gaap", "ReceivablesNetCurrent")],
    ),
    _c(
        "inventory",
        Statement.BALANCE,
        "Inventory, net",
        UnitKind.MONETARY,
        "instant",
        [("us-gaap", "InventoryNet")],
    ),
    _c(
        "long_term_debt",
        Statement.BALANCE,
        "Long-term debt",
        UnitKind.MONETARY,
        "instant",
        [("us-gaap", "LongTermDebtNoncurrent"), ("us-gaap", "LongTermDebt")],
        note=(
            "LongTermDebtNoncurrent excludes current maturities; LongTermDebt may be total. "
            "Debt is the least comparable balance-sheet concept across issuers - see "
            "docs/CONCEPTS.md."
        ),
    ),
    _c(
        "short_term_debt",
        Statement.BALANCE,
        "Short-term debt",
        UnitKind.MONETARY,
        "instant",
        [
            ("us-gaap", "LongTermDebtCurrent"),
            ("us-gaap", "OtherShortTermBorrowings"),
            ("us-gaap", "ShortTermBorrowings"),
            ("us-gaap", "CommercialPaper"),
        ],
    ),
    _c(
        "shares_outstanding",
        Statement.BALANCE,
        "Shares outstanding",
        UnitKind.SHARES,
        "instant",
        [
            ("us-gaap", "CommonStockSharesOutstanding"),
            ("dei", "EntityCommonStockSharesOutstanding"),
        ],
        note=(
            "CommonStockSharesOutstanding is dated at the balance-sheet instant and is preferred. "
            "The dei fallback is cover-page shares at the filing date, not the balance-sheet date; "
            "the source element is always exposed."
        ),
    ),
    # ---------------------------------------------------------------- cashflow
    _c(
        "operating_cash_flow",
        Statement.CASHFLOW,
        "Cash flow from operating activities",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivities"),
            ("us-gaap", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"),
        ],
    ),
    _c(
        "investing_cash_flow",
        Statement.CASHFLOW,
        "Cash flow from investing activities",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "NetCashProvidedByUsedInInvestingActivities"),
            ("us-gaap", "NetCashProvidedByUsedInInvestingActivitiesContinuingOperations"),
        ],
    ),
    _c(
        "financing_cash_flow",
        Statement.CASHFLOW,
        "Cash flow from financing activities",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "NetCashProvidedByUsedInFinancingActivities"),
            ("us-gaap", "NetCashProvidedByUsedInFinancingActivitiesContinuingOperations"),
        ],
    ),
    _c(
        "capex",
        Statement.CASHFLOW,
        "Capital expenditure",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "PaymentsToAcquirePropertyPlantAndEquipment"),
            ("us-gaap", "PaymentsToAcquireProductiveAssets"),
            ("us-gaap", "PaymentsForCapitalImprovements"),
        ],
        sign_policy="magnitude_outflow",
        note="Stored as a positive outflow magnitude. Never add this to operating cash flow without negating it.",
    ),
    _c(
        "depreciation_amortization",
        Statement.CASHFLOW,
        "Depreciation, depletion and amortization",
        UnitKind.MONETARY,
        "duration",
        [
            ("us-gaap", "DepreciationDepletionAndAmortization"),
            ("us-gaap", "DepreciationAmortizationAndAccretionNet"),
            ("us-gaap", "Depreciation"),
        ],
    ),
    _c(
        "dividends_paid",
        Statement.CASHFLOW,
        "Dividends paid",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "PaymentsOfDividends"), ("us-gaap", "PaymentsOfDividendsCommonStock")],
        sign_policy="magnitude_outflow",
    ),
    _c(
        "share_repurchases",
        Statement.CASHFLOW,
        "Repurchase of common stock",
        UnitKind.MONETARY,
        "duration",
        [("us-gaap", "PaymentsForRepurchaseOfCommonStock")],
        sign_policy="magnitude_outflow",
    ),
)

CONCEPTS: dict[str, ConceptDef] = {concept.key: concept for concept in _CONCEPTS}

_CONCEPT_BY_TAG: dict[tuple[str, str], list[ConceptDef]] = {}
for _concept in _CONCEPTS:
    for _ns, _tag in _concept.source_tags:
        _CONCEPT_BY_TAG.setdefault((_ns, _tag), []).append(_concept)

DERIVATIONS: dict[str, DerivationDef] = {
    "gross_profit": DerivationDef(
        key="gross_profit",
        statement=Statement.INCOME,
        label="Gross profit (derived)",
        rule_id="atlas.derived.gross_profit.v1",
        requires=("revenue", "cost_of_revenue"),
        unit_kind=UnitKind.MONETARY,
        period_type="duration",
        description="revenue - cost_of_revenue, computed only when both are observed in the same unit and period.",
    ),
    "total_debt": DerivationDef(
        key="total_debt",
        statement=Statement.BALANCE,
        label="Total debt (derived)",
        rule_id="atlas.derived.total_debt.v1",
        requires=("long_term_debt", "short_term_debt"),
        unit_kind=UnitKind.MONETARY,
        period_type="instant",
        description=(
            "long_term_debt + short_term_debt. Both components must be present at the same "
            "instant; a partial sum is reported as such rather than as total debt."
        ),
    ),
    "free_cash_flow": DerivationDef(
        key="free_cash_flow",
        statement=Statement.CASHFLOW,
        label="Free cash flow (derived)",
        rule_id="atlas.derived.free_cash_flow.v1",
        requires=("operating_cash_flow", "capex"),
        unit_kind=UnitKind.MONETARY,
        period_type="duration",
        description=(
            "operating_cash_flow - capex, where capex is the positive outflow magnitude. "
            "This is a simple definition, not a universal one: issuers and analysts differ."
        ),
    ),
}

# Statement display order used by the CLI.
STATEMENT_ORDER = (Statement.INCOME, Statement.BALANCE, Statement.CASHFLOW)


@dataclass(frozen=True, slots=True)
class TagResolution:
    """The outcome of mapping a canonical concept onto available source tags."""

    concept: str
    namespace: str
    tag: str
    priority: int
    reason: str
    considered: tuple[str, ...] = field(default=())

    @property
    def source_tag(self) -> str:
        return f"{self.namespace}:{self.tag}"


def _parse_tag(tag: tuple[str, str] | str) -> tuple[str, str]:
    if isinstance(tag, str):
        namespace, _, name = tag.partition(":")
        return namespace, name
    return tag


def resolve_tag(
    concept_key: str,
    available_tags: Iterable[tuple[str, str] | str],
    *,
    issuer_overrides: Mapping[str, str] | None = None,
) -> TagResolution | None:
    """Choose the highest-priority available source tag for a canonical concept.

    Resolution is a pure, inspectable function of (concept, available tags, overrides).
    It returns ``None`` when the issuer simply does not report the concept: missing is
    missing, and Atlas does not substitute a neighbouring element.
    """
    concept = CONCEPTS.get(concept_key)
    if concept is None:
        raise KeyError(f"unknown canonical concept {concept_key!r}")
    available = {_parse_tag(tag) for tag in available_tags}
    override = (issuer_overrides or {}).get(concept_key)
    if override:
        namespace, _, name = override.partition(":")
        if (namespace, name) in available:
            return TagResolution(
                concept=concept_key,
                namespace=namespace,
                tag=name,
                priority=-1,
                reason="issuer_override",
                considered=tuple(f"{ns}:{t}" for ns, t in concept.source_tags),
            )
        # An override that the issuer does not report is an error in the override,
        # not a licence to fall back silently to a different economic definition.
        return None
    for index, (namespace, tag) in enumerate(concept.source_tags):
        if (namespace, tag) in available:
            return TagResolution(
                concept=concept_key,
                namespace=namespace,
                tag=tag,
                priority=index,
                reason="first_available_priority",
                considered=tuple(f"{ns}:{t}" for ns, t in concept.source_tags[: index + 1]),
            )
    return None


def concepts_for_statement(statement: str) -> list[ConceptDef]:
    return [c for c in _CONCEPTS if c.statement == statement]


def concept_keys() -> list[str]:
    return list(CONCEPTS.keys())


def concept_metadata() -> dict[str, dict[str, object]]:
    """Serializable concept registry, used by docs generation and the CLI."""
    return {
        key: {
            "statement": c.statement,
            "label": c.label,
            "unit_kind": c.unit_kind.value,
            "period_type": c.period_type,
            "sign_policy": c.sign_policy,
            "source_tags": [f"{ns}:{tag}" for ns, tag in c.source_tags],
            "note": c.note,
        }
        for key, c in CONCEPTS.items()
    }


def resolve_derivation(key: str) -> DerivationDef:
    if key not in DERIVATIONS:
        raise KeyError(f"unknown derivation {key!r}")
    return DERIVATIONS[key]


def canonical_unit_for(concept_key: str) -> Unit:
    concept = CONCEPTS.get(concept_key)
    if concept is not None:
        return concept.unit()
    derivation = DERIVATIONS.get(concept_key)
    if derivation is not None:
        return ConceptDef(
            key=derivation.key,
            statement=derivation.statement,
            label=derivation.label,
            unit_kind=derivation.unit_kind,
            period_type=derivation.period_type,
            source_tags=(),
        ).unit()
    raise KeyError(f"unknown concept {concept_key!r}")
