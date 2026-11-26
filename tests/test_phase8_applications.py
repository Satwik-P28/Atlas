"""Phase 8: deterministic packages, enforced rights and portable application lifecycles."""

from __future__ import annotations

import base64
import copy
import io
import json
import zipfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from atlas.applications.contracts import (
    PACKAGE_SCHEMA,
    MissingDependencyError,
    PackageIntegrityError,
    PackageValidationError,
    build_package,
    pretty,
    read_package,
)
from atlas.applications.packs import DomainPackService
from atlas.applications.rights import DataRightsEngine, RightsViolation
from atlas.applications.sdk import build_source, load_source, scaffold
from atlas.applications.sdk import test_source as sdk_test_source
from atlas.applications.service import ApplicationService
from atlas.core.temporal import iso, utcnow
from atlas.economic.service import EconomicService
from atlas.storage.db import Database
from atlas.storage.migrations import LATEST_VERSION
from atlas.storage.safety import migrate_safely
from atlas.storage.sources import ensure_default_sources
from atlas.terminal.api import create_app


@pytest.fixture(scope="module")
def flagship(tmp_path_factory):
    root = tmp_path_factory.mktemp("phase8-flagship")
    db = Database(root / "source.db")
    db.migrate()
    ensure_default_sources(db)
    economic = EconomicService(db)
    economic.bootstrap()
    run = economic.analyze(as_of=iso(utcnow()), persist=True)
    scenario = economic.scenario(run["run_id"])
    service = ApplicationService(db)
    built = service.create_economic_package(run["run_id"], scenario_id=scenario["scenario_id"])
    package_path = root / "flagship.atlas"
    package_path.write_bytes(built["payload"])
    result = {
        "root": root,
        "db_path": root / "source.db",
        "run": run,
        "scenario": scenario,
        "payload": built["payload"],
        "manifest": built["manifest"],
        "package_path": package_path,
        "package_sha256": built["package_sha256"],
    }
    db.close()
    return result


def _fresh(path: Path) -> Database:
    db = Database(path)
    db.migrate()
    ensure_default_sources(db)
    return db


