"""Strict, independent verification of research certificates.

The verifier is the part of the system allowed to say "this number is trustworthy, and here is
why". It shares no arithmetic with the Financial-Economic Compiler: it parses printed source text
with its own regular expression and computes with ``fractions.Fraction``. Agreement between two
implementations that share no code is evidence; agreement of an implementation with itself is not.

Verification levels
-------------------
``ARITHMETIC_VERIFIED``
    The payload is well formed, its fingerprint matches its body, the recorded inputs recompute to
    the recorded result under this module's own arithmetic, the typed display precision matches, and
    the recorded economic amount is consistent with the recorded scale. Nothing about the source
    is claimed.
``SOURCE_VERIFIED``
    Additionally: the accession is pinned in a source manifest, the manifest's document digest
    equals the certificate's, the original document bytes hash to that digest, the source table is
    located inside those bytes by content hash, the printed text at the recorded row and column is
    reproduced, every semantic field matches the pin, and the arithmetic recomputed from the
    *snapshot's* text equals the result.
``SOURCE_UNVERIFIED``
    Arithmetic holds but authoritative source evidence was unavailable (no manifest, no bytes, or
    a legacy caller-supplied hash map). Explicitly not an error.
``INVALID``
    A required check failed; ``reasons`` names the failures.

What source verification does and does not establish
----------------------------------------------------
It establishes that the answer's cell exists, at those coordinates, in the document whose bytes
were authenticated, and that the arithmetic over that printed text is correct.

It does **not** establish: that the document was publicly available at ``information_cutoff``
(availability is a modelled timestamp, not a witnessed publication event); that the resolved
concept is the economically intended one; that an unsigned manifest was authored honestly; or that
an unsigned certificate came from Atlas at all.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from fractions import Fraction
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, Request, build_opener

from .certificate import SCHEMA, fingerprint

VERIFIER_SCHEMA = "atlas.research_certificate.verify.v1"
VERIFIER_VERSION = "1.1.0"
MANIFEST_SCHEMA = "atlas.focus.source_manifest.v1"

OPERATORS = ("lookup", "percentage_change", "ratio", "margin", "total")
_ANSWER_TYPE_OPERATOR = {
    "reported_value": "lookup",
    "percentage_change": "percentage_change",
    "margin_percent": "margin",
    "ratio": "ratio",
    "sum": "total",
}

#: Operators whose result has no currency dimension, so no scaled economic amount exists.
_DIMENSIONLESS = {"ratio", "margin", "percentage_change"}
_UNIT_KIND = {"percentage_change": "percent", "margin": "percent", "ratio": "ratio"}
#: A column header can corroborate a period only if it prints one.
_YEAR = re.compile(r"(?:19|20)\d{2}")

#: Fields the schema makes mandatory. ``currency`` and ``economic_amount`` may be null, but the
#: key must be present so a verifier can tell "declared dimensionless" from "quietly deleted".
MANDATORY_RESULT_FIELDS = ("value", "value_exact", "display_places", "economic_amount",
                           "period", "currency", "unit")


class VerificationLevel(str, Enum):
    ARITHMETIC_VERIFIED = "ARITHMETIC_VERIFIED"
    SOURCE_VERIFIED = "SOURCE_VERIFIED"
    SOURCE_UNVERIFIED = "SOURCE_UNVERIFIED"
    INVALID = "INVALID"


class VerificationError(ValueError):
    """Raised when trusted evidence cannot be interpreted."""


# ------------------------------------------------------------------ independent arithmetic
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
    """Quantize with half-up rounding, without touching ``decimal`` context state."""
    scaled = value * (10 ** places)
    numerator, denominator = scaled.numerator, scaled.denominator
    sign = -1 if numerator < 0 else 1
    quotient, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return Decimal(sign * quotient).scaleb(-places)


def compute(operator: str, raws: list[str]) -> Fraction:
    if operator not in OPERATORS:
        raise VerificationError(f"unsupported operator: {operator}")
    values = [parse_printed(raw) for raw in raws]
    if not values:
        raise VerificationError("no inputs")
    if operator in {"lookup", "total"}:
        return values[0] if operator == "lookup" else sum(values, Fraction(0))
    if len(values) < 2:
        raise VerificationError(f"{operator} needs two inputs")
    numerator, denominator = values[0], values[1]
    if denominator == 0:
        raise VerificationError("zero denominator")
    if operator == "ratio":
        return numerator / denominator
    if operator == "margin":
        return numerator / denominator * 100
    return (numerator - denominator) / denominator * 100


# ------------------------------------------------------------------ trusted evidence
#: Only SEC document endpoints may be fetched. Anything else is refused rather than followed.
_LIVE_HOSTS = {"www.sec.gov"}
_LIVE_PATH_PREFIX = "/Archives/edgar/data/"
_LIVE_MAX_BYTES = 45 * 1024 * 1024


def fetch_source_bytes(url: str, user_agent: str | None = None) -> bytes | None:
    """Fetch an SEC document, refusing anything outside the approved endpoint shape."""
    parsed = urlparse(str(url or ""))
    if parsed.scheme != "https":
        return None
    if parsed.hostname not in _LIVE_HOSTS:
        return None
    if not parsed.path.startswith(_LIVE_PATH_PREFIX):
        return None
    # Restrict the exact URL shape, including encoded paths and credentials.
    if (parsed.query or parsed.fragment or parsed.username or parsed.password or
            parsed.port not in (None, 443) or "%" in parsed.path or
            any(piece in (".", "..") for piece in parsed.path.split("/"))):
        return None
    if not user_agent:
        return None

    class _NoRedirect(HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None

    try:
        opener = build_opener(_NoRedirect())
        with opener.open(Request(url, headers={"User-Agent": user_agent,
                                              "Accept-Encoding": "identity"}),  # noqa: S310
                         timeout=45) as response:
            payload = response.read(_LIVE_MAX_BYTES + 1)
    except Exception:  # noqa: BLE001 - unavailable network is reported, not raised
        return None
    if len(payload) > _LIVE_MAX_BYTES:
        return None
    return payload


@dataclass(slots=True)
class TrustedEvidence:
    """Evidence the verifier accepts, constructed outside the certificate."""

    manifest: dict[str, Any]
    snapshots: Mapping[str, bytes] = field(default_factory=dict)
    live_sec: bool = False
    user_agent: str | None = None

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

    def source_bytes(self, accession: str, entry: Mapping[str, Any]) -> tuple[bytes | None, str]:
        if accession in self.snapshots:
            return self.snapshots[accession], "snapshot"
        if not self.live_sec:
            return None, "unavailable"
        payload = fetch_source_bytes(str(entry.get("primary_document_url") or ""), self.user_agent)
        return payload, "sec_live" if payload is not None else "unavailable"


def build_source_manifest(db: Any, bindings: list[Any], *,
                          generated_at: str | None = None) -> dict[str, Any]:
    """Pin the cells a certificate will cover, from the store and the resolver.

    Derived from ingested documents and resolver bindings, never from a certificate, so the
    verifier has something the certificate does not control. Cells are keyed by content-addressed
    table hash, row and column because document and table identifiers are regenerated per ingestion.
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
        if table is None:
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
            "This manifest pins what the ingested documents contain. It is unsigned and is not a "
            "signature; it does not prove which bytes the SEC served.",
            "Cells are keyed by content hash, row and column because document and table identifiers "
            "are regenerated on every ingestion.",
        ],
    }


