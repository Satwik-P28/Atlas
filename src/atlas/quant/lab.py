"""Quant Lab orchestration: strategy objects, runs, experiments and Time Capsules."""

from __future__ import annotations

import copy
import hashlib
import json
import uuid
from datetime import date
from typing import Any

from ..core.errors import UnknownEntity, ValidationError
from ..core.temporal import iso, iso_date, utcnow
from ..market.bars import BarStore
from ..research.archive import SourceArchiveStore
from ..research.objects import ResearchObjectStore
from ..storage.db import Database
from .contracts import (
    LAB_VERSION,
    experiment_document,
    strategy_document,
    strategy_fingerprint,
    validate_strategy,
)
from .simulator import SIMULATOR_VERSION, SimulationConfig, run_simulation

LAB_SCHEMA = "atlas.quant.lab.v1"


def _instrument_meta(db: Database, security_id: str, mic: str) -> dict[str, Any]:
    row = db.query_one(
        "SELECT s.security_id, s.issuer_id, s.class_designation, i.legal_name, i.cik "
        "FROM security s JOIN issuer i ON i.issuer_id = s.issuer_id WHERE s.security_id = ?",
        (security_id,),
    )
    if row is None:
        raise ValidationError("unknown strategy instrument", security_id=security_id)
    ticker = db.query_one(
        "SELECT ta.ticker FROM ticker_assignment ta JOIN listing l ON l.listing_id = ta.listing_id "
        "WHERE l.security_id = ? ORDER BY ta.valid_from DESC LIMIT 1", (security_id,)
    )
    coverage = BarStore(db).coverage(security_id, mic)
    return {**dict(row), "ticker": ticker["ticker"] if ticker else None,
            "mic": mic, "coverage": coverage}


def universe(db: Database, *, limit: int = 100) -> list[dict[str, Any]]:
    rows = db.query(
        "SELECT s.security_id, s.issuer_id, s.class_designation, i.legal_name, i.cik, "
        "l.mic, COUNT(DISTINCT b.ts_utc) AS sessions, MIN(b.ts_utc) AS first_bar, "
        "MAX(b.ts_utc) AS last_bar "
        "FROM security s JOIN issuer i ON i.issuer_id = s.issuer_id "
        "JOIN listing l ON l.security_id = s.security_id AND l.is_primary = 1 "
        "JOIN bar b ON b.security_id = s.security_id AND b.mic = l.mic "
        "GROUP BY s.security_id, s.issuer_id, s.class_designation, i.legal_name, i.cik, l.mic "
        "HAVING sessions >= 2 ORDER BY sessions DESC, i.legal_name LIMIT ?",
        (max(1, min(int(limit), 300)),),
    )
    result = []
    for row in rows:
        item = dict(row)
        ticker = db.query_one(
            "SELECT ta.ticker FROM ticker_assignment ta JOIN listing l ON l.listing_id = ta.listing_id "
            "WHERE l.security_id = ? ORDER BY ta.valid_from DESC LIMIT 1", (row["security_id"],)
        )
        item["ticker"] = ticker["ticker"] if ticker else None
        item["source_ids"] = [r["source_id"] for r in db.query(
            "SELECT DISTINCT source_id FROM bar WHERE security_id = ? AND mic = ?",
            (row["security_id"], row["mic"]),
        )]
        result.append(item)
    return result


def _source_ids_for(db: Database, security_id: str, mic: str) -> list[str]:
    rows = db.query(
        "SELECT DISTINCT source_id FROM bar WHERE security_id = ? AND mic = ? ORDER BY source_id",
        (security_id, mic),
    )
    return [row["source_id"] for row in rows]


