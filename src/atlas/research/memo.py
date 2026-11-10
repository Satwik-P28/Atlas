"""Evidence-grounded research memo: one authoritative object, several views.

The memo is built from the existing equity-research service and its claims. It never
recalculates a number: every figure in every export is a claim that a verifier checked
against stored evidence or a reproducible transformation. Markdown, HTML and the JSON
manifest are views of the same object, so a screen, a report and a download cannot disagree.
"""

from __future__ import annotations

import hashlib
import html
import json
from typing import Any, Iterable

from ..core.errors import ValidationError
from ..core.temporal import iso, utcnow
from ..fec.compiler import COMPILER_VERSION
from ..storage.db import Database
from . import claims as claim_contract
from .equity import EquityResearchService
from .objects import ResearchObjectStore

MEMO_SCHEMA = "atlas.research_memo.v1"
MEMO_VERSION = "1.0.0"
MANIFEST_SCHEMA = "atlas.research_memo.manifest.v1"
INTEGRITY_SCHEMA = "atlas.research_integrity.v1"
EXPORT_FORMATS = ("markdown", "html", "json")

SECTION_ORDER = (
    ("identity", "Report identity and version"),
    ("issuer_security", "Issuer and relevant security"),
    ("cutoff", "Information cutoff"),
    ("objective", "Research objective"),
    ("financial_summary", "Financial summary"),
    ("historical_analysis", "Historical financial analysis"),
    ("valuation_methodology", "Valuation methodology"),
    ("model_assumptions", "Explicit model assumptions"),
    ("scenarios", "Scenario and sensitivity results"),
    ("numerical_validation", "Numerical validation"),
    ("market_comparison", "Market comparison, where valid"),
    ("analyst_thesis", "Analyst thesis or hypotheses"),
    ("risks_counterarguments", "Risks and counterarguments"),
    ("evidence_coverage", "Evidence coverage"),
    ("unresolved_contradictions", "Unresolved contradictions"),
    ("source_limitations", "Source limitations"),
    ("research_integrity", "Research integrity results"),
    ("references", "References"),
    ("reproduction_manifest", "Reproduction manifest"),
    ("export_rights", "Export and rights information"),
)


