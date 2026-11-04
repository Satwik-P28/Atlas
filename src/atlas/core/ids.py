"""Stable internal identifiers.

Design rules (see ``docs/adr/0002-identity-conventions.md``):

1. Internal ids are **deterministic** and derived from identity anchors, never from
   mutable attributes such as a ticker. Re-running an ingestion produces the same
   ids, which makes synchronisation idempotent without a global counter.
2. Ids are **opaque, prefixed and readable** (``ISS-CIK0000320193``). The prefix
   states the entity class so a log line or CLI response is self-describing.
3. A ticker is *not* an anchor for a security. It is a time-bounded attribute of a
   listing.
4. Where no authoritative anchor exists, a digested canonical key is used and the
   result is explicitly "probable", not "confirmed".
"""

from __future__ import annotations

import re
import uuid

from .errors import ValidationError

# Fixed namespace for uuid5 derivation. Changing this invalidates every stored id,
# so it is part of the on-disk contract (bump the schema version if it ever changes).
_NAMESPACE = uuid.UUID("1b4e28ba-2fa1-11d2-883f-0016d3cca427")

_CIK_RE = re.compile(r"^[A-Z]*0*(\d{1,10})$")


def _digest(*parts: str) -> str:
    return uuid.uuid5(_NAMESPACE, "\x1f".join(parts)).hex


# --------------------------------------------------------------------------- #
# Normalisation helpers
# --------------------------------------------------------------------------- #
def normalize_cik(cik: str | int) -> str:
    """Return a zero-padded 10-digit SEC CIK.

    Accepts ``320193``, ``0000320193``, ``CIK0000320193``.
    """
    raw = str(cik).strip().upper()
    if raw.startswith("CIK"):
        raw = raw[3:]
    raw = raw.strip()
    if not raw.isdigit():
        raise ValidationError("invalid CIK", cik=cik)
    digits = raw.lstrip("0") or "0"
    if len(digits) > 10:
        raise ValidationError("CIK longer than 10 digits", cik=cik)
    return digits.zfill(10)


def normalize_ticker(ticker: str) -> str:
    """Canonical ticker form: upper-case, no surrounding space.

    Dots and hyphens are preserved because they are significant on some venues
    (``BRK.B``, ``BF-B``). We never map between the two automatically: that is a
    venue convention, and guessing would silently merge different instruments.
    """
    if ticker is None:
        raise ValidationError("ticker is required")
    value = str(ticker).strip().upper()
    if not value:
        raise ValidationError("ticker is empty")
    if any(ch.isspace() for ch in value):
        raise ValidationError("ticker contains whitespace", ticker=ticker)
    if len(value) > 32:
        raise ValidationError("ticker implausibly long", ticker=ticker)
    return value


def normalize_class_key(designation: str) -> str:
    """Canonical share-class key used to distinguish securities of one issuer.

    ``"Common Stock"`` -> ``common``; ``"Class A Common Stock"`` -> ``class_a``;
    ``"Class B"`` -> ``class_b``. Anything unrecognised is slugified verbatim so two
    different designations never collapse into one security by accident.
    """
    if designation is None or not str(designation).strip():
        raise ValidationError("share class designation is required")
    text = str(designation).strip().lower()
    for noise in ("common stock", "ordinary shares", "ordinary share", "common shares", "stock"):
        text = text.replace(noise, " ")
    text = re.sub(r"[^a-z0-9]+", "_", text).strip("_")
    if not text:
        return "common"
    if text in {"common", "ordinary", "capital", "common_"}:
        return "common"
    if text.startswith("class_") and len(text) > 6:
        return text
    return text


# --------------------------------------------------------------------------- #
# Entity ids
# --------------------------------------------------------------------------- #
def issuer_id_for_cik(cik: str | int) -> str:
    """Issuer id anchored on the SEC CIK (authoritative for US registrants)."""
    return f"ISS-CIK{normalize_cik(cik)}"


def issuer_id_for_entity(legal_name: str, country: str | None = None) -> str:
    """Issuer id for a legal entity without an authoritative registry anchor.

    Deliberately distinct from CIK-anchored ids so that linking a CIK later creates a
    merge decision rather than silently reusing an id.
    """
    name = " ".join(str(legal_name).split()).lower()
    if not name:
        raise ValidationError("legal name is required")
    return "ISS-E" + _digest("legal_entity", name, (country or "").upper())[:16]


def security_id(issuer: str, class_key: str) -> str:
    """Security id: issuer identity plus share-class key. Ticker is never an input."""
    return "SEC-" + _digest("security", issuer, normalize_class_key(class_key))[:20]


def listing_id(security: str, mic: str, valid_from: str) -> str:
    """A listing is (security, venue) scoped to the interval it was effective."""
    return "LST-" + _digest("listing", security, mic.upper(), valid_from)[:16]


def ticker_assignment_id(listing: str, ticker: str, valid_from: str) -> str:
    return "TKR-" + _digest("ticker", listing, normalize_ticker(ticker), valid_from)[:16]


def identifier_assignment_id(security: str, scheme: str, value: str, valid_from: str) -> str:
    return "IDT-" + _digest("identifier", security, scheme.upper(), value, valid_from)[:16]


def relationship_id(from_issuer: str, to_issuer: str, rel_type: str, valid_from: str) -> str:
    return "REL-" + _digest("relationship", from_issuer, to_issuer, rel_type, valid_from)[:16]


# --------------------------------------------------------------------------- #
# Records
# --------------------------------------------------------------------------- #
def evidence_id(
    *,
    source_id: str,
    entity_id: str,
    concept: str,
    accession_number: str | None,
    period_start: str | None,
    period_end: str | None,
    unit: str,
    value_numeric: str | None,
    availability_time: str | None,
    revision_kind: str,
) -> str:
    """Deterministic evidence id.

    The identity of an observation is *what was asserted, about whom, over which
    period, from which source document, when it became available*. Two records that
    agree on all of those are the same evidence. Any difference (a restated value, a
    different accession, a different period or availability time) yields a distinct
    record, which is exactly the behaviour required to preserve history.

    ``period_start`` is part of the tuple because an annual and a quarterly fact can
    share an end date; omitting it would collapse two different economic quantities.
    """
    return "EV-" + _digest(
        "evidence",
        source_id,
        entity_id,
        concept,
        accession_number or "",
        period_start or "",
        period_end or "",
        unit,
        value_numeric or "",
        availability_time or "",
        revision_kind,
    )[:24]


def filing_id(accession_number: str) -> str:
    accession = accession_number.strip()
    if not accession:
        raise ValidationError("accession number is required")
    return "FIL-" + _digest("filing", accession)[:20]


def raw_document_id(source_id: str, content_hash: str) -> str:
    return "DOC-" + _digest("raw_document", source_id, content_hash)[:20]


def action_id(security: str, action_type: str, ex_date: str, terms_key: str) -> str:
    return "ACT-" + _digest("action", security, action_type, ex_date, terms_key)[:20]


def issue_id(scope: str, subject_id: str, code: str, detail: str) -> str:
    return "DQI-" + _digest("issue", scope, subject_id, code, detail)[:20]


def ingestion_run_id(command: str, started_at: str) -> str:
    return "RUN-" + _digest("run", command, started_at)[:20]


def source_slug(name: str) -> str:
    """Readable deterministic slug for a registered source."""
    slug = re.sub(r"[^a-z0-9]+", "-", str(name).strip().lower()).strip("-")
    if not slug:
        raise ValidationError("source name is required", name=name)
    return slug