# ------------------------------------------------------------------ report
@dataclass(slots=True)
class VerificationReport:
    level: VerificationLevel
    certificate_fingerprint: str | None
    checks: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    recomputed_value: str | None = None
    method: str | None = None
    source_route: str | None = None
    problems: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    semantic_status: dict[str, Any] | None = None

    def add(self, name: str, passed: bool, detail: Any = None) -> bool:
        self.checks.append({"check": name, "passed": bool(passed),
                            **({"detail": detail} if detail is not None else {})})
        if not passed:
            self.reasons.append(name if detail is None else f"{name}:{detail}")
        return bool(passed)

    @property
    def status(self) -> str:
        return {VerificationLevel.SOURCE_VERIFIED: "valid",
                VerificationLevel.ARITHMETIC_VERIFIED: "arithmetic_only",
                VerificationLevel.SOURCE_UNVERIFIED: "unverified",
                VerificationLevel.INVALID: "invalid"}[self.level]

    def as_dict(self) -> dict[str, Any]:
        return {
            "schema": VERIFIER_SCHEMA,
            "verifier_version": VERIFIER_VERSION,
            "level": self.level.value,
            "status": self.status,
            "certificate_fingerprint": self.certificate_fingerprint,
            "method": self.method,
            "source_route": self.source_route,
            "recomputed_value": self.recomputed_value,
            "checks": self.checks,
            "reasons": self.reasons,
            "problems": sorted(set(self.reasons)) or [],
            "limitations": self.limitations,
            "semantic_status": self.semantic_status,
        }


