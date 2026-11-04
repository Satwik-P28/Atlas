"""Workspace document and persistence tests (no third-party validation library)."""

from __future__ import annotations

import pytest

from atlas.core.errors import StorageError, ValidationError
from atlas.entities.master import SecurityMaster
from atlas.storage.db import Database
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.store import WatchlistStore, WorkspaceStore
from atlas.terminal.workspaces import fingerprint, presets, validate_workspace


def test_presets_are_validated_documents():
    for preset in presets():
        assert preset["schema"] == "atlas.workspace.v1"
        assert preset["panels"]
        assert all(panel["type"] for panel in preset["panels"])
        assert all(1 <= panel["span"] <= preset["columns"] for panel in preset["panels"])


def test_validation_rejects_unknown_shapes():
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "panels": [{"id": "a", "type": "chart", "security_id": "S", "config": {"eval": "1"}}]})
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "unexpected": True, "panels": presets()[0]["panels"]})
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "panels": []})
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "panels": [{"id": "a", "type": "chart", "span": 1}]})  # missing security_id
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "panels": [
            {"id": "a", "type": "chart", "security_id": "S", "span": 1},
            {"id": "a", "type": "chart", "security_id": "S", "span": 1},
        ]})


def test_standard_mode_rejects_advanced_panels():
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "mode": "standard", "panels": [
            {"id": "a", "type": "xray", "evidence_id": "EV-1", "span": 1}
        ]})


def test_chart_indicator_references_are_validated():
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "panels": [
            {"id": "a", "type": "chart", "security_id": "S", "span": 1,
             "config": {"indicators": [{"key": "sma", "params": {"window": 50, "typo": 1}}]}}
        ]})
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "panels": [
            {"id": "a", "type": "chart", "security_id": "S", "span": 1,
             "config": {"indicators": [{"key": "magic_indicator"}]}}
        ]})


def test_span_cannot_exceed_columns():
    with pytest.raises(ValidationError):
        validate_workspace({"name": "x", "columns": 2, "panels": [
            {"id": "a", "type": "chart", "security_id": "S", "span": 3}
        ]})


def test_fingerprint_is_stable_and_order_sensitive():
    document = presets()[0]
    assert fingerprint(document) == fingerprint({**document})
    reordered = {**document, "panels": list(reversed(document["panels"]))}
    assert fingerprint(document) != fingerprint(reordered)


@pytest.fixture()
def store_db(tmp_path):
    db = Database(tmp_path / "workspaces.db")
    db.migrate()
    ensure_default_sources(db)
    master = SecurityMaster(db)
    issuer = master.register_issuer(legal_name="Test Co", cik="0000000042", source_id="sec-edgar")
    master.ensure_venue("XNAS", "Nasdaq")
    security = master.ensure_security(issuer, class_designation="common stock", currency="USD")
    listing = master.ensure_listing(security, "XNAS", valid_from="2020-01-01", is_primary=True)
    master.assign_ticker(listing, "TST", valid_from="2024-01-01", confidence=0.6,
                         status="probable", source_id="sec-edgar")
    yield {"db": db, "issuer": issuer, "security": security}
    db.close()


def test_workspace_store_persists_and_rejects_duplicates(store_db):
    db = store_db["db"]
    store = WorkspaceStore(db)
    document = {
        "name": "My layout",
        "mode": "advanced",
        "columns": 2,
        "panels": [{"id": "c", "type": "chart", "security_id": store_db["security"], "span": 2}],
    }
    created = store.create(document)
    assert created["document"]["panels"][0]["config"]["view"] == "split"  # server filled defaults

    reopened = WorkspaceStore(db)
    assert reopened.get(created["workspace_id"])["fingerprint"] == created["fingerprint"]

    with pytest.raises(StorageError):
        store.create(document)

    updated = store.update(created["workspace_id"], {**document, "columns": 1,
                                                     "panels": [{**document["panels"][0], "span": 1}]})
    assert updated["document"]["columns"] == 1

    store.delete(created["workspace_id"])
    with pytest.raises(ValidationError):
        store.get(created["workspace_id"])


def test_watchlist_references_stable_security_ids(store_db):
    store = WatchlistStore(store_db["db"])
    watchlist = store.create("Core", security_ids=[store_db["security"]])
    assert watchlist["items"][0]["ticker"] == "TST"
    assert watchlist["items"][0]["security_id"] == store_db["security"]

    # Idempotent add does not duplicate or reorder.
    again = store.add_item(watchlist["watchlist_id"], store_db["security"])
    assert len(again["items"]) == 1

    with pytest.raises(ValidationError):
        store.add_item(watchlist["watchlist_id"], "AAPL")  # a ticker is not an identity

    with pytest.raises(ValidationError):
        store.reorder(watchlist["watchlist_id"], ["SEC-unrelated"])
