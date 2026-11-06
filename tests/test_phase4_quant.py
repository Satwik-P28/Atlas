"""Phase 4 independent validation for Quant Lab.

The accounting checks here are independent arithmetic on a hand-built ledger; the
simulator checks assert event ordering from first principles. They do not call a second
production engine, and they never adjust expected values to fit an observed result.
"""

from __future__ import annotations

import hashlib
import time
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient

from atlas.core.temporal import iso
from atlas.entities.master import SecurityMaster
from atlas.fec import compile_model
from atlas.market.actions import ActionStore, CorporateAction
from atlas.market.bars import Bar, BarStore
from atlas.quant.contracts import strategy_document, validate_strategy
from atlas.quant.features import FeatureEngine
from atlas.quant.lab import QuantLab, template_spec, universe
from atlas.quant.portfolio import Portfolio, max_affordable_quantity
from atlas.quant.simulator import SimulationConfig, run_simulation
from atlas.research.archive import SourceArchiveStore
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.api import create_app


def _bar(security_id: str, day: str, open_: str, close: str, *, volume: str = "1000") -> Bar:
    return Bar(
        security_id=security_id, mic="XNAS", ts_utc=f"{day}T21:00:00Z",
        open=Decimal(open_), high=Decimal(open_), low=Decimal(close),
        close=Decimal(close), volume=Decimal(volume), currency="USD",
        source_id="atlas-synthetic",
    )


def _fixture(tmp_path, *, extra_future: bool = False):
    db = Database(tmp_path / "quant.db")
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq")
    issuer = master.register_issuer(legal_name="Lab Instrument", cik="0000000999",
                                    source_id="atlas-synthetic")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="2024-01-01", is_primary=True)
    master.assign_ticker(listing, "LAB", valid_from="2024-01-01", confidence=1.0,
                         status="confirmed", source_id="atlas-synthetic")
    BarStore(db).ingest([
        _bar(security, "2024-01-02", "10", "10"),
        _bar(security, "2024-01-03", "11", "12"),
        _bar(security, "2024-01-04", "13", "13"),
    ])
    if extra_future:
        BarStore(db).ingest([_bar(security, "2024-01-05", "100", "100")])
    return db, security


def _buy_hold(security: str) -> dict:
    return {
        "schema_version": "atlas.strategy.v1", "name": "Buy hold", "version": "1.0.0",
        "universe": {"instruments": [{"security_id": security, "mic": "XNAS"}]},
        "features": [{"name": "close", "kind": "price", "window": 1}],
        "signal": {"kind": "buy_hold"},
        "decision_frequency": "daily",
        "execution": {"signal_at": "close", "fill_at": "next_open",
                      "commission_bps": 0, "slippage_bps": 0},
        "initial_capital": 1000, "constraints": {"long_only": True, "max_position": 1},
        "risk_free_rate": 0.0, "benchmark": {"kind": "buy_hold"},
    }


def test_schema_has_phase4_objects(tmp_path):
    db, _ = _fixture(tmp_path)
    assert db.schema_version() == LATEST_VERSION == 12
    tables = {row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"quant_run", "feature_snapshot", "source_archive", "source_archive_link"} <= tables
    db.close()


def test_portfolio_reconciles_independently():
    # Independent hand calculation:
    # 1000 - (10*10 + 5) = 895; sell 4 at 12 less 2 = 46 -> 941.
    # 2-for-1 split leaves 12 shares and total basis 603; dividend 12 -> cash 953.
    # mark 6 -> holdings 72 -> total 1025.
    portfolio = Portfolio("SEC-test", Decimal("1000"))
    portfolio.buy("2024-01-02", Decimal("10"), reference_price=Decimal("10"),
                  fill_price=Decimal("10"), commission=Decimal("5"))
    portfolio.sell("2024-01-03", Decimal("4"), reference_price=Decimal("12"),
                   fill_price=Decimal("12"), commission=Decimal("2"))
    portfolio.apply_split("2024-01-04", Decimal("2"))
    portfolio.apply_dividend("2024-01-04", Decimal("1"))
    portfolio.mark(Decimal("6"))
    assert portfolio.cash == Decimal("953")
    assert portfolio.position.quantity == Decimal("12")
    assert portfolio.position.cost_basis == Decimal("63")
    assert portfolio.realized_pnl == Decimal("4")
    assert portfolio.equity == Decimal("1025")
    recon = portfolio.reconciliation()
    assert recon["reconciled"] is True
    assert recon["ending_cash"] == "953"
    assert recon["total_portfolio_value"] == "1025"