def _rezip(entries: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name in sorted(entries):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            archive.writestr(info, entries[name])
    return buffer.getvalue()


def test_schema_10_and_application_tables(tmp_path):
    db = Database(tmp_path / "schema.db")
    assert db.migrate() == list(range(1, 16))
    assert LATEST_VERSION == 15
    assert db.schema_version() == 15
    tables = {row["name"] for row in db.query("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"application_installation", "application_execution", "domain_pack_installation"} <= tables
    db.close()


def test_flagship_package_is_deterministic_declarative_and_explicitly_unsigned(flagship):
    payload = flagship["payload"]
    assert payload == ApplicationService(Database(flagship["db_path"], create=False)).create_economic_package(
        flagship["run"]["run_id"], scenario_id=flagship["scenario"]["scenario_id"]
    )["payload"]
    loaded = read_package(payload)
    manifest = loaded["manifest"]
    assert manifest["schema"] == PACKAGE_SCHEMA
    assert manifest["package_id"] == f"APKG-{manifest['content_root'][:20]}"
    assert manifest["signature"] is None
    assert manifest["signature_status"] == "unsigned"
    assert manifest["trust"]["publisher_verified"] is False
    assert manifest["reproducibility"]["level"] == "computationally_reproducible"
    assert manifest["application"]["runtime"]["model_runtime"] == "atlas.economic.weather_demand.v1"
    assert all(not item["path"].endswith((".py", ".js", ".sh", ".exe")) for item in manifest["files"])
    assert {item["path"] for item in manifest["files"]} >= {
        "application.json", "data/panel.json", "artifacts/analysis.json",
        "artifacts/scenario.json", "sources.json", "README.md",
    }
    analysis = json.loads(loaded["files"]["artifacts/analysis.json"])
    assert abs(analysis["test"]["rmse"] - 2956.577890101359) < 1e-9
    assert abs(analysis["test"]["r2"] + 0.8934655019352953) < 1e-12
    assert analysis["causal_status"] == "not_identified"
    scenario = json.loads(loaded["files"]["artifacts/scenario.json"])
    assert scenario["financial"]["cost_interval_90"][0] < scenario["financial"]["cost_delta_usd"]
    assert scenario["financial"]["cost_interval_90"][1] > scenario["financial"]["cost_delta_usd"]
    assert "hypothetical" in json.dumps(scenario).lower()


def test_path_traversal_tampering_and_forbidden_file_types_are_rejected(flagship):
    loaded = read_package(flagship["payload"])
    entries = dict(loaded["files"])
    entries["manifest.json"] = pretty(loaded["manifest"])
    entries["../escape.json"] = b"{}"
    with pytest.raises(PackageValidationError):
        read_package(_rezip(entries))

    with pytest.raises(PackageValidationError):
        read_package(_rezip({
            "manifest.json": pretty(loaded["manifest"]),
            "application.json": loaded["files"]["application.json"],
            "run.py": b"print('no')",
        }))

    tampered = dict(loaded["files"])
    tampered["data/panel.json"] = b'{"rows":[]}'
    tampered["manifest.json"] = pretty(loaded["manifest"])
    with pytest.raises(PackageIntegrityError):
        read_package(_rezip(tampered))


def test_rights_fail_closed_for_restricted_sources_and_package_files(flagship):
    app = copy.deepcopy(flagship["manifest"]["application"])
    app["sources"][0]["redistribution"] = "restricted"
    with pytest.raises(RightsViolation):
        build_package(app, {"application.json": pretty(app)})
    decisions = DataRightsEngine.decisions_for_metadata(app["sources"])
    first = next(item for item in decisions if item["source_id"] == app["sources"][0]["source_id"])
    assert first["actions"]["packaging"]["allowed"] is False
    assert first["actions"]["export"]["allowed"] is False
    assert first["actions"]["redistribution"]["allowed"] is False
    assert first["actions"]["analysis"]["allowed"] is True


def test_unsatisfied_operator_dependency_is_inspect_only(flagship):
    app = copy.deepcopy(flagship["manifest"]["application"])
    app["dependencies"]["operators"][0]["version"] = "0.0.0-not-installed"
    with pytest.raises(MissingDependencyError):
        build_package(app, {"application.json": pretty(app)})


def test_clean_install_execute_export_fork_compare_and_uninstall(flagship, tmp_path):
    db = _fresh(tmp_path / "clean.db")
    try:
        service = ApplicationService(db)
        installed = service.install(flagship["payload"])
        assert installed["status"] == "installed"
        assert installed["package_sha256"] == flagship["package_sha256"]
        assert installed["reproducibility"] == "computationally_reproducible"
        again = service.install(flagship["payload"])
        assert again["already_installed"] is True
        assert service.verify(installed["install_id"])["status"] == "verified_integrity"

        result = service.execute(installed["install_id"])
        assert result["status"] == "reproduced"
        assert result["reproduced"] is True
        assert abs(result["analysis"]["actual_test_rmse"] - 2956.577890101359) < 1e-9
        assert abs(result["analysis"]["actual_test_r2"] + 0.8934655019352953) < 1e-12
        assert result["scenario"]["expected_cost_delta_usd"] == pytest.approx(
            result["scenario"]["actual_cost_delta_usd"]
        )
        assert result["historical_integrity"]["company_exposure"] == "hypothetical"
        assert result["historical_integrity"]["replay_2023"] == "unsupported_without_historical_vintage"

        exported, filename = service.export_bytes(installed["install_id"])
        assert exported == flagship["payload"]
        assert filename.endswith(".atlas")
        assert service.gallery()["count"] == 1
        assert service.open(installed["install_id"])["package_verified"] is True
        assert service.execute(installed["install_id"], {"shock_c": 4.0})["reproduced"] is True

        forked = service.fork(installed["install_id"], name="Independent reanalysis", version="1.0.1")
        assert forked["source"]["install_id"] == installed["install_id"]
        assert forked["fork"]["status"] == "installed"
        assert forked["comparison"]["equal"] is False
        assert any(change["path"] == "name" for change in forked["comparison"]["changes"])
        assert service.verify(forked["fork"]["install_id"])["status"] == "verified_integrity"

        removed = service.uninstall(installed["install_id"])
        assert removed["research_object_retained"] is True
        assert db.scalar("SELECT COUNT(*) FROM application_execution") >= 1
        assert db.scalar("SELECT COUNT(*) FROM research_object") >= 1
    finally:
        db.close()


def test_clean_install_from_a_separately_created_database(flagship, tmp_path):
    """Import the package into a database that never saw the source panel."""
    db = _fresh(tmp_path / "import.db")
    try:
        assert db.scalar("SELECT COUNT(*) FROM economic_observation") == 0
        service = ApplicationService(db)
        installed = service.install(flagship["payload"])
        assert db.scalar("SELECT COUNT(*) FROM economic_observation") == 0
        result = service.execute(installed["install_id"])
        assert result["reproduced"] is True
        assert result["analysis"]["actual_test_rmse"] == pytest.approx(2956.577890101359)
        assert db.scalar("SELECT COUNT(*) FROM economic_observation") == 0
    finally:
        db.close()


def test_transactional_install_rolls_back_on_object_validation(flagship, tmp_path, monkeypatch):
    db = _fresh(tmp_path / "rollback.db")
    try:
        service = ApplicationService(db)

        def fail(*args, **kwargs):
            raise PackageIntegrityError("injected post-validation failure")

        monkeypatch.setattr(service, "_create_app_object", fail)
        with pytest.raises(PackageIntegrityError):
            service.install(flagship["payload"])
        assert db.scalar("SELECT COUNT(*) FROM application_installation") == 0
        assert db.scalar("SELECT COUNT(*) FROM research_object") == 0
    finally:
        db.close()


def test_domain_pack_installs_through_the_declarative_contract(flagship, tmp_path):
    root = tmp_path / "pack"
    root.mkdir()
    package_path = root / "flagship.atlas"
    package_path.write_bytes(flagship["payload"])
    pack = {
        "schema": "atlas.domain_pack.v1",
        "pack_id": "atlas.energy-research",
        "name": "Energy research essentials",
        "version": "1.0.0",
        "publisher": {"id": "atlas.first-party", "name": "Atlas first-party"},
        "license": "Apache-2.0",
        "compatibility": {"minimum": "0.3.0", "maximum_exclusive": "0.4.0"},
        "kind": "declarative",
        "dependencies": {"compiler": "atlas.fec.compiler.v1", "operators": []},
        "capabilities": ["execute_fec_operator", "render_declarative_ui"],
        "sources": [{"source_id": "eia-930", "redistribution": "permitted"}],
        "resources": {"max_package_bytes": 8 * 1024 * 1024},
        "object_types": ["weather_demand_analysis"],
        "validation": {"mode": "package-integrity-and-runtime-reproduction"},
        "test_vectors": [{"name": "flagship reproduces", "expected": "reproduced"}],
        "limitations": ["No real-estate templates are included in Phase 8."],
        "applications": [{"path": "flagship.atlas", "sha256": flagship["package_sha256"]}],
        "created_at": "2026-11-05T00:00:00Z",
    }
    pack_path = root / "pack.json"
    pack_path.write_text(json.dumps(pack), encoding="utf-8")
    db = _fresh(tmp_path / "pack.db")
    try:
        packs = DomainPackService(db)
        installed = packs.install(pack_path)
        assert installed["executable_code"] is False
        assert len(installed["applications"]) == 1
        assert packs.list()[0]["pack_id"] == "atlas.energy-research"
        assert ApplicationService(db).gallery()["pack_count"] == 1
        removed = packs.uninstall("atlas.energy-research", "1.0.0")
        assert removed["applications_retained"]
        assert ApplicationService(db).gallery()["count"] == 1
    finally:
        db.close()


def test_unsafe_pack_paths_and_executable_pack_content_are_rejected(tmp_path):
    db = _fresh(tmp_path / "badpack.db")
    try:
        with pytest.raises(Exception):
            DomainPackService(db).install({
                "schema": "atlas.domain_pack.v1", "pack_id": "bad", "name": "Bad",
                "version": "1.0.0", "publisher": {"id": "x"}, "license": "none",
                "compatibility": {}, "kind": "declarative", "dependencies": {},
                "capabilities": [], "sources": [], "resources": {}, "object_types": [],
                "validation": {}, "test_vectors": [{"name": "x"}], "limitations": ["x"],
                "applications": [{"path": "../escape.atlas"}], "created_at": "2026-01-01T00:00:00Z",
            })
    finally:
        db.close()


def test_migration_safety_backs_up_and_upgrades(tmp_path):
    path = tmp_path / "upgrade.db"
    db = Database(path)
    assert db.migrate(target=9) == list(range(1, 10))
    db.execute("INSERT INTO app_setting (owner_id, key, value, updated_at) VALUES (?,?,?,?)",
               ("local", "keep", '"me"', "2026-01-01T00:00:00Z"))
    db.close()
    upgraded = Database(path)
    try:
        result = migrate_safely(upgraded, backup_dir=tmp_path / "backups")
        assert result["status"] == "migrated"
        assert result["from_version"] == 9 and result["to_version"] == 15
        assert result["backup_path"] and Path(result["backup_path"]).exists()
        assert upgraded.schema_version() == 15
        assert upgraded.scalar("SELECT value FROM app_setting WHERE key = 'keep'") == '"me"'
        assert upgraded.integrity_check() == "ok"
    finally:
        upgraded.close()


def test_sdk_scaffold_test_build_and_extract(tmp_path):
    project = tmp_path / "sdk-project"
    created = scaffold(project, name="Market cap example")
    source = load_source(created["path"])
    assert source["application"]["runtime"]["kind"] == "fec_model"
    tested = sdk_test_source(created["path"])
    assert tested["status"] == "valid" and tested["executable_plugin_code"] is False
    output = tmp_path / "sdk.atlas"
    built = build_source(created["path"], output)
    assert built["package_id"].startswith("APKG-")
    assert built["package_sha256"] and output.exists()
    loaded = read_package(output.read_bytes())
    assert loaded["manifest"]["reproducibility"]["level"] == "fully_reproducible"
    assert "artifacts/model.json" in loaded["files"]


def test_real_first_party_pack_fixture_installs(flagship, tmp_path):
    root = Path(__file__).resolve().parents[1]
    pack_path = root / "fixtures" / "phase8" / "energy_research_pack.json"
    fixture_package = read_package((root / "fixtures" / "phase8" /
                                    "flagship_weather_demand.atlas").read_bytes())
    assert pack_path.exists()
    db = _fresh(tmp_path / "real-pack.db")
    try:
        installed = DomainPackService(db).install(pack_path)
        assert installed["pack_id"] == "atlas.energy-research"
        assert len(installed["applications"]) == 1
        assert ApplicationService(db).gallery()["count"] == 1
        assert installed["manifest"]["applications"][0]["sha256"] == fixture_package["package_sha256"]
    finally:
        db.close()


def test_cli_sdk_and_real_pack_commands(tmp_path, capsys):
    from atlas.cli import main

    project = tmp_path / "cli-project"
    package = tmp_path / "cli.atlas"
    db_path = tmp_path / "cli.db"
    assert main(["--db", str(db_path), "app", "init", str(project), "--name", "CLI example"]) == 0
    assert main(["--db", str(db_path), "--json", "app", "test", "--file", str(project / "atlas.app.json")]) == 0
    assert main(["--db", str(db_path), "--json", "app", "build", "--file",
                 str(project / "atlas.app.json"), "--out", str(package)]) == 0
    assert package.exists()
    assert main(["--db", str(db_path), "--json", "app", "install", "--package", str(package)]) == 0
    assert main(["--db", str(db_path), "--json", "app", "list"]) == 0
    assert main(["--db", str(db_path), "--json", "app", "verify", "--package", str(package)]) == 0
    assert main(["--db", str(db_path), "--json", "doctor"]) == 0
    pack_db = tmp_path / "cli-pack.db"
    root = Path(__file__).resolve().parents[1]
    assert main(["--db", str(pack_db), "--json", "app", "pack", "install", "--file",
                 str(root / "fixtures" / "phase8" / "energy_research_pack.json")]) == 0
    assert main(["--db", str(pack_db), "--json", "app", "pack", "list"]) == 0
    output = capsys.readouterr().out
    assert "atlas.energy-research" in output


def test_application_api_base64_roundtrip(flagship, tmp_path):
    path = tmp_path / "api.db"
    db = _fresh(path)
    db.close()
    client = TestClient(create_app(path))
    health = client.get("/api/health").json()
    assert health["schema_version"] == 15
    assert health["application_installations"] == 0
    assert client.get("/api/applications").json()["count"] == 0
    installed = client.post("/api/applications/install", json={
        "package_base64": base64.b64encode(flagship["payload"]).decode("ascii"),
    })
    assert installed.status_code == 201, installed.text
    install_id = installed.json()["install_id"]
    gallery = client.get("/api/applications").json()
    assert gallery["count"] == 1
    assert client.get(f"/api/applications/{install_id}/open").json()["package_verified"] is True
    verified = client.get(f"/api/applications/{install_id}/verify").json()
    assert verified["publisher_verified"] is False
    executed = client.post(f"/api/applications/{install_id}/execute", json={"inputs": {"shock_c": 2.0}})
    assert executed.status_code == 200, executed.text
    assert executed.json()["reproduced"] is True
    downloaded = client.get(f"/api/applications/{install_id}/download")
    assert downloaded.status_code == 200
    assert downloaded.content == flagship["payload"]
    assert downloaded.headers["content-type"] == "application/zip"
    forked = client.post(f"/api/applications/{install_id}/fork", json={
        "name": "API fork", "version": "1.0.1",
    })
    assert forked.status_code == 201, forked.text
    compared = client.get(f"/api/applications/{install_id}/compare", params={
        "right": forked.json()["fork"]["install_id"],
    }).json()
    assert compared["equal"] is False
    removed = client.delete(f"/api/applications/{install_id}")
    assert removed.status_code == 200
    assert client.get("/api/applications").json()["count"] == 1
