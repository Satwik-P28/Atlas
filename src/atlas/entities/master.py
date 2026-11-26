"""Security and entity master.

Identity rules enforced here (see ``docs/adr/0002-identity-conventions.md``):

* An **issuer** is a legal entity. It is anchored on the SEC CIK when available.
* A **security** is a tradable instrument issued by exactly one issuer, distinguished
  by its share class. Its id never contains a ticker.
* A **listing** is a (security, venue) pair over an interval.
* A **ticker** is a time-bounded attribute of a listing. Tickers are reused and
  changed; therefore every assignment carries an interval, a confidence and a status.

Resolution never guesses. When a ticker maps to more than one security under the
requested time semantics, the resolver reports an ambiguous result with every
candidate and the reason, instead of picking the most recent one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from typing import Any, Sequence

from ..core.errors import AmbiguousResolution, UnknownEntity, ValidationError
from ..core.ids import (
    identifier_assignment_id,
    issuer_id_for_cik,
    issuer_id_for_entity,
    listing_id,
    normalize_cik,
    normalize_class_key,
    normalize_ticker,
    relationship_id,
    security_id as make_security_id,
    ticker_assignment_id,
)
from ..core.temporal import iso, iso_date, parse_date, utcnow
from ..storage.db import Database

STATUS_CONFIRMED = "confirmed"
STATUS_PROBABLE = "probable"
STATUS_UNVERIFIED = "unverified"
STATUS_RETRACTED = "retracted"

RESOLUTION_CONFIRMED = "confirmed"
RESOLUTION_PROBABLE = "probable"
RESOLUTION_AMBIGUOUS = "ambiguous"
RESOLUTION_NONE = "none"


@dataclass(slots=True)
class Candidate:
    security_id: str
    issuer_id: str
    legal_name: str
    class_designation: str
    mic: str | None
    ticker: str | None
    valid_from: str | None
    valid_to: str | None
    confidence: float
    status: str
    evidence_note: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {name: getattr(self, name) for name in self.__slots__}


@dataclass(slots=True)
class Resolution:
    """Inspectable outcome of an identity query."""

    query: dict[str, Any]
    candidates: list[Candidate]
    method: str
    confidence: str
    reasoning: list[str] = field(default_factory=list)

    @property
    def ambiguous(self) -> bool:
        return self.confidence == RESOLUTION_AMBIGUOUS

    @property
    def resolved(self) -> Candidate | None:
        if self.confidence in {RESOLUTION_CONFIRMED, RESOLUTION_PROBABLE} and len(self.candidates) == 1:
            return self.candidates[0]
        return None

    def require_single(self) -> Candidate:
        if self.ambiguous:
            raise AmbiguousResolution(
                "multiple securities match; Atlas refuses to choose one",
                candidates=[c.to_dict() for c in self.candidates],
                **self.query,
            )
        if not self.candidates:
            raise UnknownEntity("no security matches the query", **self.query)
        return self.candidates[0]

    def to_dict(self) -> dict[str, Any]:
        return {
            "query": self.query,
            "method": self.method,
            "confidence": self.confidence,
            "ambiguous": self.ambiguous,
            "reasoning": self.reasoning,
            "candidates": [c.to_dict() for c in self.candidates],
        }


class SecurityMaster:
    """CRUD and resolution over issuers, securities, listings and identifiers."""

    def __init__(self, db: Database) -> None:
        self.db = db

    # ------------------------------------------------------------------ venues
    def ensure_venue(self, mic: str, name: str, *, country: str | None = None, timezone: str = "UTC") -> str:
        mic_code = mic.strip().upper()
        if not mic_code:
            raise ValidationError("venue MIC is required")
        self.db.execute(
            "INSERT INTO venue (mic, name, country, timezone) VALUES (?,?,?,?) "
            "ON CONFLICT(mic) DO UPDATE SET name=excluded.name, country=excluded.country, "
            "timezone=excluded.timezone",
            (mic_code, name, country, timezone),
        )
        return mic_code

    def venues(self) -> list[dict[str, Any]]:
        return [{k: row[k] for k in row.keys()} for row in self.db.query("SELECT * FROM venue ORDER BY mic")]

    # ----------------------------------------------------------------- issuers
    def register_issuer(
        self,
        *,
        legal_name: str,
        cik: str | int | None = None,
        entity_type: str | None = "corporation",
        domicile_country: str | None = "US",
        sic: str | None = None,
        fiscal_year_end: str | None = None,
        source_id: str | None = None,
        is_active: bool = True,
    ) -> str:
        if not legal_name or not legal_name.strip():
            raise ValidationError("legal name is required for an issuer")
        now = iso(utcnow())
        if cik is not None:
            normalized = normalize_cik(cik)
            issuer = issuer_id_for_cik(normalized)
            existing = self.db.query_one("SELECT issuer_id, legal_name FROM issuer WHERE cik = ?", (normalized,))
            if existing is not None:
                self.db.execute(
                    "UPDATE issuer SET legal_name = ?, entity_type = COALESCE(?, entity_type), "
                    "sic = COALESCE(?, sic), fiscal_year_end = COALESCE(?, fiscal_year_end), "
                    "domicile_country = COALESCE(?, domicile_country), is_active = ?, updated_at = ? "
                    "WHERE issuer_id = ?",
                    (legal_name.strip(), entity_type, sic, fiscal_year_end, domicile_country, int(is_active), now, existing["issuer_id"]),
                )
                return str(existing["issuer_id"])
            self.db.execute(
                "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, domicile_country, sic, "
                "fiscal_year_end, is_active, provenance_source, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (issuer, normalized, legal_name.strip(), entity_type, domicile_country, sic, fiscal_year_end,
                 int(is_active), source_id, now, now),
            )
            return issuer
        issuer = issuer_id_for_entity(legal_name, domicile_country)
        self.db.execute(
            "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, domicile_country, sic, "
            "fiscal_year_end, is_active, provenance_source, created_at, updated_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(issuer_id) DO UPDATE SET "
            "legal_name=excluded.legal_name, updated_at=excluded.updated_at",
            (issuer, None, legal_name.strip(), entity_type, domicile_country, sic, fiscal_year_end,
             int(is_active), source_id, now, now),
        )
        return issuer

    def issuer(self, issuer_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM issuer WHERE issuer_id = ?", (issuer_id,))
        return {k: row[k] for k in row.keys()} if row is not None else None

    def issuer_by_cik(self, cik: str | int) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM issuer WHERE cik = ?", (normalize_cik(cik),))
        return {k: row[k] for k in row.keys()} if row is not None else None

    def require_issuer_by_cik(self, cik: str | int) -> dict[str, Any]:
        issuer = self.issuer_by_cik(cik)
        if issuer is None:
            raise UnknownEntity("issuer is not registered", cik=normalize_cik(cik))
        return issuer

    # --------------------------------------------------------------- securities
    def ensure_security(
        self,
        issuer_id: str,
        *,
        class_designation: str = "common stock",
        security_type: str = "common_stock",
        currency: str | None = "USD",
        source_id: str | None = None,
        is_active: bool = True,
        note: str | None = None,
    ) -> str:
        if self.issuer(issuer_id) is None:
            raise UnknownEntity("issuer is not registered", issuer_id=issuer_id)
        class_key = normalize_class_key(class_designation)
        sec_id = make_security_id(issuer_id, class_key)
        now = iso(utcnow())
        self.db.execute(
            "INSERT INTO security (security_id, issuer_id, security_type, class_designation, share_class_key, "
            "currency, is_active, first_observed_at, note) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(security_id) DO UPDATE SET security_type=excluded.security_type, "
            "currency=COALESCE(excluded.currency, security.currency), is_active=excluded.is_active, "
            "note=COALESCE(excluded.note, security.note)",
            (sec_id, issuer_id, security_type, class_designation, class_key, currency, int(is_active), now, note),
        )
        return sec_id

    def security(self, security_id: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM security WHERE security_id = ?", (security_id,))
        return {k: row[k] for k in row.keys()} if row is not None else None

    def securities_for_issuer(self, issuer_id: str) -> list[dict[str, Any]]:
        rows = self.db.query("SELECT * FROM security WHERE issuer_id = ? ORDER BY share_class_key", (issuer_id,))
        return [{k: row[k] for k in row.keys()} for row in rows]

    def retire_security(self, security_id: str, as_of: str | None = None, *, reason: str | None = None) -> None:
        """Mark a security delisted: close its listings and ticker assignments.

        Historical rows are never deleted; delisting is expressed by closing the
        intervals, so historical queries still resolve the security.
        """
        if self.security(security_id) is None:
            raise UnknownEntity("unknown security", security_id=security_id)
        cutoff = iso_date(as_of) if as_of else iso_date(utcnow())
        with self.db.transaction():
            self.db.execute(
                "UPDATE security SET is_active = 0, last_observed_at = ?, note = COALESCE(?, note) WHERE security_id = ?",
                (cutoff, reason, security_id),
            )
            self.db.execute(
                "UPDATE listing SET valid_to = ? WHERE security_id = ? AND (valid_to IS NULL OR valid_to > ?)",
                (cutoff, security_id, cutoff),
            )
            self.db.execute(
                "UPDATE ticker_assignment SET valid_to = ? WHERE listing_id IN "
                "(SELECT listing_id FROM listing WHERE security_id = ?) AND (valid_to IS NULL OR valid_to > ?)",
                (cutoff, security_id, cutoff),
            )

    # ----------------------------------------------------------------- listings
    def ensure_listing(
        self,
        security_id: str,
        mic: str,
        *,
        valid_from: str | None = None,
        currency: str | None = None,
        is_primary: bool = False,
        source_id: str | None = None,
    ) -> str:
        if self.security(security_id) is None:
            raise UnknownEntity("unknown security", security_id=security_id)
        if self.db.query_one("SELECT mic FROM venue WHERE mic = ?", (mic.upper(),)) is None:
            raise UnknownEntity("unknown venue; register it first", mic=mic)
        start = iso_date(valid_from) if valid_from else iso_date(utcnow())
        lst_id = listing_id(security_id, mic, start)
        self.db.execute(
            "INSERT INTO listing (listing_id, security_id, mic, currency, valid_from, valid_to, is_primary, source_id) "
            "VALUES (?,?,?,?,?,NULL,?,?) ON CONFLICT(listing_id) DO UPDATE SET "
            "currency=COALESCE(excluded.currency, listing.currency), is_primary=excluded.is_primary",
            (lst_id, security_id, mic.upper(), currency, start, int(is_primary), source_id),
        )
        return lst_id

    def listings(self, security_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM listing WHERE security_id = ? ORDER BY valid_from, mic", (security_id,)
        )
        return [{k: row[k] for k in row.keys()} for row in rows]

    def listing(self, listing_id_value: str) -> dict[str, Any] | None:
        row = self.db.query_one("SELECT * FROM listing WHERE listing_id = ?", (listing_id_value,))
        return {k: row[k] for k in row.keys()} if row is not None else None

    # ------------------------------------------------------------------ tickers
    def assign_ticker(
        self,
        listing_id_value: str,
        ticker: str,
        *,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        status: str = STATUS_CONFIRMED,
        source_id: str | None = None,
        evidence_note: str | None = None,
    ) -> str:
        if self.listing(listing_id_value) is None:
            raise UnknownEntity("unknown listing", listing_id=listing_id_value)
        if not 0.0 <= confidence <= 1.0:
            raise ValidationError("confidence must be within [0, 1]", confidence=confidence)
        if status not in {STATUS_CONFIRMED, STATUS_PROBABLE, STATUS_UNVERIFIED, STATUS_RETRACTED}:
            raise ValidationError("invalid assignment status", status=status)
        symbol = normalize_ticker(ticker)
        start = iso_date(valid_from) if valid_from else iso_date(utcnow())
        end = iso_date(valid_to) if valid_to else None
        if end is not None and end < start:
            raise ValidationError("ticker assignment ends before it starts", ticker=symbol)
        assignment = ticker_assignment_id(listing_id_value, symbol, start)
        self.db.execute(
            "INSERT INTO ticker_assignment (ticker_assignment_id, listing_id, ticker, valid_from, valid_to, "
            "confidence, status, source_id, evidence_note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(ticker_assignment_id) DO UPDATE SET valid_to=excluded.valid_to, "
            "confidence=excluded.confidence, status=excluded.status, evidence_note=excluded.evidence_note",
            (assignment, listing_id_value, symbol, start, end, confidence, status, source_id, evidence_note,
             iso(utcnow())),
        )
        return assignment

    def current_ticker(self, security_id: str, as_of: str | None = None) -> dict[str, Any] | None:
        moment = iso_date(as_of) if as_of else iso_date(utcnow())
        row = self.db.query_one(
            "SELECT ta.*, l.mic FROM ticker_assignment ta JOIN listing l ON l.listing_id = ta.listing_id "
            "WHERE l.security_id = ? AND ta.status != 'retracted' AND ta.valid_from <= ? "
            "AND (ta.valid_to IS NULL OR ta.valid_to >= ?) ORDER BY l.is_primary DESC, ta.valid_from DESC LIMIT 1",
            (security_id, moment, moment),
        )
        return {k: row[k] for k in row.keys()} if row is not None else None

    def record_ticker_change(
        self,
        security_id: str,
        new_ticker: str,
        effective_date: str,
        *,
        source_id: str | None = None,
        note: str | None = None,
    ) -> dict[str, Any]:
        """Close the current ticker on its effective eve and open the successor.

        The old assignment is retained with a closed interval, so a historical query
        for the period before the change still resolves the old symbol to the same
        security.
        """
        effective = parse_date(effective_date)
        listing = self.db.query_one(
            "SELECT l.listing_id FROM listing l WHERE l.security_id = ? AND "
            "(l.valid_to IS NULL OR l.valid_to >= ?) ORDER BY l.is_primary DESC, l.valid_from LIMIT 1",
            (security_id, effective.isoformat()),
        )
        if listing is None:
            raise UnknownEntity("security has no active listing to rename", security_id=security_id)
        close_at = (effective - timedelta(days=1)).isoformat()
        current = self.current_ticker(security_id, as_of=close_at)
        with self.db.transaction():
            if current is not None:
                self.db.execute(
                    "UPDATE ticker_assignment SET valid_to = ? WHERE ticker_assignment_id = ? AND valid_to IS NULL",
                    (close_at, current["ticker_assignment_id"]),
                )
            new_id = self.assign_ticker(
                listing["listing_id"],
                new_ticker,
                valid_from=effective.isoformat(),
                confidence=1.0,
                status=STATUS_CONFIRMED,
                source_id=source_id,
                evidence_note=note,
            )
        return {
            "security_id": security_id,
            "previous_ticker": current["ticker"] if current else None,
            "previous_closed_on": close_at if current else None,
            "new_ticker": normalize_ticker(new_ticker),
            "new_assignment_id": new_id,
            "effective_date": effective.isoformat(),
        }

    def ticker_assignments(self, security_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT ta.*, l.mic FROM ticker_assignment ta JOIN listing l ON l.listing_id = ta.listing_id "
            "WHERE l.security_id = ? ORDER BY ta.valid_from",
            (security_id,),
        )
        return [{k: row[k] for k in row.keys()} for row in rows]

    def ticker_conflicts(self, ticker: str | None = None) -> list[dict[str, Any]]:
        """Overlapping assignments of the same ticker to different securities."""
        sql = (
            "SELECT ta.ticker, ta.valid_from, ta.valid_to, ta.status, ta.confidence, l.security_id, "
            "l.mic, ta.ticker_assignment_id FROM ticker_assignment ta "
            "JOIN listing l ON l.listing_id = ta.listing_id WHERE ta.status != 'retracted'"
        )
        params: Sequence[Any] = ()
        if ticker:
            sql += " AND ta.ticker = ?"
            params = (normalize_ticker(ticker),)
        sql += " ORDER BY ta.ticker, ta.valid_from"
        rows = self.db.query(sql, params)
        conflicts: list[dict[str, Any]] = []
        for i, a in enumerate(rows):
            for b in rows[i + 1 :]:
                if a["ticker"] != b["ticker"] or a["security_id"] == b["security_id"]:
                    continue
                a_end = a["valid_to"] or "9999-12-31"
                b_end = b["valid_to"] or "9999-12-31"
                if a["valid_from"] <= b_end and b["valid_from"] <= a_end:
                    conflicts.append(
                        {
                            "ticker": a["ticker"],
                            "security_a": a["security_id"],
                            "security_b": b["security_id"],
                            "overlap": [max(a["valid_from"], b["valid_from"]), min(a_end, b_end)],
                            "assignments": [a["ticker_assignment_id"], b["ticker_assignment_id"]],
                        }
                    )
        return conflicts

    # -------------------------------------------------------------- identifiers
    def assign_identifier(
        self,
        security_id: str,
        scheme: str,
        value: str,
        *,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        status: str = STATUS_CONFIRMED,
        source_id: str | None = None,
        licence_note: str | None = None,
    ) -> str:
        if self.security(security_id) is None:
            raise UnknownEntity("unknown security", security_id=security_id)
        if not scheme or not value:
            raise ValidationError("identifier scheme and value are required")
        if not 0.0 <= confidence <= 1.0:
            raise ValidationError("confidence must be within [0, 1]", confidence=confidence)
        start = iso_date(valid_from) if valid_from else None
        assignment = identifier_assignment_id(security_id, scheme, value, start or "")
        self.db.execute(
            "INSERT INTO security_identifier (assignment_id, security_id, scheme, value, valid_from, valid_to, "
            "confidence, status, source_id, licence_note, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(assignment_id) DO UPDATE SET confidence=excluded.confidence, status=excluded.status, "
            "valid_to=excluded.valid_to, licence_note=excluded.licence_note",
            (assignment, security_id, scheme.upper(), value.strip(), start,
             iso_date(valid_to) if valid_to else None, confidence, status, source_id, licence_note, iso(utcnow())),
        )
        return assignment

    def identifiers(self, security_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM security_identifier WHERE security_id = ? ORDER BY scheme, valid_from", (security_id,)
        )
        return [{k: row[k] for k in row.keys()} for row in rows]

    # ------------------------------------------------------------ relationships
    def record_relationship(
        self,
        from_issuer_id: str,
        to_issuer_id: str,
        relationship_type: str,
        *,
        valid_from: str | None = None,
        valid_to: str | None = None,
        confidence: float = 1.0,
        source_id: str | None = None,
        note: str | None = None,
    ) -> str:
        if from_issuer_id == to_issuer_id:
            raise ValidationError("an issuer cannot relate to itself", issuer=from_issuer_id)
        for issuer in (from_issuer_id, to_issuer_id):
            if self.issuer(issuer) is None:
                raise UnknownEntity("unknown issuer in relationship", issuer_id=issuer)
        start = iso_date(valid_from) if valid_from else None
        rel_id = relationship_id(from_issuer_id, to_issuer_id, relationship_type, start or "")
        self.db.execute(
            "INSERT INTO entity_relationship (relationship_id, from_issuer_id, to_issuer_id, relationship_type, "
            "valid_from, valid_to, confidence, source_id, note) VALUES (?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(relationship_id) DO UPDATE SET valid_to=excluded.valid_to, confidence=excluded.confidence, "
            "note=excluded.note",
            (rel_id, from_issuer_id, to_issuer_id, relationship_type, start,
             iso_date(valid_to) if valid_to else None, confidence, source_id, note),
        )
        return rel_id

    def relationships(self, issuer_id: str) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM entity_relationship WHERE from_issuer_id = ? OR to_issuer_id = ?", (issuer_id, issuer_id)
        )
        return [{k: row[k] for k in row.keys()} for row in rows]

    # --------------------------------------------------------------- resolution
    def resolve_ticker(self, ticker: str, as_of: str | None = None) -> Resolution:
        """Resolve a ticker under explicit time semantics, without guessing."""
        symbol = normalize_ticker(ticker)
        moment = iso_date(as_of) if as_of else None
        sql = (
            "SELECT ta.ticker, ta.valid_from, ta.valid_to, ta.confidence, ta.status, ta.evidence_note, "
            "l.security_id, l.mic, s.issuer_id, s.class_designation, i.legal_name "
            "FROM ticker_assignment ta "
            "JOIN listing l ON l.listing_id = ta.listing_id "
            "JOIN security s ON s.security_id = l.security_id "
            "JOIN issuer i ON i.issuer_id = s.issuer_id "
            "WHERE ta.ticker = ? AND ta.status != 'retracted'"
        )
        params: list[Any] = [symbol]
        if moment is not None:
            sql += " AND ta.valid_from <= ? AND (ta.valid_to IS NULL OR ta.valid_to >= ?)"
            params.extend([moment, moment])
        else:
            sql += " AND ta.valid_to IS NULL"
        rows = self.db.query(sql + " ORDER BY ta.valid_from DESC", params)

        candidates = [
            Candidate(
                security_id=row["security_id"],
                issuer_id=row["issuer_id"],
                legal_name=row["legal_name"],
                class_designation=row["class_designation"],
                mic=row["mic"],
                ticker=row["ticker"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                confidence=float(row["confidence"]),
                status=row["status"],
                evidence_note=row["evidence_note"],
            )
            for row in rows
        ]
        reasoning: list[str] = []
        query = {"ticker": symbol, "as_of": moment}
        if not candidates:
            reasoning.append(
                f"No {symbol} ticker assignment covers {'the current period' if moment is None else moment}."
            )
            historical = self.db.query(
                "SELECT COUNT(*) AS n FROM ticker_assignment WHERE ticker = ?", (symbol,)
            )
            if historical and historical[0]["n"]:
                reasoning.append(
                    f"{historical[0]['n']} historical assignment(s) exist for {symbol} but none covers "
                    + (
                        f"{moment}; the ticker is not evidenced as active on that date."
                        if moment
                        else "the current date. Retry with an as-of date inside an assignment window."
                    )
                )
            return Resolution(query=query, candidates=[], method="ticker_assignment",
                              confidence=RESOLUTION_NONE, reasoning=reasoning)

        distinct = {c.security_id for c in candidates}
        if len(distinct) > 1:
            reasoning.append(
                f"{symbol} maps to {len(distinct)} distinct securities under these time semantics; "
                "a ticker is not a permanent identifier, so Atlas reports every candidate."
            )
            for candidate in candidates:
                reasoning.append(
                    f"{candidate.security_id} ({candidate.legal_name}, {candidate.class_designation}) on "
                    f"{candidate.mic} held {symbol} from {candidate.valid_from} to {candidate.valid_to or 'present'}."
                )
            return Resolution(query=query, candidates=candidates, method="ticker_assignment",
                              confidence=RESOLUTION_AMBIGUOUS, reasoning=reasoning)

        candidate = candidates[0]
        if candidate.status == STATUS_CONFIRMED and candidate.confidence >= 0.9:
            confidence = RESOLUTION_CONFIRMED
        elif candidate.confidence >= 0.5:
            confidence = RESOLUTION_PROBABLE
        else:
            confidence = RESOLUTION_PROBABLE
            reasoning.append("Assignment confidence is below 0.5; treat this match as tentative.")
        reasoning.append(
            f"{symbol} resolved to {candidate.security_id} ({candidate.legal_name}, "
            f"{candidate.class_designation}) via assignment valid {candidate.valid_from}.."
            f"{candidate.valid_to or 'present'}."
        )
        if candidate.status != STATUS_CONFIRMED:
            reasoning.append(f"Assignment status is '{candidate.status}', not 'confirmed'.")
        return Resolution(query=query, candidates=[candidate], method="ticker_assignment",
                          confidence=confidence, reasoning=reasoning)

    def resolve_identifier(self, scheme: str, value: str, as_of: str | None = None) -> Resolution:
        scheme_key = scheme.strip().upper()
        moment = iso_date(as_of) if as_of else None
        sql = (
            "SELECT si.*, s.issuer_id, s.class_designation, i.legal_name, "
            "(SELECT mic FROM listing l WHERE l.security_id = si.security_id ORDER BY l.is_primary DESC LIMIT 1) AS mic, "
            "(SELECT ticker FROM ticker_assignment ta WHERE ta.listing_id IN "
            " (SELECT listing_id FROM listing l2 WHERE l2.security_id = si.security_id) "
            " ORDER BY ta.valid_from DESC LIMIT 1) AS ticker "
            "FROM security_identifier si "
            "JOIN security s ON s.security_id = si.security_id "
            "JOIN issuer i ON i.issuer_id = s.issuer_id "
            "WHERE si.scheme = ? AND si.value = ? AND si.status != 'retracted'"
        )
        params: list[Any] = [scheme_key, value.strip()]
        if moment is not None:
            sql += " AND (si.valid_from IS NULL OR si.valid_from <= ?) AND (si.valid_to IS NULL OR si.valid_to >= ?)"
            params.extend([moment, moment])
        rows = self.db.query(sql, params)
        candidates = [
            Candidate(
                security_id=row["security_id"],
                issuer_id=row["issuer_id"],
                legal_name=row["legal_name"],
                class_designation=row["class_designation"],
                mic=row["mic"],
                ticker=row["ticker"],
                valid_from=row["valid_from"],
                valid_to=row["valid_to"],
                confidence=float(row["confidence"]),
                status=row["status"],
            )
            for row in rows
        ]
        reasoning = [
            f"Identifier {scheme_key}:{value} matched {len(candidates)} security record(s)."
        ] if candidates else [f"No stored {scheme_key}:{value} identifier."]
        if len({c.security_id for c in candidates}) > 1:
            reasoning.append("Identifier is not unique across securities; conflicting sources must be reconciled.")
            return Resolution(query={"scheme": scheme_key, "value": value, "as_of": moment},
                              candidates=candidates, method="security_identifier",
                              confidence=RESOLUTION_AMBIGUOUS, reasoning=reasoning)
        confidence = RESOLUTION_NONE
        if candidates:
            confidence = RESOLUTION_CONFIRMED if candidates[0].confidence >= 0.9 else RESOLUTION_PROBABLE
        return Resolution(query={"scheme": scheme_key, "value": value, "as_of": moment},
                          candidates=candidates, method="security_identifier",
                          confidence=confidence, reasoning=reasoning)

    # ----------------------------------------------------------------- profiles
    def security_profile(self, security_id: str) -> dict[str, Any]:
        security = self.security(security_id)
        if security is None:
            raise UnknownEntity("unknown security", security_id=security_id)
        issuer = self.issuer(security["issuer_id"])
        return {
            "security": security,
            "issuer": issuer,
            "listings": self.listings(security_id),
            "tickers": self.ticker_assignments(security_id),
            "identifiers": self.identifiers(security_id),
            "relationships": self.relationships(security["issuer_id"]) if issuer else [],
            "current_ticker": self.current_ticker(security_id),
        }

    def issuer_profile(self, *, cik: str | int | None = None, issuer_id: str | None = None) -> dict[str, Any]:
        if issuer_id is None:
            if cik is None:
                raise ValidationError("either cik or issuer_id is required")
            issuer = self.require_issuer_by_cik(cik)
        else:
            issuer = self.issuer(issuer_id)
            if issuer is None:
                raise UnknownEntity("unknown issuer", issuer_id=issuer_id)
        securities = []
        for security in self.securities_for_issuer(issuer["issuer_id"]):
            securities.append(
                {
                    "security": security,
                    "listings": self.listings(security["security_id"]),
                    "tickers": self.ticker_assignments(security["security_id"]),
                    "identifiers": self.identifiers(security["security_id"]),
                }
            )
        return {
            "issuer": issuer,
            "securities": securities,
            "relationships": self.relationships(issuer["issuer_id"]),
        }
