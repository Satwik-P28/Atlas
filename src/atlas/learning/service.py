"""Phase 6 orchestration and persistence."""

from __future__ import annotations

import json
import uuid
from datetime import date
from typing import Any

from ..core.errors import UnknownEntity, ValidationError
from ..core.temporal import iso, iso_date, utcnow
from ..research.objects import ResearchObjectStore
from ..storage.db import Database
from .contracts import (
    continuous_forecast_document,
    experiment_document,
    forecast_document,
    model_document,
)
from .data import catalog, load_panel
from .experiments import run_experiment
from .features import DEFAULT_FEATURES, catalogue
from .metrics import summarize
from .models import MODEL_LIBRARY, model_metadata, predict
from .monitoring import compare_validation_to_test, feature_drift, realized_calibration

LEARNING_SCHEMA = "atlas.learning.run.v2"


class LearningService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.objects = ResearchObjectStore(db)

    def catalog(self) -> dict[str, Any]:
        datasets = catalog(self.db)
        return {
            "schema": LEARNING_SCHEMA,
            "datasets": datasets,
            "features": catalogue(),
            "models": [dict(item) for item in MODEL_LIBRARY],
            "providers": __import__("atlas.learning.data", fromlist=["PROVIDERS"]).PROVIDERS,
            "forecast_schema": "atlas.forecast.v1",
            "targets": catalogue()["targets"],
            "limitations": [
                "Observed provider rows are not point-in-time verified without a vintage archive.",
                "Restricted vendor data is retained locally and is not redistributed.",
                "Forecast skill is not the same as economic value.",
            ],
        }

    def run(
        self,
        *,
        dataset: str | None = None,
        source_id: str | None = None,
        models: list[str] | None = None,
        features: list[str] | None = None,
        target: str = "direction",
        seed: int = 20261105,
        persist: bool = True,
        hypothesis: str | None = None,
    ) -> dict[str, Any]:
        panel = load_panel(self.db, dataset=dataset, source_id=source_id)
        result = run_experiment(
            panel, models=models, features=features, target=target, seed=seed,
            hypothesis=hypothesis or "Point-in-time price and volume features improve next-session probability forecasts over climatology.",
        )
        return self._persist(panel, result) if persist else result

    def run_from_panel(self, panel: dict[str, Any], *, persist: bool = False,
                       **kwargs: Any) -> dict[str, Any]:
        result = run_experiment(panel, **kwargs)
        return self._persist(panel, result) if persist else result

    def _persist(self, panel: dict[str, Any], result: dict[str, Any]) -> dict[str, Any]:
        run_id = result["run_id"]
        existing = self.db.query_one("SELECT run_id FROM learning_run WHERE run_id = ?", (run_id,))
        if existing:
            return self.get_run(run_id)
        now = iso(utcnow())
        fingerprint = __import__("atlas.learning.contracts", fromlist=["digest"]).digest(result)
        spec = {
            "models": [item["model"] for item in result["attempts"]],
            "features": result["features"], "target": result.get("target_key", "direction"),
            "seed": result["model"]["artifact"].get("seed"),
            "hypothesis": result["hypothesis"], "split": result["split"],
        }
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO learning_run (run_id, kind, dataset_id, source_id, target, data_class, "
                "as_of, start_date, end_date, spec_json, result_json, fingerprint, status, duration_ms, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, "experiment", result["dataset"]["dataset_id"], result["dataset"]["source_id"],
                 result.get("target_key", "direction"), result["dataset"]["data_class"], iso(utcnow()),
                 result["dataset"]["start"], result["dataset"]["end"], json.dumps(spec, sort_keys=True),
                 json.dumps(result, sort_keys=True, default=str), fingerprint, "succeeded",
                 result["duration_ms"], now),
            )
            for index, attempt in enumerate(result["attempts"], start=1):
                self.db.execute(
                    "INSERT INTO learning_attempt (attempt_id, run_id, stage, model_key, rank, selected, "
                    "metrics_json, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (f"LATT-{uuid.uuid4().hex[:18]}", run_id, attempt["stage"], attempt["model"],
                     int(attempt.get("rank", index)), int(bool(attempt.get("selected"))),
                     json.dumps(attempt.get("metrics") or {"error": attempt.get("error")}, sort_keys=True), now),
                )
        source_ids = [result["dataset"]["source_id"]]
        model_name = f"{result['selection']['selected_label']} · {run_id[-6:]}"
        model_object = self.objects.create(model_document(
            name=model_name, version=result["model"]["version"],
            artifact=result["model"]["artifact"], result=result, source_ids=source_ids,
        ))
        experiment_object = self.objects.create(experiment_document(
            name=f"Learning experiment · {run_id[-6:]}", run=result,
            model_object_id=model_object["object_id"], source_ids=source_ids,
        ))
        model_id = f"LMOD-{uuid.uuid4().hex[:16]}"
        artifact = result["model"]["artifact"]
        metadata = {
            "run_id": run_id, "data_class": result["dataset"]["data_class"],
            "rights": result["dataset"]["rights"], "split": result["split"],
            "test": result["test"], "audit": result["audit"], "conclusion": result["conclusion"],
            "software": artifact.get("software"), "source_hash": result["dataset"]["content_hash"],
        }
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO learning_model (model_id, run_id, object_id, name, version, family, target, "
                "dataset_id, data_class, feature_schema_json, artifact_json, metadata_json, fingerprint, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (model_id, run_id, model_object["object_id"], model_name, result["model"]["version"],
                 result["selection"]["selected_family"], result.get("target_key", "direction"), result["dataset"]["dataset_id"],
                 result["dataset"]["data_class"], json.dumps(result["features"], sort_keys=True),
                 json.dumps(artifact, sort_keys=True, default=str),
                 json.dumps(metadata, sort_keys=True, default=str), result["model"]["fingerprint"], now),
            )
            for item in result["forecasts"]:
                forecast = forecast_document(
                    model_id=model_id, security_id=item["security_id"], as_of=item["date"],
                    horizon=1, probability=item["probability"], data_class=result["dataset"]["data_class"],
                )
                self.db.execute(
                    "INSERT INTO learning_forecast (forecast_id, run_id, model_id, security_id, as_of, "
                    "horizon, probability, lower, upper, outcome, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                    (forecast["forecast_id"], run_id, model_id, item["security_id"], item["date"], 1,
                     item["probability"], None, None, item.get("target"), now),
                )
            self.db.execute(
                "UPDATE learning_run SET model_object_id = ?, experiment_object_id = ?, result_json = ? WHERE run_id = ?",
                (model_object["object_id"], experiment_object["object_id"],
                 json.dumps(result, sort_keys=True, default=str), run_id),
            )
        result["model_object_id"] = model_object["object_id"]
        result["experiment_object_id"] = experiment_object["object_id"]
        result["model_id"] = model_id
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM learning_run WHERE run_id = ?", (run_id,))
        if row is None:
            raise UnknownEntity("unknown learning run", run_id=run_id)
        result = json.loads(row["result_json"])
        result["run_id"] = row["run_id"]
        result["model_object_id"] = row["model_object_id"]
        result["experiment_object_id"] = row["experiment_object_id"]
        model = self.db.query_one("SELECT model_id FROM learning_model WHERE run_id = ?", (run_id,))
        result["model_id"] = model["model_id"] if model else None
        return result

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT run_id, dataset_id, target, data_class, start_date, end_date, status, "
            "duration_ms, result_json, created_at FROM learning_run ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        items = []
        for row in rows:
            item = dict(row)
            result = json.loads(item.pop("result_json"))
            items.append({**item, "conclusion": result.get("conclusion"),
                          "selected_model": result.get("selection", {}).get("selected_model"),
                          "test_brier": result.get("test", {}).get("brier"),
                          "brier_skill": result.get("test", {}).get("brier_skill_vs_climatology"),
                          "audit_counts": result.get("audit", {}).get("counts")})
        return items

    def models(self, limit: int = 100) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT model_id, run_id, object_id, name, version, family, target, dataset_id, "
            "data_class, fingerprint, metadata_json, created_at FROM learning_model "
            "ORDER BY created_at DESC LIMIT ?", (max(1, min(int(limit), 200)),),
        )
        return [ {**{key: row[key] for key in row.keys() if key != "metadata_json"},
                  "metadata": json.loads(row["metadata_json"])} for row in rows]

    def forecast(self, run_id: str, security_id: str | None = None) -> dict[str, Any]:
        run = self.get_run(run_id)
        forecasts = run.get("forecasts") or []
        if security_id:
            forecasts = [item for item in forecasts if item["security_id"] == security_id]
        if not forecasts:
            raise ValidationError("run has no stored test forecasts", run_id=run_id,
                                  security_id=security_id)
        latest = max(item["date"] for item in forecasts)
        selected = [item for item in forecasts if item["date"] == latest]
        model = self.db.query_one("SELECT model_id FROM learning_model WHERE run_id = ?", (run_id,))
        if model is None:
            raise ValidationError("run has no stored model artifact", run_id=run_id)
        return {
            "schema": "atlas.forecast.v1", "run_id": run_id, "model_id": model["model_id"],
            "as_of": latest, "horizon_sessions": 1,
            "forecasts": [
                forecast_document(model_id=model["model_id"], security_id=item["security_id"],
                                  as_of=item["date"], horizon=1, probability=item["probability"],
                                  data_class=run["dataset"]["data_class"])
                for item in selected
            ],
            "note": "These are test-interval forecasts, not a live trading recommendation.",
        }

    def monitor(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        row = self.db.query_one(
            "SELECT artifact_json, feature_schema_json FROM learning_model WHERE run_id = ?", (run_id,)
        )
        if row is None:
            raise ValidationError("run has no model artifact", run_id=run_id)
        panel = load_panel(self.db, dataset=run["dataset"]["dataset_id"])
        artifact = json.loads(row["artifact_json"])
        features = json.loads(row["feature_schema_json"])
        drift = feature_drift(panel, artifact, features)
        calibration = realized_calibration(run.get("forecasts") or [])
        return {
            "schema": "atlas.learning.monitor.v1", "run_id": run_id,
            "drift": drift, "calibration": calibration,
            "validation_vs_test": compare_validation_to_test(
                {"brier": run["selection"]["brier"], "observations": run["split"]["validation"]["rows"]},
                run["test"],
            ),
            "automatic_retrain": False,
            "automatic_deployment": False,
            "sample_sizes": {"test_forecasts": len(run.get("forecasts") or []),
                             "recent_sessions": drift["recent_sessions"]},
        }

    def memory(self, *, target: str | None = None, model: str | None = None,
               conclusion: str | None = None, limit: int = 100) -> dict[str, Any]:
        items = self.list_runs(limit=limit)
        if target:
            items = [item for item in items if item["target"] == target]
        if model:
            items = [item for item in items if item["selected_model"] == model]
        if conclusion:
            items = [item for item in items if item["conclusion"] == conclusion]
        return {
            "schema": "atlas.learning.memory.v1",
            "items": items,
            "counts": {
                "runs": len(items),
                "not_supported": sum(1 for item in items if item["conclusion"] == "not_supported"),
                "inconclusive": sum(1 for item in items if item["conclusion"] == "inconclusive"),
                "supported": sum(1 for item in items
                                 if item["conclusion"] == "validation_supported_with_caveats"),
            },
            "note": "Memory is the persisted experiment ledger; it is usable without an LLM.",
        }

    def portfolio_experiment(self, run_id: str, *, security_id: str, threshold: float = 0.55,
                             commission_bps: float = 2.0, slippage_bps: float = 5.0) -> dict[str, Any]:
        from ..quant.lab import QuantLab
        from ..quant.simulator import SimulationConfig

        if not 0.0 <= threshold <= 1.0:
            raise ValidationError("threshold must be in [0,1]")
        run = self.get_run(run_id)
        rows = [item for item in run.get("forecasts") or [] if item["security_id"] == security_id]
        if len(rows) < 20:
            raise ValidationError("not enough test forecasts for a portfolio experiment",
                                  security_id=security_id, forecasts=len(rows))
        dates = sorted({item["date"] for item in rows})
        spec = {
            "schema_version": "atlas.strategy.v1",
            "name": f"Learning probability · {run_id[-6:]} · {security_id[-8:]} · t{threshold:.2f}",
            "version": "1.0.0",
            "description": "Frozen out-of-sample probability forecasts mapped to a long-only next-open rule.",
            "universe": {"instruments": [{"security_id": security_id, "mic": "XNAS"}]},
            "features": [{"name": "close", "kind": "price", "window": 1}],
            "signal": {
                "kind": "learning_probability", "threshold": float(threshold),
                "forecasts": [{"date": item["date"], "probability": float(item["probability"])}
                              for item in rows],
                "model_id": run.get("model_id"), "forecast_run_id": run_id,
            },
            "decision_frequency": "daily",
            "execution": {"signal_at": "close", "fill_at": "next_open",
                          "commission_bps": commission_bps, "slippage_bps": slippage_bps},
            "initial_capital": 100_000.0,
            "constraints": {"long_only": True, "max_position": 1.0},
            "risk_free_rate": 0.0,
            "benchmark": {"kind": "buy_hold"},
            "source_ids": [run["dataset"]["source_id"]],
        }
        config = SimulationConfig(as_of=dates[-1], start=dates[0], end=dates[-1],
                                  commission_bps=commission_bps, slippage_bps=slippage_bps)
        backtest = QuantLab(self.db).run(spec=spec, config=config, persist=True,
                                         hypothesis=f"Frozen learning probabilities above {threshold:.2f} produce a positive net strategy result.")
        application_name = f"Forecast to portfolio · {run_id[-6:]} · {security_id[-8:]} · t{threshold:.2f}"
        existing_application = self.db.query_one(
            "SELECT object_id FROM research_object WHERE owner_id = 'local' AND kind = 'application' "
            "AND name = ? AND version = '1.0.0'", (application_name,)
        )
        if existing_application:
            application = self.objects.get(existing_application["object_id"])
        else:
            application = self.objects.create({
                "schema_version": "atlas.research_object.v1", "kind": "application",
                "name": application_name,
                "version": "1.0.0", "status": "validated",
                "description": "A frozen learning forecast converted into a declared long-only rule and reconciled by the existing event-driven simulator.",
                "as_of": iso(utcnow()), "mode": "atlas_ingested", "evidence_ids": [],
                "source_ids": [run["dataset"]["source_id"]],
                "object_ids": [run.get("model_object_id")] if run.get("model_object_id") else [],
                "assumptions": ["The test forecasts are frozen before this simulation."],
                "limitations": run.get("limitations", []),
                "spec": {
                    "purpose": "forecast-to-portfolio", "views": ["forecast", "backtest", "audit"],
                    "learning_run_id": run_id, "security_id": security_id,
                    "threshold": threshold, "strategy_object_id": backtest.get("strategy_object_id"),
                    "backtest": {"metrics": backtest.get("metrics"),
                                 "result_fingerprint": backtest.get("result_fingerprint")},
                },
            })
        return {"schema": "atlas.learning.portfolio.v1", "run_id": run_id,
                "security_id": security_id, "threshold": threshold,
                "backtest": backtest, "application": application,
                "interpretation": "Predictive evaluation and strategy economics are separate claims."}

    def discovery(self, *, budget: int = 6, dataset: str | None = None) -> dict[str, Any]:
        from .discovery import discover
        panel = load_panel(self.db, dataset=dataset)
        return discover(panel, budget=budget)


__all__ = ["LEARNING_SCHEMA", "LearningService"]
