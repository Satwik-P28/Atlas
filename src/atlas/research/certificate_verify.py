"""Independent verification of research certificates (v10.0.0).

The verifier is the part of the system that is allowed to say "this number is trustworthy, and
here is why". It therefore shares no arithmetic with the Financial-Economic Compiler: it parses
the printed source text with its own regular expression and computes with ``fractions.Fraction``.
Agreement between two implementations that share no code is evidence. Agreement of an
implementation with itself is not.

Verification outcomes
---------------------
``ARITHMETIC_VERIFIED``
    The recorded inputs recompute to the recorded result under the verifier's own arithmetic, and
    the payload is internally consistent. Nothing about the source is claimed.
``SOURCE_VERIFIED``
    Additionally, the original document bytes were authenticated against a pinned fingerprint, the
    source table was located inside those bytes, the printed cell text at the recorded coordinates
    was reproduced, every semantic field matched a pinned source manifest, and the arithmetic was
    recomputed from the *snapshot's* text rather than the certificate's.
``SOURCE_UNVERIFIED``
    Arithmetic holds but authoritative source evidence was unavailable. Explicitly not an error:
    a certificate can be arithmetically valid while source authentication is impossible offline.
``INVALID``
    A required check failed. ``reasons`` names each failure.

Trust model
-----------
A certificate cannot authenticate itself. ``TrustedEvidence`` must be constructed from material the
certificate does not control: the source manifest is a pinned, version-controlled record of what
the filings contain, and the snapshot bytes come from the original SEC document. A manifest alone
is deliberately *not* enough for ``SOURCE_VERIFIED``; it is reported as ``manifest_only`` because a
manifest cannot prove that the document it describes is the document that was actually served.
"""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping

from .certificate import (
    Certificate,
    canonical,
    payload_fingerprint,
    raw_values,
    structural_problems,
)

VERIFIER_SCHEMA = "atlas.research.certificate_verification.v1"
VERIFIER_VERSION = "10.0.0"

MANIFEST_SCHEMA = "atlas.focus.source_manifest.v1"


class VerificationLevel(str, Enum):
    ARITHMETIC_VERIFIED = "ARITHMETIC_VERIFIED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"
    INVALID = "INVALID"


class VerificationError(ValueError):
    """Raised when trusted evidence cannot be interpreted."""


# --------------------------------------------------------------------------- independent arithmetic
#: Deliberately not shared with ``atlas.fec`` or ``atlas.research.financial_verification``.
_RAW = re.compile(
    r"^(?P<open>\()?\s*(?P<sign>[-+])?\s*\$?\s*(?P<body>\d[\d,]*(?:\.\d+)?)\s*%?\s*\)?$")
_NON_NUMERIC = {"", "-", "--", "—", "–", "n/a", "na", "nm", "*"}


def parse_printed(text: Any) -> Fraction:
    """Parse one printed filing value. Parentheses are negative; a dash is never zero."""
    cleaned = "" if text is None else str(text).strip()
    if cleaned.lower() in _NON_NUMERIC:
        raise VerificationError(f"not a numeric value: {text!r}")
    match = _RAW.match(cleaned)
    if not match:
        raise VerificationError(f"unparseable printed value: {text!r}")
    if bool(match.group("open")) != cleaned.endswith(")"):
        raise VerificationError(f"unbalanced parentheses: {text!r}")
    magnitude = Fraction(match.group("body").replace(",", ""))
    negative = bool(match.group("open")) or match.group("sign") == "-"
    return -magnitude if negative else magnitude


def round_half_up(value: Fraction, places: int = 2) -> Decimal:
    """Quantize with half-up rounding, implemented without ``decimal`` context state."""
    scaled = value * (10 ** places)
    numerator, denominator = scaled.numerator, scaled.denominator
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return Decimal(sign * quotient).scaleb(-places)


def compute(operator: str, raws: list[str]) -> Fraction:
    """Evaluate one supported financial operator from printed text alone."""
    if operator not in {"lookup", "percentage_change", "ratio", "margin", "total"}:
        raise VerificationError(f"unsupported operator: {operator}")
    values = [parse_printed(raw) for raw in raws]
    if operator == "lookup":
        return values[0]
    if operator == "total":
        return sum(values, Fraction(0))
    numerator, denominator = values[0], values[1]
    if denominator == 0:
        raise VerificationError("zero denominator")
    if operator == "ratio":
        return numerator / denominator
    if operator == "margin":
        return numerator / denominator * 100
    return (numerator - denominator) / denominator * 100


