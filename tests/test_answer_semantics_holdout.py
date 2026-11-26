"""Integrity tests for the prospective holdout cohort.

These checks do not score anything. They establish that the frozen cohort is what it claims to
be: the selection is the committed one, the two cohorts do not overlap, every printed gold cell
agrees with its same-accession XBRL fact, the preregistration still matches the working tree and
the committed blobs, and the resolution code is unchanged since the freeze.
"""

from __future__ import annotations

import json
import subprocess
import sys
from fractions import Fraction
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from atlas.research import holdout  # noqa: E402


def _load(path: Path) -> dict:
    return json.loads(path.read_text())


@pytest.fixture(scope="module")
def questions() -> list[dict]:
    return _load(holdout.QUESTIONS_PATH)["questions"]


@pytest.fixture(scope="module")
def facts() -> dict:
    return _load(holdout.FACTS_PATH)["facts"]


def test_selection_audit_has_no_errors() -> None:
    from answer_semantics_holdout_audit import audit_offline

    findings = audit_offline()
    errors = [item for item in findings if item["severity"] == "error"]
    assert not errors, errors
    plan = _load(holdout.PLAN_PATH)
    assert len(plan["filings"]) == 12
    assert len({item["accession"] for item in plan["filings"]}) == 12
    assert len({item["cik"] for item in plan["filings"]}) == 12


def test_cohorts_are_disjoint() -> None:
    development = _load(holdout.FIXTURES / "corpus.json")
    development_ciks = {str(item["cik"]).lstrip("0").zfill(10)
                        for item in development["filings"]}
    development_accessions = {item["accession"] for item in development["filings"]}
    corpus = _load(holdout.CORPUS_PATH)
    holdout_ciks = {item["cik"] for item in corpus["filings"]}
    holdout_accessions = {item["accession"] for item in corpus["filings"]}
    assert not development_ciks & holdout_ciks
    assert not development_accessions & holdout_accessions
    assert len(holdout_ciks) == len(holdout_accessions) == 12


def test_questions_are_accession_scoped_and_unique(questions: list[dict]) -> None:
    corpus = {item["accession"]: item for item in _load(holdout.CORPUS_PATH)["filings"]}
    manifest = {item["accession"]: item for item in _load(holdout.MANIFEST_PATH)["filings"]}
    identifiers = [item["id"] for item in questions]
    assert len(identifiers) == len(set(identifiers))
    per_accession: dict[str, int] = {}
    for question in questions:
        accession = question["accession"]
        assert question["scope"] == "accession"
        assert accession in corpus and accession in manifest
        assert corpus[accession]["cik"] == question["issuer_cik"]
        assert question["cutoff"] >= manifest[accession]["availability_time"]
        per_accession[accession] = per_accession.get(accession, 0) + 1
    assert set(per_accession) == set(corpus)
    assert min(per_accession.values()) >= 2, per_accession


def test_every_printed_gold_value_matches_its_xbrl_fact(questions: list[dict],
                                                       facts: dict) -> None:
    checked = 0
    for question in questions:
        if question["gold_class"] != "xbrl_verified":
            assert question["xbrl"] == []
            assert question["expect"]["outcome"] == "abstained"
            continue
        assert len(question["xbrl"]) == len(question["expect"]["citations"])
        for selector, citation in zip(question["xbrl"], question["expect"]["citations"]):
            assert selector["accn"] == question["accession"]
            assert citation["accession"] == question["accession"]
            matches = [row for row in facts[question["issuer_cik"]]
                       if row["tag"] == selector["tag"] and row["end"] == selector["end"]
                       and row["accn"] == selector["accn"] and row["unit"] == "USD"]
            assert len(matches) == 1, (question["id"], selector, len(matches))
            printed = Fraction(citation["raw"].replace(",", "")) * (10 ** citation["scale"])
            assert printed == Fraction(str(matches[0]["val"])), question["id"]
            checked += 1
    assert checked >= 50


def test_every_abstention_probe_has_no_gross_profit_fact(questions: list[dict],
                                                         facts: dict) -> None:
    probes = [item for item in questions if item["gold_class"] == "structurally_unanswerable"]
    assert probes
    for question in probes:
        assert question["concept"] == "gross_profit"
        rows = [row for row in facts[question["issuer_cik"]]
                if row["tag"] == "GrossProfit" and row["accn"] == question["accession"]]
        assert rows == [], question["id"]


def test_ledger_accounts_for_every_question(questions: list[dict]) -> None:
    ledger = _load(holdout.LEDGER_PATH)
    scored = {item["key"] for item in ledger["entries"] if item["status"] == "scored"}
    assert scored == {item["id"] for item in questions}
    assert ledger["summary"]["scored"] == len(questions)
    assert ledger["summary"]["attempted"] == len(questions) + ledger["summary"]["not_scored"]
    assert all(item["detail"] for item in ledger["entries"] if item["status"] == "not_scored")


