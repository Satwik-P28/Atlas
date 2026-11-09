"""Official FFIEC FR Y-9C consolidated holding-company evidence.

The FFIEC National Information Center publishes one quarterly caret-delimited archive
containing FR Y-9C, FR Y-9LP and FR Y-9SP rows. This adapter deliberately stores only
declared FR Y-9C fields for a declared top-tier RSSD. It never treats the archive as a
Call Report, never joins a bank subsidiary's values into the parent, and never invents a
publication date: the bulk archive carries the reporting period and the retrieval time,
but not the historical release timestamp or a vintage.

The archive is therefore usable as a current consolidated snapshot and as an audited
source observation. It is *not* claimed to be a point-in-time reconstruction. A caller
that needs a historical cutoff must supply a verified publication timestamp through
``ingest_archive(published_at=...)``; otherwise the observation is marked unavailable at
that cutoff.
"""

from __future__ import annotations

import csv
import hashlib
import io
import json
import re
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping
from xml.etree import ElementTree as ET

from ..core.temporal import iso, utcnow
from ..storage.db import Database

FR_Y9C_SCHEMA = "atlas.fr_y9c.evidence.v1"
SOURCE_ID = "ffiec-nic-bhcf"
SOURCE_URL = "https://www.ffiec.gov/npw/FinancialReport/FinancialDataDownload"
SOURCE_ARCHIVE_URL = "https://www.ffiec.gov/npw/FinancialReport/ReturnBHCFZipFiles?zipfilename={name}"
SOURCE_LICENCE = "public_domain"
DATA_RIGHTS = "public_domain_us_government"
FORM = "FR Y-9C"
PARSER_VERSION = "atlas.fr_y9c.bhcf.v1"

