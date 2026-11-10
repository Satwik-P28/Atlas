"""Typed, independently verifiable research claims.

A claim is a statement in a memo together with the exact objects that support it. Nothing in
this module creates a fact: a claim either resolves to stored evidence and a reproducible
transformation, or it is reported as unsupported. The verifier never deletes a failing claim
and never promotes an analyst opinion to an observation.

Contract: ``atlas.research_claim.v1``. The vocabulary for verification outcomes is fixed so
a caller cannot invent a softer word for a failed check.
"""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal, InvalidOperation
from typing import Any, Iterable

from ..core.errors import ValidationError
from ..fec.compiler import COMPILER_VERSION
from ..storage.db import Database

CLAIM_SCHEMA = "atlas.research_claim.v1"
CLAIM_VERSION = "1.0.0"
ARITHMETIC_VERSION = "atlas.claim.arithmetic.v1"

CLAIM_TYPES = (
    "observed_fact",
    "derived_financial_metric",
    "model_output",
    "analyst_assumption",
    "analyst_hypothesis",
    "methodology_disclosure",
    "unsupported_claim",
)
FACTUAL_TYPES = frozenset({"observed_fact", "derived_financial_metric", "model_output"})
VERIFICATION_OUTCOMES = (
    "verified",
    "partially_verified",
    "unsupported",
    "missing_evidence",
    "incompatible_model",
    "restricted_source",
    "unverifiable_historical_availability",
)
# Hypotheses and disclosures are not factual assertions, so they carry an explicit
# not-applicable marker instead of borrowing a factual outcome.
NON_FACTUAL_OUTCOME = "not_applicable"

RELATIVE_TOLERANCE = Decimal("1e-9")
REDISTRIBUTABLE = frozenset({"public_domain", "project_authored", "permitted"})

FACT_KEYS = (
    "revenue",
    "gross_profit",
    "operating_income",
    "net_income",
    "operating_cash_flow",
    "capex",
    "assets",
    "liabilities",
    "equity",
    "cash_and_equivalents",
    "eps_diluted",
    "shares_outstanding",
)

FORMULAS: dict[str, dict[str, Any]] = {
    "free_cash_flow": {
        "formula": "operating_cash_flow - abs(capex)",
        "inputs": ("operating_cash_flow", "capex"),
        "display": "Free cash flow",
    },
    "gross_margin": {
        "formula": "gross_profit / revenue",
        "inputs": ("gross_profit", "revenue"),
        "display": "Gross margin",
    },
    "operating_margin": {
        "formula": "operating_income / revenue",
        "inputs": ("operating_income", "revenue"),
        "display": "Operating margin",
    },
    "net_margin": {
        "formula": "net_income / revenue",
        "inputs": ("net_income", "revenue"),
        "display": "Net margin",
    },
    "roe": {
        "formula": "net_income / equity",
        "inputs": ("net_income", "equity"),
        "display": "Return on equity",
    },
}


def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _money(value: Decimal | None) -> str:
    return "—" if value is None else f"{value:,.2f}"


def claim_id(issuer_id: str, claim_type: str, key: str) -> str:
    digest = hashlib.sha256(f"{issuer_id}|{claim_type}|{key}".encode("utf-8")).hexdigest()
    return f"CLM-{digest[:16]}"


def _claim(
    *,
    issuer_id: str,
    claim_type: str,
    key: str,
    statement: str,
    value: Any = None,
    unit: str | None = None,
    currency: str | None = None,
    period: dict[str, Any] | None = None,
    cutoff: str | None = None,
    evidence_ids: Iterable[str] = (),
    observation_ids: Iterable[str] = (),
    model: dict[str, Any] | None = None,
    assumptions: Iterable[str] = (),
    transformation: str | None = None,
    computation: dict[str, Any] | None = None,
    limitations: Iterable[str] = (),
    concept: str | None = None,
    requires_review: bool = False,
) -> dict[str, Any]:
    if claim_type not in CLAIM_TYPES:
        raise ValidationError("unknown claim type", claim_type=claim_type)
    return {
        "schema": CLAIM_SCHEMA,
        "claim_version": CLAIM_VERSION,
        "claim_id": claim_id(issuer_id, claim_type, key),
        "key": key,
        "research_object_id": None,
        "issuer_id": issuer_id,
        "claim_type": claim_type,
        "concept": concept,
        "statement": statement,
        "value": None if value is None else str(value),
        "unit": unit,
        "currency": currency,
        "period": period or {},
        "cutoff": cutoff,
        "evidence_ids": sorted(set(evidence_ids)),
        "observation_ids": sorted(set(observation_ids)),
        "model": model,
        "assumption_ids": sorted(set(assumptions)),
        "transformation": transformation,
        "computation": computation,
        "verification": {
            "outcome": NON_FACTUAL_OUTCOME
            if claim_type not in FACTUAL_TYPES
            else "unsupported",
            "checks": [],
            "diagnostics": [],
        },
        "requires_review": requires_review,
        "limitations": list(limitations),
    }