def test_invalid_orders_and_affordable_quantity():
    portfolio = Portfolio("SEC-test", Decimal("100"))
    with pytest.raises(Exception):
        portfolio.buy("2024-01-02", Decimal("11"), reference_price=Decimal("10"),
                      fill_price=Decimal("10"), commission=Decimal("0"))
    with pytest.raises(Exception):
        portfolio.sell("2024-01-02", Decimal("1"), reference_price=Decimal("10"),
                       fill_price=Decimal("10"), commission=Decimal("0"))
    assert max_affordable_quantity(Decimal("100"), Decimal("11"), Decimal("0")) == Decimal("9")
    assert max_affordable_quantity(Decimal("100"), Decimal("11"), Decimal("0")) * Decimal("11") <= Decimal("100")


def test_signal_fills_at_next_open_not_same_close(tmp_path):
    db, security = _fixture(tmp_path)
    result = run_simulation(
        db, _buy_hold(security),
        config=SimulationConfig(as_of="2024-01-05", start="2024-01-02", end="2024-01-04",
                                initial_capital=1000),
    )
    assert result["trades"][0]["date"] == "2024-01-03"
    assert result["trades"][0]["fill_price"] == "11"
    # 90 shares because 1000 / 11 floors; 90 * 13 plus 10 residual cash = 1180.
    assert result["metrics"]["end_equity"] == 1180.0
    assert result["reconciliation"]["reconciled"] is True
    assert result["equity_curve"][0]["equity"] == "1000"
    db.close()


def test_split_and_dividend_are_applied_once(tmp_path):
    db, security = _fixture(tmp_path)
    actions = ActionStore(db)
    actions.add(CorporateAction(
        security_id=security, action_type="split", ex_date="2024-01-04",
        ratio_from=Decimal("1"), ratio_to=Decimal("2"), source_id="atlas-synthetic",
        availability_time="2024-01-04T21:00:00Z",
    ))
    actions.add(CorporateAction(
        security_id=security, action_type="cash_dividend", ex_date="2024-01-04",
        cash_amount=Decimal("1"), currency="USD", source_id="atlas-synthetic",
        availability_time="2024-01-04T21:00:00Z",
    ))
    # Replace the 01-04 raw price with the post-split price.
    db.execute("DELETE FROM bar WHERE security_id = ? AND ts_utc LIKE '2024-01-04%'", (security,))
    BarStore(db).ingest([_bar(security, "2024-01-04", "6", "6")])
    result = run_simulation(
        db, _buy_hold(security),
        config=SimulationConfig(as_of="2024-01-05", start="2024-01-02", end="2024-01-04",
                                initial_capital=1000),
    )
    assert result["trades"][0]["date"] == "2024-01-03"
    assert result["trades"][0]["quantity"] == "90"
    # cash 10 + dividend 180, 180 shares at 6 = 1080.
    assert result["metrics"]["end_equity"] == 1270.0
    assert result["reconciliation"]["dividend_income"] == "180"
    assert result["reconciliation"]["reconciled"] is True
    db.close()


def test_costs_reduce_result_and_same_run_is_deterministic(tmp_path):
    db, security = _fixture(tmp_path)
    free = _buy_hold(security)
    costly = _buy_hold(security)
    costly["execution"] = {**costly["execution"], "commission_bps": 100}
    a = run_simulation(db, free, config=SimulationConfig(as_of="2024-01-05", start="2024-01-02",
                                                          end="2024-01-04", initial_capital=1000))
    b = run_simulation(db, costly, config=SimulationConfig(as_of="2024-01-05", start="2024-01-02",
                                                            end="2024-01-04", initial_capital=1000))
    c = run_simulation(db, free, config=SimulationConfig(as_of="2024-01-05", start="2024-01-02",
                                                          end="2024-01-04", initial_capital=1000))
    assert a["metrics"]["end_equity"] > b["metrics"]["end_equity"]
    assert a["result_fingerprint"] == c["result_fingerprint"]
    assert b["metrics"]["transaction_costs"] > a["metrics"]["transaction_costs"]
    db.close()