# ------------------------------------------------------------------ verification
def _normalise(text: Any) -> str:
    return " ".join(str(text or "").split())


def _period_in_label(label: Any) -> str | None:
    """Return the quarter/year a column header prints, or None if it prints no period."""
    match = _YEAR.search(str(label or ""))
    return match.group(0) if match else None


def period_assignment(bindings: list[Mapping[str, Any]]) -> dict[str, Any]:
    """Say whether the pinned column header actually corroborates the bound period.

    A column header that prints a different period from the one the binding claims means the
    table's header geometry does not support the period assignment, even when the value itself is
    authentic. That is reported as ``unresolved`` rather than certified: the certificate may still
    be source-verified for the cell, its coordinates and the arithmetic.
    """
    details: list[dict[str, Any]] = []
    for index, binding in enumerate(bindings):
        header = _period_in_label(binding.get("column_label"))
        period = str(binding.get("period") or "")
        if header is None:
            state = "not_determined"
        elif header == period:
            state = "header_confirmed"
        else:
            state = "conflict"
        details.append({"binding": index, "period": period,
                        "column_label": binding.get("column_label"), "state": state})
    if any(entry["state"] == "conflict" for entry in details):
        status = "unresolved"
    elif all(entry["state"] == "header_confirmed" for entry in details):
        status = "header_confirmed"
    else:
        status = "not_determined"
    return {"period_assignment": status, "details": details}


def _instant(value: Any) -> datetime | None:
    """Parse offset-aware ISO timestamps to UTC before comparison."""
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None or parsed.utcoffset() is None:
            return None
        return parsed.astimezone(timezone.utc)
    except (TypeError, ValueError, OverflowError):
        return None


def resolve_operator(payload: Mapping[str, Any]) -> str | None:
    """The operator is a fact the certificate states; never infer it from prose."""
    requirement = payload.get("normalized_requirement")
    if not isinstance(requirement, Mapping):
        requirement = {}
    candidate = str(requirement.get("operator") or "")
    if candidate in OPERATORS:
        return candidate
    computation = payload.get("typed_computation")
    if not isinstance(computation, Mapping):
        computation = {}
    candidate = str(computation.get("operator") or "")
    if candidate in OPERATORS:
        return candidate
    answer_type = str(computation.get("answer_type")
                      or (payload.get("result") or {}).get("answer_type") or "")
    return _ANSWER_TYPE_OPERATOR.get(answer_type)


def _table_from_snapshot(payload: bytes,
                        table_sha256: str) -> tuple[list[list[str]] | None, str | None]:
    """Locate the source table inside the original document by content hash, not position."""
    from .knowledge import extract_units

    for unit in extract_units(payload.decode("utf-8", errors="replace")):
        if unit.get("kind") != "table":
            continue
        digest = hashlib.sha256(str(unit.get("body") or "").encode("utf-8")).hexdigest()
        if digest == table_sha256:
            return list(unit.get("rows") or []), None
    return None, "table_not_found_in_source_bytes"


