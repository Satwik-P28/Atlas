"""Research certificates for source-bound financial results (v10.0.0).

A research certificate is a standalone record of one computed financial value and the exact
evidence it came from. It answers a narrower question than a citation does: not "which document
mentions this number" but "which document, which table, which row, which column, which printed
text, and which typed computation produced this value".

What a certificate proves
-------------------------
On its own, a certificate proves *internal consistency*: the payload hashes to its stated
fingerprint, the recorded inputs recompute to the recorded result, and the identities agree with
each other. That is worth having, because it makes an accidental edit visible.

What a certificate does not prove
---------------------------------
A fingerprint is not an authority. An attacker who changes an input cell and the claimed result
together can recompute every fingerprint the certificate owns and produce a self-consistent
artifact. Nothing inside the certificate can detect that, because the certificate is the thing
being checked. Authenticity requires evidence the certificate does not control: the original
document bytes, and a pinned record of what those bytes are supposed to contain.

``atlas.research.certificate_verify`` implements that separation and reports one of
``ARITHMETIC_VERIFIED``, ``SOURCE_VERIFIED``, ``SOURCE_UNVERIFIED`` or ``INVALID``.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Iterable, Sequence

CERTIFICATE_SCHEMA = "atlas.research.certificate.v1"
CERTIFICATE_VERSION = "10.0.0"

#: Operators a certificate may claim. The verifier recomputes each one independently.
OPERATORS = ("lookup", "percentage_change", "ratio", "margin", "total")

#: Fields every certificate must carry. Missing fields are a structural failure, never a default.
REQUIRED_TOP_LEVEL = (
    "schema", "certificate_version", "subject", "evidence", "computation", "result",
    "independent", "limitations",
)
REQUIRED_SUBJECT = (
    "issuer_id", "issuer_name", "accession", "form_type", "document_id", "document_sha256",
    "primary_document_url", "cutoff",
)
REQUIRED_BINDING = (
    "concept", "document_id", "accession", "table_id", "table_sha256", "unit_id", "unit_sha256",
    "row", "column", "row_label", "column_label", "raw", "value", "scale", "currency", "period",
    "availability_time", "statement_family", "entity_scope",
)
REQUIRED_COMPUTATION = (
    "operator", "formula", "answer_type", "metric", "period", "compiler_version",
    "operator_versions", "fec_fingerprint", "plan",
)
REQUIRED_RESULT = ("value", "unit", "currency", "answer_type")


class CertificateError(ValueError):
    """Raised when a certificate cannot be built or is structurally unusable."""


def canonical(payload: Any) -> str:
    """Canonical JSON: sorted keys, no insignificant whitespace, one representation per value."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)


def payload_fingerprint(payload: dict[str, Any]) -> str:
    """The certificate's own fingerprint: sha256 over the canonical payload.

    Deliberately excludes the ``fingerprint`` key so the digest can be recomputed from the body.
    """
    body = {key: value for key, value in payload.items() if key != "fingerprint"}
    return hashlib.sha256(canonical(body).encode("utf-8")).hexdigest()


def _require(condition: bool, message: str, **context: Any) -> None:
    if not condition:
        raise CertificateError(message if not context else f"{message}: {canonical(context)}")


@dataclass(frozen=True, slots=True)
class Certificate:
    """An immutable certificate payload together with its fingerprint."""

    payload: dict[str, Any]
    fingerprint: str

    @property
    def subject(self) -> dict[str, Any]:
        return self.payload["subject"]

    @property
    def evidence(self) -> list[dict[str, Any]]:
        return list(self.payload["evidence"])

    @property
    def result(self) -> dict[str, Any]:
        return self.payload["result"]

    def as_dict(self) -> dict[str, Any]:
        return {**self.payload, "fingerprint": self.fingerprint}

    def to_json(self, *, indent: int = 2) -> str:
        return json.dumps(self.as_dict(), indent=indent, sort_keys=True) + "\n"


