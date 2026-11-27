"""Partitioned Parquet evidence, DuckDB queries and on-demand materialisation.

The fixture is a synthetic companyfacts archive committed through the real snapshot
store, so the tests exercise the same code the benchmark runs without any network.

The adversarial cases here are the Phase V corrections: unknown availability is never
treated as knowable, a screen refuses mixed units, currencies and durations, and a
restatement is identified by the full observation identity rather than concept and
period end alone.
"""
from __future__ import annotations

import json
import zipfile
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.open_data.columnar import (
    AVAILABILITY_BOUNDED,
    AVAILABILITY_ESTIMATED,
    AVAILABILITY_OBSERVED,
    AVAILABILITY_UNKNOWN,
    CONSOLIDATED_SCOPE,
    ColumnarEvidence,
    IncomparableScreen,
    ScreenSpec,
    availability_class,
    build_from_archive,
    extract_member,
    load_manifest,
    totals,
)


def _obs(
    value: int | str,
    *,
    accn: str,
    start: str | None = "2023-01-01",
    end: str = "2023-12-31",
    form: str = "10-K",
    filed: str | None = "2024-02-01",
    fy: int = 2023,
    fp: str = "FY",
) -> dict:
    observation: dict = {"end": end, "val": value, "accn": accn, "fy": fy, "fp": fp, "form": form}
    if start:
        observation["start"] = start
    if filed:
        observation["filed"] = filed
    return observation


def _payload(cik: int, name: str, facts: dict[str, dict[str, list[dict]]]) -> dict:
    elements = {tag: {"units": units} for tag, units in facts.items()}
    return {"cik": cik, "entityName": name, "facts": {"us-gaap": elements}}


def _standard(number: int, *, amended: bool = False) -> dict:
    revenue = [_obs(1000 * number, accn=f"000000{number}-24-000001")]
    if amended:
        revenue.append(_obs(900 * number, accn=f"000000{number}-24-000002", form="10-K/A",
                            filed="2024-03-01"))
    return _payload(number, f"Company {number}", {
        "Assets": {"USD": [_obs(5000 * number, accn=f"000000{number}-24-000001", start=None)]},
        "Revenues": {"USD": revenue},
    })


def _archive(tmp_path: Path, payloads: list[dict]) -> Path:
    archive = tmp_path / "companyfacts.zip"
    with zipfile.ZipFile(archive, "w") as bundle:
        for payload in payloads:
            bundle.writestr(f"CIK{int(payload['cik']):010d}.json", json.dumps(payload))
    return archive


def _build(tmp_path: Path, payloads: list[dict] | None = None) -> tuple[Path, dict]:
    if payloads is None:
        payloads = [_standard(number, amended=number == 2) for number in range(1, 5)]
    root = tmp_path / "columnar"
    manifest = build_from_archive(_archive(tmp_path, payloads), root, snapshot_id="snap",
                                  bucket_count=2)
    return root, manifest


def _open(root: Path) -> ColumnarEvidence:
    return ColumnarEvidence(root)


def test_rows_are_partitioned_hashed_and_counted(tmp_path: Path) -> None:
    root, manifest = _build(tmp_path)
    assert manifest["companies"] == 4
    assert manifest["records"] > 0
    assert manifest["partitioning"]["buckets"] == 2
    assert manifest["schema"] == "atlas.open_data.columnar.v2"
    assert manifest["scope"]["value"] == CONSOLIDATED_SCOPE
    assert manifest["availability"]["historical"] == ["observed", "bounded"]
    paths = [entry["path"] for entry in manifest["files"]]
    assert paths and all("cik_bucket=" in path for path in paths)
    stored = totals(root)
    assert stored["parquet_bytes"] > 0
    assert stored["archive_bytes"] > 0
    assert {entry["cik"] for entry in manifest["member_index"]} == {
        "0000000001", "0000000002", "0000000003", "0000000004"}


def test_duckdb_answers_without_importing_the_universe(tmp_path: Path) -> None:
    root, _ = _build(tmp_path)
    columnar = _open(root)
    try:
        rows = columnar.company("2")
        assert rows and all(row["cik"] == "0000000002" for row in rows)
        assert {row["consolidated_scope"] for row in rows} == {CONSOLIDATED_SCOPE}
        statement = columnar.statement("2")
        assert statement["period_end"] == "2023-12-31"
        assert {"assets", "revenue"} <= set(statement["concepts"])
        # A cutoff before the first filing exposes no observation.
        assert columnar.point_in_time("2", "2020-01-01T00:00:00Z") == []
        assert columnar.point_in_time("2", "2025-01-01T00:00:00Z")
        screening = columnar.screen(concept="revenue", fiscal_year=2023, period="annual")
        assert {row["cik"] for row in screening} >= {"0000000001", "0000000002"}
        restated = columnar.restatements("2")
        assert any(item["amended"] for item in restated)
        assert columnar.restatements("1") == []
    finally:
        columnar.close()