def canonical(document: Any) -> str:
    return json.dumps(document, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def _hashable(memo: dict[str, Any]) -> dict[str, Any]:
    """Strip derived fields so the hash is stable and independently recomputable."""
    body = {
        key: value for key, value in memo.items()
        if key not in {"content_hash", "generated_at", "memo_id"}
    }
    manifest = dict(body.get("manifest") or {})
    manifest.pop("content_hash", None)
    body["manifest"] = manifest
    body["claims"] = [
        {key: value for key, value in claim.items() if key != "research_object_id"}
        for claim in body.get("claims") or []
    ]
    return body


def memo_hash(memo: dict[str, Any]) -> str:
    return hashlib.sha256(canonical(_hashable(memo)).encode("utf-8")).hexdigest()


def _by_type(claims: list[dict[str, Any]], claim_type: str) -> list[dict[str, Any]]:
    return [claim for claim in claims if claim["claim_type"] == claim_type]


def _by_key(claims: list[dict[str, Any]], prefix: str) -> list[dict[str, Any]]:
    return [claim for claim in claims if str(claim["key"]).startswith(prefix)]


def _outcome(claim: dict[str, Any]) -> str:
    return str((claim.get("verification") or {}).get("outcome"))


# ------------------------------------------------------------------------- integrity
def integrity_report(analysis: dict[str, Any], claims: list[dict[str, Any]]) -> dict[str, Any]:
    """Four independent integrity dimensions. No single trust score is produced."""
    valuation = analysis["valuation"]
    workspace = analysis["workspace"]
    factual = [claim for claim in claims if claim["claim_type"] in claim_contract.FACTUAL_TYPES]
    unverified = [claim["claim_id"] for claim in factual if _outcome(claim) != "verified"]
    missing = [
        claim["claim_id"] for claim in factual
        if _outcome(claim) in {"missing_evidence", "unverifiable_historical_availability"}
    ]
    restricted = [
        claim["claim_id"] for claim in factual if _outcome(claim) == "restricted_source"
    ]

    if not factual:
        evidence_dimension = {
            "outcome": "insufficient_evidence",
            "detail": "no factual claim could be constructed for this issuer",
        }
    elif missing:
        evidence_dimension = {
            "outcome": "fail",
            "detail": f"{len(missing)} claim(s) cannot resolve their evidence",
            "claims": missing,
        }
    elif unverified:
        evidence_dimension = {
            "outcome": "fail",
            "detail": f"{len(unverified)} claim(s) are not independently verified",
            "claims": unverified,
        }
    else:
        evidence_dimension = {
            "outcome": "pass",
            "detail": f"{len(factual)} factual claim(s) resolve to stored evidence or a "
                      "reproducible transformation",
        }
    evidence_dimension.update({
        "dimension": "evidence",
        "checks": {
            "cited_evidence_records": sum(len(claim["evidence_ids"]) for claim in claims),
            "cutoff": workspace["as_of"],
            "restricted_claims": restricted,
            "conflicts": [
                claim["claim_id"] for claim in claims
                if (claim.get("verification") or {}).get("diagnostics")
                and any(
                    item.get("code") in {"value_mismatch", "period_mismatch", "issuer_mismatch"}
                    for item in claim["verification"]["diagnostics"]
                )
            ],
            "rights": claim_contract.rights_decision(
                (workspace.get("provenance") or {}).get("sources") or []
            ),
        },
        "note": "Coverage, conflicts, cutoff and rights are reported, never folded into a score.",
    })

    model_claims = _by_type(claims, "model_output")
    audit = valuation.get("audit") or (valuation.get("institution") or {}).get("audit") or {}
    arithmetic_ok = bool(audit.get("arithmetic_valid", audit.get("passed", False)))
    audit_verdict = audit.get("verdict") or (
        "arithmetic_pass" if audit.get("passed") else "arithmetic_failure" if audit else None
    )
    if not model_claims:
        computational = {
            "outcome": "not_applicable",
            "detail": "no model output is claimed for this issuer",
        }
    elif not arithmetic_ok:
        computational = {
            "outcome": "fail",
            "detail": f"independent arithmetic audit verdict {audit_verdict}",
        }
    elif any(_outcome(claim) != "verified" for claim in model_claims):
        computational = {
            "outcome": "fail",
            "detail": "a model claim failed verification",
            "claims": [claim["claim_id"] for claim in model_claims if _outcome(claim) != "verified"],
        }
    else:
        computational = {
            "outcome": "pass",
            "detail": f"{len(model_claims)} model claim(s) reproduce from the recorded "
                      "assumptions and pass the independent component audit",
        }
    computational.update({
        "dimension": "computational",
        "checks": {
            "arithmetic_verdict": audit_verdict,
            "component_checks": len(audit.get("checks") or []),
            "compiler_version": COMPILER_VERSION,
            "assumption_count": len(_by_type(claims, "analyst_assumption")),
        },
        "note": "A passing deterministic model is arithmetic consistency, not economic truth.",
    })

    statistical = {
        "dimension": "statistical",
        "outcome": "not_applicable",
        "detail": (
            "This memo contains no forecast evaluation, regression or hypothesis test; a "
            "deterministic valuation is not statistical evidence."
        ),
        "checks": {"empirical_tests": 0},
        "note": "Statistical integrity is never marked passed because a model executed.",
    }

    decision = valuation.get("sensitivity") or (valuation.get("institution") or {}).get("sensitivity")
    supported = bool(valuation.get("economically_supported"))
    scenario_claims = _by_type(claims, "analyst_hypothesis")
    if not model_claims:
        decision_dimension = {
            "outcome": "insufficient_evidence",
            "detail": "no supported valuation exists, so decision robustness cannot be assessed",
        }
    elif not decision:
        decision_dimension = {
            "outcome": "insufficient_evidence",
            "detail": "no sensitivity grid was produced for this valuation",
        }
    elif not supported:
        decision_dimension = {
            "outcome": "fail",
            "detail": f"valuation verdict {audit_verdict} is not economically supported",
        }
    else:
        decision_dimension = {
            "outcome": "pass",
            "detail": "valuation is supported and its sensitivity grid is reported alongside "
                      "the declared assumptions",
        }
    decision_dimension.update({
        "dimension": "decision",
        "checks": {
            "economically_supported": supported,
            "sensitivity_available": bool(decision),
            "hypotheses": len(scenario_claims),
            "final_findings": [finding.get("code") for finding in valuation.get("findings") or []],
        },
        "note": "An investment conclusion requires the analyst; the memo reports the uncertainty.",
    })

    dimensions = [evidence_dimension, computational, statistical, decision_dimension]
    return {
        "schema": INTEGRITY_SCHEMA,
        "dimensions": {item["dimension"]: item for item in dimensions},
        "failures": [
            {"dimension": item["dimension"], "detail": item["detail"]}
            for item in dimensions if item["outcome"] == "fail"
        ],
        "outcome_counts": {
            outcome: sum(1 for item in dimensions if item["outcome"] == outcome)
            for outcome in ("pass", "fail", "insufficient_evidence", "not_applicable", "not_run")
        },
        "note": (
            "Each dimension is reported independently. There is no aggregate trust percentage, "
            "and a failure names the claim or check that failed."
        ),
    }


class ResearchMemoService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.equity = EquityResearchService(db)
        self.store = ResearchObjectStore(db)

    # ------------------------------------------------------------------- building
    def build(
        self,
        identifier: str,
        *,
        as_of: str | None = None,
        mode: str | None = None,
        assumptions: dict[str, Any] | None = None,
        method: str | None = None,
        workspace_id: str | None = None,
        name: str | None = None,
        observation_pin: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        analysis = self.equity.analyse(
            identifier, assumptions=assumptions, as_of=as_of, mode=mode,
            method=method, observation_pin=observation_pin,
        )
        workspace = analysis["workspace"]
        company = workspace["company"]
        cutoff = workspace["as_of"]
        issued = claim_contract.build_claims(analysis, cutoff=cutoff)
        verified = claim_contract.verify_claims(self.db, issued)
        integrity = integrity_report(analysis, verified)
        sources = (workspace.get("provenance") or {}).get("sources") or []
        rights = claim_contract.rights_decision(sources)
        evidence_ids = sorted({eid for claim in verified for eid in claim["evidence_ids"]})
        citations = [claim_contract.evidence_citation(self.db, eid) for eid in evidence_ids]
        market = workspace.get("market_price") or {}
        pin = None
        if market.get("status") == "available":
            selection = market.get("source_selection") or {}
            pin = claim_contract.observation_citation({
                "observation_id": selection.get("observation_id"),
                "security_id": selection.get("security_id") or (
                    (market.get("security") or {}).get("security_id")
                ),
                "mic": selection.get("mic") or market.get("mic"),
                "source_id": selection.get("source_id") or market.get("source_id"),
                "session": selection.get("session") or market.get("as_of"),
                "revision_seq": selection.get("revision_seq") or market.get("revision_seq"),
                "content_hash": selection.get("content_hash") or market.get("content_hash"),
                "redistribution": selection.get("redistribution") or market.get("redistribution"),
                "adjustment": selection.get("adjustment") or market.get("adjustment"),
            })
        models = [
            claim_contract.model_citation(claim["model"])
            for claim in verified if claim["claim_type"] == "model_output"
        ]
        memo: dict[str, Any] = {
            "schema": MEMO_SCHEMA,
            "memo_version": MEMO_VERSION,
            "memo_id": None,
            "name": name or f"{company['legal_name']} equity research memo",
            "workspace_id": workspace_id,
            "issuer": {
                "issuer_id": company["issuer_id"],
                "legal_name": company["legal_name"],
                "cik": company.get("cik"),
                "sic": company.get("sic"),
                "ticker": workspace["coverage"].get("ticker"),
                "business_model": (valuation_eligibility := analysis["valuation"]["eligibility"]).get(
                    "business_model"
                ),
                "valuation_method": valuation_eligibility.get("method"),
            },
            "cutoff": cutoff,
            "mode": workspace["mode"],
            "objective": (
                f"Establish, from stored evidence, what {company['legal_name']}'s reported "
                "financial statements imply for the value of the business under explicit "
                "analyst assumptions."
            ),
            "claims": verified,
            "sections": [],
            "integrity": integrity,
            "citations": {"evidence": citations, "market_observation": pin, "model": models},
            "rights": rights,
            "manifest": {},
            "generated_at": iso(utcnow()),
        }
        memo["manifest"] = self._manifest(memo)
        memo["sections"] = self._sections(memo, analysis)
        memo["content_hash"] = memo_hash(memo)
        memo["memo_id"] = f"RMO-{memo['content_hash'][:16]}"
        memo["manifest"]["content_hash"] = memo["content_hash"]
        memo["manifest"]["memo_id"] = memo["memo_id"]
        for claim in memo["claims"]:
            claim["research_object_id"] = memo["memo_id"]
        return memo

    def _sections(self, memo: dict[str, Any], analysis: dict[str, Any]) -> list[dict[str, Any]]:
        claims = memo["claims"]
        valuation = analysis["valuation"]
        workspace = analysis["workspace"]
        coverage = workspace["coverage"]
        verified = [claim for claim in claims if _outcome(claim) == "verified"]
        rejected = [
            claim for claim in claims
            if claim["claim_type"] in claim_contract.FACTUAL_TYPES and _outcome(claim) != "verified"
        ]
        sections: dict[str, dict[str, Any]] = {}

        def add(section_id: str, *, titles: tuple[str, str], claim_ids: Iterable[str] = (),
                items: Iterable[dict[str, Any]] = (), notes: Iterable[str] = ()) -> None:
            sections[section_id] = {
                "id": section_id,
                "title": titles[1],
                "claim_ids": sorted(set(claim_ids)),
                "items": list(items),
                "notes": list(notes),
            }

        titles = dict(SECTION_ORDER)
        add("identity", titles=("identity", titles["identity"]), items=[{
            "label": "Memo version", "value": MEMO_VERSION,
        }, {
            "label": "Memo id", "value": memo.get("memo_id") or "computed at save",
        }, {
            "label": "Content hash", "value": memo.get("content_hash") or "computed at save",
        }])
        add("issuer_security", titles=("issuer_security", titles["issuer_security"]), items=[
            {"label": key, "value": value}
            for key, value in memo["issuer"].items()
        ])
        add("cutoff", titles=("cutoff", titles["cutoff"]),
            claim_ids=[claim["claim_id"] for claim in _by_key(claims, "disclosure.information_cutoff")],
            items=[{"label": "Information cutoff", "value": memo["cutoff"]},
                   {"label": "Availability mode", "value": memo["mode"]}],
            notes=["A claim dated after this cutoff is not allowed into the memo."])
        add("objective", titles=("objective", titles["objective"]), items=[
            {"label": "Objective", "value": memo["objective"]},
        ])
        add("financial_summary", titles=("financial_summary", titles["financial_summary"]),
            claim_ids=[claim["claim_id"] for claim in _by_type(claims, "observed_fact")],
            items=[
                {"label": claim["statement"], "value": claim["value"],
                 "unit": claim["unit"], "outcome": _outcome(claim)}
                for claim in _by_type(claims, "observed_fact")
            ])
        add("historical_analysis", titles=("historical_analysis", titles["historical_analysis"]),
            claim_ids=[claim["claim_id"] for claim in _by_type(claims, "derived_financial_metric")],
            items=[
                {"label": claim["statement"], "value": claim["value"],
                 "formula": claim.get("transformation"), "outcome": _outcome(claim)}
                for claim in _by_type(claims, "derived_financial_metric")
            ])
        eligibility = valuation["eligibility"]
        add("valuation_methodology", titles=("valuation_methodology", titles["valuation_methodology"]),
            claim_ids=[claim["claim_id"] for claim in _by_type(claims, "methodology_disclosure")],
            items=[{"label": "Admissible method", "value": eligibility.get("method")},
                   {"label": "Business model", "value": eligibility.get("business_model")},
                   {"label": "Eligibility", "value": eligibility.get("status")},
                   {"label": "Rejected method", "value": eligibility.get("rejected_method")}],
            notes=list(eligibility.get("reasons") or []))
        add("model_assumptions", titles=("model_assumptions", titles["model_assumptions"]),
            claim_ids=[claim["claim_id"] for claim in _by_type(claims, "analyst_assumption")],
            items=[
                {"label": claim["statement"], "value": claim["value"],
                 "type": "analyst assumption"}
                for claim in _by_type(claims, "analyst_assumption")
            ],
            notes=["Assumptions are authored. They are not reported facts."])
        scenarios = valuation.get("scenarios") or {}
        sensitivity = valuation.get("sensitivity") or {}
        add("scenarios", titles=("scenarios", titles["scenarios"]),
            items=[{"label": key, "value": item.get("value_per_share"),
                    "delta": item.get("delta_vs_base")}
                   for key, item in (scenarios.get("scenarios") or {}).items()],
            notes=["Conditional arithmetic from one shared model definition, not a forecast."])
        add("numerical_validation", titles=("numerical_validation", titles["numerical_validation"]),
            claim_ids=[claim["claim_id"] for claim in _by_type(claims, "model_output")],
            items=[
                {"label": check.get("name"),
                 "value": check.get("status") or ("pass" if check.get("passed") else "fail")}
                for check in (valuation.get("audit") or {}).get("checks") or []
            ],
            notes=[
                f"Verdict {(valuation.get('audit') or {}).get('verdict') or 'not run'}",
                "Components are recomputed outside the compiled operator graph.",
            ])
        market = workspace.get("market_price") or {}
        add("market_comparison", titles=("market_comparison", titles["market_comparison"]),
            items=[{"label": "Status", "value": market.get("status") or "unavailable"},
                   {"label": "Observation", "value": (memo["citations"]["market_observation"] or {}).get(
                       "observation_id") or "no authorised price"}],
            notes=["A missing price is reported as unavailable, never substituted."])
        add("analyst_thesis", titles=("analyst_thesis", titles["analyst_thesis"]),
            claim_ids=[claim["claim_id"] for claim in _by_type(claims, "analyst_hypothesis")],
            items=[{"label": claim["statement"], "value": "hypothesis",
                    "outcome": _outcome(claim)}
                   for claim in _by_type(claims, "analyst_hypothesis")])
        add("risks_counterarguments", titles=("risks_counterarguments", titles["risks_counterarguments"]),
            items=[
                {"label": finding.get("code"), "value": finding.get("severity"),
                 "detail": finding.get("message") or finding.get("detail")}
                for finding in valuation.get("findings") or []
            ],
            notes=[
                "Findings are the model's own counterarguments; the memo does not summarise "
                "them into a recommendation."
            ])
        add("evidence_coverage", titles=("evidence_coverage", titles["evidence_coverage"]),
            items=[{"label": "Evidence records", "value": coverage["evidence_records"]},
                   {"label": "Mapped concepts", "value": coverage["concepts"]},
                   {"label": "Annual periods", "value": coverage["annual_periods"]},
                   {"label": "Filings", "value": coverage["filings"]},
                   {"label": "Resolved citations", "value": sum(
                       1 for item in memo["citations"]["evidence"]
                       if item.get("status") == "resolved")}],
            notes=list(coverage.get("limitations") or []))
        add("unresolved_contradictions", titles=(
            "unresolved_contradictions", titles["unresolved_contradictions"]),
            claim_ids=[claim["claim_id"] for claim in rejected],
            items=[
                {"label": claim["key"], "value": _outcome(claim),
                 "detail": "; ".join(
                     item.get("detail") or "" for item in
                     (claim.get("verification") or {}).get("diagnostics") or []
                 )}
                for claim in rejected
            ],
            notes=["A failing claim stays in the memo with its diagnostic."])
        add("source_limitations", titles=("source_limitations", titles["source_limitations"]),
            items=[{"label": "Limitation", "value": item}
                   for item in workspace.get("limitations") or []],
            notes=["Sources are enumerated in the references section with their rights class."])
        add("research_integrity", titles=("research_integrity", titles["research_integrity"]),
            items=[
                {"label": dimension, "value": payload["outcome"],
                 "detail": payload["detail"]}
                for dimension, payload in memo["integrity"]["dimensions"].items()
            ])
        add("references", titles=("references", titles["references"]),
            items=[
                {"label": item.get("evidence_id"), "value": item.get("status"),
                 "detail": f"{item.get('form_type') or '—'} {item.get('accession_number') or ''} "
                           f"{item.get('concept') or ''}".strip()}
                for item in memo["citations"]["evidence"]
            ] + [
                {"label": model.get("fingerprint") or model.get("model"),
                 "value": model.get("status"),
                 "detail": f"{model.get('model')} v{model.get('version')}"}
                for model in memo["citations"]["model"]
            ])
        add("reproduction_manifest", titles=(
            "reproduction_manifest", titles["reproduction_manifest"]),
            items=[
                {"label": "Evidence dependencies", "value": len(memo["manifest"]["evidence_dependencies"])},
                {"label": "Model fingerprints", "value": len(memo["manifest"]["model_fingerprints"])},
                {"label": "Compiler version", "value": COMPILER_VERSION},
                {"label": "Memo content hash", "value": memo.get("content_hash") or "computed at save"},
            ])
        add("export_rights", titles=("export_rights", titles["export_rights"]),
            items=[{"label": "Redistributable", "value": memo["rights"]["redistributable"]}]
            + [
                {"label": "Blocked source", "value": item["source_id"],
                 "detail": item["redistribution"]}
                for item in memo["rights"]["blocked_sources"]
            ],
            notes=[memo["rights"]["note"]])
        return [sections[section_id] for section_id, _ in SECTION_ORDER]

    def _manifest(self, memo: dict[str, Any]) -> dict[str, Any]:
        return {
            "schema": MANIFEST_SCHEMA,
            "memo_id": memo.get("memo_id"),
            "memo_version": memo["memo_version"],
            "content_hash": memo.get("content_hash"),
            "issuer_id": memo["issuer"]["issuer_id"],
            "cutoff": memo["cutoff"],
            "mode": memo["mode"],
            "compiler_version": COMPILER_VERSION,
            "evidence_dependencies": sorted({
                eid for claim in memo["claims"] for eid in claim["evidence_ids"]
            }),
            "observation_pins": [memo["citations"]["market_observation"]]
            if memo["citations"]["market_observation"] else [],
            "model_fingerprints": [
                item.get("fingerprint") for item in memo["citations"]["model"]
                if item.get("fingerprint")
            ],
            "assumptions": sorted({
                assumption for claim in memo["claims"]
                for assumption in claim["assumption_ids"]
            }),
            "integrity": {
                dimension: payload["outcome"]
                for dimension, payload in memo["integrity"]["dimensions"].items()
            },
            "rights": memo["rights"],
            "generate_command": (
                f"atlas research memo {memo['issuer']['issuer_id']} --as-of {memo['cutoff']}"
            ),
        }

    # ------------------------------------------------------------------ persistence
    def save(self, memo: dict[str, Any], *, version: str = "1.0.0",
             name: str | None = None,
             expected_content_hash: str | None = None) -> dict[str, Any]:
        """Persist a reviewed memo, refusing to store a different one silently.

        The caller reviews a preview and must save exactly that memo. If evidence, an
        assumption, an observation revision or a rights declaration changed between the
        preview and the save, the rebuild has a different content hash and the save is
        refused with both hashes, so the analyst reviews the new memo instead of learning
        later that a different research object was stored than the one they approved.
        """
        if expected_content_hash and memo.get("content_hash") != expected_content_hash:
            raise ValidationError(
                "the reviewed memo no longer matches the current evidence; review the "
                "rebuilt memo before saving it",
                code="memo_content_changed",
                expected_content_hash=expected_content_hash,
                actual_content_hash=memo.get("content_hash"),
            )
        document = {
            "schema_version": "atlas.research_object.v1",
            "kind": "memo",
            "name": name or memo["name"],
            "version": version,
            "status": "draft" if memo["integrity"]["failures"] else "validated",
            "description": (
                f"Evidence-grounded research memo for {memo['issuer']['legal_name']} at "
                f"cutoff {memo['cutoff']}"
            ),
            "as_of": memo["cutoff"],
            "mode": memo["mode"],
            "evidence_ids": memo["manifest"]["evidence_dependencies"],
            "source_ids": ["sec-edgar"],
            "object_ids": [],
            "spec": {
                "issuer_id": memo["issuer"]["issuer_id"],
                "cutoff": memo["cutoff"],
                "memo_version": memo["memo_version"],
                "content_hash": memo["content_hash"],
                "workspace_id": memo.get("workspace_id"),
                "sections": memo["sections"],
                "claims": memo["claims"],
                "integrity": memo["integrity"],
                "manifest": memo["manifest"],
                "rights": memo["rights"],
                "citations": memo["citations"],
                "objective": memo["objective"],
                "issuer": memo["issuer"],
            },
            "assumptions": memo["manifest"]["assumptions"],
            "limitations": [
                item["value"] for item in next(
                    section for section in memo["sections"] if section["id"] == "source_limitations"
                )["items"]
            ],
        }
        stored = self.store.create(document)
        return {
            "object_id": stored["object_id"],
            "version": stored["version"],
            "content_hash": stored["content_hash"],
            "status": stored["status"],
            "memo": memo,
        }

    def get(self, object_id: str) -> dict[str, Any]:
        stored = self.store.get(object_id)
        if stored["kind"] != "memo":
            raise ValidationError("research object is not a memo", kind=stored["kind"])
        spec = stored["document"]["spec"]
        return {
            "object_id": stored["object_id"],
            "name": stored["name"],
            "version": stored["version"],
            "status": stored["status"],
            "content_hash": stored["content_hash"],
            "created_at": stored["created_at"],
            "memo": {
                "schema": MEMO_SCHEMA,
                "memo_version": spec.get("memo_version"),
                "memo_id": stored["object_id"],
                "name": stored["name"],
                "workspace_id": spec.get("workspace_id"),
                "issuer": spec.get("issuer"),
                "cutoff": spec.get("cutoff"),
                "mode": stored["document"]["mode"],
                "objective": spec.get("objective"),
                "claims": spec.get("claims") or [],
                "sections": spec.get("sections") or [],
                "integrity": spec.get("integrity") or {},
                "citations": spec.get("citations") or {},
                "rights": spec.get("rights") or {},
                "manifest": spec.get("manifest") or {},
                "content_hash": spec.get("content_hash"),
            },
        }

    def list(self, *, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.store.list(kind="memo", limit=limit)
        return [
            {
                "object_id": row["object_id"],
                "name": row["name"],
                "version": row["version"],
                "status": row["status"],
                "content_hash": row["content_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        left_claims = {claim["claim_id"]: claim for claim in left["memo"]["claims"]}
        right_claims = {claim["claim_id"]: claim for claim in right["memo"]["claims"]}
        added = [right_claims[key] for key in sorted(set(right_claims) - set(left_claims))]
        removed = [left_claims[key] for key in sorted(set(left_claims) - set(right_claims))]
        changed = []
        for key in sorted(set(left_claims) & set(right_claims)):
            before, after = left_claims[key], right_claims[key]
            differences = {
                field: [before.get(field), after.get(field)]
                for field in ("value", "statement", "evidence_ids")
                if before.get(field) != after.get(field)
            }
            if differences:
                changed.append({"claim_id": key, "key": before["key"],
                                "type": before["claim_type"], "changes": differences})
        return {
            "schema": "atlas.research_memo.comparison.v1",
            "left": {"object_id": left["object_id"], "version": left["version"],
                     "content_hash": left["content_hash"]},
            "right": {"object_id": right["object_id"], "version": right["version"],
                      "content_hash": right["content_hash"]},
            "equal": left["content_hash"] == right["content_hash"],
            "claims": {
                "added": [{"claim_id": claim["claim_id"], "key": claim["key"]} for claim in added],
                "removed": [{"claim_id": claim["claim_id"], "key": claim["key"]} for claim in removed],
                "changed": changed,
            },
            "assumptions": {
                "left": left["memo"]["manifest"].get("assumptions", []),
                "right": right["memo"]["manifest"].get("assumptions", []),
            },
            "model_fingerprints": {
                "left": left["memo"]["manifest"].get("model_fingerprints", []),
                "right": right["memo"]["manifest"].get("model_fingerprints", []),
            },
            "integrity": {
                "left": left["memo"]["integrity"].get("outcome_counts", {}),
                "right": right["memo"]["integrity"].get("outcome_counts", {}),
            },
        }

    # --------------------------------------------------------------------- export
    def export(self, object_id: str, *, format: str = "markdown") -> dict[str, Any]:
        if format not in EXPORT_FORMATS:
            raise ValidationError("unsupported export format", format=format,
                                  supported=list(EXPORT_FORMATS))
        stored = self.get(object_id)
        memo = stored["memo"]
        if not memo["rights"].get("redistributable", False):
            raise ValidationError(
                "export refused: a cited source does not permit redistribution",
                blocked_sources=memo["rights"].get("blocked_sources") or [],
            )
        if format == "markdown":
            content, media_type, suffix = render_markdown(memo), "text/markdown", "md"
        elif format == "html":
            content, media_type, suffix = render_html(memo), "text/html", "html"
        else:
            content, media_type, suffix = render_json(memo), "application/json", "json"
        digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
        manifest = {
            "schema": MANIFEST_SCHEMA,
            "exported_at": iso(utcnow()),
            "format": format,
            "content_hash": digest,
            "object_id": stored["object_id"],
            "memo_version": stored["version"],
            "memo_content_hash": stored["content_hash"],
            "issuer_id": memo["issuer"]["issuer_id"],
            "cutoff": memo["cutoff"],
            "evidence_dependencies": memo["manifest"]["evidence_dependencies"],
            "observation_pins": memo["manifest"]["observation_pins"],
            "model_fingerprints": memo["manifest"]["model_fingerprints"],
            "integrity": memo["manifest"].get("integrity") or {
                dimension: payload.get("outcome")
                for dimension, payload in (memo.get("integrity") or {}).get("dimensions", {}).items()
            },
            "rights_decision": {
                "redistributable": True,
                "blocked_sources": [],
            },
            "compiler_version": COMPILER_VERSION,
        }
        identifier = (memo["issuer"].get("ticker") or memo["issuer"]["issuer_id"]).replace("/", "_")
        return {
            "object_id": stored["object_id"],
            "format": format,
            "media_type": media_type,
            "filename": f"{identifier}-research-memo-v{stored['version']}.{suffix}",
            "content": content,
            "manifest": manifest,
        }

    def check_changes(self, object_id: str) -> dict[str, Any]:
        from .changes import check

        stored = self.get(object_id)
        return check(self.db, stored["memo"], object_id=stored["object_id"])

    def revise(self, object_id: str, *, version: str | None = None,
               as_of: str | None = None) -> dict[str, Any]:
        stored = self.get(object_id)
        memo = stored["memo"]
        current = tuple(int(part) for part in stored["version"].split(".")[:3])
        target = version or f"{current[0]}.{current[1]}.{current[2] + 1}"
        rebuilt = self.build(
            memo["issuer"]["issuer_id"],
            as_of=as_of or stored["created_at"],
            mode=memo["mode"],
            workspace_id=memo.get("workspace_id"),
            name=stored["name"],
        )
        return self.save(rebuilt, version=target, name=stored["name"])


# ----------------------------------------------------------------------- renderers
def _claim_line(claim: dict[str, Any]) -> str:
    outcome = _outcome(claim)
    return f"{claim['statement']} _[{claim['claim_type']}, {outcome}]_"


def render_markdown(memo: dict[str, Any]) -> str:
    issuer = memo["issuer"]
    lines = [
        f"# {issuer['legal_name']} — Research memo",
        "",
        f"**Memo version:** {memo['memo_version']}  ",
        f"**Issuer:** {issuer['legal_name']} (CIK {issuer.get('cik') or '—'}, "
        f"ticker {issuer.get('ticker') or 'not mapped'})  ",
        f"**Information cutoff:** {memo['cutoff']} ({memo['mode']})  ",
        f"**Memo content hash:** `{memo['content_hash']}`  ",
        "**Status:** every factual and numeric claim below resolves to stored evidence or a "
        "reproducible transformation. No language model generated a factual claim.",
        "",
        f"## Objective",
        "",
        memo["objective"],
        "",
    ]
    for section in memo["sections"]:
        if section["id"] in {"identity", "issuer_security", "objective"}:
            continue
        lines.extend([f"## {section['title']}", ""])
        claim_map = {claim["claim_id"]: claim for claim in memo["claims"]}
        for claim_id in section["claim_ids"]:
            claim = claim_map.get(claim_id)
            if claim:
                lines.append(f"- {_claim_line(claim)}")
        if section["items"]:
            lines.extend(["", "| Item | Value | Detail |", "| --- | --- | --- |"])
            for item in section["items"]:
                label = str(item.get("label"))
                value = item.get("value")
                detail = item.get("detail") or ""
                lines.append(
                    f"| {label.replace('|', '\\|')} | "
                    f"{'—' if value is None else str(value).replace('|', '\\|')} | "
                    f"{str(detail).replace('|', '\\|')} |"
                )
        for note in section["notes"]:
            lines.append(f"\n> {note}")
        lines.append("")
    lines.extend(["## Claim register", "", "| Claim | Type | Outcome | Evidence |",
                  "| --- | --- | --- | --- |"])
    for claim in memo["claims"]:
        lines.append(
            f"| {claim['claim_id']} | {claim['claim_type']} | {_outcome(claim)} | "
            f"{len(claim['evidence_ids'])} record(s) |"
        )
    lines.extend(["", "## Export and rights", "", memo["rights"]["note"], ""])
    return "\n".join(lines).rstrip("\n") + "\n"


def render_html(memo: dict[str, Any]) -> str:
    """Self-contained, sanitized HTML. Every dynamic value is escaped."""
    issuer = memo["issuer"]

    def esc(value: Any) -> str:
        return html.escape("" if value is None else str(value), quote=True)

    parts = [
        "<!DOCTYPE html>",
        "<html lang=\"en\"><head><meta charset=\"utf-8\">",
        f"<title>{esc(issuer['legal_name'])} — research memo</title>",
        "<style>body{font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif;max-width:60rem;"
        "margin:2rem auto;padding:0 1rem;color:#111}h1,h2{line-height:1.2}"
        "table{border-collapse:collapse;width:100%;margin:.5rem 0 1rem}"
        "th,td{border:1px solid #d0d0d0;padding:.35rem .5rem;text-align:left;font-size:13px}"
        "th{background:#f6f6f6}code{background:#f2f2f2;padding:0 .2rem}</style>",
        "</head><body>",
        f"<h1>{esc(issuer['legal_name'])} — Research memo</h1>",
        "<table><tbody>",
    ]
    for label, value in (
        ("Memo version", memo["memo_version"]),
        ("Issuer", issuer["legal_name"]),
        ("CIK", issuer.get("cik")),
        ("Ticker", issuer.get("ticker")),
        ("Information cutoff", f"{memo['cutoff']} ({memo['mode']})"),
        ("Memo content hash", memo["content_hash"]),
    ):
        parts.append(f"<tr><th>{esc(label)}</th><td>{esc(value)}</td></tr>")
    parts.append("</tbody></table>")
    parts.append(f"<h2>Objective</h2><p>{esc(memo['objective'])}</p>")
    claim_map = {claim["claim_id"]: claim for claim in memo["claims"]}
    for section in memo["sections"]:
        if section["id"] in {"identity", "issuer_security", "objective"}:
            continue
        parts.append(f"<h2>{esc(section['title'])}</h2>")
        claim_ids = [cid for cid in section["claim_ids"] if cid in claim_map]
        if claim_ids:
            parts.append("<ul>")
            for claim_id in claim_ids:
                claim = claim_map[claim_id]
                parts.append(
                    f"<li>{esc(claim['statement'])} "
                    f"<em>[{esc(claim['claim_type'])}, {esc(_outcome(claim))}]</em></li>"
                )
            parts.append("</ul>")
        if section["items"]:
            parts.append("<table><thead><tr><th>Item</th><th>Value</th><th>Detail</th></tr>"
                         "</thead><tbody>")
            for item in section["items"]:
                parts.append(
                    f"<tr><td>{esc(item.get('label'))}</td><td>{esc(item.get('value'))}</td>"
                    f"<td>{esc(item.get('detail'))}</td></tr>"
                )
            parts.append("</tbody></table>")
        for note in section["notes"]:
            parts.append(f"<p><em>{esc(note)}</em></p>")
    parts.append("<h2>Claim register</h2><table><thead><tr><th>Claim</th><th>Type</th>"
                 "<th>Outcome</th><th>Evidence</th></tr></thead><tbody>")
    for claim in memo["claims"]:
        parts.append(
            f"<tr><td>{esc(claim['claim_id'])}</td><td>{esc(claim['claim_type'])}</td>"
            f"<td>{esc(_outcome(claim))}</td><td>{len(claim['evidence_ids'])}</td></tr>"
        )
    parts.append("</tbody></table>")
    parts.append(f"<p>{esc(memo['rights']['note'])}</p>")
    parts.append("</body></html>")
    return "\n".join(parts) + "\n"


def render_json(memo: dict[str, Any]) -> str:
    return json.dumps(
        {
            "schema": MANIFEST_SCHEMA,
            "memo": memo,
            "note": (
                "Machine-readable research manifest. Claims, citations and integrity results "
                "are identical to the Markdown and HTML views."
            ),
        },
        indent=2,
        sort_keys=True,
        ensure_ascii=False,
    ) + "\n"


def verify_export(export: dict[str, Any]) -> dict[str, Any]:
    """Detect a tampered export: the manifest must describe the bytes it shipped with."""
    digest = hashlib.sha256(export["content"].encode("utf-8")).hexdigest()
    manifest = export.get("manifest") or {}
    return {
        "content_hash_matches": digest == manifest.get("content_hash"),
        "memo_hash_present": bool(manifest.get("memo_content_hash")),
        "schema": manifest.get("schema"),
        "expected": manifest.get("content_hash"),
        "actual": digest,
    }