def _period(metrics: dict[str, Any]) -> dict[str, Any]:
    return {
        "end": metrics.get("period_end"),
        "start": metrics.get("period_start"),
        "type": metrics.get("period_type"),
        "fiscal_period": metrics.get("fiscal_period"),
    }


# --------------------------------------------------------------------------- builders
def _fact_claims(analysis: dict[str, Any], *, cutoff: str) -> list[dict[str, Any]]:
    workspace = analysis["workspace"]
    metrics = workspace["metrics"]
    issuer_id = workspace["company"]["issuer_id"]
    period = _period(metrics)
    claims: list[dict[str, Any]] = []
    for key in FACT_KEYS:
        item = (metrics.get("metrics") or {}).get(key)
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        value = _dec(item["value"])
        claims.append(_claim(
            issuer_id=issuer_id,
            claim_type="observed_fact",
            key=key,
            concept=item.get("concept") or key,
            statement=(
                f"{key.replace('_', ' ').capitalize()} was {_money(value)} "
                f"{item.get('unit') or 'USD'} for period {period.get('end') or 'unknown'}."
            ),
            value=item["value"],
            unit=item.get("unit"),
            currency=item.get("currency") or "USD",
            period=period,
            cutoff=cutoff,
            evidence_ids=item.get("evidence_ids") or [],
            limitations=[
                "Reported value as stored; Atlas does not adjust or smooth the figure."
            ],
        ))
    return claims


def _derived_claims(analysis: dict[str, Any], *, cutoff: str) -> list[dict[str, Any]]:
    workspace = analysis["workspace"]
    metrics = workspace["metrics"]
    issuer_id = workspace["company"]["issuer_id"]
    period = _period(metrics)
    claims: list[dict[str, Any]] = []
    for key, spec in FORMULAS.items():
        item = (metrics.get("metrics") or {}).get(key)
        if not isinstance(item, dict) or item.get("value") is None:
            continue
        inputs = []
        usable = True
        for name in spec["inputs"]:
            source = (metrics.get("metrics") or {}).get(name)
            if not isinstance(source, dict) or source.get("value") is None:
                usable = False
                break
            inputs.append({
                "key": name,
                "value": str(source["value"]),
                "evidence_ids": sorted(set(source.get("evidence_ids") or [])),
            })
        if not usable:
            continue
        value = _dec(item["value"])
        claims.append(_claim(
            issuer_id=issuer_id,
            claim_type="derived_financial_metric",
            key=key,
            concept=key,
            statement=f"{spec['display']} is {value if value is None else round(float(value), 10)} "
                      f"computed as `{spec['formula']}` for period {period.get('end') or 'unknown'}.",
            value=item["value"],
            unit=item.get("unit"),
            currency=item.get("currency") or "USD",
            period=period,
            cutoff=cutoff,
            evidence_ids=[
                evidence_id for entry in inputs for evidence_id in entry["evidence_ids"]
            ],
            transformation=spec["formula"],
            computation={
                "formula_key": key,
                "formula": spec["formula"],
                "operator_version": ARITHMETIC_VERSION,
                "inputs": inputs,
                "tolerance": str(RELATIVE_TOLERANCE),
            },
            limitations=[
                "Recomputed from reported inputs with plain arithmetic, independently of the "
                "read model that produced it."
            ],
        ))
    return claims