# --------------------------------------------------------------------------- trusted evidence
@dataclass(slots=True)
class TrustedEvidence:
    """Evidence the verifier accepts, constructed outside the certificate.

    ``manifest`` pins what each filing is supposed to contain. ``snapshots`` (accession -> bytes)
    supplies the original document. ``live_sec`` fetches the original document by the URL recorded
    in the manifest, which is the only route that does not depend on this repository at all.
    """

    manifest: dict[str, Any]
    snapshots: Mapping[str, bytes] = field(default_factory=dict)
    live_sec: bool = False
    user_agent: str | None = None
    notes: list[str] = field(default_factory=list)

    @classmethod
    def from_manifest_file(cls, path: Any, *, snapshots: Mapping[str, bytes] | None = None,
                           live_sec: bool = False, user_agent: str | None = None) -> "TrustedEvidence":
        manifest = json.loads(Path(path).read_text(encoding="utf-8"))
        if manifest.get("schema") != MANIFEST_SCHEMA:
            raise VerificationError(f"unexpected manifest schema: {manifest.get('schema')!r}")
        return cls(manifest=manifest, snapshots=snapshots or {}, live_sec=live_sec,
                   user_agent=user_agent)

    def document_entry(self, accession: str) -> dict[str, Any] | None:
        return (self.manifest.get("documents") or {}).get(accession)

    def source_bytes(self, accession: str, entry: dict[str, Any]) -> tuple[bytes | None, str]:
        """Return the original document bytes and the route that supplied them."""
        if accession in self.snapshots:
            return self.snapshots[accession], "snapshot"
        if not self.live_sec:
            return None, "unavailable"
        url = entry.get("primary_document_url")
        if not url:
            return None, "unavailable"
        return _fetch(url, self.user_agent), "sec_live"


def _fetch(url: str, user_agent: str | None) -> bytes | None:
    from urllib.request import Request, urlopen

    headers = {"User-Agent": user_agent or "AtlasQuant/0.1 verification@example.com",
               "Accept-Encoding": "identity"}
    try:
        with urlopen(Request(url, headers=headers), timeout=45) as response:  # noqa: S310
            return response.read()
    except Exception:  # noqa: BLE001 - an unavailable network is reported, not raised
        return None


# --------------------------------------------------------------------------- report
@dataclass(slots=True)
class VerificationReport:
    level: VerificationLevel
    certificate_fingerprint: str | None
    checks: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    recomputed_value: str | None = None
    method: str | None = None
    source_route: str | None = None
    limitations: list[str] = field(default_factory=list)

    def add(self, name: str, passed: bool, detail: Any = None) -> bool:
        self.checks.append({"check": name, "passed": bool(passed),
                            **({"detail": detail} if detail is not None else {})})
        if not passed:
            self.reasons.append(name if detail is None else f"{name}:{detail}")
        return bool(passed)

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": VERIFIER_SCHEMA,
            "verifier_version": VERIFIER_VERSION,
            "level": self.level.value,
            "certificate_fingerprint": self.certificate_fingerprint,
            "method": self.method,
            "source_route": self.source_route,
            "recomputed_value": self.recomputed_value,
            "checks": self.checks,
            "reasons": self.reasons,
            "limitations": self.limitations,
        }


def _normalise(text: Any) -> str:
    return " ".join(str(text or "").split())


def _table_from_snapshot(payload: bytes,
                         table_sha256: str) -> tuple[list[list[str]] | None, str | None]:
    """Locate the source table inside the original document and return its rows.

    The table is identified by the hash of the text block it was extracted from, not by its
    position, so a document whose pagination shifted cannot silently match the wrong table.
    """
    from .knowledge import extract_units

    units = extract_units(payload.decode("utf-8", errors="replace"))
    for unit in units:
        if unit.get("kind") != "table":
            continue
        digest = hashlib.sha256(str(unit.get("body") or "").encode("utf-8")).hexdigest()
        if digest == table_sha256:
            return list(unit.get("rows") or []), None
    return None, "table_not_found_in_source_bytes"


