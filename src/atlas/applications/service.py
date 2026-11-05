"""Portable research-application lifecycle over the existing Atlas runtime."""

from __future__ import annotations

import copy
import hashlib
import json
import re
import time
from pathlib import Path
from typing import Any

from ..core.errors import MissingDataError, UnknownEntity, ValidationError
from ..core.temporal import iso, parse_iso, utcnow
from ..economic.model import run_weather_demand
from ..economic.scenario import run_scenario
from ..economic.service import EconomicService
from ..fec import compile_model
from ..fec.operators import REGISTRY
from ..fec.runtime import ExecutionEngine
from ..research.objects import ResearchObjectStore
from ..storage.db import Database
from .contracts import (
    APPLICATION_SCHEMA,
    RUNTIME_VERSION,
    PackageIntegrityError,
    MissingDependencyError,
    build_package,
    dependency_diagnostics,
    digest,
    pretty,
    read_package,
)
from .rights import DataRightsEngine, RightsViolation

INSTALL_SCHEMA = "atlas.application.installation.v1"
EXECUTION_SCHEMA = "atlas.application.execution.v1"
ECONOMIC_APPLICATION_ID = "atlas.firstparty.weather-demand-ercot"
ECONOMIC_RUNTIME = "atlas.economic.weather_demand.v1"


def _binary(payload: bytes) -> bytes:
    return payload


def _safe_slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.lower()).strip("-")
    return (slug or "application")[:60]


def _app_diff(left: dict[str, Any], right: dict[str, Any]) -> list[dict[str, Any]]:
    changes: list[dict[str, Any]] = []

    def walk(a: Any, b: Any, path: str) -> None:
        if isinstance(a, dict) and isinstance(b, dict):
            for key in sorted(set(a) | set(b)):
                walk(a.get(key), b.get(key), f"{path}.{key}" if path else key)
        elif isinstance(a, list) and isinstance(b, list):
            if a != b:
                changes.append({"path": path, "left": a, "right": b})
        elif a != b:
            changes.append({"path": path, "left": a, "right": b})

    walk(left, right, "")
    return changes


