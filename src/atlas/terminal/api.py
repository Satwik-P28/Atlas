"""HTTP API for the Atlas terminal.

The API is a thin, typed presentation layer over ``atlas.terminal.read_models``. It
never computes a financial value itself: statements, metrics, provenance and identity
resolution all come from the Phase 1 contracts, so the browser and the CLI cannot
disagree about a number.

Operational choices:

* **One SQLite connection per request.** SQLite connections are not safe for concurrent
  use across threads; opening per request costs ~1 ms and removes a class of
  intermittent failures. WAL lets readers proceed while a write commits.
* **Restricted CORS.** Only loopback development origins are allowed by default. The
  terminal is a local application; it is not a public multi-tenant service.
* **Structured errors.** Every domain error becomes
  ``{"error": {"code", "message", "context"}}`` with a stable status code, so the UI can
  render an "ambiguous identity" or "incomplete reconstruction" state rather than a
  generic failure.
* **No arbitrary query surface.** Clients send filters and workspace documents, which
  are validated; they never send SQL, expressions or code.
"""

from __future__ import annotations

import copy
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.errors import (
    AmbiguousResolution,
    AtlasError,
    NotSupportedError,
    StorageError,
    UnknownEntity,
    ValidationError,
)
from ..core.temporal import AsOfMode, iso, utcnow
from ..evidence import SELECTION_POLICY
from ..storage.db import Database
from ..storage.migrations import LATEST_VERSION
from ..research import objects as research_objects
from ..research import validation as research_validation
from ..fec import compile_model
from ..fec import valuation as fec_valuation
from ..fec.operators import REGISTRY, operator_versions
from ..fec.runtime import ExecutionEngine
from . import indicators, read_models, screener, workspaces
from .store import SettingsStore, WatchlistStore, WorkspaceStore

DEFAULT_DB = os.environ.get("ATLAS_DB", "var/atlas.db")
DEFAULT_ORIGINS = os.environ.get(
    "ATLAS_TERMINAL_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
).split(",")

STATUS_BY_ERROR: tuple[tuple[type[BaseException], int], ...] = (
    (UnknownEntity, 404),
    (AmbiguousResolution, 409),
    (ValidationError, 422),
    (NotSupportedError, 422),
    (StorageError, 409),
    (AtlasError, 500),
)


# --------------------------------------------------------------------- schemas
class ResearchObjectCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    document: dict[str, Any]


class ModelCompileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: dict[str, Any]


class ModelRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: dict[str, Any]
    inputs: dict[str, Any] = Field(default_factory=dict)
    persist: bool = True


class DcfRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    issuer: str
    assumptions: dict[str, Any] = Field(default_factory=dict)
    as_of: str | None = None
    mode: Literal["public_available", "atlas_ingested"] | None = None


class ReverseDcfRequest(DcfRequest):
    target_price: float
    variable: Literal["terminal_growth", "operating_margin", "revenue_growth", "wacc"] = "terminal_growth"
    bounds: list[float] | None = None


class SensitivityRequest(DcfRequest):
    wacc_values: list[float] | None = None
    growth_values: list[float] | None = None


class ScenarioRequest(DcfRequest):
    custom: dict[str, dict[str, Any]] | None = None


class ForkRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class ObjectExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] = Field(default_factory=dict)
    persist: bool = True


class WatchlistCreate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=400)
    security_ids: list[str] = Field(default_factory=list, max_length=50)


class WatchlistUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str | None = Field(default=None, min_length=1, max_length=80)
    notes: str | None = Field(default=None, max_length=400)


class ItemBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    security_id: str


class OrderBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    security_ids: list[str]


class IndicatorRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    params: dict[str, Any] = Field(default_factory=dict)


class MarketRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    range: str = "1Y"
    start: str | None = None
    end: str | None = None
    view: Literal["raw", "split", "total_return"] = "split"
    indicators: list[IndicatorRequest] = Field(default_factory=list, max_length=6)
    as_of: str | None = None


class IndicatorPreview(BaseModel):
    model_config = ConfigDict(extra="forbid")
    security_id: str
    range: str = "1Y"
    view: Literal["raw", "split", "total_return"] = "split"
    indicators: list[IndicatorRequest] = Field(min_length=1, max_length=6)
    as_of: str | None = None


class FilterModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    op: Literal["gt", "gte", "lt", "lte", "eq", "between"]
    value: float
    value2: float | None = None


class SortModel(BaseModel):
    model_config = ConfigDict(extra="forbid")
    metric: str
    direction: Literal["asc", "desc"] = "desc"


class ScreenRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    filters: list[FilterModel] = Field(default_factory=list, max_length=12)
    match: Literal["AND", "OR"] = "AND"
    sort: SortModel | None = None
    limit: int = Field(default=50, ge=1, le=200)
    as_of: str | None = None
    mode: Literal["public_available", "atlas_ingested"] | None = None


class SettingBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    key: str
    value: Any


# ------------------------------------------------------------------ app wiring
def _open(path: str | Path) -> Database:
    return Database(path, create=False)


def get_db(request: Request):
    path = request.app.state.db_path
    if not Path(path).exists():
        raise HTTPException(
            status_code=503,
            detail={
                "code": "database_missing",
                "message": "Atlas database not found",
                "context": {
                    "path": str(path),
                    "fix": "run `python scripts/build_terminal_db.py` (or `atlas sec sync ...`) to create it",
                },
            },
        )
    db = _open(path)
    try:
        if db.schema_version() < LATEST_VERSION:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "database_needs_migration",
                    "message": "Atlas database was created by an older schema",
                    "context": {"found": db.schema_version(), "supported": LATEST_VERSION,
                                "fix": "run `atlas --db <path> init`"},
                },
            )
        yield db
    finally:
        db.close()


def _error_payload(code: str, message: str, context: Any = None) -> dict[str, Any]:
    return {"error": {"code": code, "message": message, "context": context or {}}}