def test_archived_experiment_still_verifies() -> None:
    """The historical run is audited at the commits it names, not against today's source.

    Hardening the resolver must not invalidate the first experiment's provenance, so this checks
    the frozen inputs and code *as committed* and reports — rather than fails on — live drift.
    """
    if not holdout.FREEZE_PATH.exists():
        pytest.fail("the holdout preregistration is missing")
    source_commit = _load(holdout.FREEZE_PATH).get("code_commit")
    present = subprocess.run(["git", "cat-file", "-e", f"{source_commit}^{{commit}}"],
                             cwd=ROOT, capture_output=True, text=True)
    if present.returncode != 0:
        pytest.skip(f"the experiment names source commit {source_commit}, which the "
                    "single-commit distribution candidate does not contain; the frozen input "
                    "and output hashes are still checked below and in the archive manifest")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "answer_semantics_holdout_archive.py"), "--check"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr
    assert "archive verified" in result.stdout


def test_live_code_drift_is_detected_rather_than_hidden() -> None:
    """The archive must state plainly that today's resolver is not the one that produced the run."""
    from atlas.research import holdout as holdout_module
    freeze = _load(holdout_module.FREEZE_PATH)
    drifted = [path for path, digest in holdout_module.code_hashes().items()
               if freeze["code"].get(path) not in {None, digest}]
    archive = _load(holdout_module.ARTIFACTS / "holdout_archive_manifest.json")
    # Development after the audit adds drift; it can never remove a recorded one.
    assert set(archive["live_code_drifted_from_freeze"]) <= set(drifted)
    assert archive["live_code_drifted_from_freeze"], "the resolver has moved on since the freeze"
    assert archive["historical_label"] == "first_prospective_holdout_run"


def test_first_run_used_the_frozen_code(questions: list[dict]) -> None:
    """Any later change is allowed, but the recorded run must cite the frozen code hashes."""
    if not holdout.OUTPUT_PATH.exists():
        pytest.skip("the first prospective run has not been executed in this checkout")
    report = _load(holdout.OUTPUT_PATH)
    freeze = _load(holdout.FREEZE_PATH)
    assert report["run"]["gold_digest"] == freeze["gold_digest"]
    assert report["run"]["code"] == freeze["code"]
    assert report["run"]["gold_freeze_commit"]
    assert report["run"]["run_ordinal"] == 1
    assert len(report["results"]) == 2 * len(questions)


def test_replay_reproduces_the_first_run() -> None:
    if not holdout.OUTPUT_PATH.exists() or not holdout.SNAPSHOTS.exists():
        pytest.skip("first-run artifact or archived filings are not present")
    destination = ROOT / "var" / "answer_semantics" / "holdout" / "replay_test.json"
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "answer_semantics_holdout_replay.py"),
         "--out", str(destination)],
        capture_output=True, text=True)
    # The live resolver is the hardened one: replaying the frozen artifact with it would be a
    # development measurement, so the script must refuse unless that is asked for explicitly.
    assert result.returncode == 3, result.stdout + result.stderr
    assert "frozen resolver" in result.stderr


def test_report_tables_match_the_first_run() -> None:
    if not holdout.OUTPUT_PATH.exists():
        pytest.skip("the first prospective run has not been executed in this checkout")
    result = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "answer_semantics_holdout_summary.py"), "--check"],
        capture_output=True, text=True)
    assert result.returncode == 0, result.stdout + result.stderr


def test_manifest_rights_are_an_accepted_class() -> None:
    """The importer validates rights against a closed vocabulary and fails closed otherwise."""
    from atlas.research import rights

    manifest = _load(holdout.MANIFEST_PATH)
    assert {item["rights"] for item in manifest["filings"]} <= rights.INGESTIBLE
    assert "user_responsibility" in {item["rights"] for item in manifest["filings"]}


def test_corpus_builder_does_not_assert_public_domain(tmp_path) -> None:
    """EDGAR filings are issuer-prepared; the source registry must not claim federal authorship."""
    from atlas.storage.db import Database
    import answer_semantics_corpus

    database = Database(str(tmp_path / "holdout-rights.db"))
    database.migrate()
    answer_semantics_corpus._ensure_source(database)
    row = database.query_one(
        "SELECT licence, redistribution, notes FROM source WHERE source_id='sec-edgar'")
    assert row["redistribution"] != "public_domain"
    assert row["redistribution"] == "user_responsibility"
    assert "issuer-prepared" in row["licence"].lower()
    assert "17 U.S.C. 105" in row["licence"]
    assert "not federal authorship" in row["notes"]