def test_exact_source_member_is_reconstructable(tmp_path: Path) -> None:
    root, _ = _build(tmp_path)
    extracted = extract_member(root, "3")
    with zipfile.ZipFile(tmp_path / "companyfacts.zip") as bundle:
        original = bundle.read(extracted["member"])
    assert extracted["content"] == original
    assert extracted["sha256"] == load_manifest(root)["member_index"][2]["sha256"]


def test_one_company_can_be_materialised_on_demand(tmp_path: Path) -> None:
    root, _ = _build(tmp_path)
    columnar = _open(root)
    try:
        outcome = columnar.materialize("1", tmp_path / "lazy.db", snapshot_id="snap")
    finally:
        columnar.close()
    assert outcome["records"] > 0
    assert outcome["inserted"] + outcome["superseding"] > 0
    assert (tmp_path / "lazy.db").stat().st_size > 0
    import sqlite3

    connection = sqlite3.connect(tmp_path / "lazy.db")
    try:
        assert connection.execute("SELECT COUNT(DISTINCT cik) FROM issuer").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM evidence").fetchone()[0] == outcome["inserted"]
    finally:
        connection.close()


def test_a_missing_company_is_refused(tmp_path: Path) -> None:
    root, _ = _build(tmp_path)
    with pytest.raises(KeyError):
        extract_member(root, "999")


# ------------------------------------------------------------- availability
def test_availability_classes_distinguish_evidence_strength() -> None:
    assert availability_class({"availability_time": "2024-02-01T21:30:00Z",
                               "availability_precision": "exact"}) == AVAILABILITY_OBSERVED
    assert availability_class({"availability_time": "2024-02-01T23:59:59Z",
                               "availability_precision": "date"}) == AVAILABILITY_BOUNDED
    assert availability_class({
        "availability_time": "2024-02-01T21:30:00Z",
        "availability_precision": "exact",
        "availability_basis": "sec_acceptance_plus_publication_lag_v1",
    }) == AVAILABILITY_ESTIMATED
    assert availability_class({"availability_time": None,
                               "availability_precision": "unknown"}) == AVAILABILITY_UNKNOWN


def test_unknown_availability_is_excluded_from_history_and_counted(tmp_path: Path) -> None:
    payload = _payload(1, "Company 1", {
        "Revenues": {"USD": [_obs(1000, accn="0000000001-24-000001", filed=None)]},
    })
    root, _ = _build(tmp_path, [payload])
    columnar = _open(root)
    try:
        assert columnar.company("1")
        assert columnar.point_in_time("1", "2025-01-01T00:00:00Z") == []
        report = columnar.availability("1")
        assert report["by_class"][AVAILABILITY_UNKNOWN] >= 1
        assert report["usable_historically"] == 0
        # The current view may show it; a historical cut-off may not.
        assert columnar.statement("1")["concepts"] == {"revenue": "1000"}
        assert columnar.statement("1", as_of="2025-01-01T00:00:00Z")["concepts"] == {}
        detail = columnar.screen_report(ScreenSpec(concept="revenue", fiscal_year=2023,
                                                  period="annual"))
        assert detail["selected"] == []
        assert detail["excluded"]["unknown_availability"] >= 1
        assert any("availability is unknown" in item["reason"] for item in detail["refused"])
    finally:
        columnar.close()


def test_future_dated_observations_are_excluded_by_the_cutoff(tmp_path: Path) -> None:
    payload = _payload(1, "Company 1", {
        "Revenues": {"USD": [_obs(1000, accn="0000000001-27-000001", filed="2027-02-01")]},
    })
    root, _ = _build(tmp_path, [payload])
    columnar = _open(root)
    try:
        detail = columnar.screen_report(
            ScreenSpec(concept="revenue", fiscal_year=2023, period="annual",
                       as_of="2026-01-01T00:00:00Z"))
        assert detail["selected"] == []
        assert detail["excluded"]["not_available_at_cutoff"] >= 1
        later = columnar.screen_report(
            ScreenSpec(concept="revenue", fiscal_year=2023, period="annual",
                       as_of="2027-06-01T00:00:00Z"))
        assert [row["cik"] for row in later["selected"]] == ["0000000001"]
    finally:
        columnar.close()