def create_app(db_path: str | Path | None = None, *, web_dist: str | Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Atlas Quant Terminal API",
        version="0.2.0",
        description=(
            "Read-oriented API over the Atlas temporal evidence kernel. Financial values are "
            "returned with evidence ids; derived metrics carry formulas and input ids. "
            "Point-in-time selection is always explicit (`as_of` + `mode`)."
        ),
        openapi_url="/api/openapi.json",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.db_path = str(db_path or DEFAULT_DB)
    app.state.web_dist = Path(web_dist) if web_dist else Path(__file__).resolve().parents[3] / "web" / "dist"

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[origin.strip() for origin in DEFAULT_ORIGINS if origin.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["content-type"],
        max_age=600,
    )

    @app.exception_handler(AtlasError)
    async def atlas_error_handler(request: Request, exc: AtlasError) -> JSONResponse:
        status = next((code for cls, code in STATUS_BY_ERROR if isinstance(exc, cls)), 500)
        return JSONResponse(status_code=status, content=_error_payload(exc.code, str(exc), exc.context))

    @app.exception_handler(RequestValidationError)
    async def validation_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        return JSONResponse(
            status_code=422,
            content=_error_payload("invalid_request", "request validation failed", {"errors": exc.errors()}),
        )

    @app.exception_handler(StarletteHTTPException)
    async def http_error_handler(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        detail = exc.detail
        if isinstance(detail, dict) and "code" in detail:
            return JSONResponse(status_code=exc.status_code, content={"error": detail})
        return JSONResponse(
            status_code=exc.status_code,
            content=_error_payload("http_error", str(detail), {"status": exc.status_code}),
        )

    # ---------------------------------------------------------------- metadata
    @app.get("/api/health", tags=["system"])
    def terminal_health() -> dict[str, Any]:
        path = Path(app.state.db_path)
        payload: dict[str, Any] = {
            "status": "ok" if path.exists() else "missing_database",
            "database": str(path),
            "as_of": iso(utcnow()),
            "terminal_schema": read_models.TERMINAL_SCHEMA,
        }
        if path.exists():
            db = _open(path)
            try:
                payload.update(
                    {
                        "schema_version": db.schema_version(),
                        "supported_schema": LATEST_VERSION,
                        "integrity_check": db.integrity_check(),
                        "evidence": int(db.scalar("SELECT COUNT(*) FROM evidence", default=0) or 0),
                        "issuers": int(db.scalar("SELECT COUNT(*) FROM issuer", default=0) or 0),
                        "bars": int(db.scalar("SELECT COUNT(*) FROM bar", default=0) or 0),
                    }
                )
            finally:
                db.close()
        return payload

    @app.get("/api/schema", tags=["system"])
    def contract() -> dict[str, Any]:
        return {
            "terminal_schema": read_models.TERMINAL_SCHEMA,
            "workspace_schema": "atlas.workspace.v1",
            "selection_policy": SELECTION_POLICY,
            "as_of_modes": [{"value": m.value, "description": m.description} for m in AsOfMode],
            "indicator_versions": {key: spec.version for key, spec in indicators.REGISTRY.items()},
            "panel_types": sorted(workspaces.PANEL_TYPES),
            "error_codes": [
                "unknown_entity",
                "ambiguous_resolution",
                "validation_error",
                "storage_error",
                "database_missing",
                "database_needs_migration",
                "invalid_request",
            ],
            "notes": [
                "Every financial value is accompanied by its evidence_id.",
                "Derived metrics are computed at read time; none are stored as evidence.",
            ],
        }

    # --------------------------------------------------------------- companies
    @app.get("/api/companies", tags=["companies"])
    def companies(q: str | None = None, limit: int = Query(default=200, ge=1, le=500),
                  db: Database = Depends(get_db)) -> dict[str, Any]:
        items = read_models.list_companies(db, q=q, limit=limit)
        return {"items": items, "count": len(items), "schema": read_models.TERMINAL_SCHEMA}

    @app.get("/api/search", tags=["companies"])
    def search(
        q: str = Query(min_length=1, max_length=80),
        limit: int = Query(default=10, ge=1, le=25),
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        """Typeahead over stored issuers only. Atlas never invents a match."""
        items = [
            {
                "issuer_id": item["issuer_id"],
                "label": item["legal_name"],
                "cik": item.get("cik"),
                "tickers": [
                    ticker["ticker"]
                    for security in item.get("securities", [])
                    for ticker in security.get("tickers", [])
                    if ticker.get("ticker")
                ],
            }
            for item in read_models.list_companies(db, q=q, limit=limit)
        ]
        return {"items": items, "count": len(items)}

    @app.get("/api/companies/{identifier}", tags=["companies"])
    def company(identifier: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return read_models.company_detail(db, identifier)

    @app.get("/api/companies/{identifier}/statements", tags=["companies"])
    def statements(
        identifier: str,
        statement: str = "income",
        period: str = "FY",
        as_of: str | None = None,
        mode: str | None = None,
        limit: int = Query(default=6, ge=1, le=20),
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        return read_models.statements(
            db, identifier, statement=statement, period=period, as_of=as_of, mode=mode, limit=limit
        )

    @app.get("/api/companies/{identifier}/metrics", tags=["companies"])
    def metrics(identifier: str, as_of: str | None = None, mode: str | None = None,
                db: Database = Depends(get_db)) -> dict[str, Any]:
        issuer = read_models.resolve_company(db, identifier)
        from .metric_store import get_issuer_metrics

        return get_issuer_metrics(db, issuer["issuer_id"], as_of=as_of, mode=mode)

    @app.get("/api/companies/{identifier}/filings", tags=["companies"])
    def filings(
        identifier: str,
        limit: int = Query(default=25, ge=1, le=100),
        offset: int = Query(default=0, ge=0),
        forms: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        requested = [part.strip() for part in (forms or "").split(",") if part.strip()]
        return read_models.filings(db, identifier, limit=limit, offset=offset, forms=requested)

    @app.get("/api/companies/{identifier}/events", tags=["companies"])
    def events(identifier: str, limit: int = Query(default=40, ge=1, le=200),
               db: Database = Depends(get_db)) -> dict[str, Any]:
        return read_models.events(db, identifier, limit=limit)

    @app.get("/api/companies/{identifier}/health", tags=["companies"])
    def company_health(identifier: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return read_models.health(db, identifier)

    # -------------------------------------------------------------- research views
    @app.get("/api/companies/{identifier}/history", tags=["research"])
    def company_history(
        identifier: str,
        concepts: str | None = None,
        limit: int = Query(default=8, ge=1, le=20),
        as_of: str | None = None,
        mode: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        requested = [part.strip() for part in (concepts or "").split(",") if part.strip()]
        return read_models.financial_history(
            db, identifier, concepts=requested or None, limit=limit, as_of=as_of, mode=mode
        )

    @app.get("/api/companies/{identifier}/peers", tags=["research"])
    def company_peers(
        identifier: str,
        as_of: str | None = None,
        mode: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        from .cache import get_or_compute

        return get_or_compute(
            db,
            "peers",
            {"identifier": identifier, "as_of": as_of, "mode": mode},
            lambda: read_models.peers(db, identifier, as_of=as_of, mode=mode),
            ttl=120.0 if as_of is None else None,
        )

    @app.get("/api/companies/{identifier}/revisions", tags=["research"])
    def company_revisions(
        identifier: str,
        limit: int = Query(default=50, ge=1, le=200),
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        return read_models.revisions(db, identifier, limit=limit)

    @app.get("/api/research/validation/{identifier}", tags=["research"])
    def company_validation(
        identifier: str,
        as_of: str | None = None,
        mode: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        return research_validation.run(db, identifier, as_of=as_of, mode=mode)

    # ------------------------------------------------------------------ market
    @app.get("/api/markets/overview", tags=["market"])
    def markets(db: Database = Depends(get_db)) -> dict[str, Any]:
        return read_models.market_overview(db)

    @app.get("/api/securities/{security_id}/market", tags=["market"])
    def market_get(
        security_id: str,
        range: str = "1Y",
        start: str | None = None,
        end: str | None = None,
        view: Literal["raw", "split", "total_return"] = "split",
        as_of: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        return read_models.market_series(
            db, security_id, range_key=range, start=start, end=end, view=view, as_of=as_of
        )

    @app.post("/api/securities/{security_id}/market", tags=["market"])
    def market_post(security_id: str, body: MarketRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        return read_models.market_series(
            db,
            security_id,
            range_key=body.range,
            start=body.start,
            end=body.end,
            view=body.view,
            indicators=[item.model_dump() for item in body.indicators],
            as_of=body.as_of,
        )

    @app.get("/api/securities/{security_id}/actions", tags=["market"])
    def security_actions(security_id: str, as_of: str | None = None,
                         db: Database = Depends(get_db)) -> dict[str, Any]:
        from ..market.actions import ActionStore

        return {
            "security_id": security_id,
            "items": [a.to_dict() for a in ActionStore(db).list(security_id, knowledge_as_of=as_of)],
            "as_of": as_of,
            "schema": read_models.TERMINAL_SCHEMA,
        }

    # -------------------------------------------------------------- indicators
    @app.get("/api/indicators", tags=["indicators"])
    def indicator_catalog() -> dict[str, Any]:
        return {"items": indicators.catalog(), "count": len(indicators.REGISTRY)}

    @app.post("/api/indicators/preview", tags=["indicators"])
    def indicator_preview(body: IndicatorPreview, db: Database = Depends(get_db)) -> dict[str, Any]:
        series = read_models.market_series(
            db, body.security_id, range_key=body.range, view=body.view, as_of=body.as_of
        )
        closes = series["index"] if body.view == "total_return" else series["bars"]
        bars = [
            {
                "date": point["time"],
                "open": point.get("value"),
                "high": point.get("value"),
                "low": point.get("value"),
                "close": point.get("value"),
                "volume": 0,
            }
            for point in closes
        ] if body.view == "total_return" else [
            {"date": bar["date"], "open": bar["open"], "high": bar["high"], "low": bar["low"],
             "close": bar["close"], "volume": bar.get("volume") or 0}
            for bar in closes
        ]
        return {
            "security_id": body.security_id,
            "view": body.view,
            "bars": len(bars),
            **indicators.compute_many([item.model_dump() for item in body.indicators], bars),
            "schema": read_models.TERMINAL_SCHEMA,
        }

    # ----------------------------------------------------------------- x-ray
    @app.get("/api/evidence/{evidence_id}", tags=["evidence"])
    def evidence(evidence_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        payload = read_models.xray(db, evidence_id)
        payload["research_impact"] = research_objects.ResearchObjectStore(db).evidence_impact(evidence_id)
        return payload

    # --------------------------------------------------------- research objects
    @app.get("/api/research/objects", tags=["research"])
    def research_object_list(
        kind: str | None = None,
        status: str | None = None,
        limit: int = Query(default=100, ge=1, le=500),
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        store = research_objects.ResearchObjectStore(db)
        return {
            "items": store.list(kind=kind, status=status, limit=limit),
            "schema": research_objects.SCHEMA_VERSION,
            "kinds": list(research_objects.KINDS),
            "statuses": list(research_objects.STATUSES),
        }

    @app.post("/api/research/objects", tags=["research"], status_code=201)
    def research_object_create(
        body: ResearchObjectCreate, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return research_objects.ResearchObjectStore(db).create(body.document)

    @app.get("/api/research/objects/{object_id}", tags=["research"])
    def research_object_get(object_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return research_objects.ResearchObjectStore(db).get(object_id)

    @app.post("/api/research/objects/{object_id}/fork", tags=["research"], status_code=201)
    def research_object_fork(
        object_id: str, body: ForkRequest, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return research_objects.ResearchObjectStore(db).fork(
            object_id, name=body.name, version=body.version
        )

    @app.get("/api/research/compare", tags=["research"])
    def research_object_compare(
        left: str, right: str, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return research_objects.ResearchObjectStore(db).compare(left, right)

    @app.get("/api/research/objects/{object_id}/export", tags=["research"])
    def research_object_export(object_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return research_objects.ResearchObjectStore(db).export_manifest(object_id)

    @app.post("/api/research/objects/{object_id}/execute", tags=["research"])
    def research_object_execute(
        object_id: str, body: ObjectExecuteRequest, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        stored = research_objects.ResearchObjectStore(db).get(object_id)
        if stored["kind"] != "model":
            raise ValidationError("only model research objects are executable", kind=stored["kind"])
        spec = (stored["document"].get("spec") or {}).get("model_spec")
        if not isinstance(spec, dict):
            raise ValidationError("model object does not contain an atlas.model.v1 spec")
        model = compile_model(spec)
        result = ExecutionEngine(db).execute(model, body.inputs, persist=body.persist)
        result["object_id"] = object_id
        return result

    # ------------------------------------------------------------ models & FEC
    @app.get("/api/models/operators", tags=["models"])
    def model_operators() -> dict[str, Any]:
        return {
            "items": [
                {"key": key, "version": spec.version, "arity": spec.arity,
                 "formula": spec.formula, "description": spec.description}
                for key, spec in sorted(REGISTRY.items())
            ],
            "operator_versions": operator_versions(),
            "schema_version": "atlas.model.v1",
            "expression_policy": "allowlisted AST arithmetic and named functions; no eval/exec",
        }

    @app.post("/api/models/compile", tags=["models"])
    def model_compile(body: ModelCompileRequest) -> dict[str, Any]:
        model = compile_model(body.spec)
        return {**model.to_dict(), "canonical_spec": model.spec}

    @app.post("/api/models/run", tags=["models"])
    def model_run(body: ModelRunRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        model = compile_model(body.spec)
        result = ExecutionEngine(db).execute(model, body.inputs, persist=body.persist)
        result["compiled"] = model.to_dict()
        return result

    @app.get("/api/models/runs/{run_id}", tags=["models"])
    def model_run_get(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        row = db.query_one("SELECT * FROM model_run WHERE run_id = ?", (run_id,))
        if row is None:
            raise UnknownEntity("unknown model run", run_id=run_id)
        payload = json.loads(row["result_json"])
        payload["execution_record"] = {
            "run_id": row["run_id"], "status": row["status"],
            "duration_ms": row["duration_ms"], "created_at": row["created_at"],
            "as_of": row["as_of"], "mode": row["mode"], "fingerprint": row["fingerprint"],
        }
        return payload

    # --------------------------------------------------------------- valuation
    @app.get("/api/valuation/defaults/{identifier}", tags=["valuation"])
    def valuation_defaults(
        identifier: str, as_of: str | None = None, mode: str | None = None,
        db: Database = Depends(get_db),
    ) -> dict[str, Any]:
        issuer = read_models.resolve_company(db, identifier)
        from .metric_store import get_issuer_metrics

        metrics = get_issuer_metrics(db, issuer["issuer_id"], as_of=as_of, mode=mode)
        defaults = fec_valuation.defaults_from_metrics(metrics)
        return {
            "issuer": {"issuer_id": issuer["issuer_id"], "legal_name": issuer["legal_name"]},
            "defaults": defaults,
            "metrics": metrics.get("metrics", {}),
            "period_end": metrics.get("period_end"),
            "price": metrics.get("price"),
            "price_as_of": metrics.get("price_as_of"),
            "schema": fec_valuation.VALUATION_SCHEMA,
            "notes": [
                "Revenue, margin, capex, cash, debt and shares are evidence-linked defaults.",
                "WACC, tax, D&A and working-capital assumptions remain explicit user assumptions.",
            ],
        }

    @app.post("/api/valuation/dcf", tags=["valuation"])
    def valuation_dcf(body: DcfRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        return fec_valuation.run_dcf(
            db, body.issuer, body.assumptions, as_of=body.as_of, mode=body.mode
        )

    @app.post("/api/valuation/reverse", tags=["valuation"])
    def valuation_reverse(body: ReverseDcfRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        return fec_valuation.reverse_dcf(
            db, body.issuer, body.target_price, variable=body.variable,
            bounds=tuple(body.bounds) if body.bounds else None,
            assumptions=body.assumptions, as_of=body.as_of, mode=body.mode,
        )

    @app.post("/api/valuation/scenarios", tags=["valuation"])
    def valuation_scenarios(body: ScenarioRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        return fec_valuation.scenarios(
            db, body.issuer, body.assumptions, as_of=body.as_of, mode=body.mode,
            custom=body.custom,
        )

    @app.post("/api/valuation/sensitivity", tags=["valuation"])
    def valuation_sensitivity(body: SensitivityRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        return fec_valuation.sensitivity(
            db, body.issuer, wacc_values=body.wacc_values, growth_values=body.growth_values,
            assumptions=body.assumptions, as_of=body.as_of, mode=body.mode,
        )

    # --------------------------------------------------------------- screeners
    @app.get("/api/screeners/metrics", tags=["screeners"])
    def screener_metrics() -> dict[str, Any]:
        return {"items": screener.metric_catalog(), "count": len(screener.SOURCE_METRICS)}

    @app.post("/api/screeners/run", tags=["screeners"])
    def run_screener(body: ScreenRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        from .cache import get_or_compute

        def compute() -> dict[str, Any]:
            return screener.run_screener(
                db,
                filters=[item.model_dump() for item in body.filters],
                match=body.match,
                sort=body.sort.model_dump() if body.sort else None,
                limit=body.limit,
                as_of=body.as_of,
                mode=body.mode,
            )

        # Explicit as-of screens are deterministic, so only time-relative screens need a TTL.
        return get_or_compute(
            db,
            "screen",
            body.model_dump(),
            compute,
            ttl=60.0 if body.as_of is None else None,
        )

    # -------------------------------------------------------------- watchlists
    @app.get("/api/watchlists", tags=["watchlists"])
    def watchlists(db: Database = Depends(get_db)) -> dict[str, Any]:
        items = WatchlistStore(db).list()
        return {"items": items, "count": len(items)}

    @app.post("/api/watchlists", tags=["watchlists"], status_code=201)
    def create_watchlist(body: WatchlistCreate, db: Database = Depends(get_db)) -> dict[str, Any]:
        return WatchlistStore(db).create(body.name, notes=body.notes, security_ids=body.security_ids)

    @app.get("/api/watchlists/{watchlist_id}", tags=["watchlists"])
    def get_watchlist(watchlist_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return WatchlistStore(db).get(watchlist_id)

    @app.patch("/api/watchlists/{watchlist_id}", tags=["watchlists"])
    def update_watchlist(watchlist_id: str, body: WatchlistUpdate,
                         db: Database = Depends(get_db)) -> dict[str, Any]:
        return WatchlistStore(db).update(watchlist_id, name=body.name, notes=body.notes)

    @app.delete("/api/watchlists/{watchlist_id}", tags=["watchlists"], status_code=204)
    def delete_watchlist(watchlist_id: str, db: Database = Depends(get_db)) -> None:
        WatchlistStore(db).delete(watchlist_id)

    @app.post("/api/watchlists/{watchlist_id}/items", tags=["watchlists"])
    def add_item(watchlist_id: str, body: ItemBody, db: Database = Depends(get_db)) -> dict[str, Any]:
        return WatchlistStore(db).add_item(watchlist_id, body.security_id)

    @app.delete("/api/watchlists/{watchlist_id}/items/{security_id}", tags=["watchlists"])
    def remove_item(watchlist_id: str, security_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return WatchlistStore(db).remove_item(watchlist_id, security_id)

    @app.put("/api/watchlists/{watchlist_id}/order", tags=["watchlists"])
    def reorder(watchlist_id: str, body: OrderBody, db: Database = Depends(get_db)) -> dict[str, Any]:
        return WatchlistStore(db).reorder(watchlist_id, body.security_ids)

    # -------------------------------------------------------------- workspaces
    @app.get("/api/workspaces/presets", tags=["workspaces"])
    def workspace_presets(issuer: str | None = None, security: str | None = None) -> dict[str, Any]:
        presets = workspaces.presets()
        if issuer and security:
            def substitute(value: Any) -> Any:
                if isinstance(value, str):
                    return value.replace("{issuer}", issuer).replace("{security}", security)
                if isinstance(value, list):
                    return [substitute(item) for item in value]
                if isinstance(value, dict):
                    return {key: substitute(item) for key, item in value.items()}
                return value

            presets = [substitute(preset) for preset in presets]
        return {
            "items": presets,
            "resolved": bool(issuer and security),
            "placeholders": ["{issuer}", "{security}"],
        }

    @app.get("/api/workspaces", tags=["workspaces"])
    def workspace_list(db: Database = Depends(get_db)) -> dict[str, Any]:
        items = WorkspaceStore(db).list()
        return {"items": items, "count": len(items)}

    @app.post("/api/workspaces", tags=["workspaces"], status_code=201)
    def workspace_create(payload: Any = Body(...), db: Database = Depends(get_db)) -> dict[str, Any]:
        return WorkspaceStore(db).create(payload)

    @app.get("/api/workspaces/{workspace_id}", tags=["workspaces"])
    def workspace_get(workspace_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return WorkspaceStore(db).get(workspace_id)

    @app.put("/api/workspaces/{workspace_id}", tags=["workspaces"])
    def workspace_update(workspace_id: str, payload: Any = Body(...),
                         db: Database = Depends(get_db)) -> dict[str, Any]:
        return WorkspaceStore(db).update(workspace_id, payload)

    @app.delete("/api/workspaces/{workspace_id}", tags=["workspaces"], status_code=204)
    def workspace_delete(workspace_id: str, db: Database = Depends(get_db)) -> None:
        WorkspaceStore(db).delete(workspace_id)

    # ---------------------------------------------------------------- settings
    @app.get("/api/settings", tags=["settings"])
    def get_settings(db: Database = Depends(get_db)) -> dict[str, Any]:
        return {"values": SettingsStore(db).all()}

    @app.put("/api/settings", tags=["settings"])
    def put_setting(body: SettingBody, db: Database = Depends(get_db)) -> dict[str, Any]:
        return {"values": SettingsStore(db).set(body.key, body.value)}

    # -------------------------------------------------------------- static SPA
    dist: Path = app.state.web_dist
    if (dist / "assets").exists():
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse(status_code=404, content=_error_payload("not_found", "unknown API route", {"path": path}))
        candidate = (dist / path).resolve() if path else dist / "index.html"
        if path and candidate.is_file() and dist.resolve() in candidate.parents:
            return FileResponse(candidate)
        index = dist / "index.html"
        if index.exists():
            return FileResponse(index)
        return JSONResponse(
            status_code=503,
            content=_error_payload(
                "frontend_not_built",
                "the terminal frontend has not been built",
                {"dist": str(dist), "fix": "cd web && npm install && npm run build"},
            ),
        )

    return app


def serve(db_path: str | Path | None = None, *, host: str = "127.0.0.1", port: int = 8000) -> None:
    import uvicorn

    uvicorn.run(create_app(db_path), host=host, port=port, log_level="info")


if __name__ == "__main__":  # pragma: no cover - manual launch
    serve()