def test_feature_cutoff_excludes_future_bars(tmp_path):
    db, security = _fixture(tmp_path, extra_future=True)
    engine = FeatureEngine(db)
    specs = [{"name": "sma2", "kind": "sma", "window": 2},
             {"name": "ret", "kind": "return", "window": 2}]
    early = engine.compute(security, "XNAS", specs, as_of="2024-01-03")
    late = engine.compute(security, "XNAS", specs, as_of="2024-01-05")
    assert early.points[-1]["date"] == "2024-01-03"
    assert [point["date"] for point in early.points] == ["2024-01-03"]
    assert early.points[0]["values"]["sma2"] == pytest.approx(11.0)
    assert early.points[0]["values"]["ret"] == pytest.approx(0.2)
    assert late.points[-1]["date"] == "2024-01-05"
    assert early.feature_fingerprint == late.feature_fingerprint
    assert early.metadata["source_ids"] == ["atlas-synthetic"]
    db.close()


def test_source_archive_is_content_addressed_and_rights_aware(tmp_path):
    db, _ = _fixture(tmp_path)
    store = SourceArchiveStore(db)
    first = store.archive(source_id="atlas-synthetic", resource_id="fixture-1",
                          content="exact source bytes", media_type="text/plain",
                          retention_policy="local_only")
    second = store.archive(source_id="atlas-synthetic", resource_id="fixture-1",
                           content="exact source bytes", media_type="text/plain",
                           retention_policy="local_only")
    assert first["archive_id"] == second["archive_id"]
    assert first["sha256"] == hashlib.sha256(b"exact source bytes").hexdigest()
    assert store.content(first["archive_id"]) == b"exact source bytes"
    assert store.status_for_sources(["atlas-synthetic"])["status"] == "archived"
    assert store.status_for_sources(["sec-edgar"])["status"] == "external_provider_only"
    assert store.status_for_evidence([])["status"] == "no_evidence"
    db.close()


def test_compiler_wide_graph_scaling_and_correctness():
    # 1,000 nodes with the old quadratic topological scan. The new adjacency pass must
    # remain correct for a genuine chain and finish without degrading validation.
    nodes = [{"id": "n0", "op": "add", "inputs": ["x", "x"]}]
    for index in range(1, 1000):
        nodes.append({"id": f"n{index}", "op": "add", "inputs": [f"n{index - 1}", "x"]})
    spec = {
        "schema_version": "atlas.model.v1", "name": "Wide graph", "interface": "graph",
        "inputs": [{"name": "x", "type": "Scalar"}], "nodes": nodes,
        "outputs": {"out": "n999"},
    }
    started = time.perf_counter()
    model = compile_model(spec)
    elapsed = time.perf_counter() - started
    assert len(model.order) == 1001  # 1,000 operation nodes plus the declared input
    assert model.outputs["out"] == "n999"
    # Generous ceiling for shared CI; the measured local time is reported separately.
    assert elapsed < 2.0
    assert model.nodes["n0"].type is not None


