"""Versioned valuation eligibility contract.

A number produced by a model is not evidence that the model was appropriate. This module
separates the questions that an equity research system must answer in order:

1. Is any implemented methodology admissible for this issuer at all?
2. Are the inputs that methodology requires present in the evidence store?
3. Is the methodology applicable on the available disclosures (not merely executable)?
4. Does an independent arithmetic reconstruction of every component agree?
5. Has an analyst reviewed the economic assumptions and their limitations?
6. Has the result been checked against an independently implemented reference?

The states form a ladder. A later state is never inferred from an earlier one: an
executing model stops at ``arithmetically_verified`` until the economic review and the
reference benchmark are recorded explicitly. This is the mechanism that prevents an
executing DCF from being presented as an economically supported valuation.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping

CONTRACT_VERSION = "atlas.valuation_eligibility.v3"
CONTRACT_SCHEMA = "atlas.valuation_eligibility.contract.v3"

UNSUPPORTED = "unsupported"
INSUFFICIENT_SOURCE_COVERAGE = "insufficient_source_coverage"
METHODOLOGICALLY_ELIGIBLE = "methodologically_eligible"
ARITHMETICALLY_VERIFIED = "arithmetically_verified"
ECONOMICALLY_REVIEWED = "economically_reviewed"
INDEPENDENTLY_BENCHMARKED = "independently_benchmarked"

STATE_ORDER = (
    UNSUPPORTED,
    INSUFFICIENT_SOURCE_COVERAGE,
    METHODOLOGICALLY_ELIGIBLE,
    ARITHMETICALLY_VERIFIED,
    ECONOMICALLY_REVIEWED,
    INDEPENDENTLY_BENCHMARKED,
)

DCF = "unlevered_fcff_dcf"
RESIDUAL_INCOME = "residual_income_equity"
JUSTIFIED_EARNINGS = "justified_earnings_equity"
REIT_FFO = "reit_ffo_affo_nav"
PROPERTY_NOI = "property_noi_dcf"

#: Inputs each method actually consumes. A bank model does not need revenue, and a DCF
#: does not need total liabilities, so the requirement list is per method rather than a
#: single global checklist.
REQUIRED_INPUTS: dict[str, tuple[str, ...]] = {
    DCF: ("revenue", "shares_outstanding", "net_income", "cash_and_equivalents"),
    RESIDUAL_INCOME: ("equity", "net_income", "shares_outstanding"),
    JUSTIFIED_EARNINGS: ("net_income", "equity", "shares_outstanding", "eps_diluted"),
}

#: Method-level contracts. v3 adds the evidence a method needs beyond its numeric
#: inputs, so an executable bank model cannot be described as capital-verified merely
#: because the arithmetic balanced.
METHOD_CONTRACTS: dict[str, dict[str, Any]] = {
    DCF: {
        "label": "Unlevered FCFF DCF",
        "required_inputs": list(REQUIRED_INPUTS[DCF]),
        "required_evidence": ["revenue", "reinvestment", "enterprise_to_equity_bridge"],
        "prohibited_for": ["bank", "capital_markets", "insurer", "real_estate_or_holding", "reit"],
        "evidence_note": "The bridge must subtract debt and add cash at the same date as the enterprise value.",
    },
    RESIDUAL_INCOME: {
        "label": "Equity residual income",
        "required_inputs": list(REQUIRED_INPUTS[RESIDUAL_INCOME]),
        "required_evidence": ["book_value_rollforward", "cost_of_equity", "clean_surplus"],
        "optional_evidence": ["regulatory_capital_ratios", "tangible_common_equity", "net_interest_margin", "credit_losses"],
        "prohibited_for": ["operating_company"],
        "evidence_note": (
            "A bank contract records whether regulatory capital evidence was aligned to the "
            "correct legal entity; arithmetic verification does not assert capital adequacy."
        ),
    },
    JUSTIFIED_EARNINGS: {
        "label": "Justified earnings with partial segment disclosure",
        "required_inputs": list(REQUIRED_INPUTS[JUSTIFIED_EARNINGS]),
        "required_evidence": ["earnings", "payout", "segment_limitation_disclosed"],
        "optional_evidence": ["medical_loss_ratio", "claims_reserves", "segment_split"],
        "prohibited_for": ["operating_company"],
        "evidence_note": "A consolidated insurer with a material services segment remains partial unless a segment split is observed.",
    },
    REIT_FFO: {
        "label": "REIT FFO/AFFO and net asset value",
        "required_inputs": [],
        "required_evidence": ["ffo_affo", "property_nav", "lease_roll"],
        "prohibited_for": ["operating_company", "bank", "insurer"],
        "implemented": False,
        "evidence_note": "Declared but not implemented; Atlas does not substitute an industrial DCF.",
    },
    PROPERTY_NOI: {
        "label": "Property NOI and equity cash flow",
        "required_inputs": [],
        "required_evidence": ["noi", "leases", "debt_service"],
        "prohibited_for": ["operating_company", "bank", "insurer"],
        "implemented": False,
        "evidence_note": "Declared but not implemented; no property-level observations are stored.",
    },
}

SUPPORTED_METHODS: dict[str, str] = {
    DCF: "Unlevered free cash flow to firm DCF for non-financial operating companies.",
    RESIDUAL_INCOME: (
        "Equity residual income: book value plus the present value of (ROE - cost of equity) "
        "on retained book value. Debt and deposits are operating inputs, not a separate "
        "capital structure to unlever."
    ),
    JUSTIFIED_EARNINGS: (
        "Justified earnings value with a residual-income cross-check for insurers whose "
        "consolidated statements mix underwriting and service operations."
    ),
}

PROHIBITED: dict[str, tuple[str, ...]] = {
    DCF: (
        "Any financial-institution use: banks, insurers, brokers and REIT-like balance-sheet "
        "businesses, where debt and deposits are operating and FCFF is not defined as for an "
        "industrial company.",
    ),
    RESIDUAL_INCOME: (
        "Use as a substitute for asset-based or segment-level analysis when book value is "
        "dominated by assets measured at fair value that the model treats as reproducible.",
    ),
    JUSTIFIED_EARNINGS: (
        "Use as a pure insurer model when consolidated earnings include a material non-insurance "
        "service segment and no segment split is available; the result must be labelled partial.",
    ),
}


def _sic_number(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(str(value).strip().split("-")[0])
    except (TypeError, ValueError):
        return None


def classify_business_model(sic: Any) -> dict[str, Any]:
    """Map an SIC code to a business model and the admissible methods.

    SIC is a coarse instrument. The classification is therefore stored with the model and
    is not presented as a curated industry taxonomy.
    """
    code = _sic_number(sic)
    if code is None:
        return {
            "business_model": "unknown",
            "method": None,
            "sector": None,
            "sic": None,
            "basis": "SIC not reported",
        }
    if 6000 <= code <= 6199:
        return {
            "business_model": "bank",
            "method": RESIDUAL_INCOME,
            "sector": "banking",
            "sic": code,
            "basis": f"SIC {code} is in the depository-institution division.",
        }
    if 6200 <= code <= 6299:
        return {
            "business_model": "capital_markets",
            "method": RESIDUAL_INCOME,
            "sector": "capital markets",
            "sic": code,
            "basis": (
                f"SIC {code} identifies a broker-dealer or capital-markets firm; book value and "
                "return on equity are the relevant operating quantities, not enterprise free cash flow."
            ),
        }
    if 6300 <= code <= 6411:
        return {
            "business_model": "insurer",
            "method": JUSTIFIED_EARNINGS,
            "sector": "insurance",
            "sic": code,
            "basis": f"SIC {code} is in the insurance division.",
        }
    if code == 6798:
        return {
            "business_model": "reit",
            "method": None,
            "intended_method": REIT_FFO,
            "sector": "real estate investment trust",
            "sic": code,
            "basis": (
                f"SIC {code} is a real-estate investment trust. FFO/AFFO and NAV contracts are "
                "declared but not implemented; no industrial DCF is substituted."
            ),
        }
    if 6500 <= code <= 6599:
        return {
            "business_model": "real_estate_or_holding",
            "method": None,
            "intended_method": PROPERTY_NOI,
            "sector": "real estate",
            "sic": code,
            "basis": (
                f"SIC {code} covers real-estate and holding structures; Atlas has no validated "
                "model for this business model and does not fall back to an industrial DCF."
            ),
        }
    return {
        "business_model": "operating_company",
        "method": DCF,
        "sector": "operating company",
        "sic": code,
        "basis": f"SIC {code} is outside the finance and insurance divisions.",
    }


def missing_inputs(method: str | None, available: Iterable[str]) -> list[str]:
    if method is None:
        return []
    present = set(available)
    return [key for key in REQUIRED_INPUTS.get(method, ()) if key not in present]


def build_contract(
    *,
    issuer: Mapping[str, Any],
    metrics: Mapping[str, Any],
    coverage: Mapping[str, Any],
    available: Iterable[str],
    assumptions: Mapping[str, Any] | None = None,
    arithmetic: Mapping[str, Any] | None = None,
    economic_review: Mapping[str, Any] | None = None,
    benchmark: Mapping[str, Any] | None = None,
    partial: bool = False,
    entity_check: Mapping[str, Any] | None = None,
    method_evidence: Mapping[str, Any] | None = None,
    extra_limitations: Iterable[str] = (),
) -> dict[str, Any]:
    """Build the six-state contract for one issuer and one method.

    ``arithmetic``, ``economic_review`` and ``benchmark`` are the only evidence that can
    promote the contract. Omitting them leaves the earlier state intact even when a model
    has produced a number.
    """
    classification = classify_business_model(issuer.get("sic"))
    method = classification["method"]
    dominant_method = method or DCF
    missing = missing_inputs(method, available)
    prohibited = list(PROHIBITED.get(dominant_method, ()))

    if method is None:
        state = UNSUPPORTED
        reasons = [classification["basis"], "No validated methodology is implemented for this business model."]
    elif missing:
        state = INSUFFICIENT_SOURCE_COVERAGE
        reasons = [classification["basis"], "Missing required inputs: " + ", ".join(missing) + "."]
    else:
        state = METHODOLOGICALLY_ELIGIBLE
        reasons = [classification["basis"]]
    if entity_check and entity_check.get("compatible") is False:
        state = INSUFFICIENT_SOURCE_COVERAGE
        reasons.append(
            "Entity reconciliation failed: " + str(entity_check.get("reason") or "incompatible reporting entities")
        )

    arithmetic_status = None
    if arithmetic:
        arithmetic_status = "pass" if arithmetic.get("passed") else "fail"
        if state == METHODOLOGICALLY_ELIGIBLE:
            state = ARITHMETICALLY_VERIFIED if arithmetic.get("passed") else METHODOLOGICALLY_ELIGIBLE
            if not arithmetic.get("passed"):
                reasons.append("Independent arithmetic reconstruction found a discrepancy.")
    if economic_review and state == ARITHMETICALLY_VERIFIED:
        state = ECONOMICALLY_REVIEWED
    if benchmark and state == ECONOMICALLY_REVIEWED:
        state = INDEPENDENTLY_BENCHMARKED

    limitations = []
    if partial:
        limitations.append(
            "This is a partial analysis: the consolidated disclosures do not separate every "
            "segment or regulatory entity the method would ideally use."
        )
    limitations.extend(extra_limitations)
    if missing:
        limitations.append("Missing required observations: " + ", ".join(missing) + ".")

    return {
        "schema": CONTRACT_SCHEMA,
        "contract_version": CONTRACT_VERSION,
        "company": {
            "issuer_id": issuer.get("issuer_id"),
            "cik": issuer.get("cik"),
            "legal_name": issuer.get("legal_name"),
            "ticker": coverage.get("ticker"),
            "sic": classification["sic"],
        },
        "security_identity": {
            "ticker": coverage.get("ticker"),
            "ticker_status": coverage.get("ticker_identity", {}).get("status"),
            "identity_is_provisional": coverage.get("ticker_identity", {}).get("status") != "verified",
        },
        "business_model": classification["business_model"],
        "sector": classification["sector"],
        "classification_basis": classification["basis"],
        "supported_methods": [method] if method else [],
        "method": method,
        "method_description": SUPPORTED_METHODS.get(dominant_method),
        "prohibited_methods": prohibited,
        "required_inputs": list(REQUIRED_INPUTS.get(dominant_method, ())),
        "available_inputs": sorted(set(available)),
        "missing_inputs": missing,
        "method_contract": METHOD_CONTRACTS.get(dominant_method, {}),
        "method_evidence": dict(method_evidence or {}),
        "entity_reconciliation": dict(entity_check) if entity_check else {"status": "not_evaluated"},
        "evidence_gates": {
            "data_available": not missing,
            "method_eligible": method is not None and not missing,
            "arithmetic_verified": bool(arithmetic and arithmetic.get("passed")),
            "assumptions_documented": bool(assumptions),
            "economic_review_recorded": bool(economic_review),
            "independent_benchmark_recorded": bool(benchmark),
        },
        "share_count_basis": coverage.get("share_basis") or "unknown",
        "accounting_normalization": {
            "status": "reported_facts_only",
            "note": (
                "Atlas stores the reported XBRL values with their source tags; it does not "
                "reclassify, smooth or adjust accounting policy."
            ),
        },
        "information_cutoff": metrics.get("as_of"),
        "model_assumptions": dict(assumptions or {}),
        "numerical_validation": dict(arithmetic or {}),
        "arithmetic_status": arithmetic_status,
        "economic_review": dict(economic_review) if economic_review else None,
        "independent_benchmark": dict(benchmark) if benchmark else None,
        "economic_limitations": limitations,
        "audit_status": "not_run" if not arithmetic else arithmetic_status,
        "state": state,
        "state_history": [item for item in STATE_ORDER if STATE_ORDER.index(item) <= STATE_ORDER.index(state)],
        "state_index": STATE_ORDER.index(state),
        "reasons": reasons,
        "promotion_policy": (
            "Execution alone never promotes the contract. Independent arithmetic must pass, an "
            "economic review must be recorded, and a reference benchmark must agree before the "
            "result is described as independently benchmarked."
        ),
    }