#: Selected MDRM items. Descriptions are checked against the FFIEC Financial Download
#: Dictionary, but are not substituted for the dictionary's own text in stored provenance.
#: Schedule labels come from the FR Y-9C form; no line number is claimed where it could not
#: be verified from the published form.
FIELD_SPECS: dict[str, dict[str, str]] = {
    "total_assets": {
        "code": "BHCK2170", "schedule": "Schedule HC",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "total_equity_capital": {
        "code": "BHCK3210", "schedule": "Schedule HC",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "goodwill": {
        "code": "BHCK3163", "schedule": "Schedule HC",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "perpetual_preferred_stock": {
        "code": "BHCK3283", "schedule": "Schedule HC",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "allowance_for_credit_losses": {
        "code": "BHCK3123", "schedule": "Schedule HI-B, Part II",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "net_income": {
        "code": "BHCK4340", "schedule": "Schedule HI",
        "unit": "USD_thousands", "period_type": "duration",
    },
    "cash_dividends_common": {
        "code": "BHCK4460", "schedule": "Schedule HI-A",
        "unit": "USD_thousands", "period_type": "duration",
    },
    "net_interest_income": {
        "code": "BHCK4074", "schedule": "Schedule HI",
        "unit": "USD_thousands", "period_type": "duration",
    },
    "net_charge_offs": {
        "code": "BHBC6061", "schedule": "Schedule HI-B, Memoranda",
        "unit": "USD_thousands", "period_type": "duration",
    },
    "regulatory_total_capital": {
        "code": "BHCA3792", "schedule": "Schedule HC-R",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "risk_weighted_assets": {
        "code": "BHCAA223", "schedule": "Schedule HC-R",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "tier_1_capital": {
        "code": "BHCA8274", "schedule": "Schedule HC-R",
        "unit": "USD_thousands", "period_type": "instant",
    },
    "tier_1_leverage_ratio": {
        "code": "BHCA7204", "schedule": "Schedule HC-R",
        "unit": "percent", "period_type": "instant",
    },
    "tier_1_risk_based_ratio": {
        "code": "BHCA7206", "schedule": "Schedule HC-R",
        "unit": "percent", "period_type": "instant",
    },
    "total_risk_based_ratio": {
        "code": "BHCA7205", "schedule": "Schedule HC-R",
        "unit": "percent", "period_type": "instant",
    },
    "common_equity_tier_1_ratio": {
        "code": "BHCAP793", "schedule": "Schedule HC-R",
        "unit": "percent", "period_type": "instant",
    },
    "common_equity_tier_1_before_adjustments": {
        "code": "BHCAP840", "schedule": "Schedule HC-R",
        "unit": "USD_thousands", "period_type": "instant",
    },
}

#: Public entity identity. The RSSD is the top-tier holding company identifier; the CIK is
#: the SEC registrant relationship. They are checked against the archive's legal-name field.
HOLDING_COMPANIES: dict[str, dict[str, str]] = {
    "19617": {
        "entity_id": "REG-JPM-PARENT",
        "rssd": "1039502",
        "cik": "19617",
        "legal_name": "JPMorgan Chase & Co.",
    },
}

_REQUIRED_COLUMNS = ("RSSD9001", "RSSD9999", "RSSD9017")


class FrY9CError(ValueError):
    """The supplied archive or selected entity cannot be accepted as FR Y-9C evidence."""


def _text(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _parse_number(value: str) -> tuple[float | None, str | None]:
    """Parse an original numeric string without turning blank into zero."""
    text = value.strip()
    if text == "":
        return None, ""
    if not re.fullmatch(r"[-+]?(?:\d+(?:\.\d*)?|\.\d+)", text):
        return None, text
    try:
        return float(text), text
    except ValueError:
        return None, text


# Official BHCF quarterly archives are tens of megabytes; the dictionary workbook is small.
# Both ceilings exist so a hostile or corrupt archive cannot inflate without limit.
_MAX_QUARTER_ARCHIVE_BYTES = 512 * 1024 * 1024
_MAX_DICTIONARY_MEMBER_BYTES = 64 * 1024 * 1024


def _member_bytes(archive: zipfile.ZipFile, name: str, *, limit: int) -> bytes:
    """Read one archive member with a bound on its expanded size."""
    info = archive.getinfo(name)
    if int(info.file_size) > limit:
        raise FrY9CError(f"archive member {name} exceeds the size limit")
    with archive.open(name) as handle:
        data = handle.read(limit + 1)
    if len(data) > limit:
        raise FrY9CError(f"archive member {name} exceeds the size limit")
    return data


def _dictionary_rows(path: str | Path) -> dict[str, dict[str, str]]:
    """Read the FFIEC Financial Download Dictionary without a spreadsheet dependency."""
    with zipfile.ZipFile(path) as archive:
        names = set(archive.namelist())
        shared: list[str] = []
        if "xl/sharedStrings.xml" in names:
            root = ET.fromstring(_member_bytes(archive, "xl/sharedStrings.xml",
                                              limit=_MAX_DICTIONARY_MEMBER_BYTES))
            ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
            for item in root.findall(f"{ns}si"):
                shared.append("".join(node.text or "" for node in item.iter(f"{ns}t")))
        workbook = ET.fromstring(_member_bytes(archive, "xl/workbook.xml",
                                               limit=_MAX_DICTIONARY_MEMBER_BYTES))
        rels = ET.fromstring(_member_bytes(archive, "xl/_rels/workbook.xml.rels",
                                           limit=_MAX_DICTIONARY_MEMBER_BYTES))
        targets = {rel.get("Id"): rel.get("Target") for rel in rels}
        sheets = list(workbook.find("{http://schemas.openxmlformats.org/spreadsheetml/2006/main}sheets"))
        if not sheets:
            raise FrY9CError("financial dictionary has no worksheets")
        sheet = sheets[0]
        relationship = sheet.get(
            "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
        )
        target = targets.get(relationship)
        if not target:
            raise FrY9CError("financial dictionary worksheet relationship is missing")
        target = target.lstrip("/")
        if not target.startswith("xl/"):
            target = "xl/" + target
        root = ET.fromstring(_member_bytes(archive, target, limit=_MAX_DICTIONARY_MEMBER_BYTES))
        ns = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
        parsed: list[dict[str, str]] = []
        for row in root.iter(f"{ns}row"):
            cells: dict[str, str] = {}
            for cell in row.findall(f"{ns}c"):
                ref = cell.get("r") or ""
                column = "".join(character for character in ref if character.isalpha())
                value_node = cell.find(f"{ns}v")
                value = "" if value_node is None else (value_node.text or "")
                if cell.get("t") == "s" and value:
                    value = shared[int(value)]
                elif cell.get("t") == "inlineStr":
                    value = "".join(
                        node.text or "" for node in cell.iter(f"{ns}t")
                    )
                cells[column] = value
            if cells:
                parsed.append(cells)
    result: dict[str, dict[str, str]] = {}
    for row in parsed[1:]:
        code = _text(row.get("A")).upper()
        if not code:
            continue
        result[code] = {
            "code": code,
            "description": _text(row.get("D")),
            "start_date": _text(row.get("B")),
            "end_date": _text(row.get("C")),
        }
    if not result:
        raise FrY9CError("financial dictionary contains no MDRM definitions")
    return result


def _normalise_name(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _check_identity(row: Mapping[str, str], expected: Mapping[str, str]) -> list[dict[str, Any]]:
    legal_name = _text(row.get("RSSD9017"))
    checks = [
        {
            "name": "top-tier RSSD matches the declared holding company",
            "expected": expected["rssd"],
            "actual": _text(row.get("RSSD9001")),
            "passed": _text(row.get("RSSD9001")) == expected["rssd"],
        },
        {
            "name": "archive legal name matches the SEC registrant",
            "expected": expected["legal_name"],
            "actual": legal_name,
            "passed": _normalise_name(legal_name) == _normalise_name(expected["legal_name"]),
        },
        {
            "name": "FR Y-9C reporting period is present",
            "expected": "YYYYMMDD",
            "actual": _text(row.get("RSSD9999")),
            "passed": bool(re.fullmatch(r"\d{8}", _text(row.get("RSSD9999")))),
        },
    ]
    return checks


def read_archive(
    archive_path: str | Path,
    *,
    dictionary_path: str | Path,
    rssd: str,
    expected_legal_name: str,
) -> dict[str, Any]:
    """Parse one official BHCF ZIP and return the selected row plus archive identity.

    No value is repaired or defaulted. Blank cells remain ``None`` with their original
    empty text, and every selected field must have a dictionary definition.
    """
    archive_path = Path(archive_path)
    payload = archive_path.read_bytes()
    archive_sha256 = hashlib.sha256(payload).hexdigest()
    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        members = [name for name in archive.namelist() if name.lower().endswith(".txt")]
        if len(members) != 1:
            raise FrY9CError(
                f"expected exactly one quarterly TXT member in the archive, found {len(members)}"
            )
        member = members[0]
        data = _member_bytes(archive, member, limit=_MAX_QUARTER_ARCHIVE_BYTES)
    text_sha256 = hashlib.sha256(data).hexdigest()
    try:
        decoded = data.decode("latin-1")
    except UnicodeDecodeError as exc:  # pragma: no cover - latin-1 is total
        raise FrY9CError(f"archive {member} is not readable text") from exc
    reader = csv.reader(io.StringIO(decoded, newline=""), delimiter="^")
    try:
        header = [item.strip() for item in next(reader)]
    except StopIteration as exc:
        raise FrY9CError("archive has no header row") from exc
    header_index = {name: index for index, name in enumerate(header)}
    missing_columns = [name for name in _REQUIRED_COLUMNS if name not in header_index]
    if missing_columns:
        raise FrY9CError("archive is missing required columns: " + ", ".join(missing_columns))
    definitions = _dictionary_rows(dictionary_path)
    for spec in FIELD_SPECS.values():
        if spec["code"] not in definitions:
            raise FrY9CError(f"dictionary has no definition for {spec['code']}")
    selected: dict[str, str] | None = None
    row_count = 0
    for row in reader:
        if not row:
            continue
        row_count += 1
        if len(row) <= header_index["RSSD9001"]:
            continue
        if selected is None and _text(row[header_index["RSSD9001"]]) == str(rssd):
            selected = dict(zip(header, row))
    if selected is None:
        raise FrY9CError(f"RSSD {rssd} is not present in {archive_path.name}")
    period = _text(selected.get("RSSD9999"))
    if not re.fullmatch(r"\d{8}", period):
        raise FrY9CError(f"invalid reporting date {period!r}")
    expected = {"rssd": str(rssd), "legal_name": expected_legal_name, "cik": ""}
    identity_checks = _check_identity(selected, expected)
    if not all(check["passed"] for check in identity_checks):
        failed = [check for check in identity_checks if not check["passed"]]
        raise FrY9CError("archive identity checks failed: " + json.dumps(failed, sort_keys=True))
    values: dict[str, dict[str, Any]] = {}
    for concept, spec in FIELD_SPECS.items():
        raw = _text(selected.get(spec["code"]))
        numeric, original = _parse_number(raw)
        values[concept] = {
            **spec,
            "value": numeric,
            "raw_value": raw,
            "status": "available" if numeric is not None else "missing",
            "definition": definitions[spec["code"]]["description"],
        }
    return {
        "schema": FR_Y9C_SCHEMA,
        "archive": {
            "name": archive_path.name,
            "sha256": archive_sha256,
            "text_member": member,
            "text_sha256": text_sha256,
            "bytes": len(payload),
            "rows_in_archive": row_count,
            "source_url": SOURCE_ARCHIVE_URL.format(name=archive_path.name),
            "dictionary": {
                "name": Path(dictionary_path).name,
                "sha256": hashlib.sha256(Path(dictionary_path).read_bytes()).hexdigest(),
            },
        },
        "rssd": str(rssd),
        "cik": "",
        "legal_name": _text(selected.get("RSSD9017")),
        "period_end": f"{period[:4]}-{period[4:6]}-{period[6:8]}",
        "reporting_date": period,
        "identity_checks": identity_checks,
        "values": values,
        "row": selected,
    }


def _derived(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    def value(key: str) -> float | None:
        item = values.get(key) or {}
        raw = item.get("value")
        return float(raw) if raw is not None else None

    equity = value("total_equity_capital")
    preferred = value("perpetual_preferred_stock")
    goodwill = value("goodwill")
    common = (
        equity - preferred
        if equity is not None and preferred is not None else None
    )
    # The bulk dictionary does not supply the other-intangibles code used by this
    # reporting population. Missing intangibles must therefore make TCE unavailable,
    # not equal to common equity.
    tangible = None
    return {
        "common_equity": {
            "value": common,
            "unit": "USD_thousands",
            "formula": "BHCK3210 - BHCK3283",
            "components": ["BHCK3210", "BHCK3283"],
            "status": "available" if common is not None else "not_available",
            "basis": "derived_from_consolidated_reported_fields",
        },
        "tangible_common_equity": {
            "value": tangible,
            "unit": "USD_thousands",
            "formula": "common equity - goodwill - other intangible assets",
            "components": ["BHCK3210", "BHCK3283", "BHCK3163"],
            "status": "not_available",
            "reason": (
                "Other intangible assets are not mapped in the selected FR Y-9C fields; "
                "goodwill is not used as a proxy for all intangibles."
            ),
        },
        "goodwill": {
            "value": goodwill,
            "unit": "USD_thousands",
            "status": "available" if goodwill is not None else "not_available",
        },
    }


def _upsert_source(db: Database, now: str) -> None:
    db.execute(
        "INSERT INTO source (source_id,name,kind,homepage,licence,redistribution,notes,created_at) "
        "VALUES (?,?,?,?,?,?,?,?) ON CONFLICT(source_id) DO UPDATE SET "
        "name=excluded.name, licence=excluded.licence, redistribution=excluded.redistribution, "
        "notes=excluded.notes",
        (
            SOURCE_ID,
            "FFIEC National Information Center - Holding Company Financial Data",
            "regulatory",
            SOURCE_URL,
            SOURCE_LICENCE,
            "public_domain",
            "FR Y-9C consolidated holding-company data; bulk quarterly BHCF archives. "
            "Archive rows are not point-in-time vintages and carry no release timestamp.",
            now,
        ),
    )


def ingest_archive(
    db: Database,
    archive_path: str | Path,
    dictionary_path: str | Path,
    *,
    cik: str,
    entity_id: str,
    rssd: str | None = None,
    published_at: str | None = None,
    publication_basis: str | None = None,
    retrieved_at: str | None = None,
) -> dict[str, Any]:
    """Idempotently ingest one top-tier FR Y-9C row and its exact archive bytes.

    ``published_at`` is intentionally optional and must be supplied only with evidence.
    The retriever does not infer it from the quarter end or the 45-day filing deadline.
    """
    from . import regulatory  # local import avoids a module cycle

    expected = HOLDING_COMPANIES.get(str(cik).lstrip("0"))
    if expected is None:
        raise FrY9CError(f"no declared FR Y-9C holding company for CIK {cik!r}")
    if rssd is not None and str(rssd) != expected["rssd"]:
        raise FrY9CError(
            f"RSSD {rssd} does not match the declared top-tier RSSD {expected['rssd']} for CIK {cik}"
        )
    regulatory.seed_entities(db)
    resolved_entity = db.query_one("SELECT * FROM regulatory_entity WHERE entity_id=?", (entity_id,))
    if resolved_entity is None:
        raise FrY9CError(f"regulatory entity {entity_id!r} is not declared")
    if str(resolved_entity["cik"]).lstrip("0") != str(cik).lstrip("0"):
        raise FrY9CError("entity CIK does not match the requested SEC registrant")
    if resolved_entity["consolidation_basis"] != regulatory.PARENT:
        raise FrY9CError("FR Y-9C must be attached to the consolidated parent, not a subsidiary")
    parsed = read_archive(
        archive_path,
        dictionary_path=dictionary_path,
        rssd=expected["rssd"],
        expected_legal_name=expected["legal_name"],
    )
    retrieved = retrieved_at or iso(utcnow())
    # Reject future retrieval clocks and impossible dates; do not silently repair them.
    retrieved_dt = _parse_iso(retrieved)
    if retrieved_dt > datetime.now(timezone.utc) + __import__("datetime").timedelta(minutes=5):
        raise FrY9CError("retrieved_at is in the future")
    if published_at is not None:
        published_dt = _parse_iso(published_at)
        if published_dt > retrieved_dt:
            raise FrY9CError("published_at cannot be later than retrieved_at")
        if published_dt.date().isoformat() < parsed["period_end"]:
            raise FrY9CError("published_at cannot precede the reporting period end")
    now = iso(utcnow())
    archive = parsed["archive"]
    archive_id = f"FFIEC-{archive['sha256'][:20]}"
    _upsert_source(db, now)
    db.execute(
        "INSERT INTO source_archive (archive_id,source_id,resource_id,sha256,content,media_type,"
        "retrieved_at,published_at,rights,retention_policy,schema_version,parser_version,created_at) "
        "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(archive_id) DO NOTHING",
        (
            archive_id, SOURCE_ID, archive["name"], archive["sha256"],
            Path(archive_path).read_bytes(), "application/zip", retrieved, published_at,
            DATA_RIGHTS, "retain_exact_source_bytes", FR_Y9C_SCHEMA, PARSER_VERSION, now,
        ),
    )
    db.execute(
        "UPDATE regulatory_entity SET rssd=?, notes=COALESCE(notes,'') || ? WHERE entity_id=?",
        (
            int(expected["rssd"]),
            " Top-tier FR Y-9C RSSD verified; consolidated capital is separate from the bank subsidiary.",
            entity_id,
        ),
    )
    written = 0
    missing: list[str] = []
    for concept, spec in FIELD_SPECS.items():
        item = parsed["values"][concept]
        if item["value"] is None:
            missing.append(concept)
        observation_id = f"FRY9C-{expected['rssd']}-{spec['code']}-{parsed['period_end']}-0"
        provenance = {
            "schema": FR_Y9C_SCHEMA,
            "archive": archive,
            "dictionary_definition": item["definition"],
            "schedule": spec["schedule"],
            "rssd": expected["rssd"],
            "cik": str(cik),
            "legal_name": parsed["legal_name"],
            "consolidation_basis": regulatory.PARENT,
            "reporting_form": FORM,
            "publication_timestamp_available": published_at is not None,
            "publication_basis": publication_basis
            or "bulk_archive_has_no_historical_publication_or_vintage_timestamp",
            "limitations": [
                "The quarterly BHCF archive is refreshed and does not preserve historical vintages.",
                "No release timestamp is present in the archive; retrieval time is not publication time.",
                "FR Y-9C consolidated values are not FDIC Call Report subsidiary values and are not additive.",
            ],
        }
        db.execute(
            "INSERT INTO fr_y9c_observation (observation_id,entity_id,rssd,cik,legal_name,form,"
            "schedule,field_code,concept,field_name,value_numeric,value_text,unit,period_end,"
            "reporting_date,published_at,availability_precision,availability_basis,retrieved_at,"
            "archive_id,archive_sha256,archive_name,source_id,source_url,revision,revision_status,"
            "data_rights,provenance_json,created_at) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(observation_id) DO UPDATE SET value_numeric=excluded.value_numeric,"
            "value_text=excluded.value_text,published_at=excluded.published_at,"
            "availability_precision=excluded.availability_precision,"
            "availability_basis=excluded.availability_basis,retrieved_at=excluded.retrieved_at,"
            "provenance_json=excluded.provenance_json",
            (
                observation_id, entity_id, expected["rssd"], str(cik), parsed["legal_name"],
                FORM, spec["schedule"], spec["code"], concept, item["definition"],
                item["value"], item["raw_value"], spec["unit"], parsed["period_end"],
                parsed["reporting_date"], published_at,
                "exact" if published_at else "unknown",
                publication_basis
                or "bulk_archive_has_no_historical_publication_or_vintage_timestamp",
                retrieved, archive_id, archive["sha256"], archive["name"], SOURCE_ID,
                archive["source_url"], 0,
                "current_archive_refresh" if published_at is None else "reported",
                DATA_RIGHTS, json.dumps(provenance, sort_keys=True), now,
            ),
        )
        written += 1
    return {
        "schema": "atlas.fr_y9c.ingest.v1",
        "entity_id": entity_id,
        "rssd": expected["rssd"],
        "cik": str(cik),
        "legal_name": parsed["legal_name"],
        "period_end": parsed["period_end"],
        "archive": archive,
        "identity_checks": parsed["identity_checks"],
        "observations_written": written,
        "missing_fields": missing,
        "derived": _derived(parsed["values"]),
        "published_at": published_at,
        "availability_precision": "exact" if published_at else "unknown",
        "point_in_time_eligible": published_at is not None,
        "data_rights": DATA_RIGHTS,
    }


def _parse_iso(value: str) -> datetime:
    text = str(value).strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise FrY9CError(f"invalid timestamp {value!r}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def holding_company_evidence(
    db: Database, *, cik: Any, cutoff: str | None = None, periods: int = 6
) -> dict[str, Any]:
    """Return consolidated FR Y-9C evidence with its publication-time limitation."""
    from . import regulatory

    mapping = regulatory.entity_map(db, cik)
    parent = mapping.get("parent")
    if not parent:
        return {"status": "not_declared", "cik": cik, "periods": [], "latest": None}
    rows = db.query(
        "SELECT DISTINCT period_end FROM fr_y9c_observation WHERE entity_id=? "
        "ORDER BY period_end DESC LIMIT ?",
        (parent["entity_id"], periods),
    )
    available = [row["period_end"] for row in rows]
    if not available:
        return {
            "status": "not_ingested",
            "cik": cik,
            "parent": parent,
            "periods": [],
            "latest": None,
            "historical_use": "blocked_no_fr_y9c_observation",
        }
    blocks: list[dict[str, Any]] = []
    cutoff_day = str(cutoff or "")[:10]
    for period_end in available:
        observations = db.query(
            "SELECT * FROM fr_y9c_observation WHERE entity_id=? AND period_end=? "
            "ORDER BY field_code",
            (parent["entity_id"], period_end),
        )
        values = {
            row["concept"]: {
                "observation_id": row["observation_id"],
                "value": row["value_numeric"],
                "raw_value": row["value_text"],
                "unit": row["unit"],
                "status": "available" if row["value_numeric"] is not None else "missing",
                "definition": row["field_name"],
                "schedule": row["schedule"],
                "field_code": row["field_code"],
                "published_at": row["published_at"],
                "retrieved_at": row["retrieved_at"],
                "archive_sha256": row["archive_sha256"],
                "archive_name": row["archive_name"],
                "revision_status": row["revision_status"],
                "data_rights": row["data_rights"],
            }
            for row in observations
        }
        published = [row["published_at"] for row in observations if row["published_at"]]
        retrieved = [row["retrieved_at"] for row in observations]
        included = bool(
            cutoff_day
            and published
            and all(str(item)[:10] <= cutoff_day for item in published)
        ) if cutoff_day else None
        blocks.append(
            {
                "period_end": period_end,
                "values": values,
                "derived": _derived(values),
                "publication": {
                    "published_at": min(published) if published else None,
                    "retrieved_at": max(retrieved) if retrieved else None,
                    "availability_precision": "exact" if published else "unknown",
                    "publication_timestamp_available": bool(published),
                    "included_at_cutoff": included,
                },
                "historical_use": (
                    "eligible" if published else "blocked_publication_timestamp_missing"
                ),
            }
        )
    latest = blocks[0]
    return {
        "schema": FR_Y9C_SCHEMA,
        "status": "available",
        "cik": cik,
        "parent": parent,
        "basis": regulatory.PARENT,
        "form": FORM,
        "periods": available,
        "latest": latest,
        "history": blocks,
        "archive": {
            "name": next(iter(latest["values"].values()), {}).get("archive_name"),
            "sha256": next(iter(latest["values"].values()), {}).get("archive_sha256"),
            "source_url": SOURCE_URL,
        },
        "historical_use": latest["historical_use"],
        "point_in_time_claim": (
            "verified_publication_time" if latest["publication"]["published_at"]
            else "prohibited_publication_timestamp_missing"
        ),
        "limitations": [
            "FR Y-9C describes the consolidated top-tier holding company; it is not a Call Report.",
            "The bulk BHCF archive does not preserve vintages or release timestamps. Atlas does not "
            "assume quarter-end equals publication time.",
            "Consolidated regulatory capital is not GAAP capital and is never substituted by the "
            "insured subsidiary's ratios.",
        ],
    }
