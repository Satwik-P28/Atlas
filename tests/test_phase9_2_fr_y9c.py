"""Official FR Y-9C ingestion, provenance, publication gate and parent-model tests."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from atlas.research import fr_y9c, regulatory
from atlas.research.equity import EquityResearchService
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION

ROOT = Path(__file__).resolve().parents[1]
ARCHIVE = ROOT / "fixtures" / "regulatory" / "BHCF20241231.ZIP"
DICTIONARY = ROOT / "fixtures" / "regulatory" / "Financial_Download_Dictionary.xlsx"


@pytest.fixture()
def db(tmp_path):
    database = Database(tmp_path / "fr-y9c.db")
    database.migrate()
    regulatory.seed_entities(database)
    yield database
    database.close()


@pytest.fixture()
def ingested(db):
    result = fr_y9c.ingest_archive(
        db,
        ARCHIVE,
        DICTIONARY,
        cik="19617",
        entity_id="REG-JPM-PARENT",
        retrieved_at="2026-11-06T20:00:00Z",
    )
    return db, result


def test_schema_is_13_and_fr_y9c_table_exists(db):
    assert LATEST_VERSION == 14
    assert db.schema_version() == 14
    assert "fr_y9c_observation" in db.tables()


def test_archive_hash_member_and_reported_values(ingested):
    _, result = ingested
    assert result["archive"]["name"] == "BHCF20241231.ZIP"
    assert result["archive"]["sha256"] == (
        "65b6479f0b0bc191e57cd2a446cbe31cbcaa3131bf6a1bbdbe4df259f6c89a4b"
    )
    assert result["archive"]["bytes"] == 1_509_964
    assert result["archive"]["text_member"] == "BHCF20241231.txt"
    assert result["archive"]["rows_in_archive"] == 3806
    assert result["rssd"] == "1039502"
    assert result["cik"] == "19617"
    assert result["period_end"] == "2024-12-31"
    assert result["observations_written"] == 17
    assert all(check["passed"] for check in result["identity_checks"])
    values = {
        row["field_code"]: row["value_numeric"]
        for row in ingested[0].query("SELECT field_code,value_numeric FROM fr_y9c_observation")
    }
    assert values["BHCK2170"] == 4_002_814_000.0
    assert values["BHCK3210"] == 344_758_000.0
    assert values["BHCK3163"] == 52_565_000.0
    assert values["BHCK3283"] == 20_050_000.0
    assert values["BHCAA223"] == 1_757_460_260.0
    assert values["BHCA7206"] == 16.7788
    assert values["BHCAP793"] == 15.6768


def test_ingestion_is_idempotent_and_preserves_archive_bytes(ingested):
    db, _ = ingested
    before = db.scalar("SELECT COUNT(*) FROM fr_y9c_observation")
    again = fr_y9c.ingest_archive(
        db,
        ARCHIVE,
        DICTIONARY,
        cik="19617",
        entity_id="REG-JPM-PARENT",
        retrieved_at="2026-11-06T20:00:00Z",
    )
    assert again["observations_written"] == 17
    assert db.scalar("SELECT COUNT(*) FROM fr_y9c_observation") == before
    source = db.query_one("SELECT * FROM source_archive")
    assert source["sha256"] == again["archive"]["sha256"]
    assert source["rights"] == "public_domain_us_government"
    assert len(source["content"]) == 1_509_964
    stored = db.query_one(
        "SELECT * FROM fr_y9c_observation WHERE field_code='BHCK2170'"
    )
    provenance = json.loads(stored["provenance_json"])
    assert provenance["schedule"] == "Schedule HC"
    assert provenance["consolidation_basis"] == "parent_consolidated"
    assert provenance["publication_timestamp_available"] is False
    assert len(provenance["archive"]["text_sha256"]) == 64
    assert stored["cik"] == "19617"
    assert stored["rssd"] == "1039502"


def test_missing_values_remain_missing_and_tce_is_not_proxied(ingested):
    db, result = ingested
    row = db.query_one("SELECT * FROM fr_y9c_observation WHERE field_code='BHBC6061'")
    assert row["value_numeric"] is None
    assert row["value_text"] == ""
    assert "net_charge_offs" in result["missing_fields"]
    derived = result["derived"]
    assert derived["common_equity"]["value"] == 324_708_000.0
    assert derived["tangible_common_equity"]["status"] == "not_available"
    assert derived["tangible_common_equity"]["value"] is None


def test_bulk_archive_never_claims_point_in_time_history(ingested):
    db, _ = ingested
    evidence = fr_y9c.holding_company_evidence(db, cik="19617", cutoff="2025-06-30")
    assert evidence["status"] == "available"
    assert evidence["point_in_time_claim"] == "prohibited_publication_timestamp_missing"
    assert evidence["historical_use"] == "blocked_publication_timestamp_missing"
    publication = evidence["latest"]["publication"]
    assert publication["published_at"] is None
    assert publication["included_at_cutoff"] is False
    assert publication["availability_precision"] == "unknown"


def test_verified_publication_timestamp_is_required_for_cutoff_use(db):
    with pytest.raises(fr_y9c.FrY9CError):
        fr_y9c.ingest_archive(
            db, ARCHIVE, DICTIONARY, cik="19617", entity_id="REG-JPM-PARENT",
            published_at="2024-12-01T00:00:00Z",
            retrieved_at="2026-11-06T20:00:00Z",
        )
    result = fr_y9c.ingest_archive(
        db, ARCHIVE, DICTIONARY, cik="19617", entity_id="REG-JPM-PARENT",
        published_at="2025-02-14T12:00:00Z",
        publication_basis="test-only explicit release timestamp",
        retrieved_at="2026-11-06T20:00:00Z",
    )
    assert result["point_in_time_eligible"] is True
    evidence = fr_y9c.holding_company_evidence(db, cik="19617", cutoff="2025-06-30")
    assert evidence["latest"]["publication"]["included_at_cutoff"] is True
    assert evidence["historical_use"] == "eligible"


def test_rejects_parent_subsidiary_or_wrong_rssd_mix(db):
    with pytest.raises(fr_y9c.FrY9CError):
        fr_y9c.ingest_archive(
            db, ARCHIVE, DICTIONARY, cik="19617", entity_id="REG-JPM-BANK"
        )
    with pytest.raises(fr_y9c.FrY9CError):
        fr_y9c.ingest_archive(
            db, ARCHIVE, DICTIONARY, cik="19617", entity_id="REG-JPM-PARENT", rssd="852218"
        )
    with pytest.raises(fr_y9c.FrY9CError):
        fr_y9c.ingest_archive(
            db, ARCHIVE, DICTIONARY, cik="886982", entity_id="REG-GS-PARENT"
        )


def test_consolidated_capital_is_distinct_from_subsidiary_and_parent_shares(tmp_path):
    path = tmp_path / "model.db"
    subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "build_phase9_db.py"),
            "--db", str(path), "--tickers", "JPM",
        ],
        check=True,
        capture_output=True,
    )
    db = Database(path, create=False)
    db.migrate()
    regulatory.seed_entities(db)
    for fixture in sorted((ROOT / "fixtures" / "regulatory").glob("fdic_*.json")):
        regulatory.ingest_fdic_payload(db, json.loads(fixture.read_text()))
    fr_y9c.ingest_archive(
        db, ARCHIVE, DICTIONARY, cik="19617", entity_id="REG-JPM-PARENT",
        retrieved_at="2026-11-06T20:00:00Z",
    )
    service = EquityResearchService(db)
    valuation = service.valuation("JPM")
    model = valuation["institution"]
    parent = model["parent_capital"]
    assert parent["status"] == "available_consolidated_snapshot"
    assert parent["basis"] == "parent_consolidated"
    assert parent["form"] == "FR Y-9C"
    assert parent["rssd"] == 1039502
    assert parent["period_end"] == "2024-12-31"
    assert parent["values"]["total_assets"] == 4_002_814_000.0
    assert parent["values"]["common_equity"] == 324_708_000.0
    assert parent["capital_ratios_percent"]["common_equity_tier_1_ratio"] == 15.6768
    assert parent["used_in_per_share"] is False
    assert parent["subsidiary_evidence_used_for_parent"] is False
    assert model["capital"]["status"] == "available"
    assert model["tangible_book"]["used_in_per_share"] is False
    assert model["regulatory"]["entity_map"]["parent"]["rssd"] == 1039502
    assert valuation["regulatory"]["holding_company"]["status"] == "available"
    db.close()