def _binding_payload(binding: Any, db: Any) -> dict[str, Any]:
    """Carry a resolver binding into the certificate, with the hashes it does not already hold."""
    document = db.query_one(
        "SELECT sha256, form_type, primary_document_url, availability_time, availability_precision,"
        " rights FROM knowledge_document WHERE document_id = ?", (binding.document_id,))
    _require(document is not None, "binding references an unknown document",
             document_id=binding.document_id)
    table = db.query_one("SELECT sha256, unit_id FROM knowledge_table WHERE table_id = ?",
                         (binding.table_id,))
    _require(table is not None, "binding references an unknown table", table_id=binding.table_id)
    unit = db.query_one("SELECT sha256 FROM knowledge_unit WHERE unit_id = ?", (binding.unit_id,))
    _require(unit is not None, "binding references an unknown text unit", unit_id=binding.unit_id)
    return {
        "concept": binding.concept,
        "issuer_id": binding.issuer_id,
        "document_id": binding.document_id,
        "accession": binding.accession,
        "document_sha256": document["sha256"],
        "table_id": binding.table_id,
        "table_sha256": table["sha256"],
        "unit_id": binding.unit_id,
        "unit_sha256": unit["sha256"],
        "row": int(binding.row),
        "column": int(binding.column),
        "row_label": binding.row_label,
        "column_label": binding.column_label,
        "raw": binding.raw,
        "value": str(binding.value),
        "scale": binding.scale,
        "currency": binding.currency,
        "period": binding.period,
        "statement_family": binding.statement_family,
        "statement_title": binding.statement_title,
        "entity_scope": binding.entity_scope,
        "availability_time": binding.availability_time or document["availability_time"],
        "availability_precision": (binding.availability_precision
                                  or document["availability_precision"]),
        "rights": binding.rights or document["rights"],
    }


def build_certificate(
    db: Any,
    packet: dict[str, Any],
    bindings: Sequence[Any],
    *,
    emitted_at: str | None = None,
) -> Certificate:
    """Build a certificate from an answered packet and the resolver bindings behind it.

    The packet must have ``outcome == 'answered'``. A refusal is not a certificate: an abstention
    has no result to certify, and issuing one would convert "I do not know" into an artifact that
    looks like knowledge.
    """
    if packet.get("outcome") != "answered":
        raise CertificateError(
            "only an answered packet can be certified "
            f"(outcome={packet.get('outcome')!r}, reason={packet.get('reason')!r})")
    if not bindings:
        raise CertificateError("a certificate needs at least one source binding")
    operator = str(packet.get("operator") or "")
    if operator not in OPERATORS:
        raise CertificateError(
            f"packet does not name a supported operator: {operator!r}; expected one of "
            f"{', '.join(OPERATORS)}")
    evidence = [_binding_payload(binding, db) for binding in bindings]
    issuer = db.query_one("SELECT cik, legal_name FROM issuer WHERE issuer_id = ?",
                          (evidence[0]["issuer_id"],))
    _require(issuer is not None, "certificate issuer is unknown", issuer_id=evidence[0]["issuer_id"])
    document = db.query_one(
        "SELECT accession, form_type, primary_document_url FROM knowledge_document"
        " WHERE document_id = ?", (evidence[0]["document_id"],))
    _require(document is not None, "certificate document is unknown")
    payload: dict[str, Any] = {
        "schema": CERTIFICATE_SCHEMA,
        "certificate_version": CERTIFICATE_VERSION,
        "emitted_at": emitted_at,
        "subject": {
            "issuer_id": evidence[0]["issuer_id"],
            "issuer_name": issuer["legal_name"],
            "cik": issuer["cik"],
            "accession": document["accession"],
            "form_type": document["form_type"],
            "document_id": evidence[0]["document_id"],
            "document_sha256": evidence[0]["document_sha256"],
            "primary_document_url": document["primary_document_url"],
            "cutoff": packet.get("cutoff"),
        },
        "evidence": evidence,
        "computation": {
            "operator": operator,
            "formula": packet.get("formula"),
            "answer_type": packet.get("answer_type"),
            "metric": packet.get("metric"),
            "period": packet.get("period"),
            "compiler_version": (packet.get("fec") or {}).get("compiler_version"),
            "operator_versions": (packet.get("fec") or {}).get("operator_versions"),
            "fec_fingerprint": (packet.get("fec") or {}).get("model_fingerprint"),
            "run_id": (packet.get("fec") or {}).get("run_id"),
            "plan": (packet.get("fec") or {}).get("plan"),
        },
        "result": {
            "value": str(packet.get("value")),
            "answer_type": packet.get("answer_type"),
            "unit": packet.get("unit"),
            "currency": packet.get("currency"),
            "period": packet.get("period"),
        },
        "independent": {
            "method": (packet.get("verification") or {}).get("method"),
            "verifier_version": (packet.get("verification") or {}).get("verifier_version"),
            "rounding_policy": (packet.get("verification") or {}).get("rounding_policy"),
        },
        "engine": {
            "engine_version": packet.get("engine_version"),
            "operator_version": packet.get("operator_version"),
            "reproducibility_fingerprint": packet.get("reproducibility_fingerprint"),
        },
        "limitations": list(packet.get("limitations") or []) + [
            "The certificate fingerprint proves internal consistency only; it is not a signature "
            "and confers no authority on the values it covers.",
            "Source authenticity requires independent bytes; verify with "
            "atlas.research.certificate_verify and trusted evidence.",
        ],
    }
    for key in REQUIRED_BINDING:
        _require(all(key in item for item in evidence), "binding is missing a required field",
                 field=key)
    return Certificate(payload=payload, fingerprint=payload_fingerprint(payload))


