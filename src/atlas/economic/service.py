"""Phase 7 economic intelligence orchestration."""

from __future__ import annotations

import json
import time
from typing import Any

from ..core.errors import MissingDataError, UnknownEntity, ValidationError
from ..core.temporal import iso, parse_iso, utcnow
from ..research.objects import ResearchObjectStore
from ..storage.db import Database
from . import data
from .contracts import ECONOMIC_SCHEMA, digest, stable_id
from .model import run_weather_demand
from .scenario import run_scenario

RUN_SCHEMA = "atlas.economic.analysis.v1"


class EconomicService:
    def __init__(self, db: Database) -> None:
        self.db = db
        self.objects = ResearchObjectStore(db)

    # ------------------------------------------------------------------ ingest
    def bootstrap(self) -> dict[str, Any]:
        return data.bootstrap(self.db)

    def catalog(self) -> dict[str, Any]:
        result = data.catalog(self.db)
        result["recent_analyses"] = self.list_runs(limit=20)
        result["causal_methods"] = [
            "observational association (implemented; not causal)",
            "two-by-two difference-in-differences (implemented for defensible designs)",
            "interrupted time series with level and slope change (implemented)",
        ]
        result["simulator"] = {
            "schema": "atlas.economic.scenario.v1",
            "deterministic": True,
            "monte_carlo": True,
            "financial_compiler": "atlas.fec.compiler.v1",
            "methods": ["degree-day conditional demand", "parameter draws", "sensitivity grids"],
        }
        return result

    def panel(self, *, as_of: str | None = None, mode: str = "public_available") -> dict[str, Any]:
        return data.load_panel(self.db, as_of=as_of, mode=mode)

    def graph(self, *, as_of: str | None = None, entity_id: str | None = None,
              depth: int = 2) -> dict[str, Any]:
        return data.graph(self.db, as_of=as_of, entity_id=entity_id, depth=depth)

    def conflicts(self) -> dict[str, Any]:
        items = data.list_conflicts(self.db)
        claims = self.db.query(
            "SELECT claim_id, subject_key, predicate, value_numeric, unit, source_id, "
            "epistemic_status, causal_status, claimed_at, observation_id FROM economic_claim "
            "ORDER BY claimed_at, claim_id"
        )
        claim_map = {row["claim_id"]: dict(row) for row in claims}
        for item in items:
            item["claims"] = [claim_map[claim_id] for claim_id in item["claim_ids"] if claim_id in claim_map]
        logical = [item for item in items if item.get("status") == "unresolved"]
        spatial = [item for item in items if item.get("status") == "spatial_representativeness"]
        return {
            "schema": "atlas.economic.conflicts.v1",
            "items": items,
            "count": len(items),
            "logical_conflict_count": len(logical),
            "spatial_representativeness_count": len(spatial),
            "policy": (
                "Different point locations are spatial representativeness, not a logical contradiction. "
                "Genuine same-subject value contradictions are preserved without choosing a winner."
            ),
        }

    # ------------------------------------------------------------------ model
    def analyze(self, *, as_of: str | None = None, mode: str = "public_available",
                seed: int = 20261105, persist: bool = True) -> dict[str, Any]:
        panel = data.load_panel(self.db, as_of=as_of, mode=mode)
        started = time.perf_counter()
        result = run_weather_demand(panel, seed=seed)
        result["seed"] = seed
        result["panel_completeness"] = panel["completeness"]
        result["duration_ms"] = round((time.perf_counter() - started) * 1000, 3)
        if persist:
            return self._persist(result)
        return result

    def _ensure_object(self, document: dict[str, Any]) -> dict[str, Any]:
        try:
            return self.objects.create(document)
        except ValidationError as exc:
            if "already exists" not in str(exc):
                raise
            row = self.db.query_one(
                "SELECT object_id FROM research_object WHERE owner_id = 'local' AND kind = ? "
                "AND name = ? AND version = ?",
                (document["kind"], document["name"], document["version"]),
            )
            if row is None:
                raise
            return self.objects.get(row["object_id"])

    def _object_documents(self, result: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        run_id = result["run_id"]
        source_ids = result["dataset"]["source_ids"]
        dataset = self._ensure_object({
            "schema_version": "atlas.research_object.v1", "kind": "dataset",
            "name": f"ERCOT daily demand + Dallas GHCN weather 2023 · {result['dataset']['content_hash'][:8]}",
            "version": "1.0.0",
            "status": "validated", "description": "Public daily panel joining EIA-930 ERCOT demand "
            "with two NCEI Dallas station temperature records.",
            "as_of": result["generated_at"], "mode": "atlas_ingested", "evidence_ids": [],
            "source_ids": source_ids,
            "assumptions": ["EIA Data Date is the local operating day.",
                            "Daily temperature mean is the average of station TMAX and TMIN."],
            "limitations": result["limitations"],
            "spec": {
                "universe": {"region": "ERCO", "station": "USW00013960",
                             "comparison_station": "USW00003971", "securities": []},
                "fields": ["demand_mean_mw", "temperature_mean_c", "cdd_18c", "hdd_18c"],
                "frequency": "daily",
                "adjustment": "No infilling; current public archive with retrieval availability proxy.",
            },
        })
        method = {
            "family": result["selection"]["selected_model"],
            "features": result["model"]["feature_names"],
            "split": result["split"],
            "causal_status": "association",
            "identification": "none",
            "selection_metric": "validation_rmse",
        }
        model = self._ensure_object({
            "schema_version": "atlas.research_object.v1", "kind": "model",
            "name": f"Weather-demand association · {run_id[-8:]}", "version": "1.0.0",
            "status": "validated", "description": "A same-day degree-day association between "
            "Dallas station temperature and ERCOT mean demand; not a causal model.",
            "as_of": result["generated_at"], "mode": "atlas_ingested", "evidence_ids": [],
            "source_ids": source_ids, "object_ids": [dataset["object_id"]],
            "assumptions": ["Observed same-day temperature is available.",
                            "A linear/quadratic degree-day form is adequate for this narrow slice."],
            "limitations": result["limitations"],
            "spec": {
                "inputs": result["model"]["feature_names"],
                "outputs": ["mean demand MW", "association coefficient", "parameter covariance"],
                "method": method,
                "assumptions": ["Association only; no treatment assignment."],
                "validation": {"test": result["test"], "baseline": result["baseline"],
                               "test_used_for_selection": False},
            },
        })
        experiment = self._ensure_object({
            "schema_version": "atlas.research_object.v1", "kind": "experiment",
            "name": f"Weather-to-electricity experiment · {run_id[-8:]}", "version": "1.0.0",
            "status": "validated", "description": "Chronological weather-demand experiment with a "
            "seasonal baseline, two degree-day specifications and an untouched test interval.",
            "as_of": result["generated_at"], "mode": "atlas_ingested", "evidence_ids": [],
            "source_ids": source_ids,
            "object_ids": [dataset["object_id"], model["object_id"]],
            "assumptions": ["The test interval is not used for model selection."],
            "limitations": result["limitations"],
            "spec": {
                "hypothesis": "Dallas-area temperature is associated with ERCOT daily mean demand.",
                "method": {"split": result["split"], "candidates": list(result["candidates"]),
                           "selection": result["selection"], "seed": result.get("seed")},
                "metrics": {"test": result["test"], "baseline": result["baseline"],
                            "skill_vs_seasonal": result["skill_vs_seasonal"]},
            },
        })
        return dataset, model, experiment

    def _persist(self, result: dict[str, Any]) -> dict[str, Any]:
        run_id = result["run_id"]
        existing = self.db.query_one("SELECT run_id FROM economic_analysis WHERE run_id = ?", (run_id,))
        if existing:
            return self.get_run(run_id)
        dataset, model, experiment = self._object_documents(result)
        result["dataset_object_id"] = dataset["object_id"]
        result["model_object_id"] = model["object_id"]
        result["experiment_object_id"] = experiment["object_id"]
        now = iso(utcnow())
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO economic_analysis (run_id, kind, as_of, mode, data_class, start_date, "
                "end_date, spec_json, result_json, fingerprint, model_object_id, experiment_object_id, "
                "status, stale, stale_reason, duration_ms, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (run_id, "weather_demand_association", result["generated_at"], "public_available",
                 result["dataset"]["data_class"], result["dataset"]["start"], result["dataset"]["end"],
                 json.dumps({"seed": result.get("seed"), "features": result["model"]["feature_names"],
                             "split": result["split"], "selection": result["selection"]}, sort_keys=True),
                 json.dumps(result, sort_keys=True, default=str), result["fingerprint"],
                 model["object_id"], experiment["object_id"], "succeeded", 0, None,
                 result["duration_ms"], now),
            )
            observations = self.db.query(
                "SELECT observation_id, series_id FROM economic_observation WHERE series_id IN (?,?,?)",
                (data.SERIES_DEMAND, data.SERIES_DFW, data.SERIES_REDBIRD),
            )
            for row in observations:
                self.db.execute(
                    "INSERT INTO economic_dependency (run_id, dependency_type, dependency_id, role, "
                    "stale, invalidated_at, reason) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                    (run_id, "observation", row["observation_id"], "input", 0, None, None),
                )
            for series_id in (data.SERIES_DEMAND, data.SERIES_DFW, data.SERIES_REDBIRD):
                self.db.execute(
                    "INSERT INTO economic_dependency (run_id, dependency_type, dependency_id, role, "
                    "stale, invalidated_at, reason) VALUES (?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                    (run_id, "series", series_id, "input", 0, None, None),
                )
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM economic_analysis WHERE run_id = ?", (run_id,))
        if row is None:
            raise UnknownEntity("unknown economic analysis", run_id=run_id)
        result = json.loads(row["result_json"])
        result["run_id"] = row["run_id"]
        result["status"] = row["status"]
        result["stale"] = bool(row["stale"])
        result["stale_reason"] = row["stale_reason"]
        result["model_object_id"] = row["model_object_id"]
        result["experiment_object_id"] = row["experiment_object_id"]
        result["application_object_id"] = row["application_object_id"]
        result["stored_duration_ms"] = row["duration_ms"]
        result["stored_created_at"] = row["created_at"]
        return result

    def list_runs(self, limit: int = 50) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT run_id, kind, as_of, mode, data_class, start_date, end_date, fingerprint, "
            "status, stale, stale_reason, duration_ms, created_at, result_json "
            "FROM economic_analysis ORDER BY created_at DESC LIMIT ?",
            (max(1, min(int(limit), 200)),),
        )
        items = []
        for row in rows:
            result = json.loads(row["result_json"])
            items.append({
                "run_id": row["run_id"], "kind": row["kind"], "as_of": row["as_of"],
                "mode": row["mode"], "data_class": row["data_class"],
                "start": row["start_date"], "end": row["end_date"],
                "status": row["status"], "stale": bool(row["stale"]),
                "stale_reason": row["stale_reason"], "created_at": row["created_at"],
                "selected_model": result.get("selection", {}).get("selected_model"),
                "conclusion": result.get("conclusion"),
                "test_rmse": result.get("test", {}).get("rmse"),
                "baseline_rmse": result.get("baseline", {}).get("rmse"),
                "skill_vs_seasonal": result.get("skill_vs_seasonal"),
                "causal_status": result.get("causal_status"),
            })
        return items

    # --------------------------------------------------------------- scenario
    def scenario(self, run_id: str, **kwargs: Any) -> dict[str, Any]:
        analysis = self.get_run(run_id)
        if analysis["stale"]:
            # A stale analysis can still be inspected, but a new scenario is marked
            # stale rather than silently presenting refreshed certainty.
            pass
        result = run_scenario(analysis, db=self.db, **kwargs)
        scenario_id = f"ESCN-{result['fingerprint'][:16]}"
        result["scenario_id"] = scenario_id
        existing = self.db.query_one("SELECT scenario_id FROM economic_scenario WHERE scenario_id = ?",
                                     (scenario_id,))
        if not existing:
            now = iso(utcnow())
            with self.db.transaction():
                self.db.execute(
                    "INSERT INTO economic_scenario (scenario_id, run_id, name, assumptions_json, "
                    "result_json, fingerprint, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
                    (scenario_id, run_id, result["name"],
                     json.dumps({"assumptions": result["assumptions"]}, sort_keys=True),
                     json.dumps(result, sort_keys=True, default=str), result["fingerprint"],
                     "stale" if analysis["stale"] else "succeeded", now),
                )
                self.db.execute(
                    "INSERT INTO economic_event (event_id, event_type, label, geography_code, "
                    "started_at, ended_at, observed_at, published_at, status, data_class, source_id, "
                    "metadata_json, created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                    (stable_id("EEVT", "hypothetical-temperature-shock", run_id, scenario_id),
                     "hypothetical_temperature_shock", result["name"], "ERCO",
                     result["reference_date"], result["reference_date"], result["created_at"], None,
                     "hypothetical", "hypothetical", "atlas-assumption",
                     json.dumps({"scenario_id": scenario_id, "shock_c": result["shock_c"]}, sort_keys=True),
                     now),
                )
        result["stored"] = True
        return result

    def scenarios(self, run_id: str, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT scenario_id, name, status, created_at, result_json FROM economic_scenario "
            "WHERE run_id = ? ORDER BY created_at DESC LIMIT ?",
            (run_id, max(1, min(int(limit), 100))),
        )
        return [{"scenario_id": row["scenario_id"], "name": row["name"],
                 "status": row["status"], "created_at": row["created_at"],
                 "result": json.loads(row["result_json"])} for row in rows]

    # -------------------------------------------------------------- application
    def save_application(self, run_id: str, *, name: str, purpose: str,
                         scenario_id: str | None = None) -> dict[str, Any]:
        run = self.get_run(run_id)
        scenario = None
        if scenario_id:
            row = self.db.query_one(
                "SELECT result_json FROM economic_scenario WHERE scenario_id = ? AND run_id = ?",
                (scenario_id, run_id),
            )
            if row is None:
                raise UnknownEntity("unknown scenario for this analysis", scenario_id=scenario_id)
            scenario = json.loads(row["result_json"])
        object_ids = [item for item in [run.get("dataset_object_id"), run.get("model_object_id"),
                                        run.get("experiment_object_id")] if item]
        document = {
            "schema_version": "atlas.research_object.v1", "kind": "application",
            "name": name, "version": "1.0.0", "status": "validated",
            "description": purpose, "as_of": iso(utcnow()), "mode": "atlas_ingested",
            "evidence_ids": [], "source_ids": ["eia-930", "noaa-ghcn"],
            "object_ids": object_ids,
            "assumptions": ["The economic relationship is an association, not an identified causal effect.",
                            "The firm exposure and power price are hypothetical unless supplied by a user."],
            "limitations": run.get("limitations", []),
            "spec": {
                "purpose": purpose,
                "views": ["evidence", "graph", "association", "scenario", "sentinel"],
                "run_id": run_id,
                "scenario_id": scenario_id,
                "scenario": scenario,
                "causal_status": "not_identified",
                "data_class": "observed + hypothetical scenario",
            },
        }
        application = self._ensure_object(document)
        self.db.execute("UPDATE economic_analysis SET application_object_id = ? WHERE run_id = ?",
                        (application["object_id"], run_id))
        return application

    # ----------------------------------------------------------------- sentinel
    def sentinel_refresh(self) -> dict[str, Any]:
        manifest = data._manifest()
        expected = manifest["panel"]["sha256"]
        series = self.db.query("SELECT series_id, metadata_json FROM economic_series")
        observed_hashes = {}
        for row in series:
            metadata = json.loads(row["metadata_json"])
            observed_hashes[row["series_id"]] = metadata.get("fixture_sha256")
        changed = sorted(series_id for series_id, value in observed_hashes.items() if value != expected)
        now = iso(utcnow())
        alerts = []
        if changed:
            for series_id in changed:
                alert_id = stable_id("EALT", "fixture-hash", series_id, expected)
                self.db.execute(
                    "INSERT INTO economic_alert (alert_id, alert_type, severity, run_id, dependency_id, "
                    "summary, detail_json, status, created_at) VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (alert_id, "source_archive_changed", "warning", None, series_id,
                     "The committed economic fixture hash differs from the ingested series metadata.",
                     json.dumps({"expected": expected, "observed": observed_hashes[series_id]},
                                sort_keys=True), "open", now),
                )
                alerts.append({"alert_id": alert_id, "series_id": series_id,
                               "summary": "source archive changed; dependent research requires review"})
        dependencies = self.db.query(
            "SELECT dependency_type, dependency_id, COUNT(*) AS runs, SUM(stale) AS stale "
            "FROM economic_dependency GROUP BY dependency_type, dependency_id ORDER BY dependency_type, dependency_id"
        )
        stale_runs = self.db.query(
            "SELECT run_id, stale_reason FROM economic_analysis WHERE stale = 1 ORDER BY created_at DESC"
        )
        conflict_rows = data.list_conflicts(self.db)
        recent_alerts = self.db.query(
            "SELECT alert_id, alert_type, severity, run_id, dependency_id, summary, status, created_at "
            "FROM economic_alert ORDER BY created_at DESC LIMIT 20"
        )
        latest_observation = self.db.query_one(
            "SELECT MAX(period_end) AS latest, MAX(observed_at) AS retrieved, COUNT(*) AS rows "
            "FROM economic_observation"
        )
        return {
            "schema": "atlas.economic.sentinel.v1",
            "checked_at": now,
            "source_freshness": {
                "fixture_sha256_expected": expected,
                "series_hashes": observed_hashes,
                "changed_series": changed,
                "latest_period": latest_observation["latest"],
                "latest_retrieval": latest_observation["retrieved"],
                "observations": latest_observation["rows"],
            },
            "dependencies": [dict(row) for row in dependencies],
            "stale_runs": [dict(row) for row in stale_runs],
            "conflicts": conflict_rows,
            "alerts": [dict(row) for row in recent_alerts],
            "generated_alerts": alerts,
            "automatic_retrain": False,
            "automatic_deployment": False,
            "note": "A source revision marks dependent runs stale; it never rewrites a saved investment thesis.",
        }

    def revise_observation(self, observation_id: str, *, value: float,
                           published_at: str | None = None, reason: str) -> dict[str, Any]:
        row = self.db.query_one("SELECT * FROM economic_observation WHERE observation_id = ?",
                                (observation_id,))
        if row is None:
            raise UnknownEntity("unknown economic observation", observation_id=observation_id)
        if not isinstance(value, (int, float)):
            raise ValidationError("revised observation value must be numeric")
        period_end = row["period_end"]
        published = iso(parse_iso(published_at)) if published_at else None
        if published and published[:10] < period_end:
            raise ValidationError("published_at cannot precede the observation period")
        revision_seq = int(row["revision_seq"]) + 1
        now = iso(utcnow())
        payload = {"series_id": row["series_id"], "date": row["period_start"], "value": value,
                   "unit": row["unit"], "vintage": f"revision-{now}", "revision_seq": revision_seq}
        new_id = stable_id("EOBS", payload)
        metadata = json.loads(row["metadata_json"])
        with self.db.transaction():
            self.db.execute(
                "INSERT INTO economic_observation (observation_id, series_id, source_id, period_start, "
                "period_end, published_at, availability_time, availability_precision, availability_basis, "
                "observed_at, vintage, revision_seq, supersedes, value_numeric, unit, quality, data_class, "
                "raw_ref, content_hash, metadata_json, created_at) "
                "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT DO NOTHING",
                (new_id, row["series_id"], row["source_id"], row["period_start"], row["period_end"],
                 published, now, "exact", "explicit revision received by Atlas", now,
                 f"revision-{now}", revision_seq, observation_id, float(value), row["unit"],
                 "revised_source", row["data_class"], row["raw_ref"],
                 digest({**payload, **metadata}), json.dumps(metadata, sort_keys=True), now),
            )
            stale_runs = [item["run_id"] for item in self.db.query(
                "SELECT DISTINCT run_id FROM economic_dependency WHERE dependency_type = 'observation' "
                "AND dependency_id = ?", (observation_id,)
            )]
            self.db.execute(
                "UPDATE economic_dependency SET stale = 1, invalidated_at = ?, reason = ? "
                "WHERE dependency_type = 'observation' AND dependency_id = ?",
                (now, reason, observation_id),
            )
            for run_id in stale_runs:
                self.db.execute(
                    "UPDATE economic_analysis SET stale = 1, stale_reason = ? WHERE run_id = ?",
                    (f"observation revised: {reason}", run_id),
                )
                self.db.execute(
                    "INSERT INTO economic_alert (alert_id, alert_type, severity, run_id, dependency_id, "
                    "summary, detail_json, status, created_at) VALUES (?,?,?,?,?,?,?,?,?) "
                    "ON CONFLICT DO NOTHING",
                    (stable_id("EALT", "observation-revised", run_id, observation_id, now),
                     "observation_revised", "warning", run_id, observation_id,
                     "An economic observation was revised; dependent analysis is stale.",
                     json.dumps({"old_observation_id": observation_id, "new_observation_id": new_id,
                                 "reason": reason, "value": value}, sort_keys=True), "open", now),
                )
        return {"schema": "atlas.economic.revision.v1", "old_observation_id": observation_id,
                "new_observation_id": new_id, "revision_seq": revision_seq,
                "stale_runs": stale_runs, "notice": "The old observation is retained; nothing is deleted."}

    # ------------------------------------------------------------------- replay
    def replay(self, run_id: str, *, as_of: str, mode: str = "public_available") -> dict[str, Any]:
        original = self.get_run(run_id)
        try:
            panel = data.load_panel(self.db, as_of=as_of, mode=mode)
        except MissingDataError as exc:
            return {
                "schema": "atlas.economic.replay.v1", "run_id": run_id,
                "as_of": as_of, "mode": mode, "status": "insufficient_evidence",
                "reason": str(exc), "context": exc.context, "original_fingerprint": original["fingerprint"],
                "reproduced": False,
                "note": "The current archive has no evidenced historical vintage for this cutoff. "
                        "Atlas refuses to manufacture one.",
            }
        reproduced = run_weather_demand(panel, seed=20261105)
        matches = reproduced["fingerprint"] == original["fingerprint"]
        return {
            "schema": "atlas.economic.replay.v1", "run_id": run_id, "as_of": as_of,
            "mode": mode, "status": "reproduced" if matches else "diverged",
            "original_fingerprint": original["fingerprint"],
            "reproduced_fingerprint": reproduced["fingerprint"],
            "rows": panel["row_count"], "reproduced": matches,
            "completeness": panel["completeness"],
            "note": "A match reproduces the calculation from retained observations; it does not "
                    "establish that the archive is a historical as-issued vintage.",
        }

    # ------------------------------------------------------------------ memory
    def memory(self, limit: int = 100) -> dict[str, Any]:
        runs = self.list_runs(limit=limit)
        return {
            "schema": "atlas.economic.memory.v1",
            "items": runs,
            "counts": {
                "runs": len(runs),
                "stale": sum(1 for item in runs if item["stale"]),
                "applications": int(self.db.scalar(
                    "SELECT COUNT(*) FROM economic_analysis WHERE application_object_id IS NOT NULL",
                    default=0,
                ) or 0),
                "association_supported": sum(
                    1 for item in runs if item["conclusion"] in {
                        "association_supported_with_caveats", "association_supported_forecast_unstable"
                    }
                ),
                "forecast_unstable": sum(
                    1 for item in runs if item["conclusion"] == "association_supported_forecast_unstable"
                ),
                "not_supported": sum(1 for item in runs if item["conclusion"] == "not_supported"),
            },
            "note": "Every analysis remains, including failures and stale results.",
        }

    def benchmarks(self) -> dict[str, Any]:
        analyses = self.db.row_count("economic_analysis")
        observations = self.db.row_count("economic_observation")
        edges = self.db.row_count("economic_edge")
        return {
            "schema": "atlas.economic.benchmarks.v1",
            "observations": observations,
            "edges": edges,
            "analyses": analyses,
            "note": "Authoritative measured benchmark is artifacts/phase7_benchmarks.json.",
        }