def verify_payload(payload: Mapping[str, Any], *, evidence: TrustedEvidence | None = None,
                   trusted_sources: Mapping[str, Mapping[str, Any]] | None = None
                   ) -> dict[str, Any]:
    """Verify a certificate payload and return a machine-readable report."""
    if not isinstance(payload, Mapping):
        report = VerificationReport(level=VerificationLevel.INVALID, certificate_fingerprint=None)
        report.add("structure", False, "certificate is not an object")
        return report.as_dict()
    report = VerificationReport(
        level=VerificationLevel.INVALID,
        certificate_fingerprint=str(payload.get("certificate_fingerprint") or "") or None,
    )
    if not report.add("schema", payload.get("schema") == SCHEMA,
                      f"expected {SCHEMA}, found {payload.get('schema')!r}"):
        return report.as_dict()
    body = {key: value for key, value in payload.items() if key != "certificate_fingerprint"}
    actual = fingerprint(body)
    if not report.add("certificate_fingerprint", actual == payload.get("certificate_fingerprint"),
                      None if actual == payload.get("certificate_fingerprint")
                      else f"recomputed {actual}"):
        return report.as_dict()

    bindings = list(payload.get("input_bindings") or [])
    if not report.add("bindings", bool(bindings), "no input bindings"):
        return report.as_dict()
    if not report.add("binding_objects", all(isinstance(b, Mapping) for b in bindings),
                      "all input bindings must be objects"):
        return report.as_dict()
    operator = resolve_operator(payload)
    if not report.add("operator", operator in OPERATORS,
                      f"cannot resolve operator from {payload.get('normalized_requirement')!r}"):
        return report.as_dict()
    assert operator is not None
    expected_inputs = {"lookup": 1, "percentage_change": 2, "ratio": 2, "margin": 2}
    if operator in expected_inputs and not report.add(
            "binding_count", len(bindings) == expected_inputs[operator],
            f"{operator} needs {expected_inputs[operator]} inputs, certificate has {len(bindings)}"):
        return report.as_dict()

    # The displayed answer is a signed claim too. A certificate may only carry the fields the
    # schema makes mandatory; deleting one is a schema violation, not a reason to skip its check.
    result = payload.get("result")
    if not isinstance(result, Mapping):
        report.add("result_object", False, "result is not an object")
        return report.as_dict()
    missing = [name for name in MANDATORY_RESULT_FIELDS if name not in result]
    if not report.add("result_fields_present", not missing, missing):
        return report.as_dict()

    # Compare actual instants, not strings: +00:00 and Z sort differently.
    cutoff = payload.get("information_cutoff")
    cutoff_instant = _instant(cutoff)
    if cutoff_instant is None:
        report.add("cutoff_valid", False, "an explicit offset-aware ISO cutoff is required")
        return report.as_dict()
    for index, binding in enumerate(bindings):
        available = binding.get("availability_time")
        if not report.add(f"availability_present_{index}", bool(available),
                          "binding has no availability time"):
            return report.as_dict()
        available_instant = _instant(available)
        if available_instant is None:
            report.add(f"availability_valid_{index}", False,
                       f"invalid or timezone-naive availability timestamp: {available!r}")
            return report.as_dict()
        if not report.add(f"not_future_evidence_{index}",
                          available_instant <= cutoff_instant,
                          f"available {available} after cutoff {cutoff}"):
            return report.as_dict()
        scale = binding.get("scale")
        if not report.add(f"scale_present_{index}",
                          type(scale) is int and -12 <= scale <= 18,
                          "scale must be an integer exponent between -12 and 18"):
            return report.as_dict()

    # Scale compatibility across operands is a precondition of the arithmetic, not a label on the
    # answer. A ratio, margin or percentage change of printed values is economically meaningless
    # when one operand is printed in thousands and another in millions, even though every printed
    # number and every source pin agrees. The production engine refuses that before computing;
    # this verifier must reach the same conclusion from its own evidence instead of trusting the
    # producer's earlier unit check. Checking it once here, before any operator branch, also keeps
    # a scaled result (``total``) from depending on whether it carries an economic amount.
    scales = {binding.get("scale") for binding in bindings}
    if not report.add("binding_scale_consistent", len(scales) == 1 and None not in scales,
                      f"input scales {sorted(str(scale) for scale in scales)} must agree"):
        return report.as_dict()

    # Arithmetic over the inputs the certificate carries.
    raws = [str(binding.get("raw") or "") for binding in bindings]
    try:
        computed = compute(operator, raws)
    except VerificationError as exc:
        report.add("independent_arithmetic", False, str(exc))
        return report.as_dict()
    try:
        raw_places = result.get("display_places")
        places = 2 if raw_places is None else int(raw_places)
    except (TypeError, ValueError, OverflowError):
        report.add("display_places_valid", False, "display precision is not an integer")
        return report.as_dict()
    if not 0 <= places <= 12:
        report.add("display_places_valid", False, "display precision outside 0..12")
        return report.as_dict()
    displayed = round_half_up(computed, places=places)
    report.recomputed_value = str(displayed)
    report.method = "fraction_reimplementation_v2"
    claimed = result.get("value")
    try:
        agrees = claimed is not None and Decimal(str(claimed)) == displayed
    except Exception:  # noqa: BLE001 - non-numeric claim is a failure, not a crash
        agrees = False
    if not report.add("independent_arithmetic", agrees,
                      None if agrees else f"claimed {claimed!r} recomputed {displayed}"):
        return report.as_dict()

    # ``value_exact`` is mandatory: a certificate that drops the exact value is asking the
    # verifier to trust the rounded display string alone.
    exact = result.get("value_exact")
    if exact is None:
        report.add("exact_result_present", False, "value_exact is missing")
        return report.as_dict()
    try:
        exact_agrees = Fraction(str(exact)) == computed
    except (ValueError, ZeroDivisionError):
        exact_agrees = False
    if not report.add("exact_result", exact_agrees,
                      None if exact_agrees else f"claimed {exact} recomputed {computed}"):
        return report.as_dict()

    dimensionless = operator in _DIMENSIONLESS
    economic = result.get("economic_amount")
    # A scaled result must carry a scaled amount that follows from the exact value and the
    # recorded scale; a dimensionless result must declare null rather than invent one. A resigned
    # certificate that changes the scale passes the arithmetic check above; this catches it.
    if dimensionless:
        if not report.add("economic_amount_not_applicable", economic is None,
                          f"dimensionless {operator} must not carry {economic!r}"):
            return report.as_dict()
    elif economic is None:
        report.add("economic_amount_present", False,
                   f"scaled {operator} requires an economic amount")
        return report.as_dict()
    else:
        scale = int(next(iter(scales)))
        expected_amount = Decimal(computed.numerator) / Decimal(computed.denominator) \
            * (Decimal(10) ** scale)
        if not report.add("economic_amount",
                          Decimal(str(economic)) == expected_amount,
                          f"claimed {economic}, expected {expected_amount}"):
            return report.as_dict()

    # --- displayed result metadata must agree with the verified inputs --------------------
    # These checks are internal consistency, so they apply at every level. They stop a resigning
    # attacker from leaving authentic bindings in place while relabelling the displayed answer.
    periods = [str(binding.get("period") or "") for binding in bindings]
    if operator == "percentage_change":
        shape_ok = len(periods) == 2 and periods[0] != periods[1]
        expected_period = f"{periods[0]} vs {periods[1]}"
    else:
        shape_ok = len(set(periods)) == 1
        expected_period = periods[0]
    if not report.add("binding_period_shape", shape_ok, periods):
        return report.as_dict()
    claimed_period = _normalise(result.get("period"))
    if not report.add("result_period", claimed_period == _normalise(expected_period),
                      f"claimed {result.get('period')!r}, inputs give {expected_period!r}"):
        return report.as_dict()

    currencies = {_normalise(binding.get("currency")) for binding in bindings}
    if not report.add("binding_currency_consistent", len(currencies) == 1,
                      sorted(currencies)):
        return report.as_dict()
    pinned_currency = next(iter(currencies))
    if not report.add("result_currency",
                      _normalise(result.get("currency")) == pinned_currency,
                      f"claimed {result.get('currency')!r}, inputs carry "
                      f"{pinned_currency or None!r}"):
        return report.as_dict()

    # A dimensionless result is not scaled, and its unit kind is the answer type; a scaled result
    # inherits the binding's exponent and currency attribution.
    unit = result.get("unit")
    if not isinstance(unit, Mapping):
        report.add("result_unit", False, "unit is not an object")
        return report.as_dict()
    expected_scale = 0 if dimensionless else int(next(iter(scales)))
    if not report.add("result_unit_scale", unit.get("scale") == expected_scale,
                      f"claimed {unit.get('scale')!r}, inputs give {expected_scale}"):
        return report.as_dict()
    expected_kind = _UNIT_KIND[operator] if dimensionless else pinned_currency
    if not report.add("result_unit_kind", _normalise(unit.get("kind")) == _normalise(expected_kind),
                      f"claimed {unit.get('kind')!r}, expected {expected_kind!r}"):
        return report.as_dict()

    # The requirement, the compiled computation, the concept list, the reporting scope and the
    # displayed result must describe the same operation. This is consistency, not semantics: it
    # cannot show that the concept or period is the economically correct reading.
    requirement = payload.get("normalized_requirement")
    computation = payload.get("typed_computation")
    if not report.add("requirement_objects",
                      isinstance(requirement, Mapping) and isinstance(computation, Mapping),
                      "normalized_requirement and typed_computation must be objects"):
        return report.as_dict()
    assert isinstance(requirement, Mapping) and isinstance(computation, Mapping)
    if not report.add("operator_agreement",
                      requirement.get("operator") == computation.get("operator") == operator,
                      f"requirement {requirement.get('operator')!r}, computation "
                      f"{computation.get('operator')!r}, resolved {operator!r}"):
        return report.as_dict()
    if not report.add("requirement_concept",
                      _normalise(requirement.get("concept")) ==
                      _normalise(bindings[0].get("concept")),
                      f"requirement {requirement.get('concept')!r}, input "
                      f"{bindings[0].get('concept')!r}"):
        return report.as_dict()
    if not report.add("requirement_period",
                      _normalise(requirement.get("period")) == _normalise(periods[0]),
                      f"requirement {requirement.get('period')!r}, input {periods[0]!r}"):
        return report.as_dict()
    bound_concepts = [_normalise(binding.get("concept")) for binding in bindings]
    if not report.add("financial_concepts",
                      [_normalise(concept) for concept in
                       (payload.get("financial_concepts") or [])] == bound_concepts,
                      f"declared {payload.get('financial_concepts')!r}, bound {bound_concepts!r}"):
        return report.as_dict()
    expected_answer_type = next((name for name, mapped in _ANSWER_TYPE_OPERATOR.items()
                                 if mapped == operator), None)
    if not report.add("answer_type",
                      expected_answer_type is not None and
                      str(computation.get("answer_type") or "") == expected_answer_type,
                      f"claimed {computation.get('answer_type')!r} for {operator!r}"):
        return report.as_dict()
    scope = _normalise(payload.get("reporting_entity_scope"))
    issuer_scope = _normalise((payload.get("issuer_identity") or {})
                             .get("reporting_entity_scope"))
    if not report.add("reporting_scope",
                      bool(scope) and scope == issuer_scope and
                      all(_normalise(binding.get("entity_scope")) == scope
                          for binding in bindings),
                      f"certificate {scope!r}, issuer {issuer_scope!r}, inputs "
                      f"{[binding.get('entity_scope') for binding in bindings]!r}"):
        return report.as_dict()

    # Period meaning is not certified from a header that does not print the claimed period.
    report.semantic_status = period_assignment(bindings)
    if report.semantic_status["period_assignment"] == "unresolved":
        conflicts = [detail for detail in report.semantic_status["details"]
                     if detail["state"] == "conflict"]
        report.limitations.append(
            "period_assignment_unresolved: the pinned column header does not print the bound "
            f"period {[detail['period'] for detail in conflicts]!r} at the selected column "
            f"({[detail['column_label'] for detail in conflicts]!r}). The cell, its coordinates and "
            "the arithmetic are source-verified; the meaning of the period is not.")
    report.limitations.append(
        "Requirement, computation, concept, scope and result metadata are checked for internal "
        "agreement only. Agreeing with each other does not establish that the concept or period is "
        "the economically correct reading of the statement.")

    for name in ("operator_version", "execution_fingerprint"):
        if not report.add(name, bool(computation.get(name)), f"{name} missing"):
            return report.as_dict()

    if evidence is None:
        if trusted_sources is not None:
            report.level = VerificationLevel.SOURCE_UNVERIFIED
            report.reasons.append("legacy_trusted_sources_insufficient")
            report.limitations.append(
                "Caller-supplied hashes are not evidence: they can be copied from the certificate "
                "under test. Supply a pinned manifest and the original bytes instead.")
            return report.as_dict()
        report.level = VerificationLevel.ARITHMETIC_VERIFIED
        report.limitations.append(
            "No trusted source evidence was supplied. The computation matches the inputs the "
            "certificate carries; whether those inputs match the filing was not established.")
        return report.as_dict()

    # One document per certificate is the verifier's current trust scope. Do not use
    # source bytes for the first accession to validate inputs from another filing.
    first_accession = str(bindings[0].get("accession") or "")
    first_issuer = bindings[0].get("issuer_id")
    first_digest = bindings[0].get("document_sha256")
    if not report.add("single_source_document",
                      all(str(b.get("accession") or "") == first_accession
                          and b.get("issuer_id") == first_issuer
                          and b.get("document_sha256") == first_digest
                          for b in bindings),
                      "all inputs must refer to the same accession, issuer and document"):
        return report.as_dict()

    # --- pinned manifest: semantics the certificate does not control -----------------------
    manifest_entry = evidence.document_entry(first_accession)
    if not report.add("manifest_document", manifest_entry is not None,
                      "accession is not pinned in the source manifest"):
        return report.as_dict()
    assert manifest_entry is not None

    issuer_identity = payload.get("issuer_identity") or {}
    if not isinstance(issuer_identity, Mapping):
        report.add("issuer_identity", False, "issuer identity is not an object")
        return report.as_dict()
    for name in ("issuer_id", "cik", "issuer_name"):
        if not report.add(f"manifest_{name}",
                          _normalise(issuer_identity.get(name)) ==
                          _normalise(manifest_entry.get(name)),
                          f"certificate {name} differs from pinned source"):
            return report.as_dict()
    if not report.add("binding_issuer",
                      all(_normalise(b.get("issuer_id")) ==
                          _normalise(manifest_entry.get("issuer_id")) for b in bindings),
                      "input binding issuer differs from pinned source"):
        return report.as_dict()

    # Selected source records are signed claims too. They must not silently
    # contradict the bound cells or the independently pinned accession.
    selected = payload.get("selected_sources")
    if not report.add("selected_source_count",
                      isinstance(selected, list) and len(selected) == len(bindings) and
                      all(isinstance(item, Mapping) for item in selected),
                      "selected source records do not match bound inputs"):
        return report.as_dict()
    assert isinstance(selected, list)
    for index, (source, binding) in enumerate(zip(selected, bindings)):
        for name in ("accession", "document_sha256", "source_table_sha256",
                     "document_id", "table_id", "unit_id", "cell_id",
                     "availability_time", "rights"):
            if not report.add(f"selected_{name}_{index}",
                              _normalise(source.get(name)) == _normalise(binding.get(name)),
                              f"selected source {name} differs from bound input"):
                return report.as_dict()
        for name in ("form_type", "primary_document_url"):
            if not report.add(f"manifest_source_{name}_{index}",
                              _normalise(source.get(name)) ==
                              _normalise(manifest_entry.get(name)),
                              f"selected source {name} differs from pinned document"):
                return report.as_dict()

    claimed_document = bindings[0].get("document_sha256")
    if not report.add("document_digest_present", bool(claimed_document),
                      "certificate does not record a document digest"):
        return report.as_dict()
    if not report.add("manifest_document_sha256",
                      _normalise(manifest_entry.get("document_sha256")) == _normalise(claimed_document),
                      "document digest differs from the pinned manifest"):
        return report.as_dict()
    issuer = payload.get("issuer_identity") or {}
    for name, pinned in (("issuer_id", manifest_entry.get("issuer_id")),
                         ("cik", manifest_entry.get("cik"))):
        claimed_value = issuer.get(name) if name == "issuer_id" else issuer.get(name)
        if name == "issuer_id" and claimed_value is None:
            claimed_value = bindings[0].get("issuer_id")
        if not report.add(f"manifest_{name}", _normalise(claimed_value) == _normalise(pinned),
                          f"pinned {pinned!r} claimed {claimed_value!r}"):
            return report.as_dict()

    pinned_cells = {(cell["table_sha256"], int(cell["row"]), int(cell["column"])): cell
                    for cell in manifest_entry.get("cells", [])}
    semantic_fields = ("raw", "value", "row_label", "column_label", "period", "scale", "currency",
                       "concept", "statement_family", "availability_time")
    for index, binding in enumerate(bindings):
        key = (binding.get("source_table_sha256"), int(binding.get("row")),
               int(binding.get("column")))
        pinned = pinned_cells.get(key)
        if not report.add(f"manifest_cell_{index}", pinned is not None,
                          f"cell {key} is not pinned"):
            return report.as_dict()
        assert pinned is not None
        for name in semantic_fields:
            if not report.add(f"manifest_{name}_{index}",
                              _normalise(pinned.get(name)) == _normalise(binding.get(name)),
                              f"pinned {pinned.get(name)!r} claimed {binding.get(name)!r}"):
                return report.as_dict()

    # --- original bytes: authenticity the certificate cannot manufacture --------------------
    source_payload, route = evidence.source_bytes(str(bindings[0]["accession"]), manifest_entry)
    report.source_route = route
    if source_payload is None:
        report.level = VerificationLevel.SOURCE_UNVERIFIED
        report.reasons.append("no_source_bytes")
        report.limitations.append(
            "The pinned manifest matched, but the original document bytes were unavailable, so "
            "authenticity was not established. A manifest cannot prove which bytes were served.")
        return report.as_dict()

    actual_digest = hashlib.sha256(source_payload).hexdigest()
    if not report.add("source_bytes_sha256", actual_digest == claimed_document,
                      None if actual_digest == claimed_document else f"bytes hash to {actual_digest}"):
        return report.as_dict()

    snapshot_raws: list[str] = []
    for index, binding in enumerate(bindings):
        rows, problem = _table_from_snapshot(source_payload, str(binding["source_table_sha256"]))
        if not report.add(f"source_table_{index}", rows is not None, problem):
            return report.as_dict()
        assert rows is not None
        row, column = int(binding["row"]), int(binding["column"])
        if not report.add(f"source_coordinates_{index}",
                          0 <= row < len(rows) and 0 <= column < len(rows[row]),
                          f"row {row} column {column} outside the source table"):
            return report.as_dict()
        printed = _normalise(rows[row][column])
        if not report.add(f"source_cell_text_{index}", printed == _normalise(binding.get("raw")),
                          f"source prints {printed!r}, certificate claims {binding.get('raw')!r}"):
            return report.as_dict()
        snapshot_raws.append(printed)

    try:
        from_source = compute(operator, snapshot_raws)
    except VerificationError as exc:
        report.add("source_arithmetic", False, str(exc))
        return report.as_dict()
    if not report.add("source_arithmetic",
                      round_half_up(from_source, places=places) == displayed,
                      f"source {round_half_up(from_source, places=places)} vs certificate {displayed}"):
        return report.as_dict()

    report.level = VerificationLevel.SOURCE_VERIFIED
    report.limitations.append(
        "Source verification authenticates the printed cell, its coordinates, the document digest "
        "and the arithmetic. It does not prove the filing's publication time, that the resolved "
        "concept is the economically intended one, or that an unsigned manifest was authored "
        "honestly.")
    return report.as_dict()


def verify_certificate_file(path: str | Path, *, evidence: TrustedEvidence | None = None,
                            trusted_sources: Mapping[str, Mapping[str, Any]] | None = None
                            ) -> dict[str, Any]:
    payload = json.loads(Path(path).read_text(encoding="utf-8"))
    result = verify_payload(payload, evidence=evidence, trusted_sources=trusted_sources)
    result["path"] = str(path)
    return result


def load_certificate(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


__all__ = [
    "MANIFEST_SCHEMA", "OPERATORS", "VERIFIER_SCHEMA", "VERIFIER_VERSION", "TrustedEvidence",
    "VerificationError", "VerificationLevel", "VerificationReport", "build_source_manifest",
    "compute", "fetch_source_bytes", "load_certificate", "parse_printed", "resolve_operator",
    "round_half_up", "verify_certificate_file", "verify_payload",
]