# --------------------------------------------------------------------------- verification
def verify(certificate: Certificate, evidence: TrustedEvidence | None = None) -> VerificationReport:
    """Verify a certificate. Trusted evidence is optional and strictly additive."""
    report = VerificationReport(level=VerificationLevel.INVALID,
                               certificate_fingerprint=certificate.fingerprint)

    problems = structural_problems(certificate)
    if not report.add("structure", not problems, ", ".join(problems) if problems else None):
        return report

    recomputed_fingerprint = payload_fingerprint(certificate.payload)
    if not report.add("certificate_fingerprint", recomputed_fingerprint == certificate.fingerprint,
                      None if recomputed_fingerprint == certificate.fingerprint
                      else f"recomputed {recomputed_fingerprint}"):
        return report

    # Independent arithmetic over the inputs *carried by the certificate*.
    operator = certificate.payload["computation"]["operator"]
    try:
        recomputed = compute(operator, raw_values(certificate))
    except VerificationError as exc:
        report.add("independent_arithmetic", False, str(exc))
        return report
    claimed = certificate.result.get("value")
    report.recomputed_value = str(round_half_up(recomputed))
    try:
        agrees = Decimal(str(claimed)) == round_half_up(recomputed)
    except Exception:  # noqa: BLE001 - a non-numeric claimed value is a failure, not a crash
        agrees = False
    if not report.add("independent_arithmetic", agrees,
                      None if agrees else f"claimed {claimed} recomputed {report.recomputed_value}"):
        return report
    report.method = "fraction_reimplementation_v1"

    if evidence is None:
        report.level = VerificationLevel.ARITHMETIC_VERIFIED
        report.limitations.append(
            "No trusted source evidence was supplied. The computation matches the inputs the "
            "certificate carries; whether those inputs match the filing was not established.")
        return report

    # --- pinned manifest: semantics the certificate does not control -----------------------
    subject = certificate.subject
    entry = evidence.document_entry(subject["accession"])
    if not report.add("manifest_document", entry is not None,
                      None if entry is not None else f"accession {subject['accession']} not pinned"):
        return report
    assert entry is not None
    if not report.add("manifest_document_sha256",
                      _normalise(entry.get("document_sha256")) == _normalise(subject["document_sha256"]),
                      "document bytes differ from the pinned manifest"):
        return report
    for name in ("issuer_id", "issuer_name", "cik", "form_type"):
        if not report.add(f"manifest_issuer_{name}",
                          _normalise(entry.get(name)) == _normalise(subject.get(name)),
                          f"pinned {entry.get(name)!r} claimed {subject.get(name)!r}"):
            return report

    # Cells are keyed by content-addressed table hash, row and column rather than by generated
    # ids: document and table identifiers are newly minted on every ingestion, so keying on them
    # would make a pinned manifest unusable after a rebuild.
    manifest_cells = {(cell["table_sha256"], int(cell["row"]), int(cell["column"])): cell
                      for cell in entry.get("cells", [])}
    semantic_fields = ("raw", "row_label", "column_label", "period", "scale", "currency",
                       "concept", "value", "unit_sha256", "statement_family",
                       "availability_time")
    for index, item in enumerate(certificate.evidence):
        key = (item["table_sha256"], int(item["row"]), int(item["column"]))
        pinned = manifest_cells.get(key)
        if not report.add(f"manifest_cell_{index}", pinned is not None,
                          None if pinned is not None else f"cell {key} is not pinned"):
            return report
        assert pinned is not None
        for name in semantic_fields:
            if not report.add(f"manifest_{name}_{index}",
                              _normalise(pinned.get(name)) == _normalise(item.get(name)),
                              f"pinned {pinned.get(name)!r} claimed {item.get(name)!r}"):
                return report

    # --- original bytes: authenticity the certificate cannot manufacture --------------------
    payload, route = evidence.source_bytes(subject["accession"], entry)
    report.source_route = route
    if payload is None:
        report.level = VerificationLevel.SOURCE_UNVERIFIED
        report.reasons.append("no_source_bytes")
        report.limitations.append(
            "The pinned manifest matched, but the original document bytes were unavailable, so "
            "authenticity was not established. A manifest cannot prove which bytes were served.")
        return report

    actual = hashlib.sha256(payload).hexdigest()
    if not report.add("source_bytes_sha256", actual == subject["document_sha256"],
                      None if actual == subject["document_sha256"] else f"bytes hash to {actual}"):
        return report

    snapshot_raws: list[str] = []
    for index, item in enumerate(certificate.evidence):
        rows, problem = _table_from_snapshot(payload, item["table_sha256"])
        if not report.add(f"source_table_{index}", rows is not None, problem):
            return report
        assert rows is not None
        row, column = int(item["row"]), int(item["column"])
        if not report.add(f"source_coordinates_{index}",
                          0 <= row < len(rows) and 0 <= column < len(rows[row]),
                          f"row {row} column {column} outside the source table"):
            return report
        printed = _normalise(rows[row][column])
        if not report.add(f"source_cell_text_{index}", printed == _normalise(item["raw"]),
                          f"source prints {printed!r}, certificate claims {item['raw']!r}"):
            return report
        snapshot_raws.append(printed)

    # --- arithmetic from the snapshot text, not from the certificate's claims --------------
    try:
        from_source = compute(operator, snapshot_raws)
    except VerificationError as exc:
        report.add("source_arithmetic", False, str(exc))
        return report
    source_value = round_half_up(from_source)
    if not report.add("source_arithmetic", source_value == round_half_up(recomputed),
                      f"source {source_value} vs certificate {report.recomputed_value}"):
        return report

    report.level = VerificationLevel.SOURCE_VERIFIED
    report.limitations.append(
        "Source verification authenticates the printed cell, its coordinates and the arithmetic. "
        "It does not prove that the resolved concept is the economically intended one; that "
        "mapping is pinned by the manifest and remains a semantic judgement.")
    return report