def _model_claims(analysis: dict[str, Any], *, cutoff: str) -> list[dict[str, Any]]:
    valuation = analysis["valuation"]
    workspace = analysis["workspace"]
    issuer_id = workspace["company"]["issuer_id"]
    metadata = analysis["metadata"]
    model_claims: list[dict[str, Any]] = []
    institutional = valuation.get("institution")
    if institutional:
        outputs = institutional.get("outputs") or {}
        audit_block = institutional.get("audit") or {}
        model = {
            "name": institutional.get("method"),
            "version": institutional.get("model_version"),
            "compiler_version": COMPILER_VERSION,
            "fingerprint": institutional.get("fingerprint"),
            # Institution models report ``passed``; the DCF reports ``arithmetic_valid`` and a
            # ``verdict``. Both shapes are read so a missing verdict can never read as a pass.
            "audit_verdict": audit_block.get("verdict") or (
                "arithmetic_pass" if audit_block.get("passed") else "arithmetic_failure"
            ),
            "arithmetic_valid": bool(
                audit_block.get("arithmetic_valid", audit_block.get("passed", False))
            ),
            "executes": bool(institutional.get("executes")),
        }
        for key in ("value_per_share", "equity_value", "residual_income_value"):
            if outputs.get(key) is None:
                continue
            model_claims.append(_claim(
                issuer_id=issuer_id,
                claim_type="model_output",
                key=f"institution.{key}",
                statement=(
                    f"`{institutional.get('method')}` v{institutional.get('model_version')} "
                    f"returns {key} = {outputs[key]} USD."
                ),
                value=outputs[key],
                unit="USD per share" if key == "value_per_share" else "USD",
                currency="USD",
                period=_period(workspace["metrics"]),
                cutoff=cutoff,
                model=model,
                assumptions=sorted((institutional.get("assumptions") or {}).keys()),
                transformation=str(institutional.get("method")),
                limitations=list(institutional.get("limitations") or []),
            ))
        return model_claims
    dcf = valuation.get("dcf")
    if not dcf:
        return model_claims
    audit = valuation.get("audit") or {}
    manifest = dcf.get("manifest") or {}
    model = {
        "name": "unlevered_fcff_dcf",
        "version": manifest.get("model_version") or manifest.get("version"),
        "compiler_version": manifest.get("compiler_version") or COMPILER_VERSION,
        "fingerprint": dcf.get("fingerprint"),
        "audit_verdict": audit.get("verdict"),
        "arithmetic_valid": bool(audit.get("arithmetic_valid")),
        "executes": True,
    }
    outputs = dcf.get("outputs") or {}
    for key in ("value_per_share", "equity_value", "enterprise_value", "pv_terminal"):
        if outputs.get(key) is None:
            continue
        model_claims.append(_claim(
            issuer_id=issuer_id,
            claim_type="model_output",
            key=f"dcf.{key}",
            statement=(
                f"Compiled FCFF DCF returns {key.replace('_', ' ')} = "
                f"{_money(_dec(outputs[key]))} USD."
            ),
            value=outputs[key],
            unit="USD per share" if key == "value_per_share" else "USD",
            currency="USD",
            period=_period(workspace["metrics"]),
            cutoff=cutoff,
            model=model,
            assumptions=sorted((dcf.get("assumptions") or {}).keys()),
            transformation="PV(FCFF) + PV(terminal value) + cash - debt, divided by shares",
            limitations=[
                "The model is reproducible arithmetic over reported inputs and analyst "
                "assumptions; it is not an economic validation or an investment recommendation."
            ],
        ))
    return model_claims


def _assumption_claims(analysis: dict[str, Any], *, cutoff: str) -> list[dict[str, Any]]:
    valuation = analysis["valuation"]
    workspace = analysis["workspace"]
    issuer_id = workspace["company"]["issuer_id"]
    source = (valuation.get("dcf") or {}).get("assumptions") if valuation.get("dcf") else (
        (valuation.get("institution") or {}).get("assumptions") or {}
    )
    if not isinstance(source, dict):
        return []
    claims: list[dict[str, Any]] = []
    for key in sorted(source):
        value = source[key]
        if isinstance(value, (list, dict)):
            rendered = json.dumps(value, sort_keys=True, default=str)
        else:
            rendered = str(value)
        claims.append(_claim(
            issuer_id=issuer_id,
            claim_type="analyst_assumption",
            key=f"assumption.{key}",
            statement=f"Analyst assumption `{key}` is set to {rendered}.",
            value=rendered,
            cutoff=cutoff,
            limitations=[
                "This is an authored assumption. It is not a reported fact and is not "
                "promoted by verification."
            ],
        ))
    return claims


