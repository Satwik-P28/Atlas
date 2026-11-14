"""Atlas research certificates (``atlas.research_certificate.v1``).

A certificate packages one source-backed financial answer so an independent verifier can check
identity, availability, types, arithmetic and fingerprints without calling the production
answer-resolution pipeline.

Canonical JSON serialization (UTF-8, sorted keys, no insignificant whitespace beyond a trailing
newline on disk) is the only serialization that participates in the certificate fingerprint.

Trust model
-----------
The certificate records what the answer pipeline selected. Its fingerprint proves the payload is
internally consistent; it does **not** make the payload authoritative. Source authenticity is
established only by ``atlas.research.certificate_verify`` against evidence the certificate does not
control (a pinned source manifest plus the original document bytes). ``build_certificate`` therefore
records the document digest and URL it was built against, so a verifier can authenticate them later.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

SCHEMA = "atlas.research_certificate.v1"
ISSUER_IDENTITY = "atlas.research_certificate.issuer.v1"
CERTIFICATE_VERSION = "1.1.0"


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


def _binding_data(binding: Any) -> dict[str, Any]:
    if hasattr(binding, "__slots__"):
        return {name: getattr(binding, name) for name in binding.__slots__}
    if isinstance(binding, Mapping):
        return dict(binding)
    return dict(binding.__dict__)


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
    source_documents: Mapping[str, Mapping[str, Any]] | None = None,
    issuer_identity: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Build a certificate from a bound answer packet and its ResolvedFinancialInput list.

    ``source_documents`` maps ``document_id`` to the identity of the document the answer was
    computed from: ``sha256`` (of the exact bytes that were ingested), ``primary_document_url`` and
    ``form_type``. Supplying it is what allows a later strict verification to authenticate the
    source; omitting it yields a certificate that can only ever reach ``ARITHMETIC_VERIFIED``.
    """
    if answer.get("outcome") != "answered":
        raise ValueError("refused answers cannot be certified")
    documents = dict(source_documents or {})
    issuer_record = dict(issuer_identity or {})
    input_bindings: list[dict[str, Any]] = []
    sources: list[dict[str, Any]] = []
    concepts: list[str] = []
    for binding in bindings:
        data = _binding_data(binding)
        document = dict(documents.get(str(data["document_id"])) or {})
        concepts.append(str(data.get("concept") or ""))
        input_bindings.append({
            "issuer_id": data["issuer_id"],
            "concept": data.get("concept"),
            "document_id": data["document_id"],
            "accession": data["accession"],
            "document_sha256": document.get("sha256"),
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
            "document_sha256": document.get("sha256"),
            "primary_document_url": document.get("primary_document_url"),
            "form_type": document.get("form_type"),
            "table_id": data["table_id"],
            "unit_id": data["unit_id"],
            "cell_id": data["cell_id"],
            "source_table_sha256": data["source_table_sha256"],
            "availability_time": data.get("availability_time"),
            "rights": data.get("rights"),
        })
    first = input_bindings[0]
    requirement = dict(normalized_requirement or {
        # The operator is recorded on the answer packet. ``formula`` is prose for humans and is
        # not a dispatch key; falling back to it made every certificate look like a lookup.
        "operator": answer.get("operator"),
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
            # The CIK is the authoritative issuer identifier; without it a verifier cannot pin
            # identity and must not claim source verification.
            "cik": issuer_record.get("cik"),
            "issuer_name": issuer_record.get("issuer_name"),
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
            "operator": answer.get("operator"),
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
    payload = cert.to_dict()
    payload["limitations"] = list(payload["limitations"]) + [
        "The certificate fingerprint proves internal consistency only. It is not a signature, it "
        "confers no authority on the values it covers, and it cannot detect an attacker who "
        "recomputes it over altered inputs.",
        "Source authenticity and semantic intent require independent evidence: verify with "
        "atlas.research.certificate_verify against a pinned source manifest and the original "
        "document bytes.",
    ]
    # Re-fingerprint after appending limitations so the digest covers the final payload.
    body = {key: value for key, value in payload.items() if key != "certificate_fingerprint"}
    payload["certificate_fingerprint"] = fingerprint(body)
    return payload


def verify_certificate_payload(
    payload: Mapping[str, Any],
    *,
    evidence: Any = None,
    trusted_sources: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Compatibility entry point; the implementation lives in ``certificate_verify``.

    ``trusted_sources`` is the legacy mapping of accession → claimed hashes. It is treated as
    insufficient evidence, because a hash supplied by the caller proves nothing about the bytes.
    """
    from .certificate_verify import verify_payload

    return verify_payload(payload, evidence=evidence, trusted_sources=trusted_sources)


__all__ = [
    "SCHEMA", "CERTIFICATE_VERSION", "ResearchCertificate", "build_certificate",
    "verify_certificate_payload", "fingerprint",
]
