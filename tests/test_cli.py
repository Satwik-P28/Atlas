"""CLI behaviour: every documented command must execute and print useful output."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from atlas.cli import main

FIXTURES = Path(__file__).resolve().parents[1] / "fixtures"
RESTATEMENT = str(FIXTURES / "sec_restatement")
MARKET_CSV = str(FIXTURES / "market" / "aapl_split_bars.csv")
RESTATEMENT_CIK = "1999999"


@pytest.fixture()
def cli_db(tmp_path, capsys):
    path = str(tmp_path / "cli.db")
    assert main(["--db", path, "init"]) == 0
    capsys.readouterr()
    return path


def test_init_reports_schema(cli_db, capsys):
    assert main(["--db", cli_db, "--json", "stats"]) == 0
    payload = json.loads(capsys.readouterr().out)
    from atlas.storage.migrations import LATEST_VERSION

    assert payload["schema_version"] == LATEST_VERSION
    assert "evidence" in payload["tables"]


def test_concepts_lists_registry(cli_db, capsys):
    assert main(["--db", cli_db, "--json", "concepts"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert "revenue" in payload["concepts"]
    assert "gross_profit" in payload["derivations"]


def test_sec_sync_offline_then_query(cli_db, capsys):
    assert main(["--db", cli_db, "sec", "sync", "--cik", RESTATEMENT_CIK, "--offline", RESTATEMENT]) == 0
    sync_output = capsys.readouterr().out
    assert "issuer" in sync_output

    assert main(["--db", cli_db, "--json", "facts", "--cik", RESTATEMENT_CIK, "--concept", "revenue"]) == 0
    facts = json.loads(capsys.readouterr().out)
    assert facts["facts"]
    assert facts["mode"] == "public_available"
    assert facts["completeness"] == "complete_for_query"
    evidence_id = facts["facts"][0]["evidence_id"]

    assert main(["--db", cli_db, "--json", "explain", "--evidence-id", evidence_id]) == 0
    explained = json.loads(capsys.readouterr().out)
    assert explained["record"]["evidence_id"] == evidence_id
    assert explained["narrative"]
    assert explained["source"]["redistribution"] == "public_domain"


def test_asof_query_does_not_leak_the_restatement(cli_db, capsys):
    assert main(["--db", cli_db, "sec", "sync", "--cik", RESTATEMENT_CIK, "--offline", RESTATEMENT]) == 0
    capsys.readouterr()
    assert main(["--db", cli_db, "asof", "--cik", RESTATEMENT_CIK, "--date", "2024-06-01",
                 "--concept", "revenue"]) == 0
    text = capsys.readouterr().out
    assert "100000000" in text
    assert "90000000" not in text
    assert "not available at the requested instant" in text


def test_entity_show_and_securities(cli_db, capsys):
    assert main(["--db", cli_db, "sec", "sync", "--cik", RESTATEMENT_CIK, "--offline", RESTATEMENT]) == 0
    capsys.readouterr()
    assert main(["--db", cli_db, "--json", "entity", "show", "--cik", RESTATEMENT_CIK]) == 0
    payload = json.loads(capsys.readouterr().out)
    securities = payload["profile"]["securities"]
    assert securities and securities[0]["security"]["security_id"].startswith("SEC-")
    assert securities[0]["tickers"][0]["ticker"] == "ATLR"


def test_bars_import_show_and_validate(cli_db, capsys):
    assert main(["--db", cli_db, "sec", "sync", "--cik", RESTATEMENT_CIK, "--offline", RESTATEMENT]) == 0
    capsys.readouterr()
    assert main(["--db", cli_db, "--json", "entity", "show", "--cik", RESTATEMENT_CIK]) == 0
    profile = json.loads(capsys.readouterr().out)
    security_id = profile["profile"]["securities"][0]["security"]["security_id"]

    assert main(["--db", cli_db, "bars", "import", "--file", MARKET_CSV, "--security-id", security_id,
                 "--mic", "XNAS"]) == 0
    imported = capsys.readouterr().out
    assert "inserted=8" in imported

    assert main(["--db", cli_db, "bars", "show", "--security-id", security_id, "--mic", "XNAS",
                 "--start", "2020-08-01", "--end", "2020-09-30"]) == 0
    raw = capsys.readouterr().out
    assert "499.23" in raw

    assert main(["--db", cli_db, "actions", "add", "--security-id", security_id, "--type", "split",
                 "--ex-date", "2020-08-31", "--ratio", "4:1", "--available-at", "2020-08-28T20:30:00Z"]) == 0
    capsys.readouterr()
    assert main(["--db", cli_db, "actions", "list", "--security-id", security_id]) == 0
    actions = capsys.readouterr().out
    assert "split" in actions

    assert main(["--db", cli_db, "bars", "show", "--security-id", security_id, "--mic", "XNAS",
                 "--start", "2020-08-01", "--end", "2020-09-30", "--adjustment", "split"]) == 0
    adjusted = capsys.readouterr().out
    assert "124.8075" in adjusted

    assert main(["--db", cli_db, "bars", "validate", "--security-id", security_id, "--mic", "XNAS"]) == 0


def test_stats_and_validate_return_success_on_clean_data(cli_db, capsys):
    assert main(["--db", cli_db, "sec", "sync", "--cik", RESTATEMENT_CIK, "--offline", RESTATEMENT]) == 0
    capsys.readouterr()
    assert main(["--db", cli_db, "validate"]) == 0
    capsys.readouterr()
    assert main(["--db", cli_db, "--json", "stats"]) == 0
    stats = json.loads(capsys.readouterr().out)
    assert stats["evidence"]["evidence_records"] > 0


def test_cli_missing_selector_is_a_domain_error(cli_db, capsys):
    code = main(["--db", cli_db, "entity", "show"])
    captured = capsys.readouterr()
    assert code == 2
    assert "requires --cik" in captured.err


def test_cli_reports_domain_errors_without_traceback(cli_db, capsys):
    code = main(["--db", cli_db, "explain", "--evidence-id", "EV-nope"])
    captured = capsys.readouterr()
    assert code == 2
    assert "error:" in captured.err