def _disclosure_claims(analysis: dict[str, Any], *, cutoff: str) -> list[dict[str, Any]]:
    valuation = analysis["valuation"]
    workspace = analysis["workspace"]
    coverage = workspace["coverage"]
    issuer_id = workspace["company"]["issuer_id"]
    eligibility = valuation.get("eligibility") or {}
    disclosures: list[dict[str, Any]] = []

    def add(key: str, statement: str, limitations: Iterable[str] = ()) -> None:
        disclosures.append(_claim(
            issuer_id=issuer_id,
            claim_type="methodology_disclosure",
            key=f"disclosure.{key}",
            statement=statement,
            cutoff=cutoff,
            limitations=list(limitations),
        ))

    add(
        "business_model",
        f"Issuer is a {eligibility.get('business_model') or 'unclassified'} business "
        f"(SIC {eligibility.get('sic')}); the admissible valuation method is "
        f"`{eligibility.get('method') or 'none'}`.",
        [str(eligibility.get("method_basis") or "")],
    )
    if eligibility.get("rejected_method"):
        add(
            "rejected_method",
            f"`{eligibility['rejected_method']}` is rejected for this issuer type; Atlas does "
            "not run an inappropriate model to produce a number.",
        )
    add(
        "information_cutoff",
        f"All claims are restricted to evidence available at or before {cutoff}.",
    )
    add(
        "coverage",
        f"The fixture holds {coverage['evidence_records']:,} evidence records across "
        f"{coverage['concepts']} concepts and {coverage['annual_periods']} annual periods "
        f"({coverage['first_period'] or '—'} to {coverage['last_period'] or '—'}).",
        [
            "The compact fixture is not a complete SEC archive, so absence of a concept is not "
            "evidence that the issuer never reported it."
        ],
    )
    if coverage["missing_core_concepts"]:
        add(
            "missing_core_concepts",
            "Missing core concepts: " + ", ".join(coverage["missing_core_concepts"]) + ".",
            ["Missing inputs are reported, never zero-filled."],
        )
    market = workspace.get("market_price") or {}
    if market.get("status") != "available":
        add(
            "no_market_price",
            "No authorised market observation is stored for this issuer, so market multiples "
            "and market-implied reverse DCF are unavailable.",
            ["A synthetic or vendor price is never substituted into real-company research."],
        )
    else:
        source_selection = market.get("source_selection") or {}
        add(
            "market_price",
            f"Market comparison uses the selected observation dated {market.get('as_of')} from "
            f"`{source_selection.get('source_id') or 'unknown source'}` under policy "
            f"`{source_selection.get('policy')}`.",
            [
                "A price is an observation by one provider, not a consensus or a fair value."
            ],
        )
    distribution = (workspace.get("provenance") or {}).get("sources") or []
    for source in distribution:
        add(
            f"rights.{source['source_id']}",
            f"Source `{source['source_id']}` is licensed `{source.get('licence')}` with "
            f"redistribution class `{source.get('redistribution')}`.",
            ["Export is refused when a cited source does not permit redistribution."],
        )
    return disclosures


def _hypothesis_claims(analysis: dict[str, Any], *, cutoff: str) -> list[dict[str, Any]]:
    workspace = analysis["workspace"]
    issuer_id = workspace["company"]["issuer_id"]
    name = workspace["company"]["legal_name"]
    return [_claim(
        issuer_id=issuer_id,
        claim_type="analyst_hypothesis",
        key="research_question",
        statement=(
            f"Testable proposition: the reported statements of {name} support the stated "
            "valuation under the declared assumptions."
        ),
        cutoff=cutoff,
        limitations=[
            "This is the analyst's proposition. It is not an observed fact, and answering it "
            "requires the evidence and model results cited elsewhere in this memo."
        ],
    )]


def build_claims(analysis: dict[str, Any], *, cutoff: str) -> list[dict[str, Any]]:
    """Build every claim the memo may state, from the existing analysis only."""
    claims: list[dict[str, Any]] = []
    claims.extend(_fact_claims(analysis, cutoff=cutoff))
    claims.extend(_derived_claims(analysis, cutoff=cutoff))
    claims.extend(_model_claims(analysis, cutoff=cutoff))
    claims.extend(_assumption_claims(analysis, cutoff=cutoff))
    claims.extend(_disclosure_claims(analysis, cutoff=cutoff))
    claims.extend(_hypothesis_claims(analysis, cutoff=cutoff))
    return claims