class ApplicationService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.objects = ResearchObjectStore(db)
        self.rights = DataRightsEngine(db)

    # ---------------------------------------------------------------- metadata
    def _source_rows(self, source_ids: list[str]) -> list[dict[str, Any]]:
        if not source_ids:
            return []
        marks = ",".join("?" for _ in source_ids)
        rows = self.db.query(
            f"SELECT source_id, name, kind, homepage, licence, redistribution, notes "
            f"FROM source WHERE source_id IN ({marks}) ORDER BY source_id",
            sorted(set(source_ids)),
        )
        return [dict(row) for row in rows]

    def _application_spec(self, run: dict[str, Any], scenario: dict[str, Any],
                          app_object: dict[str, Any], source_rows: list[dict[str, Any]],
                          version: str) -> dict[str, Any]:
        decisions = self.rights.decisions_for_metadata(source_rows)
        if any(not item["packaging_allowed"] for item in decisions):
            raise RightsViolation("this application cannot be exported under its source rights",
                                  decisions=decisions)
        financial = scenario.get("financial", {})
        names = ["mul", "energy_cost_impact", "neg", "after_tax_cost_impact", "margin_impact"]
        operators = [
            {"name": name, "version": REGISTRY[name].version}
            for name in names if name in REGISTRY
        ]
        limitations = list(dict.fromkeys(
            list(run.get("limitations", [])) +
            [finding.get("limitation", "") for finding in run.get("audit", {}).get("findings", [])
             if finding.get("limitation")] +
            [
                "The imported application reproduces a conditional association, not a causal effect.",
                "The 2023 archive has no historical publication vintage and cannot be replayed as-of 2023.",
                "The manufacturer load, contract, price and revenue are hypothetical.",
                "The test R² remains negative; this is not a validated forward demand forecast.",
            ]
        ))
        sources = []
        for row, decision in zip(source_rows, decisions):
            sources.append({
                "source_id": row["source_id"],
                "name": row["name"],
                "kind": row["kind"],
                "homepage": row.get("homepage"),
                "license": row.get("licence") or decision["license"],
                "redistribution": row["redistribution"],
                "rights_basis": decision["license"],
                "snapshot_paths": ["data/panel.json"],
            })
        views = [
            {"id": "evidence", "type": "evidence", "title": "Source identity and provenance"},
            {"id": "graph", "type": "graph", "title": "Economic evidence graph"},
            {"id": "association", "type": "chart", "title": "Chronological association result"},
            {"id": "scenario", "type": "scenario", "title": "Hypothetical financial consequence"},
            {"id": "uncertainty", "type": "uncertainty", "title": "Uncertainty decomposition"},
            {"id": "limitations", "type": "limitations", "title": "Known failures and vintage limits"},
        ]
        return {
            "schema": APPLICATION_SCHEMA,
            "application_id": ECONOMIC_APPLICATION_ID,
            "name": app_object.get("name") or "Weather → ERCOT demand → financial exposure",
            "version": version,
            "publisher": {"id": "atlas.first-party", "name": "Atlas Quant first-party"},
            "description": app_object.get("document", {}).get(
                "description",
                "Public NOAA/EIA weather-demand association with an explicitly hypothetical financial scenario.",
            ),
            "compatibility": {"minimum": "0.3.0", "maximum_exclusive": "0.4.0"},
            "runtime": {
                "kind": "economic_weather_demand",
                "model_runtime": ECONOMIC_RUNTIME,
                "seed": int(run.get("seed", 20261105)),
                "scenario_id": scenario.get("scenario_id"),
            },
            "dependencies": {
                "compiler": "atlas.fec.compiler.v1",
                "operators": operators,
                "model_runtime": ECONOMIC_RUNTIME,
                "datasets": [
                    {"source_id": row["source_id"], "required": True,
                     "redistribution": row["redistribution"]}
                    for row in source_rows
                ],
            },
            "inputs": [
                {"key": "shock_c", "type": "Scalar", "unit": "degC",
                 "default": float(scenario.get("shock_c", 2.0))},
                {"key": "annual_consumption_mwh", "type": "Scalar", "unit": "MWh",
                 "default": float(financial.get("annual_consumption_mwh", 50000))},
                {"key": "load_sensitivity", "type": "Scalar", "unit": "fraction",
                 "default": float(financial.get("load_sensitivity", 0.5))},
                {"key": "unhedged_fraction", "type": "Scalar", "unit": "fraction",
                 "default": float(financial.get("unhedged_fraction", 0.6))},
                {"key": "power_price_usd_mwh", "type": "Scalar", "unit": "USD/MWh",
                 "default": float(financial.get("power_price_usd_mwh", 65.0))},
                {"key": "revenue_usd", "type": "Scalar", "unit": "USD",
                 "default": float(financial.get("revenue_usd", 40_000_000))},
                {"key": "tax_rate", "type": "Scalar", "unit": "fraction",
                 "default": float(financial.get("tax_rate", 0.21))},
                {"key": "draws", "type": "Scalar", "unit": "count", "default": 2000},
            ],
            "outputs": [
                {"key": "demand_change_fraction", "unit": "fraction"},
                {"key": "cost_delta_usd", "unit": "USD"},
                {"key": "after_tax_cost_usd", "unit": "USD"},
                {"key": "margin_delta", "unit": "fraction"},
                {"key": "cost_interval_90_usd", "unit": "USD"},
            ],
            "views": views,
            "sources": sources,
            "capabilities": [
                "read_approved_snapshot", "execute_fec_operator",
                "render_declarative_ui", "write_application_state",
            ],
            "resources": {
                "max_package_bytes": 8 * 1024 * 1024,
                "max_memory_mb": 256,
                "max_execution_seconds": 30,
            },
            "license": "Apache-2.0 for package/runtime metadata; source data retains its listed public-domain terms.",
            "limitations": limitations,
            "created_at": run.get("as_of") or run.get("generated_at") or iso(utcnow()),
            "state": {
                "research_run_id": run.get("run_id"),
                "analysis_fingerprint": run.get("fingerprint"),
                "scenario_id": scenario.get("scenario_id"),
                "scenario_fingerprint": scenario.get("fingerprint"),
                "causal_status": run.get("causal_status", "not_identified"),
            },
        }

    def _readme(self, app: dict[str, Any], run: dict[str, Any]) -> bytes:
        lines = [
            f"# {app['name']}",
            "",
            f"Application ID: `{app['application_id']}`  ",
            f"Version: `{app['version']}`  ",
            f"Publisher: `{app['publisher']['id']}`  ",
            f"Runtime: `{app['runtime']['model_runtime']}`",
            "",
            app["description"],
            "",
            "## Evidence result",
            "",
            f"- Analysis: `{run.get('run_id')}`",
            f"- Selected form: `{run.get('selection', {}).get('selected_model')}`",
            f"- Test RMSE: {run.get('test', {}).get('rmse')} MW",
            f"- Test R²: {run.get('test', {}).get('r2')}",
            f"- Causal status: `{run.get('causal_status')}`",
            "",
            "## Limitations",
            "",
            *[f"- {item}" for item in app["limitations"]],
            "",
            "The package is declarative. It contains no executable Python, JavaScript or shell.",
            "The package build is deterministic; its unsigned hash proves integrity, not publisher identity.",
        ]
        return ("\n".join(lines) + "\n").encode("utf-8")

    def create_economic_package(self, run_id: str, *, scenario_id: str | None = None,
                                version: str = "1.0.0") -> dict[str, Any]:
        economic = EconomicService(self.db)
        run = economic.get_run(run_id)
        scenarios = economic.scenarios(run_id)
        scenario = None
        if scenario_id:
            scenario = next((item["result"] for item in scenarios if item["scenario_id"] == scenario_id), None)
            if scenario is None:
                raise UnknownEntity("unknown scenario for this analysis", scenario_id=scenario_id)
        elif scenarios:
            scenario = scenarios[0]["result"]
        else:
            scenario = economic.scenario(run_id)
        app_object_id = run.get("application_object_id")
        if app_object_id:
            app_object = self.objects.get(app_object_id)
        else:
            app_object = {
                "name": "Weather → ERCOT demand → financial exposure",
                "document": {
                    "description": "Public NOAA/EIA association with a hypothetical manufacturing exposure.",
                },
            }
        source_ids = run.get("dataset", {}).get("source_ids") or ["eia-930", "noaa-ghcn"]
        source_rows = self._source_rows(source_ids)
        if len(source_rows) != len(set(source_ids)):
            raise MissingDataError("source metadata is missing from the database", source_ids=source_ids)
        app = self._application_spec(run, scenario, app_object, source_rows, version)
        panel = economic.panel(as_of=run.get("generated_at"), mode="public_available")
        clean_run = {
            key: copy.deepcopy(value) for key, value in run.items()
            if key not in {
                "dataset_object_id", "model_object_id", "experiment_object_id",
                "application_object_id", "stored_duration_ms", "stored_created_at",
            }
        }
        sources_doc = {
            "schema": "atlas.application.sources.v1",
            "sources": app["sources"],
            "rights": app["sources"],
            "note": "Raw EIA/NOAA archives are not included; the canonical daily panel is included.",
        }
        files = {
            "data/panel.json": pretty(panel),
            "artifacts/analysis.json": pretty(clean_run),
            "artifacts/scenario.json": pretty(scenario),
            "sources.json": pretty(sources_doc),
            "README.md": self._readme(app, run),
        }
        file_metadata = [
            {"path": "data/panel.json", "role": "approved_source_snapshot",
             "rights": "public_domain", "source_ids": sorted(set(source_ids)),
             "media_type": "application/json"},
            {"path": "artifacts/analysis.json", "role": "analysis_result",
             "rights": "public_domain", "source_ids": sorted(set(source_ids)),
             "media_type": "application/json"},
            {"path": "artifacts/scenario.json", "role": "scenario_result",
             "rights": "public_domain", "source_ids": sorted(set(source_ids)),
             "media_type": "application/json"},
            {"path": "sources.json", "role": "rights_manifest", "rights": "public_domain",
             "source_ids": sorted(set(source_ids)), "media_type": "application/json"},
            {"path": "README.md", "role": "documentation", "rights": "public_domain",
             "source_ids": [], "media_type": "text/markdown"},
        ]
        payload = build_package(
            app, files, file_metadata=file_metadata, built_at=app["created_at"],
            source_revision=run.get("generated_at", "")[:10],
            reproducibility="computationally_reproducible",
        )
        loaded = read_package(payload)
        return {
            "payload": payload,
            "manifest": loaded["manifest"],
            "package_sha256": loaded["package_sha256"],
            "package_id": loaded["manifest"]["package_id"],
            "application_id": app["application_id"],
            "version": app["version"],
            "run_id": run_id,
            "scenario_id": scenario.get("scenario_id"),
            "reproducibility": loaded["manifest"]["reproducibility"]["level"],
        }

    def export_economic(self, run_id: str, destination: str | Path, *,
                        scenario_id: str | None = None, version: str = "1.0.0") -> dict[str, Any]:
        built = self.create_economic_package(run_id, scenario_id=scenario_id, version=version)
        path = Path(destination)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(built["payload"])
        return {key: value for key, value in built.items() if key != "payload"} | {
            "path": str(path),
        }

    def export_object(self, object_id: str, destination: str | Path, *,
                      scenario_id: str | None = None) -> dict[str, Any]:
        obj = self.objects.get(object_id)
        if obj["kind"] != "application":
            raise ValidationError("only application research objects can be packaged", kind=obj["kind"])
        run_id = (obj["document"].get("spec") or {}).get("run_id")
        if not run_id:
            raise ValidationError("application object does not reference an economic run")
        return self.export_economic(run_id, destination, scenario_id=scenario_id,
                                    version=obj["version"])

    # --------------------------------------------------------------- lifecycle
    def _installation_row(self, install_id: str):
        row = self.db.query_one("SELECT * FROM application_installation WHERE install_id = ?",
                                (install_id,))
        if row is None:
            raise UnknownEntity("unknown application installation", install_id=install_id)
        return row

    def _same_install(self, package_sha256: str) -> dict[str, Any] | None:
        row = self.db.query_one(
            "SELECT install_id FROM application_installation WHERE package_sha256 = ?",
            (package_sha256,),
        )
        return self.get(row["install_id"]) if row else None

    def _create_app_object(self, app: dict[str, Any], manifest: dict[str, Any]) -> str:
        document = {
            "schema_version": "atlas.research_object.v1",
            "kind": "application",
            "name": app["name"],
            "version": app["version"],
            "status": "validated",
            "description": app["description"],
            "as_of": app["created_at"],
            "mode": "atlas_ingested",
            "evidence_ids": [],
            "source_ids": [],
            "object_ids": [],
            "assumptions": [
                "The application package is declarative and uses the installed Atlas runtime.",
                "The application package's source snapshots retain their listed rights.",
            ],
            "limitations": app["limitations"],
            "spec": {
                "purpose": app["description"],
                "views": [view["id"] for view in app["views"]],
                "package_id": manifest["package_id"],
                "application_id": app["application_id"],
                "runtime": app["runtime"]["kind"],
                "reproducibility": manifest["reproducibility"]["level"],
            },
        }
        return self.objects.create(document)["object_id"]

    def install(self, payload: bytes, *, source_installation_id: str | None = None) -> dict[str, Any]:
        loaded = read_package(payload)
        manifest = loaded["manifest"]
        app = manifest["application"]
        decisions = self.rights.decisions_for_metadata(app["sources"])
        self.rights.assert_file_rights(manifest["files"], decisions)
        if not all(item["packaging_allowed"] for item in decisions):
            raise RightsViolation("package sources do not permit redistribution",
                                  source_ids=[item["source_id"] for item in decisions
                                               if not item["packaging_allowed"]])
        existing = self._same_install(loaded["package_sha256"])
        if existing:
            return existing | {"already_installed": True}
        duplicate = self.db.query_one(
            "SELECT install_id, package_sha256 FROM application_installation "
            "WHERE application_id = ? AND version = ? AND publisher_id = ?",
            (app["application_id"], app["version"], app["publisher"]["id"]),
        )
        if duplicate:
            raise ValidationError(
                "this application version is already installed with different content",
                install_id=duplicate["install_id"], application_id=app["application_id"],
                version=app["version"],
            )
        diagnostics = dependency_diagnostics(app)
        now = iso(utcnow())
        install_id = f"AINS-{loaded['package_sha256'][:20]}"
        status = "inspect_only" if diagnostics else "installed"
        with self.db.transaction():
            object_id = self._create_app_object(app, manifest)
            self.db.execute(
                "INSERT INTO application_installation (install_id, application_id, version, "
                "publisher_id, package_id, package_sha256, package_size, manifest_json, "
                "application_json, package_blob, status, reproducibility, trust_level, "
                "signature_status, object_id, source_installation_id, diagnostics_json, "
                "installed_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (install_id, app["application_id"], app["version"], app["publisher"]["id"],
                 manifest["package_id"], loaded["package_sha256"], loaded["size_bytes"],
                 pretty(manifest), pretty(app), _binary(payload), status,
                 manifest["reproducibility"]["level"], "declared_unsigned",
                 "unsigned", object_id, source_installation_id,
                 json.dumps(diagnostics, sort_keys=True), now, now),
            )
        return self.get(install_id)

    def verify(self, install_id: str) -> dict[str, Any]:
        row = self._installation_row(install_id)
        loaded = read_package(bytes(row["package_blob"]))
        if loaded["package_sha256"] != row["package_sha256"]:
            raise PackageIntegrityError("stored package hash does not match the installation",
                                        install_id=install_id)
        return {
            "schema": "atlas.application.verification.v1",
            "install_id": install_id,
            "status": "verified_integrity",
            "package_sha256": loaded["package_sha256"],
            "package_id": loaded["manifest"]["package_id"],
            "manifest_sha256": loaded["manifest_sha256"],
            "files": len(loaded["manifest"]["files"]),
            "signature_status": loaded["manifest"]["signature_status"],
            "publisher_verified": False,
            "note": "Integrity verified. No signature verifier is configured, so publisher identity is not authenticated.",
        }

    def get(self, install_id: str) -> dict[str, Any]:
        row = self._installation_row(install_id)
        manifest = json.loads(row["manifest_json"])
        app = json.loads(row["application_json"])
        diagnostics = json.loads(row["diagnostics_json"] or "[]")
        return {
            "schema": INSTALL_SCHEMA,
            "install_id": row["install_id"],
            "application_id": row["application_id"],
            "version": row["version"],
            "publisher_id": row["publisher_id"],
            "package_id": row["package_id"],
            "package_sha256": row["package_sha256"],
            "package_size": row["package_size"],
            "status": row["status"],
            "reproducibility": row["reproducibility"],
            "trust_level": row["trust_level"],
            "signature_status": row["signature_status"],
            "publisher_verified": False,
            "diagnostics": diagnostics,
            "object_id": row["object_id"],
            "source_installation_id": row["source_installation_id"],
            "installed_at": row["installed_at"],
            "updated_at": row["updated_at"],
            "application": app,
            "manifest": {
                "package_id": manifest["package_id"],
                "content_root": manifest["content_root"],
                "created_at": manifest["created_at"],
                "sources": manifest["sources"],
                "rights": manifest["rights"],
                "reproducibility": manifest["reproducibility"],
                "limitations": app["limitations"],
                "views": app["views"],
                "files": manifest["files"],
                "build": manifest["build"],
                "signature": manifest["signature"],
            },
        }

    def list(self, *, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT install_id FROM application_installation ORDER BY installed_at DESC, install_id LIMIT ?",
            (max(1, min(int(limit), 500)),),
        )
        return [self.get(row["install_id"]) for row in rows]

    def open(self, install_id: str) -> dict[str, Any]:
        row = self._installation_row(install_id)
        loaded = read_package(bytes(row["package_blob"]))
        app = loaded["manifest"]["application"]
        diagnostics = dependency_diagnostics(app)
        readme = loaded["files"].get("README.md", b"").decode("utf-8", errors="replace")
        return {
            **self.get(install_id),
            "status": "inspect_only" if diagnostics else row["status"],
            "diagnostics": diagnostics,
            "readme": readme,
            "package_verified": loaded["package_sha256"] == row["package_sha256"],
        }

    def export_bytes(self, install_id: str) -> tuple[bytes, str]:
        row = self._installation_row(install_id)
        loaded = read_package(bytes(row["package_blob"]))
        if loaded["package_sha256"] != row["package_sha256"]:
            raise PackageIntegrityError("stored package integrity failed", install_id=install_id)
        name = f"{_safe_slug(row['application_id'])}-{row['version']}.atlas"
        return bytes(row["package_blob"]), name

    def execute(self, install_id: str, inputs: dict[str, Any] | None = None) -> dict[str, Any]:
        loaded = read_package(bytes(self._installation_row(install_id)["package_blob"]))
        manifest = loaded["manifest"]
        app = manifest["application"]
        diagnostics = dependency_diagnostics(app)
        if diagnostics:
            result = {
                "schema": EXECUTION_SCHEMA, "install_id": install_id,
                "status": "inspect_only", "diagnostics": diagnostics,
                "reproduced": False,
                "reason": "required runtime, compiler or operators are unavailable",
            }
            self._persist_execution(install_id, result, 0.0)
            return result
        started = time.perf_counter()
        runtime = app["runtime"]["kind"]
        if runtime == "economic_weather_demand":
            result = self._execute_economic(app, loaded, inputs or {})
        elif runtime == "fec_model":
            result = self._execute_fec(app, loaded, inputs or {})
        else:  # pragma: no cover - validation prevents this
            raise MissingDependencyError("unsupported runtime", runtime=runtime)
        result.update({
            "schema": EXECUTION_SCHEMA, "install_id": install_id,
            "application_id": app["application_id"], "version": app["version"],
            "duration_ms": round((time.perf_counter() - started) * 1000, 3),
            "signature_status": manifest["signature_status"],
            "publisher_verified": False,
        })
        self._persist_execution(install_id, result, result["duration_ms"])
        return result

    def _execute_economic(self, app: dict[str, Any], loaded: dict[str, Any],
                          inputs: dict[str, Any]) -> dict[str, Any]:
        files = loaded["files"]
        panel = json.loads(files["data/panel.json"].decode("utf-8"))
        expected = json.loads(files["artifacts/analysis.json"].decode("utf-8"))
        expected_scenario = json.loads(files["artifacts/scenario.json"].decode("utf-8"))
        seed = int(app["runtime"].get("seed", 20261105))
        reproduced = run_weather_demand(panel, seed=seed)
        financial = expected_scenario.get("financial", {})
        shock = float(inputs.get("shock_c", expected_scenario.get("shock_c", 2.0)))
        draws = int(inputs.get("draws", 2000))
        if not 200 <= draws <= 20000:
            raise ValidationError("draws must be in [200,20000]")
        scenario = run_scenario(
            reproduced, db=self.db, shock_c=shock,
            annual_consumption_mwh=float(inputs.get("annual_consumption_mwh",
                                                    financial.get("annual_consumption_mwh", 50000))),
            load_sensitivity=float(inputs.get("load_sensitivity",
                                               financial.get("load_sensitivity", 0.5))),
            unhedged_fraction=float(inputs.get("unhedged_fraction",
                                               financial.get("unhedged_fraction", 0.6))),
            power_price_usd_mwh=float(inputs.get("power_price_usd_mwh",
                                                 financial.get("power_price_usd_mwh", 65.0))),
            revenue_usd=float(inputs.get("revenue_usd", financial.get("revenue_usd", 40000000))),
            tax_rate=float(inputs.get("tax_rate", financial.get("tax_rate", 0.21))),
            draws=draws, seed=int(inputs.get("seed", seed)),
        )
        fingerprint_match = reproduced.get("fingerprint") == expected.get("fingerprint")
        metric_match = (
            abs(float(reproduced["test"]["rmse"]) - float(expected["test"]["rmse"])) < 1e-6
            and abs(float(reproduced["test"]["r2"]) - float(expected["test"]["r2"])) < 1e-9
        )
        expected_cost = float(financial.get("cost_delta_usd", 0))
        actual_cost = float(scenario["financial"]["cost_delta_usd"])
        cost_match = abs(actual_cost - expected_cost) < 1e-6
        overridden = sorted(inputs)
        reproduced_ok = fingerprint_match and metric_match and (cost_match or bool(overridden))
        return {
            "status": ("reproduced_with_overrides" if overridden and reproduced_ok
                       else "reproduced" if reproduced_ok else "diverged"),
            "reproduced": reproduced_ok,
            "inputs_overridden": overridden,
            "scenario_matches_packaged_result": cost_match,
            "runtime": ECONOMIC_RUNTIME,
            "analysis": {
                "expected_fingerprint": expected.get("fingerprint"),
                "actual_fingerprint": reproduced.get("fingerprint"),
                "expected_test_rmse": expected.get("test", {}).get("rmse"),
                "actual_test_rmse": reproduced["test"]["rmse"],
                "expected_test_r2": expected.get("test", {}).get("r2"),
                "actual_test_r2": reproduced["test"]["r2"],
                "selected_model": reproduced["selection"]["selected_model"],
                "causal_status": reproduced["causal_status"],
                "conclusion": reproduced["conclusion"],
            },
            "scenario": {
                "shock_c": shock,
                "expected_cost_delta_usd": expected_cost,
                "actual_cost_delta_usd": actual_cost,
                "demand_change_fraction": scenario["demand"]["change_fraction"],
                "after_tax_cost_usd": scenario["financial"]["after_tax_cost_usd"],
                "margin_delta": scenario["financial"]["margin_delta"],
                "cost_interval_90_usd": scenario["financial"]["cost_interval_90"],
                "compiler_fingerprint": scenario["financial_compiler"]["fingerprint"],
            },
            "limitations": app["limitations"],
            "historical_integrity": {
                "vintage": expected.get("dataset", {}).get("vintage"),
                "causal_status": expected.get("causal_status"),
                "test_r2": expected.get("test", {}).get("r2"),
                "mean_error_mw": expected.get("test", {}).get("mean_error"),
                "company_exposure": "hypothetical",
                "replay_2023": "unsupported_without_historical_vintage",
            },
        }

    def _execute_fec(self, app: dict[str, Any], loaded: dict[str, Any],
                     inputs: dict[str, Any]) -> dict[str, Any]:
        model_spec = json.loads(loaded["files"]["artifacts/model.json"].decode("utf-8"))
        defaults = {item["key"]: item.get("default") for item in app["inputs"]
                    if item.get("default") is not None}
        values = {**defaults, **inputs}
        model = compile_model(model_spec)
        result = ExecutionEngine(self.db, use_cache=False).execute(model, values, persist=False)
        expected = {}
        if "artifacts/expected_outputs.json" in loaded["files"]:
            expected = json.loads(loaded["files"]["artifacts/expected_outputs.json"].decode("utf-8"))
        actual = result.get("outputs", {})
        match = all(
            abs(float(actual.get(key, 0)) - float(value)) < 1e-9
            for key, value in expected.items()
        ) if expected else True
        return {
            "status": "reproduced" if match else "diverged",
            "reproduced": match,
            "runtime": model_spec.get("schema_version"),
            "model_fingerprint": result.get("fingerprint"),
            "outputs": actual,
            "expected_outputs": expected or None,
            "compiler": result.get("manifest", {}).get("compiler_version"),
            "limitations": app["limitations"],
        }

    def _persist_execution(self, install_id: str, result: dict[str, Any], duration_ms: float) -> None:
        now = iso(utcnow())
        execution_id = f"AEX-{digest({'install': install_id, 'result': result, 'at': now})[:20].upper()}"
        self.db.execute(
            "INSERT INTO application_execution (execution_id, install_id, status, result_json, "
            "duration_ms, created_at) VALUES (?,?,?,?,?,?)",
            (execution_id, install_id, result.get("status", "unknown"),
             json.dumps(result, sort_keys=True, default=str), duration_ms, now),
        )

    def fork(self, install_id: str, *, name: str, version: str) -> dict[str, Any]:
        if not name.strip() or not re.match(r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$", version):
            raise ValidationError("fork requires a non-empty name and semantic version")
        loaded = read_package(bytes(self._installation_row(install_id)["package_blob"]))
        source_app = loaded["manifest"]["application"]
        new_app = copy.deepcopy(source_app)
        new_app["application_id"] = f"atlas.local.{_safe_slug(name)}-{digest([install_id, version])[:8]}"
        new_app["name"] = name.strip()
        new_app["version"] = version
        new_app["publisher"] = {"id": "local.user", "name": "Local Atlas user"}
        new_app["created_at"] = iso(utcnow())
        new_app["limitations"] = list(dict.fromkeys(
            list(new_app.get("limitations", [])) +
            [f"Forked locally from {source_app['application_id']} {source_app['version']}; not publisher endorsed."]
        ))
        files = dict(loaded["files"])
        files["application.json"] = pretty(new_app)
        payload = build_package(
            new_app, files, file_metadata=loaded["manifest"]["files"],
            built_at=new_app["created_at"],
            reproducibility=loaded["manifest"]["reproducibility"]["level"],
        )
        installed = self.install(payload, source_installation_id=install_id)
        return {
            "schema": "atlas.application.fork.v1",
            "source": {"install_id": install_id, "application_id": source_app["application_id"],
                       "version": source_app["version"]},
            "fork": installed,
            "comparison": self.compare(install_id, installed["install_id"]),
        }

    def compare(self, left_id: str, right_id: str) -> dict[str, Any]:
        left = self.get(left_id)
        right = self.get(right_id)
        changes = _app_diff(left["application"], right["application"])
        return {
            "schema": "atlas.application.compare.v1",
            "left": {"install_id": left_id, "application_id": left["application_id"],
                     "version": left["version"], "package_sha256": left["package_sha256"]},
            "right": {"install_id": right_id, "application_id": right["application_id"],
                      "version": right["version"], "package_sha256": right["package_sha256"]},
            "equal": not changes,
            "changes": changes,
        }

    def uninstall(self, install_id: str) -> dict[str, Any]:
        row = self._installation_row(install_id)
        with self.db.transaction():
            self.db.execute("DELETE FROM application_installation WHERE install_id = ?", (install_id,))
        return {
            "schema": "atlas.application.uninstall.v1",
            "install_id": install_id,
            "application_id": row["application_id"],
            "version": row["version"],
            "status": "uninstalled",
            "research_object_retained": row["object_id"] is not None,
            "note": "Uninstall removes the installation and package bytes. Research objects and execution history are retained.",
        }

    def gallery(self) -> dict[str, Any]:
        items = self.list()
        packs = self.db.query(
            "SELECT pack_id, version, publisher_id, installed_at FROM domain_pack_installation "
            "ORDER BY installed_at DESC"
        )
        return {
            "schema": "atlas.application.gallery.v1",
            "items": items,
            "count": len(items),
            "packs": [dict(item) for item in packs],
            "pack_count": len(packs),
            "search": "local installed applications only; no centralized marketplace",
            "note": "Unsigned packages are integrity-checked local declarations, not verified publisher artifacts.",
        }

    def counts(self) -> dict[str, int]:
        return {
            "applications": int(self.db.scalar("SELECT COUNT(*) FROM application_installation", default=0) or 0),
            "executions": int(self.db.scalar("SELECT COUNT(*) FROM application_execution", default=0) or 0),
            "domain_packs": int(self.db.scalar("SELECT COUNT(*) FROM domain_pack_installation", default=0) or 0),
        }


__all__ = ["ApplicationService", "ECONOMIC_APPLICATION_ID", "ECONOMIC_RUNTIME"]