def load_certificate(payload: dict[str, Any]) -> Certificate:
    """Load a certificate and check only that its claimed fingerprint matches its body.

    Structural checks are the verifier's job; this function stays deliberately small so that a
    malformed certificate reaches the verifier and is reported as ``INVALID`` with a reason.
    """
    if not isinstance(payload, dict):
        raise CertificateError("a certificate must be a JSON object")
    claimed = payload.get("fingerprint")
    if not isinstance(claimed, str):
        raise CertificateError("a certificate must carry its fingerprint")
    return Certificate(payload={key: value for key, value in payload.items() if key != "fingerprint"},
                       fingerprint=claimed)


def load_certificate_file(path: Any) -> Certificate:
    from pathlib import Path

    return load_certificate(json.loads(Path(path).read_text(encoding="utf-8")))


def structural_problems(certificate: Certificate) -> list[str]:
    """Return every structural problem with the payload. Empty list means well-formed."""
    problems: list[str] = []
    payload = certificate.payload
    for key in REQUIRED_TOP_LEVEL:
        if key not in payload:
            problems.append(f"missing_top_level:{key}")
    if problems:
        return problems
    if payload.get("schema") != CERTIFICATE_SCHEMA:
        problems.append(f"schema_mismatch:{payload.get('schema')}")
    for key in REQUIRED_SUBJECT:
        if key not in payload["subject"]:
            problems.append(f"missing_subject:{key}")
    for key in REQUIRED_COMPUTATION:
        if key not in payload["computation"]:
            problems.append(f"missing_computation:{key}")
    for key in REQUIRED_RESULT:
        if key not in payload["result"]:
            problems.append(f"missing_result:{key}")
    if payload["computation"].get("operator") not in OPERATORS:
        problems.append(f"unsupported_operator:{payload['computation'].get('operator')}")
    evidence = payload["evidence"]
    if not isinstance(evidence, list) or not evidence:
        problems.append("empty_evidence")
    else:
        for index, item in enumerate(evidence):
            if not isinstance(item, dict):
                problems.append(f"evidence_{index}_not_object")
                continue
            for key in REQUIRED_BINDING:
                if key not in item:
                    problems.append(f"missing_binding_{index}:{key}")
    expected = payload["computation"].get("operator")
    counts = {"lookup": 1, "percentage_change": 2, "ratio": 2, "margin": 2}
    if expected in counts and len(evidence) != counts[expected]:
        problems.append(f"evidence_count_mismatch:{expected}:{len(evidence)}")
    if expected == "total" and len(evidence) < 1:
        problems.append("evidence_count_mismatch:total:0")
    return problems


def raw_values(certificate: Certificate) -> list[str]:
    """The printed source text each computation consumed, in plan order."""
    return [str(item.get("raw")) for item in certificate.payload.get("evidence", [])]


def declared_concepts(certificate: Certificate) -> Iterable[str]:
    for item in certificate.payload.get("evidence", []):
        yield str(item.get("concept"))


__all__ = [
    "CERTIFICATE_SCHEMA", "CERTIFICATE_VERSION", "Certificate", "CertificateError", "OPERATORS",
    "build_certificate", "canonical", "declared_concepts", "load_certificate",
    "load_certificate_file", "payload_fingerprint", "raw_values", "structural_problems",
]