# ---------------------------------------------------------------- screening
def _screen_payloads() -> list[dict]:
    return [
        _payload(1, "USD Co", {"Revenues": {"USD": [_obs(1000, accn="1-24-1")]}}),
        _payload(2, "USD Co 2", {"Revenues": {"USD": [_obs(2000, accn="2-24-1")]}}),
        _payload(3, "EUR Co", {"Revenues": {"EUR": [_obs(9000, accn="3-24-1")]}}),
    ]


def test_screening_refuses_mixed_currencies_and_accepts_an_explicit_choice(tmp_path: Path) -> None:
    root, _ = _build(tmp_path, _screen_payloads())
    columnar = _open(root)
    try:
        with pytest.raises(IncomparableScreen) as refusal:
            columnar.screen(concept="revenue", fiscal_year=2023, period="annual")
        message = str(refusal.value)
        assert "unit or currency" in message
        assert {group["currency"] for group in refusal.value.groups} == {"USD", "EUR"}

        usd = columnar.screen(concept="revenue", fiscal_year=2023, period="annual",
                              currency="USD", unit="USD")
        assert [row["cik"] for row in usd] == ["0000000002", "0000000001"]
        assert {row["currency"] for row in usd} == {"USD"}
        report = columnar.screen_report(ScreenSpec(concept="revenue", fiscal_year=2023,
                                                  period="annual", currency="USD", unit="USD"))
        assert report["excluded"]["wrong_unit"] >= 1
        assert report["comparable"]["scope"] == CONSOLIDATED_SCOPE
    finally:
        columnar.close()


def test_screening_enforces_one_reporting_duration(tmp_path: Path) -> None:
    payloads = [
        _payload(1, "Annual Co", {"Revenues": {"USD": [_obs(1000, accn="1-24-1")]}}),
        _payload(2, "Quarterly Co", {
            "Revenues": {"USD": [_obs(250, accn="2-24-1", start="2023-10-01", fp="Q4")]},
        }),
    ]
    root, _ = _build(tmp_path, payloads)
    columnar = _open(root)
    try:
        annual = columnar.screen_report(ScreenSpec(concept="revenue", fiscal_year=2023,
                                                   period="annual"))
        assert [row["cik"] for row in annual["selected"]] == ["0000000001"]
        assert annual["excluded"]["wrong_period"] >= 1
        quarterly = columnar.screen_report(ScreenSpec(concept="revenue", fiscal_year=2023,
                                                      period="quarter"))
        assert [row["cik"] for row in quarterly["selected"]] == ["0000000002"]
        with pytest.raises(IncomparableScreen):
            columnar.screen(concept="revenue", fiscal_year=2023, period="auto")
    finally:
        columnar.close()


def test_screening_is_exact_and_deterministic(tmp_path: Path) -> None:
    payloads = [
        _payload(1, "Co 1", {"Revenues": {"USD": [
            _obs(9007199254740992, accn="1-24-1")]}}),
        _payload(2, "Co 2", {"Revenues": {"USD": [
            _obs(9007199254740993, accn="2-24-1")]}}),
        _payload(3, "Co 3", {"Revenues": {"USD": [
            _obs(9007199254740992, accn="3-24-1")]}}),
    ]
    root, _ = _build(tmp_path, payloads)
    columnar = _open(root)
    try:
        rows = columnar.screen(concept="revenue", fiscal_year=2023, period="annual")
        assert [row["cik"] for row in rows] == [
            "0000000002", "0000000001", "0000000003"]
        assert rows[0]["value"] == "9007199254740993"
        # A float comparison would have collapsed these two values into one.
        assert rows[1]["value"] != rows[0]["value"]
        assert Decimal(rows[1]["value"]) == Decimal("9007199254740992")
        filtered = columnar.screen(concept="revenue", fiscal_year=2023, period="annual",
                                   minimum="9007199254740993")
        assert [row["cik"] for row in filtered] == ["0000000002"]
    finally:
        columnar.close()


def test_a_build_without_the_scope_column_is_refused(tmp_path: Path) -> None:
    import pyarrow.parquet as pq

    root, _ = _build(tmp_path)
    # union_by_name would reintroduce the column from a sibling bucket, so every file
    # loses it: this is a build written by the previous schema version.
    for path in (root / "evidence").rglob("*.parquet"):
        table = pq.read_table(path).drop(["consolidated_scope"])
        pq.write_table(table, path)
    columnar = _open(root)
    try:
        assert columnar.scope_verified is False
        with pytest.raises(IncomparableScreen, match="consolidated-scope"):
            columnar.statement("2")
        with pytest.raises(IncomparableScreen, match="consolidated-scope"):
            columnar.screen(concept="revenue", fiscal_year=2023, period="annual")
    finally:
        columnar.close()