def test_lab_api_run_replay_and_archive(tmp_path):
    db_path = tmp_path / "api.db"
    db = Database(db_path)
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    master.ensure_venue("XNAS", "Nasdaq")
    issuer = master.register_issuer(legal_name="API Lab", cik="0000000998",
                                    source_id="atlas-synthetic")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    master.ensure_listing(security, "XNAS", valid_from="2024-01-01", is_primary=True)
    BarStore(db).ingest([_bar(security, "2024-01-02", "10", "10"),
                         _bar(security, "2024-01-03", "11", "12"),
                         _bar(security, "2024-01-04", "13", "13")])
    db.close()
    client = TestClient(create_app(db_path))
    catalog = client.get("/api/quant/catalog")
    assert catalog.status_code == 200
    template = catalog.json()["templates"][0]
    spec = template_spec(template, catalog.json()["universe"][0], name="API buy hold")
    response = client.post("/api/quant/backtest", json={
        "spec": spec, "as_of": "2024-01-05", "start": "2024-01-02", "end": "2024-01-04",
        "persist": True,
    })
    assert response.status_code == 200, response.text
    run = response.json()
    assert run["reconciliation"]["reconciled"] is True
    assert run["experiment_object_id"]
    assert client.get(f"/api/quant/runs/{run['run_id']}").status_code == 200
    assert client.get(f"/api/quant/runs/{run['run_id']}/capsule").status_code == 200
    preview = client.post("/api/quant/preview", json={
        "spec": spec, "as_of": "2024-01-05", "start": "2024-01-02", "end": "2024-01-04",
    })
    assert preview.status_code == 200, preview.text
    assert preview.json()["mode"] == "vectorized_preview"
    assert preview.json()["not_a_fill_simulation"] is True
    # The preview is explicitly not a ledger: no cash/positions may be implied.
    assert "reconciliation" not in preview.json()
    assert preview.json()["metrics"]["end_equity"] > spec["initial_capital"]
    replay = client.post(f"/api/quant/runs/{run['run_id']}/replay")
    assert replay.status_code == 200
    assert replay.json()["reproduced"] is True
    archive = client.post("/api/research/archive", json={
        "source_id": "atlas-synthetic", "resource_id": "api-fixture",
        "content": "source bytes", "media_type": "text/plain",
    })
    assert archive.status_code == 201
    assert archive.json()["sha256"] == hashlib.sha256(b"source bytes").hexdigest()
    assert client.get("/api/research/archive-status?source_ids=atlas-synthetic").json()["status"] == "archived"


def test_strategy_contract_rejects_silent_parameter_reuse(tmp_path):
    db, security = _fixture(tmp_path)
    lab = QuantLab(db)
    first = _buy_hold(security)
    first["name"] = "Named strategy"
    lab.ensure_strategy(first)
    changed = _buy_hold(security)
    changed["name"] = "Named strategy"
    changed["execution"] = {**changed["execution"], "commission_bps": 50}
    with pytest.raises(Exception):
        lab.ensure_strategy(changed)
    db.close()


def test_model_strategy_reuses_declaration_after_compiler_stamp_change(tmp_path):
    db, security = _fixture(tmp_path)
    lab = QuantLab(db)
    template = next(item for item in lab.builtin_templates() if item["key"] == "custom_model")
    spec = {
        "schema_version": "atlas.strategy.v1", "name": "Reusable model strategy",
        "version": "1.0.0", "description": template["description"],
        "universe": {"instruments": [{"security_id": security, "mic": "XNAS"}]},
        "features": template["features"], "signal": template["signal"],
        "decision_frequency": "daily", "rebalance": "daily",
        "execution": {"signal_at": "close", "fill_at": "next_open",
                      "commission_bps": 2, "slippage_bps": 5},
        "benchmark": {"kind": "buy_hold"}, "initial_capital": 100000,
        "constraints": {"long_only": True, "max_position": 1}, "risk_free_rate": 0.02,
    }
    first = lab.ensure_strategy(spec)
    # Simulate an object written by an earlier compiler release: the declaration is
    # identical but its derived operator-registry stamp is different.
    import json
    row = db.query_one("SELECT document_json FROM research_object WHERE object_id = ?",
                       (first["object_id"],))
    document = json.loads(row["document_json"])
    document["spec"]["signal"]["model_fingerprint"] = "historical-compiler-stamp"
    db.execute("UPDATE research_object SET document_json = ? WHERE object_id = ?",
               (json.dumps(document, sort_keys=True, separators=(",", ":")), first["object_id"]))
    reused = lab.ensure_strategy(spec)
    assert reused["object_id"] == first["object_id"]
    db.close()