# ------------------------------------------------------------------------- verification
def _evidence_rows(db: Database, evidence_ids: Iterable[str]) -> dict[str, dict[str, Any]]:
    ids = sorted(set(evidence_ids))
    if not ids:
        return {}
    marks = ",".join("?" for _ in ids)
    rows = db.query(
        "SELECT evidence_id, entity_id, entity_kind, concept, period_start, period_end, "
        "value_numeric, value_text, unit, currency, source_id, availability_time, filed_date, "
        "accession_number, form_type, acceptance_datetime, revision_kind, supersedes, "
        "raw_doc_id, content_hash FROM evidence WHERE evidence_id IN (" + marks + ")",
        ids,
    )
    return {row["evidence_id"]: dict(row) for row in rows}


def _verify_inputs(db: Database, inputs: list[dict[str, Any]], issuer_id: str,
                   period_end: str | None) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    checks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    all_ids = [eid for entry in inputs for eid in entry["evidence_ids"]]
    rows = _evidence_rows(db, all_ids)
    for entry in inputs:
        expected = _dec(entry["value"])
        matched = False
        for evidence_id in entry["evidence_ids"]:
            row = rows.get(evidence_id)
            if row is None:
                diagnostics.append({
                    "code": "evidence_missing",
                    "detail": f"input `{entry['key']}` cites unknown evidence {evidence_id}",
                    "evidence_id": evidence_id,
                })
                continue
            if row["entity_id"] != issuer_id:
                diagnostics.append({
                    "code": "issuer_mismatch",
                    "detail": f"evidence {evidence_id} belongs to {row['entity_id']}, not {issuer_id}",
                    "evidence_id": evidence_id,
                })
                continue
            stored = _dec(row["value_numeric"])
            if stored is not None and expected is not None and stored == expected:
                matched = True
                if period_end and row.get("period_end") and row["period_end"] != period_end:
                    checks.append({
                        "name": f"input {entry['key']} period",
                        "passed": False,
                        "detail": f"stored period {row['period_end']} differs from {period_end}",
                    })
        checks.append({
            "name": f"input {entry['key']} resolves to stored evidence",
            "passed": matched,
            "detail": f"{len(entry['evidence_ids'])} cited record(s)",
        })
        if not matched:
            diagnostics.append({
                "code": "value_mismatch",
                "detail": f"no cited record for `{entry['key']}` holds {entry['value']}",
            })
    return checks, diagnostics


def _compute(key: str, values: dict[str, Decimal]) -> Decimal | None:
    try:
        if key == "free_cash_flow":
            return values["operating_cash_flow"] - abs(values["capex"])
        if key == "gross_margin":
            return values["gross_profit"] / values["revenue"]
        if key == "operating_margin":
            return values["operating_income"] / values["revenue"]
        if key == "net_margin":
            return values["net_income"] / values["revenue"]
        if key == "roe":
            return values["net_income"] / values["equity"]
    except (KeyError, ArithmeticError):
        return None
    return None


