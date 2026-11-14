"""Atlas research certificates (``atlas.research_certificate.v1``).

A certificate packages one source-backed financial answer so an independent verifier can check
identity, availability, types, arithmetic and fingerprints without calling the production
answer-resolution pipeline.

Canonical JSON serialization (UTF-8, sorted keys, no insignificant whitespace beyond a trailing
newline on disk) is the only serialization that participates in the certificate fingerprint.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from fractions import Fraction
from typing import Any, Mapping

from . import financial_verification as independent_math

SCHEMA = "atlas.research_certificate.v1"
ISSUER_IDENTITY = "atlas.research_certificate.issuer.v1"
CERTIFICATE_VERSION = "1.0.0"


def _canonical_bytes(payload: Mapping[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      default=str).encode("utf-8")


def fingerprint(payload: Mapping[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


@dataclass(slots=True)
class ResearchCertificate:
    research_question: str
    normalized_requirement: dict[str, Any]
    issuer_identity: dict[str, Any]
    reporting_entity_scope: str
    information_cutoff: str
    vintage_selection_policy: str
    selected_sources: list[dict[str, Any]]
    financial_concepts: list[str]
    typed_computation: dict[str, Any]
    input_bindings: list[dict[str, Any]]
    result: dict[str, Any]
    independent_verification: dict[str, Any]
    assumptions: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    schema: str = SCHEMA
    certificate_version: str = CERTIFICATE_VERSION
    issued_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if not payload["issued_at"]:
            payload["issued_at"] = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        # Fingerprint excludes itself.
        body = {key: value for key, value in payload.items() if key != "certificate_fingerprint"}
        payload["certificate_fingerprint"] = fingerprint(body)
        return payload

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    @classmethod
    def from_dict(cls, payload: Mapping[str, Any]) -> "ResearchCertificate":
        known = {field.name for field in cls.__dataclass_fields__.values()}  # type: ignore[attr-defined]
        data = {key: value for key, value in payload.items()
                if key in known and key != "certificate_fingerprint"}
        return cls(**data)  # type: ignore[arg-type]


def build_certificate(
    *,
    research_question: str,
    answer: Mapping[str, Any],
    bindings: list[Any],
    cutoff: str,
    normalized_requirement: Mapping[str, Any] | None = None,
    vintage_selection_policy: str = (
        "filing whose own period is the requested year; disagreements refused"),
    assumptions: list[str] | None = None,
    limitations: list[str] | None = None,
) -> dict[str, Any]:
    """Build a certificate from a bound answer packet and its ResolvedFinancialInput list."""
    if answer.get("outcome") != "answered":
        raise ValueError("refused answers cannot be certified")
    input_bindings: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    concepts: list[str] = []
    for binding in bindings:
        if hasattr(binding, "__slots__"):
            data = {name: getattr(binding, name) for name in binding.__slots__}
        elif isinstance(binding, Mapping):
            data = dict(binding)
        else:
            data = dict(binding.__dict__)
        concepts.append(str(data.get("concept") or ""))
        input_bindings.append({
            "issuer_id": data["issuer_id"],
            "concept": data.get("concept"),
            "document_id": data["document_id"],
            "accession": data["accession"],
            "table_id": data["table_id"],
            "unit_id": data["unit_id"],
            "cell_id": data["cell_id"],
            "row": data["row"],
            "column": data["column"],
            "row_label": data["row_label"],
            "column_label": data["column_label"],
            "period": data["period"],
            "currency": data["currency"],
            "scale": data["scale"],
            "value": data["value"],
            "raw": data["raw"],
            "source_table_sha256": data["source_table_sha256"],
            "statement_title": data.get("statement_title"),
            "statement_family": data.get("statement_family"),
            "entity_scope": data.get("entity_scope"),
            "availability_time": data.get("availability_time"),
            "rights": data.get("rights"),
            "resolver_version": data.get("resolver_version"),
            "rationale": data.get("rationale"),
        })
        sources.append({
            "document_id": data["document_id"],
            "accession": data["accession"],
            "table_id": data["table_id"],
            "unit_id": data["unit_id"],
            "cell_id": data["cell_id"],
            "source_table_sha256": data["source_table_sha256"],
            "availability_time": data.get("availability_time"),
            "rights": data.get("rights"),
        })
    first = input_bindings[0]
    requirement = dict(normalized_requirement or {
        "operator": answer.get("formula"),
        "metric": answer.get("metric"),
        "period": answer.get("period"),
        "answer_type": answer.get("answer_type"),
    })
    cert = ResearchCertificate(
        research_question=research_question,
        normalized_requirement=requirement,
        issuer_identity={
            "schema": ISSUER_IDENTITY,
            "issuer_id": first["issuer_id"],
            "reporting_entity_scope": first.get("entity_scope") or "unknown",
        },
        reporting_entity_scope=str(first.get("entity_scope") or "unknown"),
        information_cutoff=cutoff,
        vintage_selection_policy=vintage_selection_policy,
        selected_sources=sources,
        financial_concepts=[concept for concept in concepts if concept],
        typed_computation={
            "formula": answer.get("formula"),
            "answer_type": answer.get("answer_type"),
            "operator_version": answer.get("operator_version"),
            "engine_version": answer.get("engine_version"),
            "fec": answer.get("fec"),
            "execution_fingerprint": (answer.get("fec") or {}).get("model_fingerprint"),
        },
        input_bindings=input_bindings,
        result={
            "value": answer.get("value"),
            "value_exact": answer.get("value_exact"),
            "display_places": answer.get("display_places"),
            "economic_amount": answer.get("economic_amount"),
            "unit": answer.get("unit"),
            "currency": answer.get("currency"),
            "period": answer.get("period"),
        },
        independent_verification=dict(answer.get("verification") or {}),
        assumptions=list(assumptions or [
            "Selected cells are the consolidated primary statement for the requested concept.",
            "Printed scale metadata on the statement applies to every bound cell.",
        ]),
        limitations=list(limitations or list(answer.get("limitations") or [])),
    )
    return cert.to_dict()


def _parse_exact(value: Any) -> Fraction:
    return Fraction(str(value))


def verify_certificate_payload(payload: Mapping[str, Any], *,
                               trusted_sources: Mapping[str, Mapping[str, Any]] | None = None
                               ) -> dict[str, Any]:
    """Independently verify a certificate.

    ``trusted_sources`` maps accession → {sha256, availability_time, body_present}.
    When source bytes are unavailable, authenticity of a bare hash is reported as limited.
    """
    problems: list[str] = []
    if payload.get("schema") != SCHEMA:
        problems.append("schema_mismatch")
    expected = payload.get("certificate_fingerprint")
    body = {key: value for key, value in payload.items() if key != "certificate_fingerprint"}
    actual = fingerprint(body)
    if not expected or expected != actual:
        problems.append("certificate_fingerprint_mismatch")

    bindings = list(payload.get("input_bindings") or [])
    if not bindings:
        problems.append("missing_bindings")

    cutoff = str(payload.get("information_cutoff") or "")
    for binding in bindings:
        available = binding.get("availability_time")
        if not available or (cutoff and available > cutoff):
            problems.append("future_evidence")
        if binding.get("scale") is None:
            problems.append("scale_unknown")
        if binding.get("currency") is None and (payload.get("result") or {}).get("currency"):
            problems.append("currency_missing")
        accession = binding.get("accession")
        if trusted_sources is not None:
            trusted = trusted_sources.get(str(accession))
            if trusted is None:
                problems.append("source_unavailable")
            else:
                if trusted.get("availability_time") and cutoff and trusted["availability_time"] > cutoff:
                    problems.append("trusted_source_after_cutoff")
                stored_hash = binding.get("source_table_sha256")
                if trusted.get("sha256") and stored_hash and trusted["sha256"] != stored_hash:
                    problems.append("source_hash_mismatch")
                if not trusted.get("body_present", True):
                    problems.append("source_bytes_unavailable")
        elif not binding.get("source_table_sha256"):
            problems.append("source_hash_missing")

    # Typed arithmetic over raw printed values — independent of FEC.
    answer_type = (payload.get("result") or {}).get("unit", {})
    formula = (payload.get("typed_computation") or {}).get("formula") or ""
    raw_values = [str(binding.get("raw") or "") for binding in bindings]
    try:
        if "percentage" in formula or "percent" in str(
                (payload.get("typed_computation") or {}).get("answer_type") or ""):
            if "margin" in str((payload.get("typed_computation") or {}).get("answer_type") or ""):
                computed = independent_math.margin(raw_values[0], raw_values[1])
            else:
                computed = independent_math.percentage_change(raw_values[0], raw_values[1])
        elif (payload.get("typed_computation") or {}).get("answer_type") == "ratio":
            computed = independent_math.ratio(raw_values[0], raw_values[1])
        elif (payload.get("typed_computation") or {}).get("answer_type") == "sum":
            computed = independent_math.total(raw_values)
        else:
            computed = independent_math.lookup(raw_values[0])
    except Exception as exc:  # noqa: BLE001
        problems.append(f"arithmetic_refused:{type(exc).__name__}")
        computed = None

    result = payload.get("result") or {}
    if computed is not None:
        places = int(result.get("display_places") or 2)
        displayed = independent_math.round_half_up(computed, places=places)
        claimed = result.get("value")
        if claimed is None or Decimal(str(claimed)) != displayed:
            problems.append("result_mismatch")
        exact = result.get("value_exact")
        if exact is not None and _parse_exact(exact) != computed:
            problems.append("exact_result_mismatch")

    # Financial type / operator version presence.
    computation = payload.get("typed_computation") or {}
    if not computation.get("operator_version"):
        problems.append("operator_version_missing")
    if not computation.get("execution_fingerprint"):
        problems.append("execution_fingerprint_missing")

    status = "valid" if not problems else "invalid"
    return {
        "schema": "atlas.research_certificate.verify.v1",
        "status": status,
        "problems": sorted(set(problems)),
        "certificate_fingerprint": expected,
        "recomputed_fingerprint": actual,
        "limitations": [
            "A hash without independently trusted source bytes does not establish authenticity.",
            "This verifier recomputes arithmetic from printed raw values with Fraction math and "
            "does not invoke the production FinancialAnswerEngine or FEC runtime.",
        ],
    }


__all__ = [
    "SCHEMA", "CERTIFICATE_VERSION", "ResearchCertificate", "build_certificate",
    "verify_certificate_payload", "fingerprint",
]