# ------------------------------------------------------------- restatements
def test_restatement_identity_separates_duration_currency_and_repeats(tmp_path: Path) -> None:
    payload = _payload(1, "Identity Co", {
        "Revenues": {
            "USD": [
                _obs(1000, accn="1-23-1", filed="2024-02-01"),
                # The fourth quarter ends on the same date as the fiscal year: a
                # concept-and-period-end key would have called this a restatement.
                _obs(250, accn="1-23-1", start="2023-10-01", filed="2024-02-01", fp="Q4"),
                # A later comparative repeats the value unchanged: not a restatement.
                _obs(1000, accn="1-25-1", filed="2026-02-01"),
            ],
            "EUR": [
                _obs(900, accn="1-23-1", filed="2024-02-01"),
            ],
        },
    })
    root, _ = _build(tmp_path, [payload])
    columnar = _open(root)
    try:
        report = columnar.restatement_report("1")
        assert report["findings"] == []
        assert report["summary"]["repeated_comparatives"] >= 1
        categories = {item["period_kind"] for item in report["repeated_comparatives"]}
        assert "annual" in categories
        # The EUR fact is a separate identity, not a revision of the USD fact.
        assert all(item["currency"] == "USD" for item in report["repeated_comparatives"])
    finally:
        columnar.close()


def test_amendment_and_same_instant_conflict_are_reported(tmp_path: Path) -> None:
    payload = _payload(1, "Amended Co", {
        "Revenues": {"USD": [
            _obs(1000, accn="1-24-1", filed="2024-02-01"),
            _obs(900, accn="1-24-2", form="10-K/A", filed="2024-02-01"),
        ]},
    })
    root, _ = _build(tmp_path, [payload])
    columnar = _open(root)
    try:
        statement = columnar.statement("1")
        assert statement["concepts"]["revenue"] in {"900", "1000"}
        assert statement["contradictions"], "two values at one instant must be disclosed"
        assert set(statement["contradictions"][0]["values"]) == {"900", "1000"}
        report = columnar.restatement_report("1")
        assert [item["category"] for item in report["findings"]] == ["amendment_revision"]
        assert report["findings"][0]["amended"] is True
    finally:
        columnar.close()


def test_taxonomy_change_is_not_a_value_revision(tmp_path: Path) -> None:
    payload = _payload(1, "Migrating Co", {
        "Revenues": {"USD": [
            _obs(1000, accn="1-23-1", filed="2024-02-01"),
            _obs(1000, accn="1-24-1", filed="2025-02-01"),
        ]},
        "RevenueFromContractWithCustomerExcludingAssessedTax": {
            "USD": [_obs(1000, accn="1-24-1", filed="2025-02-01")],
        },
    })
    root, _ = _build(tmp_path, [payload])
    columnar = _open(root)
    try:
        report = columnar.restatement_report("1")
        assert report["findings"] == []
    finally:
        columnar.close()


# ----------------------------------------------------------- kernel parity
def test_columnar_selection_matches_the_evidence_kernel(tmp_path: Path) -> None:
    root, _ = _build(tmp_path)
    columnar = _open(root)
    try:
        outcome = columnar.materialize("2", tmp_path / "parity.db", snapshot_id="snap")
        statement = columnar.statement("2", as_of="2025-01-01T00:00:00Z")
    finally:
        columnar.close()

    import sqlite3

    from atlas.evidence.kernel import EvidenceKernel
    from atlas.storage.db import open_database

    connection = sqlite3.connect(tmp_path / "parity.db")
    try:
        entity_id = connection.execute("SELECT issuer_id FROM issuer LIMIT 1").fetchone()[0]
    finally:
        connection.close()
    db = open_database(tmp_path / "parity.db")
    try:
        selection = EvidenceKernel(db).as_of(entity_id, "2025-01-01T00:00:00Z")
    finally:
        db.close()
    kernel_values = {
        fact.concept: fact.value for fact in selection.facts
        if fact.period_end == statement["period_end"]
    }
    for concept, value in statement["concepts"].items():
        assert kernel_values.get(concept) == value, concept
    assert outcome["records"] > 0
    assert selection.excluded_unknown_availability == 0