def verify_claim(db: Database, claim: dict[str, Any]) -> dict[str, Any]:
    """Verify one claim and return the claim with its verification block filled in."""
    claim = json.loads(json.dumps(claim))
    outcome = "unsupported"
    checks: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    claim_type = claim["claim_type"]
    if claim_type not in FACTUAL_TYPES:
        claim["verification"] = {
            "outcome": NON_FACTUAL_OUTCOME,
            "checks": [{
                "name": "factual verification not applicable",
                "passed": True,
                "detail": f"`{claim_type}` claims are never presented as observed facts",
            }],
            "diagnostics": [],
        }
        return claim

    rows = _evidence_rows(db, claim["evidence_ids"])
    if claim["evidence_ids"]:
        missing = [eid for eid in claim["evidence_ids"] if eid not in rows]
        if missing:
            diagnostics.append({
                "code": "evidence_missing",
                "detail": "cited evidence does not exist in this database",
                "evidence_ids": missing,
            })

    if claim_type == "observed_fact":
        value = _dec(claim["value"])
        matched_value = False
        for evidence_id in claim["evidence_ids"]:
            row = rows.get(evidence_id)
            if row is None:
                continue
            if row["entity_id"] != claim["issuer_id"]:
                diagnostics.append({
                    "code": "issuer_mismatch",
                    "detail": f"{evidence_id} belongs to {row['entity_id']}",
                    "evidence_id": evidence_id,
                })
                continue
            if claim["period"].get("end") and row.get("period_end") != claim["period"]["end"]:
                diagnostics.append({
                    "code": "period_mismatch",
                    "detail": f"{evidence_id} period {row.get('period_end')} differs from "
                              f"{claim['period']['end']}",
                    "evidence_id": evidence_id,
                })
                continue
            if claim.get("unit") and row.get("unit") and row["unit"] != claim["unit"]:
                diagnostics.append({
                    "code": "unit_mismatch",
                    "detail": f"{evidence_id} unit {row['unit']} differs from {claim['unit']}",
                    "evidence_id": evidence_id,
                })
                continue
            if claim.get("currency") and row.get("currency") and row["currency"] != claim["currency"]:
                diagnostics.append({
                    "code": "currency_mismatch",
                    "detail": f"{evidence_id} currency {row['currency']} differs from "
                              f"{claim['currency']}",
                    "evidence_id": evidence_id,
                })
                continue
            stored = _dec(row["value_numeric"])
            if stored is None or value is None or stored != value:
                diagnostics.append({
                    "code": "value_mismatch",
                    "detail": f"{evidence_id} stores {row['value_numeric']} but the claim states "
                              f"{claim['value']}",
                    "evidence_id": evidence_id,
                })
                continue
            if claim.get("cutoff") and row.get("availability_time") \
                    and str(row["availability_time"]) > str(claim["cutoff"]):
                diagnostics.append({
                    "code": "availability_after_cutoff",
                    "detail": f"{evidence_id} became available at {row['availability_time']}, "
                              f"after the cutoff {claim['cutoff']}",
                    "evidence_id": evidence_id,
                })
                continue
            matched_value = True
        checks.append({
            "name": "claim matches a stored observation exactly",
            "passed": matched_value,
            "detail": f"{len(claim['evidence_ids'])} cited record(s)",
        })
        if not claim["evidence_ids"]:
            diagnostics.append({
                "code": "evidence_missing",
                "detail": "a factual claim must cite at least one evidence id",
            })
        outcome = "verified" if matched_value and not diagnostics else (
            "missing_evidence" if any(d["code"] == "evidence_missing" for d in diagnostics)
            else "unsupported"
        )

    elif claim_type == "derived_financial_metric":
        computation = claim.get("computation") or {}
        inputs = computation.get("inputs") or []
        input_checks, input_diagnostics = _verify_inputs(
            db, inputs, claim["issuer_id"], claim["period"].get("end")
        )
        checks.extend(input_checks)
        diagnostics.extend(input_diagnostics)
        values = {entry["key"]: _dec(entry["value"]) for entry in inputs}
        expected = _compute(computation.get("formula_key") or "", {
            key: value for key, value in values.items() if value is not None
        })
        stated = _dec(claim["value"])
        tolerance = RELATIVE_TOLERANCE * max(Decimal(1), abs(expected)) if expected is not None else None
        reproducible = (
            expected is not None and stated is not None and tolerance is not None
            and abs(expected - stated) <= tolerance
        )
        checks.append({
            "name": "independent recomputation reproduces the stated value",
            "passed": reproducible,
            "detail": f"recomputed {expected} against stated {stated} "
                      f"with tolerance {RELATIVE_TOLERANCE}",
        })
        if not reproducible:
            diagnostics.append({
                "code": "value_mismatch",
                "detail": "the derived value does not reproduce from its recorded inputs",
            })
        outcome = "verified" if reproducible and not diagnostics else (
            "missing_evidence" if any(d["code"] == "evidence_missing" for d in diagnostics)
            else "unsupported"
        )

    elif claim_type == "model_output":
        model = claim.get("model") or {}
        checks.append({
            "name": "model execution manifest is recorded",
            "passed": bool(model.get("name") and model.get("version")),
            "detail": f"{model.get('name')} v{model.get('version')}",
        })
        compiler = model.get("compiler_version")
        compatible = compiler in (None, COMPILER_VERSION)
        checks.append({
            "name": "compiler version is compatible",
            "passed": compatible,
            "detail": f"recorded {compiler}, current {COMPILER_VERSION}",
        })
        arithmetic = bool(model.get("arithmetic_valid"))
        checks.append({
            "name": "independent component audit passed",
            "passed": arithmetic,
            "detail": f"verdict {model.get('audit_verdict')}",
        })
        assumptions = (analysis_assumptions := claim.get("assumption_ids") or [])
        checks.append({
            "name": "assumptions are declared",
            "passed": bool(assumptions),
            "detail": f"{len(analysis_assumptions)} assumption(s)",
        })
        if not compatible:
            diagnostics.append({
                "code": "model_incompatible",
                "detail": "the recorded model was compiled by a different compiler version",
            })
        if not arithmetic:
            diagnostics.append({
                "code": "model_audit_failed",
                "detail": f"audit verdict {model.get('audit_verdict')}",
            })
        outcome = (
            "incompatible_model" if any(d["code"] == "model_incompatible" for d in diagnostics)
            else "verified" if all(check["passed"] for check in checks)
            else "unsupported"
        )

    claim["verification"] = {
        "outcome": outcome,
        "checks": checks,
        "diagnostics": diagnostics,
        "requires_review": outcome not in {"verified"} and outcome != NON_FACTUAL_OUTCOME,
    }
    return claim