def build_source_manifest(db: Any, bindings: list[Any], *,
                          generated_at: str | None = None) -> dict[str, Any]:
    """Pin the cells a certificate will cover, from the store and the resolver, not the claim.

    This is the operator's attestation: it is written once, reviewed and committed. It is derived
    from the ingested documents and the resolver bindings, never from a certificate, so that the
    verifier has something the certificate does not control to compare against.
    """
    documents: dict[str, Any] = {}
    for binding in bindings:
        document = db.query_one(
            "SELECT accession, sha256, form_type, primary_document_url, availability_time, issuer_id"
            " FROM knowledge_document WHERE document_id = ?", (binding.document_id,))
        if document is None:
            raise VerificationError(f"unknown document for binding {binding.document_id}")
        issuer = db.query_one("SELECT legal_name, cik FROM issuer WHERE issuer_id = ?",
                              (document["issuer_id"],))
        table = db.query_one("SELECT sha256 FROM knowledge_table WHERE table_id = ?",
                             (binding.table_id,))
        unit = db.query_one("SELECT sha256 FROM knowledge_unit WHERE unit_id = ?",
                           (binding.unit_id,))
        if table is None or unit is None:
            raise VerificationError(f"binding {binding.table_id} is not backed by a stored table")
        entry = documents.setdefault(document["accession"], {
            "accession": document["accession"],
            "document_sha256": document["sha256"],
            "form_type": document["form_type"],
            "primary_document_url": document["primary_document_url"],
            "issuer_id": document["issuer_id"],
            "issuer_name": issuer["legal_name"] if issuer else None,
            "cik": issuer["cik"] if issuer else None,
            "tables": [],
            "cells": [],
        })
        if table["sha256"] not in entry["tables"]:
            entry["tables"].append(table["sha256"])
        key = (table["sha256"], int(binding.row), int(binding.column))
        if any((cell["table_sha256"], cell["row"], cell["column"]) == key
               for cell in entry["cells"]):
            continue
        entry["cells"].append({
            "table_sha256": table["sha256"],
            "unit_sha256": unit["sha256"],
            "row": int(binding.row),
            "column": int(binding.column),
            "raw": binding.raw,
            "value": str(binding.value),
            "row_label": binding.row_label,
            "column_label": binding.column_label,
            "period": binding.period,
            "scale": binding.scale,
            "currency": binding.currency,
            "concept": binding.concept,
            "statement_family": binding.statement_family,
            "availability_time": binding.availability_time or document["availability_time"],
        })
    return {
        "schema": MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "documents": documents,
        "limitations": [
            "This manifest pins what the ingested documents contain. It is not a signature and it "
            "does not prove which bytes SEC served; authenticity comes from the source bytes.",
            "Cells are keyed by content hash, row and column because document and table "
            "identifiers are regenerated on every ingestion.",
        ],
    }


def verify_payload(payload: dict[str, Any],
                   evidence: TrustedEvidence | None = None) -> dict[str, Any]:
    """Load and verify a certificate payload, returning the machine-readable report."""
    from .certificate import load_certificate

    try:
        certificate = load_certificate(payload)
    except Exception as exc:  # noqa: BLE001 - a malformed artifact is INVALID, not a crash
        return VerificationReport(
            level=VerificationLevel.INVALID, certificate_fingerprint=None,
            reasons=[f"unloadable:{exc}"],
        ).as_dict()
    return verify(certificate, evidence).as_dict()


__all__ = [
    "MANIFEST_SCHEMA", "VERIFIER_SCHEMA", "VERIFIER_VERSION", "TrustedEvidence", "VerificationError",
    "VerificationLevel", "VerificationReport", "build_source_manifest", "compute",
    "parse_printed", "round_half_up", "verify", "verify_payload",
]
