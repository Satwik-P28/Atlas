"""Regulatory evidence for bank and insurer research.

SEC consolidated accounts and regulatory reports describe different legal entities.
JPMorgan Chase & Co. files a 10-K for the consolidated holding company; JPMorgan Chase
Bank, N.A. files Call Reports as a subsidiary. Adding the two would double-count assets.
This module keeps the entity, form and consolidation basis on every observation and
refuses to combine incompatible bases silently.

FDIC BankFind data is public domain. Values are stored in the units the regulator
publishes (USD thousands, or percent for ratios); no unit conversion is hidden.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Iterable, Mapping

from ..core.temporal import iso, utcnow
from ..storage.db import Database

REGULATORY_SCHEMA = "atlas.regulatory.evidence.v1"
REGULATORY_MAP_SCHEMA = "atlas.regulatory.entity_map.v1"
FDIC_SOURCE_ID = "fdic-bankfind"
FDIC_DATASET = "banks/financials"
FDIC_URL = "https://api.fdic.gov/banks/financials"
FDIC_LICENCE = "public_domain"
FDIC_REDISTRIBUTION = "public_domain"
CALL_REPORT_FORM = "FFIEC 031/041 Call Report (FDIC BankFind)"

PARENT = "parent_consolidated"
SUBSIDIARY = "subsidiary_standalone"


class RegulatoryReconciliationError(ValueError):
    """Two regulatory facts cannot be combined under their declared basis."""


#: Field definitions are the FDIC's published meanings, shortened but not reinterpreted.
FIELDS: dict[str, tuple[str, str]] = {
    "ASSET": ("Total assets", "USD_thousands"),
    "EQ": ("Total equity capital", "USD_thousands"),
    "EQTOT": ("Total equity capital including minority interest", "USD_thousands"),
    "INTAN": ("Goodwill and other intangible assets", "USD_thousands"),
    "NETINC": ("Net income attributable to the bank", "USD_thousands"),
    "NIM": ("Net interest income", "USD_thousands"),
    "NIMY": ("Net interest margin, annualized", "percent"),
    "INTINC": ("Total interest income", "USD_thousands"),
    "INTEXP": ("Total interest expense", "USD_thousands"),
    "NTLNLS": ("Net charge-offs", "USD_thousands"),
    "NTLNLSR": ("Net charge-off rate, annualized", "percent"),
    "ELNATR": ("Allowance for loan and lease losses", "USD_thousands"),
    "ELNATRY": ("Allowance to loans and leases", "percent"),
    "LNLSNET": ("Net loans and leases", "USD_thousands"),
    "LNLSNTV": ("Net loans and leases to assets", "percent"),
    "LNLSDEPR": ("Net loans and leases to deposits", "percent"),
    "DEP": ("Total deposits", "USD_thousands"),
    "COREDEP": ("Core deposits", "USD_thousands"),
    "DEPUNINS": ("Estimated uninsured deposits", "USD_thousands"),
    "DEPINS": ("Estimated insured deposits", "USD_thousands"),
    "FREPO": ("Federal funds purchased and repos", "USD_thousands"),
    "RBC1AAJ": ("Tier 1 leverage ratio", "percent"),
    "RBCRWAJ": ("Total risk-based capital ratio", "percent"),
    "IDT1CER": ("Common equity tier 1 ratio", "percent"),
    "IDT1RWAJR": ("Common equity tier 1 ratio, advanced approaches", "percent"),
    "EQCDIV": ("Cash dividends on common stock", "USD_thousands"),
    "EQCDIVNTINC": ("Dividends as a percent of net income", "percent"),
    "ROE": ("Return on equity, annualized", "percent"),
    "ROA": ("Return on assets, annualized", "percent"),
    "EQV": ("Equity capital to assets", "percent"),
    "BKPREM": ("Bank premises and fixed assets", "USD_thousands"),
    "NAASSET": ("Nonaccrual assets", "USD_thousands"),
    "P3ASSET": ("Assets past due 30-89 days", "USD_thousands"),
    "P9ASSET": ("Assets past due 90+ days", "USD_thousands"),
}

#: Parent/subsidiary chart. The parent is an SEC registrant; the bank is an FDIC-insured
#: subsidiary. ``parent_entity_id`` is a link, never an aggregation instruction.
ENTITIES: tuple[dict[str, Any], ...] = (
    {
        "entity_id": "REG-JPM-PARENT",
        "kind": "parent_holding_company",
        "legal_name": "JPMorgan Chase & Co.",
        "cik": "19617",
        "parent_entity_id": None,
        "consolidation_basis": PARENT,
        "regulator": "SEC",
        "notes": "Consolidated 10-K registrant. SEC facts only in this build.",
    },
    {
        "entity_id": "REG-JPM-BANK",
        "kind": "bank_subsidiary",
        "legal_name": "JPMorgan Chase Bank, N.A.",
        "cert": 628,
        "rssd": 852218,
        "cik": "19617",
        "parent_entity_id": "REG-JPM-PARENT",
        "consolidation_basis": SUBSIDIARY,
        "regulator": "OCC / FDIC",
        "notes": "Largest insured depository subsidiary; standalone Call Reports.",
    },
    {
        "entity_id": "REG-GS-PARENT",
        "kind": "parent_holding_company",
        "legal_name": "The Goldman Sachs Group, Inc.",
        "cik": "886982",
        "parent_entity_id": None,
        "consolidation_basis": PARENT,
        "regulator": "SEC",
        "notes": "Consolidated 10-K registrant. SEC facts only in this build.",
    },
    {
        "entity_id": "REG-GS-BANK",
        "kind": "bank_subsidiary",
        "legal_name": "Goldman Sachs Bank USA",
        "cert": 33124,
        "rssd": 33124,
        "cik": "886982",
        "parent_entity_id": "REG-GS-PARENT",
        "consolidation_basis": SUBSIDIARY,
        "regulator": "Federal Reserve / FDIC",
        "notes": "Insured depository subsidiary; standalone Call Reports.",
    },
    {
        "entity_id": "REG-UNH-PARENT",
        "kind": "insurer_parent",
        "legal_name": "UnitedHealth Group Incorporated",
        "cik": "731766",
        "parent_entity_id": None,
        "consolidation_basis": PARENT,
        "regulator": "SEC",
        "notes": (
            "Consolidated registrant mixing UnitedHealthcare insurance with Optum services. "
            "No CMS plan-level dataset is joined in this build."
        ),
    },
)


def seed_entities(db: Database) -> list[dict[str, Any]]:
    """Insert the declared parent/subsidiary chart idempotently."""
    now = iso(utcnow())
    source = db.query_one("SELECT source_id FROM source WHERE source_id=?", (FDIC_SOURCE_ID,))
    if source is None:
        db.execute(
            "INSERT INTO source (source_id, name, kind, homepage, licence, redistribution, notes, created_at) "
            "VALUES (?,?,?,?,?,?,?,?)",
            (
                FDIC_SOURCE_ID,
                "FDIC BankFind Suite",
                "regulatory",
                "https://banks.data.fdic.gov/",
                FDIC_LICENCE,
                FDIC_REDISTRIBUTION,
                "Call Report financials published by the FDIC; public-domain U.S. government data.",
                now,
            ),
        )
    for item in ENTITIES:
        db.execute(
            "INSERT INTO regulatory_entity (entity_id, kind, legal_name, cert, rssd, cik, "
            "parent_entity_id, consolidation_basis, regulator, source_id, licence, redistribution, "
            "notes, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(entity_id) DO UPDATE SET legal_name=excluded.legal_name, cert=excluded.cert, "
            "rssd=excluded.rssd, cik=excluded.cik, parent_entity_id=excluded.parent_entity_id, "
            "consolidation_basis=excluded.consolidation_basis, notes=excluded.notes",
            (
                item["entity_id"], item["kind"], item["legal_name"], item.get("cert"),
                item.get("rssd"), item.get("cik"), item.get("parent_entity_id"),
                item["consolidation_basis"], item.get("regulator"), FDIC_SOURCE_ID,
                FDIC_LICENCE, FDIC_REDISTRIBUTION, item.get("notes"), now,
            ),
        )
    return [dict(row) for row in db.query("SELECT * FROM regulatory_entity ORDER BY entity_id")]


def entity_map(db: Database, cik: Any) -> dict[str, Any]:
    """Return the declared legal-entity map for an SEC CIK."""
    text = str(cik or "").strip().lstrip("0")
    rows = [dict(row) for row in db.query(
        "SELECT * FROM regulatory_entity WHERE ltrim(cik,'0')=? ORDER BY kind, legal_name", (text,)
    )]
    parent = next((row for row in rows if row["consolidation_basis"] == PARENT), None)
    subsidiaries = [row for row in rows if row["consolidation_basis"] == SUBSIDIARY]
    return {
        "schema": REGULATORY_MAP_SCHEMA,
        "cik": cik,
        "parent": parent,
        "subsidiaries": subsidiaries,
        "entities": rows,
        "mapped": bool(rows),
        "aggregation_policy": (
            "Parent consolidated accounts and subsidiary standalone reports are separate "
            "reporting bases. Atlas never adds them, and a subsidiary figure is never divided "
            "by the parent's share count."
        ),
    }


def _period(value: Any) -> str:
    text = str(value).strip()
    return f"{text[:4]}-{text[4:6]}-{text[6:8]}" if len(text) == 8 else text


def ingest_fdic_payload(
    db: Database,
    payload: Mapping[str, Any],
    *,
    entity_id: str | None = None,
    source_url: str | None = None,
) -> dict[str, Any]:
    """Store one FDIC fixture payload as typed regulatory observations.

    The payload wrapper carries retrieval metadata and the rights terms. Each row is one
    reporting period. Fields not in :data:`FIELDS` are ignored rather than guessed at.
    """
    seed_entities(db)
    cert = int(payload["cert"])
    entity = db.query_one("SELECT * FROM regulatory_entity WHERE cert=?", (cert,))
    if entity is None:
        raise RegulatoryReconciliationError(f"no declared regulatory entity for FDIC certificate {cert}")
    resolved_id = entity_id or entity["entity_id"]
    retrieved = str(payload.get("retrieved_at") or iso(utcnow()))
    url = source_url or str(payload.get("url") or FDIC_URL)
    written = 0
    skipped: list[str] = []
    for row in payload.get("rows") or []:
        period = _period(row.get("REPDTE"))
        for field, (definition, unit) in FIELDS.items():
            if field not in row:
                continue
            raw = row.get(field)
            if raw is None:
                skipped.append(f"{field}@{period}")
                continue
            observation_id = f"REG-{resolved_id}-{field}-{period}"
            provenance = {
                "source": payload.get("source", "FDIC BankFind Suite"),
                "dataset": FDIC_DATASET,
                "url": url,
                "cert": cert,
                "retrieved_at": retrieved,
                "definition": definition,
                "unit": unit,
                "reporting_form": CALL_REPORT_FORM,
                "consolidation_basis": entity["consolidation_basis"],
                "legal_entity": entity["legal_name"],
                "limitations": [
                    "Call Report values describe the insured depository subsidiary, not the parent.",
                    "Retrieval time is when Atlas fetched the record; FDIC revision history is not archived.",
                ],
            }
            db.execute(
                "INSERT INTO regulatory_observation (observation_id, entity_id, form, dataset, field, "
                "value, text_value, unit, period_end, period_type, published_at, retrieved_at, "
                "definition, source_id, source_url, revision, provenance_json) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(observation_id) DO UPDATE SET value=excluded.value, "
                "retrieved_at=excluded.retrieved_at, provenance_json=excluded.provenance_json",
                (
                    observation_id, resolved_id, CALL_REPORT_FORM, FDIC_DATASET, field,
                    float(raw) if isinstance(raw, (int, float)) else None,
                    None if isinstance(raw, (int, float)) else str(raw),
                    unit, period, "instant" if field in {"ASSET", "EQ", "EQTOT", "INTAN", "ELNATR",
                                                           "LNLSNET", "DEP", "COREDEP", "DEPUNINS",
                                                           "DEPINS", "FREPO", "BKPREM", "NAASSET",
                                                           "P3ASSET", "P9ASSET"} else "duration",
                    None, retrieved, definition, FDIC_SOURCE_ID, url, 0,
                    __import__("json").dumps(provenance, sort_keys=True),
                ),
            )
            written += 1
    return {
        "schema": "atlas.regulatory.ingest.v1",
        "entity_id": resolved_id,
        "cert": cert,
        "periods": sorted({_period(row.get("REPDTE")) for row in payload.get("rows") or []}),
        "observations_written": written,
        "fields_skipped": sorted(set(skipped)),
        "retrieved_at": retrieved,
        "source": {"source_id": FDIC_SOURCE_ID, "licence": FDIC_LICENCE,
                   "redistribution": FDIC_REDISTRIBUTION},
    }


def reconcile_entities(db: Database, cik: Any) -> dict[str, Any]:
    """Validate the parent/subsidiary chart and record the reconciliation checks."""
    mapping = entity_map(db, cik)
    checks: list[dict[str, Any]] = []
    parent = mapping.get("parent")
    for subsidiary in mapping.get("subsidiaries", []):
        same_cik = str(subsidiary.get("cik") or "").lstrip("0") == str(cik or "").lstrip("0")
        linked = subsidiary.get("parent_entity_id") == (parent or {}).get("entity_id")
        basis_distinct = subsidiary.get("consolidation_basis") != (parent or {}).get("consolidation_basis")
        checks.extend([
            {"name": "subsidiary CIK matches parent registrant", "entity": subsidiary["entity_id"], "passed": same_cik},
            {"name": "subsidiary is linked to the declared parent", "entity": subsidiary["entity_id"], "passed": linked},
            {"name": "consolidation bases are distinct", "entity": subsidiary["entity_id"], "passed": basis_distinct},
        ])
        db.execute(
            "INSERT INTO entity_reconciliation (reconciliation_id, cik, parent_entity_id, subsidiary_id, "
            "status, basis, checked_at, detail) VALUES (?,?,?,?,?,?,?,?) "
            "ON CONFLICT(reconciliation_id) DO UPDATE SET status=excluded.status, checked_at=excluded.checked_at",
            (
                f"REC-{subsidiary['entity_id']}", str(cik), (parent or {}).get("entity_id"),
                subsidiary["entity_id"], "verified" if all(c["passed"] for c in checks) else "ambiguous",
                SUBSIDIARY, iso(utcnow()),
                "Parent is an SEC consolidated registrant; subsidiary is an FDIC-insured bank. Not additive.",
            ),
        )
    return {
        **mapping,
        "checks": checks,
        "status": "verified" if checks and all(check["passed"] for check in checks) else "unmapped",
    }


def assert_comparable(observations: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """Reject a cross-entity aggregate whose basis or period does not match."""
    rows = list(observations)
    if not rows:
        raise RegulatoryReconciliationError("no regulatory observations to compare")
    bases = {row.get("consolidation_basis") or row.get("basis") for row in rows}
    periods = {row.get("period_end") for row in rows}
    entities = {row.get("entity_id") for row in rows}
    if len(bases) > 1:
        raise RegulatoryReconciliationError(
            "parent consolidated and subsidiary standalone observations cannot be combined"
        )
    if len(periods) > 1:
        raise RegulatoryReconciliationError(
            "observations from different reporting periods cannot be combined without alignment"
        )
    return {
        "comparable": True,
        "basis": next(iter(bases)),
        "period_end": next(iter(periods)),
        "entities": sorted(entity for entity in entities if entity),
    }


def _period_observations(db: Database, entity_id: str, period: str) -> dict[str, dict[str, Any]]:
    rows = db.query(
        "SELECT * FROM regulatory_observation WHERE entity_id=? AND period_end=?",
        (entity_id, period),
    )
    return {
        row["field"]: {
            "observation_id": row["observation_id"],
            "value": row["value"],
            "unit": row["unit"],
            "definition": row["definition"],
            "source_url": row["source_url"],
            "form": row["form"],
        }
        for row in rows
    }


def derived_metrics(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    """Compute only identities the reported fields actually support."""
    def value(key: str) -> float | None:
        item = values.get(key)
        return None if item is None else item.get("value")

    def ratio(name: str, numerator: float | None, denominator: float | None, unit: str,
              formula: str, components: list[str]) -> dict[str, Any]:
        result = (numerator / denominator) if numerator is not None and denominator else None
        return {
            "name": name, "value": result, "unit": unit, "formula": formula,
            "components": components,
            "status": "available" if result is not None else "not_available",
        }

    equity = value("EQ")
    intangibles = value("INTAN")
    assets = value("ASSET")
    loans = value("LNLSNET")
    allowance = value("ELNATR")
    net_income = value("NETINC")
    dividends = value("EQCDIV")
    tangible = (equity - intangibles) if equity is not None and intangibles is not None else None
    return {
        "tangible_common_equity": {
            "value": tangible, "unit": "USD_thousands",
            "formula": "total equity capital - goodwill and other intangibles",
            "components": ["EQ", "INTAN"], "status": "available" if tangible is not None else "not_available",
        },
        "tangible_equity_to_assets": ratio(
            "tangible equity to assets", tangible, assets, "fraction",
            "(EQ - INTAN) / ASSET", ["EQ", "INTAN", "ASSET"],
        ),
        "equity_to_assets": ratio(
            "equity to assets", equity, assets, "fraction", "EQ / ASSET", ["EQ", "ASSET"],
        ),
        "allowance_to_loans": ratio(
            "allowance to loans", allowance, loans, "fraction", "ELNATR / LNLSNET",
            ["ELNATR", "LNLSNET"],
        ),
        "net_charge_off_rate": {
            "value": (value("NTLNLSR") / 100.0) if value("NTLNLSR") is not None else None,
            "unit": "fraction", "formula": "reported annualized NTLNLSR / 100",
            "components": ["NTLNLSR"], "status": "available" if value("NTLNLSR") is not None else "not_available",
            "note": "Reported annualized rate; not recomputed from a partial quarter.",
        },
        "retention_ratio": ratio(
            "retention", (net_income - dividends) if net_income is not None and dividends is not None else None,
            net_income, "fraction", "(NETINC - EQCDIV) / NETINC", ["NETINC", "EQCDIV"],
        ),
        "reported_ratios": {
            "tier_1_leverage": value("RBC1AAJ"),
            "total_risk_based_capital": value("RBCRWAJ"),
            "common_equity_tier_1": value("IDT1CER"),
            "net_interest_margin": value("NIMY"),
            "return_on_equity": value("ROE"),
            "return_on_assets": value("ROA"),
            "unit": "percent",
            "status": "available" if value("RBC1AAJ") is not None else "not_available",
        },
    }


def _capital_constraint(values: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    cet1 = (values.get("IDT1CER") or {}).get("value")
    leverage = (values.get("RBC1AAJ") or {}).get("value")
    total = (values.get("RBCRWAJ") or {}).get("value")
    requirements = {"common_equity_tier_1": 7.0, "tier_1_leverage": 4.0, "total_risk_based_capital": 10.5}
    observed = {"common_equity_tier_1": cet1, "tier_1_leverage": leverage,
                "total_risk_based_capital": total}
    headroom = {
        key: (observed[key] - requirements[key]) if observed[key] is not None else None
        for key in requirements
    }
    binding = min(
        ((key, headroom[key]) for key in headroom if headroom[key] is not None),
        key=lambda item: item[1], default=None,
    )
    return {
        "status": "available" if cet1 is not None else "not_available",
        "observed_percent": observed,
        "minimum_percent": requirements,
        "headroom_percentage_points": headroom,
        "binding_constraint": binding[0] if binding else None,
        "binding_headroom_points": binding[1] if binding else None,
        "dollar_rwa": None,
        "dollar_headroom": None,
        "detail": (
            "Headroom is computed in percentage points from reported ratios. Dollar RWA and "
            "dollar capital headroom are not published in this dataset and are not inferred."
        ),
    }


def regulatory_evidence(db: Database, *, cik: Any, periods: int = 6) -> dict[str, Any]:
    """Return the latest subsidiary evidence and its declared parent relationship."""
    seed_entities(db)
    mapping = reconcile_entities(db, cik)
    latest_blocks: list[dict[str, Any]] = []
    for subsidiary in mapping.get("subsidiaries", []):
        available = [
            row["period_end"] for row in db.query(
                "SELECT DISTINCT period_end FROM regulatory_observation WHERE entity_id=? "
                "ORDER BY period_end DESC LIMIT ?", (subsidiary["entity_id"], periods)
            )
        ]
        if not available:
            latest_blocks.append({
                "entity": subsidiary, "status": "not_ingested", "periods": [],
                "latest": None, "derived": None, "capital_constraint": None,
            })
            continue
        blocks = []
        for period in available:
            values = _period_observations(db, subsidiary["entity_id"], period)
            blocks.append({
                "period_end": period,
                "values": values,
                "derived": derived_metrics(values),
                "capital_constraint": _capital_constraint(values),
            })
        latest_blocks.append({
            "entity": subsidiary,
            "status": "available",
            "periods": [block["period_end"] for block in blocks],
            "latest": blocks[0],
            "history": blocks,
        })
    parent_rows = [row for row in mapping.get("entities", []) if row["consolidation_basis"] == PARENT]
    return {
        "schema": REGULATORY_SCHEMA,
        "cik": cik,
        "status": "available" if any(block["status"] == "available" for block in latest_blocks) else "not_ingested",
        "parent": parent_rows[0] if parent_rows else None,
        "subsidiaries": latest_blocks,
        "entity_map": mapping,
        "comparability": {
            "parent_basis": PARENT,
            "subsidiary_basis": SUBSIDIARY,
            "additive": False,
            "per_share_denominator": "parent SEC share count only",
            "period_alignment": "each block is a single reporting period; no cross-period ratio is formed",
        },
        "limitations": [
            "Call Report values are for the named insured depository, not the consolidated parent.",
            "Subsidiary equity is not divided by parent shares and is not added to consolidated equity.",
            "FDIC does not publish dollar risk-weighted assets in this dataset, so capital headroom is in percentage points only.",
            "FDIC revision history is not archived; the retrieval timestamp describes when Atlas fetched the record.",
        ],
    }