def verify_claims(db: Database, claims: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [verify_claim(db, claim) for claim in claims]


# --------------------------------------------------------------------------- citations
def evidence_citation(db: Database, evidence_id: str) -> dict[str, Any]:
    """Resolve one evidence record into an inspectable citation, or say it is gone."""
    row = db.query_one(
        "SELECT e.evidence_id, e.concept, e.period_start, e.period_end, e.fiscal_period, "
        "e.value_numeric, e.unit, e.currency, e.accession_number, e.form_type, e.filed_date, "
        "e.acceptance_datetime, e.availability_time, e.revision_kind, e.supersedes, "
        "e.raw_doc_id, e.content_hash, e.source_id, i.cik, i.legal_name "
        "FROM evidence e LEFT JOIN issuer i ON i.issuer_id = e.entity_id "
        "WHERE e.evidence_id = ?",
        (evidence_id,),
    )
    if row is None:
        return {
            "kind": "evidence",
            "evidence_id": evidence_id,
            "status": "unavailable",
            "reason": "the cited evidence record is not present in this database",
        }
    citation = dict(row)
    citation.update({
        "kind": "evidence",
        "status": "resolved",
        "inspector": f"/api/evidence/{evidence_id}",
        "passage": None,
        "passage_note": (
            "Atlas stores the structured XBRL fact and its source document id, not a page "
            "number; no page reference or quotation is invented."
        ),
    })
    return citation


def observation_citation(pin: dict[str, Any]) -> dict[str, Any]:
    return {
        "kind": "market_observation",
        "status": "resolved" if pin.get("observation_id") else "unavailable",
        "security_id": pin.get("security_id"),
        "mic": pin.get("mic"),
        "provider": pin.get("source_id"),
        "session": pin.get("session"),
        "revision": pin.get("revision_seq"),
        "observation_id": pin.get("observation_id"),
        "content_hash": pin.get("content_hash"),
        "rights": pin.get("redistribution"),
        "adjustment": pin.get("adjustment"),
    }


def model_citation(model: dict[str, Any] | None) -> dict[str, Any]:
    model = model or {}
    return {
        "kind": "model_output",
        "status": "resolved" if model.get("name") else "unavailable",
        "model": model.get("name"),
        "version": model.get("version"),
        "compiler_version": model.get("compiler_version"),
        "fingerprint": model.get("fingerprint"),
        "audit_verdict": model.get("audit_verdict"),
    }


def rights_decision(sources: Iterable[dict[str, Any]]) -> dict[str, Any]:
    """A source that forbids redistribution forbids export; unknown classes fail closed."""
    blocked = [
        source for source in sources
        if str(source.get("redistribution") or "").lower() not in REDISTRIBUTABLE
    ]
    return {
        "redistributable": not blocked,
        "blocked_sources": [
            {
                "source_id": source.get("source_id"),
                "redistribution": source.get("redistribution"),
                "licence": source.get("licence"),
            }
            for source in blocked
        ],
        "note": (
            "Redistribution classes outside public_domain, project_authored and permitted are "
            "treated as restricted; an unknown class permits nothing."
        ),
    }