class QuantLab:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.objects = ResearchObjectStore(db)
        self.archives = SourceArchiveStore(db)

    def ensure_strategy(self, spec: dict[str, Any], *, as_of: str | date | None = None,
                        mode: str = "atlas_ingested") -> dict[str, Any]:
        normalised = validate_strategy(spec)
        instrument = normalised["universe"]["instruments"][0]
        source_ids = _source_ids_for(self.db, instrument["security_id"], instrument["mic"])
        if not source_ids:
            raise ValidationError("strategy instrument has no market observations",
                                  security_id=instrument["security_id"])
        normalised["source_ids"] = source_ids
        document = strategy_document(normalised, as_of=as_of, mode=mode)
        existing = self.db.query_one(
            "SELECT object_id FROM research_object WHERE owner_id = 'local' AND kind = 'strategy' "
            "AND name = ? AND version = ?",
            (document["name"], document["version"]),
        )
        if existing:
            current = self.objects.get(existing["object_id"])
            if current["document"].get("spec") != document["spec"]:
                raise ValidationError(
                    "a different strategy already uses this name and version; change the name or version",
                    name=document["name"], version=document["version"],
                    existing_object_id=existing["object_id"],
                )
            return current
        return self.objects.create(document)

    def create_strategy(self, spec: dict[str, Any], *, as_of: str | date | None = None,
                        mode: str = "atlas_ingested") -> dict[str, Any]:
        return self.ensure_strategy(spec, as_of=as_of, mode=mode)

    def list_strategies(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.objects.list(kind="strategy", limit=limit)

    def list_experiments(self, limit: int = 100) -> list[dict[str, Any]]:
        return self.objects.list(kind="experiment", limit=limit)

    def run(
        self,
        *,
        strategy_id: str | None = None,
        spec: dict[str, Any] | None = None,
        config: SimulationConfig | None = None,
        persist: bool = True,
        hypothesis: str | None = None,
        experiment_name: str | None = None,
        experiment_version: str = "1.0.0",
    ) -> dict[str, Any]:
        if strategy_id:
            stored = self.objects.get(strategy_id)
            if stored["kind"] != "strategy":
                raise ValidationError("run requires a strategy object", kind=stored["kind"])
            strategy_spec = stored["document"]["spec"]
            strategy_name = stored["name"]
        elif spec is not None:
            stored = self.ensure_strategy(spec)
            strategy_spec = stored["document"]["spec"]
            strategy_name = stored["name"]
            strategy_id = stored["object_id"]
        else:
            raise ValidationError("provide either strategy_id or spec")
        result = run_simulation(self.db, strategy_spec, config=config)
        result["strategy_object_id"] = strategy_id
        result["strategy_name"] = strategy_name
        result["hypothesis"] = hypothesis
        result["lab_schema"] = LAB_SCHEMA
        result["simulator_version"] = SIMULATOR_VERSION
        run_id = f"QRUN-{uuid.uuid4().hex[:20]}"
        result["run_id"] = run_id
        result["created_at"] = iso(utcnow())
        experiment_object_id = None
        if persist:
            source_ids = [item["source_id"] for item in result["credibility"]["data_sources"]]
            source_ids = sorted(set(source_ids))
            self.db.execute(
                "INSERT INTO quant_run (run_id, strategy_object_id, strategy_fingerprint, "
                "experiment_object_id, as_of, mode, start_date, end_date, universe_json, config_json, "
                "result_json, reconciliation_json, metrics_json, status, duration_ms, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, strategy_id, strategy_fingerprint(strategy_spec), None,
                 result["config"]["as_of"], result["config"]["mode"],
                 result["period"]["start"], result["period"]["end"],
                 json.dumps(result["security"], sort_keys=True),
                 json.dumps(result["config"], sort_keys=True),
                 json.dumps(result, sort_keys=True, default=str),
                 json.dumps(result["reconciliation"], sort_keys=True),
                 json.dumps(result["metrics"], sort_keys=True),
                 "succeeded", result["duration_ms"], result["created_at"]),
            )
            name = experiment_name or f"{strategy_name} · {run_id[-6:]}"
            document = experiment_document(
                name=name, version=experiment_version, run=result,
                strategy_object_id=strategy_id, as_of=result["config"]["as_of"],
                mode=result["config"]["mode"], source_ids=source_ids,
            )
            # The strategy object is linked explicitly; the experiment is immutable.
            experiment = self.objects.create(document)
            experiment_object_id = experiment["object_id"]
            self.db.execute(
                "UPDATE quant_run SET experiment_object_id = ? WHERE run_id = ?",
                (experiment_object_id, run_id),
            )
        result["experiment_object_id"] = experiment_object_id
        return result

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM quant_run WHERE run_id = ?", (run_id,))
        if row is None:
            raise UnknownEntity("unknown quantitative run", run_id=run_id)
        payload = json.loads(row["result_json"])
        payload["run_id"] = row["run_id"]
        payload["strategy_object_id"] = row["strategy_object_id"]
        payload["experiment_object_id"] = row["experiment_object_id"]
        return payload

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT run_id, strategy_object_id, experiment_object_id, as_of, start_date, end_date, "
            "status, duration_ms, metrics_json, created_at FROM quant_run "
            "ORDER BY created_at DESC, run_id LIMIT ?", (max(1, min(int(limit), 200)),)
        )
        items = []
        for row in rows:
            item = dict(row)
            item["metrics"] = json.loads(item.pop("metrics_json"))
            items.append(item)
        return items

    def capsule(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        strategy = self.objects.get(run["strategy_object_id"]) if run.get("strategy_object_id") else None
        experiment = self.objects.get(run["experiment_object_id"]) if run.get("experiment_object_id") else None
        source_ids = [item["source_id"] for item in run.get("credibility", {}).get("data_sources", [])]
        archive = self.archives.status_for_sources(source_ids)
        bar_rows = self.db.query(
            "SELECT security_id, mic, interval, COUNT(*) AS rows, MIN(ts_utc) AS first_bar, "
            "MAX(ts_utc) AS last_bar, MAX(revision_seq) AS max_revision "
            "FROM bar WHERE security_id = ? GROUP BY security_id, mic, interval",
            (run["security"]["security_id"],),
        )
        actions = self.db.query(
            "SELECT action_id, action_type, ex_date, ratio_from, ratio_to, cash_amount, "
            "availability_time, status FROM corporate_action WHERE security_id = ? "
            "AND (? IS NULL OR ex_date <= ?) ORDER BY ex_date, action_id",
            (run["security"]["security_id"], run["config"]["end"], run["config"]["end"]),
        )
        return {
            "schema": "atlas.time_capsule.v1",
            "run_id": run_id,
            "strategy": strategy,
            "experiment": experiment,
            "bars": [dict(row) for row in bar_rows],
            "corporate_actions": [dict(row) for row in actions],
            "feature_metadata": run.get("feature_metadata"),
            "strategy_spec": run.get("strategy"),
            "simulation_config": run.get("config"),
            "execution_engine_version": run.get("simulator_version"),
            "result_fingerprint": run.get("result_fingerprint"),
            "source_archives": archive,
            "reproducibility": {
                "status": archive["status"],
                "fully_reproducible": archive["status"] == "archived",
                "note": ("Archived bytes are available for every cited provider."
                         if archive["status"] == "archived"
                         else "The numerical result is reconstructable from processed observations, "
                              "but original provider bytes are not fully archived."),
            },
            "decision_trace_available": bool(run.get("trades") is not None),
            "created_at": run.get("created_at"),
        }

    def replay(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        config = SimulationConfig(
            as_of=run["config"]["as_of"], start=run["config"]["start"],
            end=run["config"]["end"], initial_capital=run["config"]["initial_capital"],
            commission_bps=run["config"]["commission_bps"],
            slippage_bps=run["config"]["slippage_bps"], mode=run["config"]["mode"],
        )
        replay = run_simulation(self.db, run["strategy"], config=config)
        return {
            "run_id": run_id,
            "reproduced": replay["result_fingerprint"] == run.get("result_fingerprint"),
            "original_fingerprint": run.get("result_fingerprint"),
            "replay_fingerprint": replay["result_fingerprint"],
            "original_end_equity": run.get("metrics", {}).get("end_equity"),
            "replay_end_equity": replay.get("metrics", {}).get("end_equity"),
            "differences": [] if replay["result_fingerprint"] == run.get("result_fingerprint")
            else ["The stored run and replay do not have the same fingerprint."],
        }

    def builtin_templates(self) -> list[dict[str, Any]]:
        model_spec = {
            "schema_version": "atlas.model.v1", "name": "Price / SMA signal",
            "version": "1.0.0", "interface": "equation",
            "inputs": {"close": "Price[USD]", "sma": "Price[USD]"},
            "equations": [{"name": "signal", "expr": "close / sma - 1"}],
            "outputs": ["signal"], "metadata": {"purpose": "custom Quant Lab signal"},
        }
        return [
            {
                "key": "buy_hold", "label": "Buy and hold",
                "description": "Fully invested from the first executable session open.",
                "features": [{"name": "close", "kind": "price", "window": 1}],
                "signal": {"kind": "buy_hold"},
            },
            {
                "key": "sma_cross", "label": "Trend following",
                "description": "Hold when the 20-session mean is above the 100-session mean.",
                "features": [{"name": "close", "kind": "price", "window": 1}],
                "signal": {"kind": "sma_cross", "fast": 20, "slow": 100},
            },
            {
                "key": "momentum", "label": "Momentum",
                "description": "Hold when the 60-session return is positive.",
                "features": [{"name": "close", "kind": "price", "window": 1}],
                "signal": {"kind": "momentum", "fast": 60, "threshold": 0.0},
            },
            {
                "key": "custom_model", "label": "Custom Model Forge signal",
                "description": "Hold when close / 20-session SMA - 1 is positive; the signal is evaluated by the typed compiler.",
                "features": [{"name": "close", "kind": "price", "window": 1},
                             {"name": "sma20", "kind": "sma", "window": 20}],
                "signal": {"kind": "model", "model_spec": model_spec,
                           "input_map": {"close": "close", "sma": "sma20"},
                           "output": "signal"},
            },
        ]


def template_spec(template: dict[str, Any], instrument: dict[str, Any],
                  *, name: str) -> dict[str, Any]:
    spec = copy.deepcopy(template)
    spec.pop("key", None)
    spec.pop("label", None)
    spec.pop("description", None)
    spec.update({
        "schema_version": "atlas.strategy.v1",
        "name": name,
        "version": "1.0.0",
        "description": template.get("description", ""),
        "universe": {"instruments": [{"security_id": instrument["security_id"],
                                       "mic": instrument["mic"]}]},
        "decision_frequency": "daily",
        "execution": {"signal_at": "close", "fill_at": "next_open",
                      "commission_bps": 2.0, "slippage_bps": 5.0},
        "initial_capital": 100_000.0,
        "constraints": {"long_only": True, "max_position": 1.0},
        "risk_free_rate": 0.02,
        "benchmark": {"kind": "buy_hold"},
    })
    return spec


__all__ = ["LAB_SCHEMA", "QuantLab", "template_spec", "universe"]
