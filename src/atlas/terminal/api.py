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

import base64
import binascii
import copy
import json
import os
from pathlib import Path
from typing import Any, Literal

from fastapi import Body, Depends, FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from ..core.errors import (
    AmbiguousResolution,
    AtlasError,
    MissingDataError,
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
from ..research.archive import SourceArchiveStore
from ..quant.features import FeatureEngine
from ..quant.lab import LAB_SCHEMA, QuantLab, template_spec, universe as quant_universe
from ..quant.simulator import SIMULATOR_VERSION, SimulationConfig
from ..quant.vectorized import VectorizedConfig, run_preview
from ..institutional.risk import optimize as optimize_portfolio, portfolio_analysis
from ..institutional.service import (
    DEFAULT_CURVE_DATE,
    InstitutionalService,
    bond as institutional_bond,
    curve as institutional_curve,
    option as institutional_option,
)
from ..institutional.universe import aligned_panel, returns_matrix
from ..institutional.validation import walk_forward
from ..learning.features import catalogue as learning_feature_catalogue
from ..learning.service import LEARNING_SCHEMA, LearningService
from ..economic.service import ECONOMIC_SCHEMA, EconomicService
from ..applications.contracts import PACKAGE_SCHEMA
from ..applications.packs import DomainPackService
from ..applications.service import ApplicationService
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
    (MissingDataError, 422),
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


class FeatureRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    security_id: str
    mic: str | None = None
    features: list[dict[str, Any]]
    start: str | None = None
    end: str | None = None
    as_of: str | None = None
    missing: Literal["skip", "error"] = "skip"
    persist: bool = False


class StrategyCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spec: dict[str, Any]
    as_of: str | None = None
    mode: Literal["public_available", "atlas_ingested"] = "atlas_ingested"


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: str | None = None
    spec: dict[str, Any] | None = None
    as_of: str | None = None
    start: str | None = None
    end: str | None = None
    initial_capital: float | None = Field(default=None, gt=0, le=1_000_000_000)
    commission_bps: float | None = Field(default=None, ge=0, le=500)
    slippage_bps: float | None = Field(default=None, ge=0, le=500)


class BacktestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    strategy_id: str | None = None
    spec: dict[str, Any] | None = None
    as_of: str | None = None
    start: str | None = None
    end: str | None = None
    initial_capital: float | None = Field(default=None, gt=0, le=1_000_000_000)
    commission_bps: float | None = Field(default=None, ge=0, le=500)
    slippage_bps: float | None = Field(default=None, ge=0, le=500)
    hypothesis: str | None = Field(default=None, max_length=1000)
    experiment_name: str | None = Field(default=None, max_length=120)
    persist: bool = True


class BondRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    settlement_date: str
    maturity_date: str
    coupon_rate: float = Field(ge=0, le=1)
    curve_date: str = DEFAULT_CURVE_DATE
    face: float = Field(default=100.0, gt=0, le=1_000_000)
    frequency: int = Field(default=2, ge=1, le=12)
    persist: bool = True


class OptionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    spot: float = Field(gt=0)
    strike: float = Field(gt=0)
    time: float = Field(ge=0, le=50)
    rate: float = Field(ge=-0.99, le=1)
    volatility: float = Field(ge=0, le=5)
    dividend_yield: float = Field(default=0.0, ge=-0.99, le=1)
    persist: bool = True


class PortfolioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, float] = Field(default_factory=dict)
    lookback: int = Field(default=252, ge=20, le=5_000)
    capital: float = Field(default=100_000, gt=0, le=1_000_000_000)
    risk_free: float = Field(default=0.0, ge=-0.1, le=0.5)
    persist: bool = True


class OptimizeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    weights: dict[str, float] = Field(default_factory=dict)
    max_weight: float = Field(default=0.6, gt=0, le=1)
    cash_weight: float = Field(default=0.0, ge=0, lt=1)
    target_return: float | None = Field(default=None, ge=-1, le=5)
    shrinkage: float = Field(default=0.0, ge=0, le=1)
    current_weights: dict[str, float] | None = None
    persist: bool = True


class ValidationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    folds: int = Field(default=4, ge=1, le=12)
    train: int = Field(default=252, ge=20, le=2_000)
    validation: int = Field(default=63, ge=20, le=1_000)
    test: int = Field(default=63, ge=20, le=1_000)
    embargo: int = Field(default=5, ge=1, le=100)
    step: int = Field(default=63, ge=1, le=500)
    mode: Literal["rolling", "expanding"] = "rolling"
    lookbacks: list[int] = Field(default_factory=lambda: [20, 60, 120], min_length=1, max_length=5)
    rebalance: int = Field(default=21, ge=1, le=252)
    commission_bps: float = Field(default=2.0, ge=0, le=500)
    persist: bool = True


class InstitutionalApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["fixed_income", "portfolio_risk", "optimization", "walk_forward"]
    name: str = Field(min_length=1, max_length=120)
    inputs: dict[str, Any] = Field(default_factory=dict)
    result: dict[str, Any]
    object_ids: list[str] = Field(default_factory=list, max_length=20)


class LearningExperimentRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: str | None = None
    source_id: str | None = None
    models: list[Literal["climatology", "ridge", "logistic", "mlp"]] = Field(
        default_factory=lambda: ["climatology", "ridge", "logistic", "mlp"], min_length=1, max_length=4
    )
    features: list[str] | None = Field(default=None, max_length=8)
    target: Literal["direction"] = "direction"
    seed: int = Field(default=20261105, ge=0, le=2**31 - 1)
    persist: bool = True
    hypothesis: str | None = Field(default=None, max_length=1000)


class LearningPortfolioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    security_id: str = Field(min_length=1, max_length=80)
    threshold: float = Field(default=0.55, ge=0, le=1)
    commission_bps: float = Field(default=2.0, ge=0, le=500)
    slippage_bps: float = Field(default=5.0, ge=0, le=500)


class LearningDiscoveryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    dataset: str | None = None
    budget: int = Field(default=6, ge=1, le=24)


class LearningApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="forecast research", max_length=240)


class LearningMemoryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: str | None = None
    model: str | None = None
    conclusion: str | None = None
    limit: int = Field(default=50, ge=1, le=200)


class EconomicAnalyzeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    as_of: str | None = None
    mode: Literal["public_available", "atlas_ingested"] = "public_available"
    seed: int = Field(default=20261105, ge=0, le=2**31 - 1)
    persist: bool = True


class EconomicScenarioRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    shock_c: float = Field(default=2.0, ge=-10.0, le=10.0)
    annual_consumption_mwh: float = Field(default=50_000.0, ge=0, le=100_000_000)
    load_sensitivity: float = Field(default=0.5, ge=0, le=10)
    unhedged_fraction: float = Field(default=0.6, ge=0, le=1)
    power_price_usd_mwh: float = Field(default=65.0, ge=0, le=10_000)
    revenue_usd: float = Field(default=40_000_000.0, gt=0, le=1_000_000_000_000)
    tax_rate: float = Field(default=0.21, ge=0, le=1)
    draws: int = Field(default=2_000, ge=200, le=20_000)
    seed: int = Field(default=20261105, ge=0, le=2**31 - 1)


class EconomicApplicationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    scenario_id: str | None = None
    name: str = Field(min_length=1, max_length=120)
    purpose: str = Field(default="weather-to-electricity economic investigation", max_length=500)


class ApplicationExportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    run_id: str
    scenario_id: str | None = None
    version: str = Field(default="1.0.0", pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class ApplicationInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    package_base64: str = Field(min_length=1)


class ApplicationExecuteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    inputs: dict[str, Any] = Field(default_factory=dict)


class ApplicationForkBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    version: str = Field(pattern=r"^\d+\.\d+\.\d+(?:-[0-9A-Za-z.-]+)?$")


class DomainPackInstallRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    manifest: dict[str, Any]
    packages: dict[str, str] = Field(default_factory=dict)


class EconomicRevisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: float
    published_at: str | None = None
    reason: str = Field(min_length=3, max_length=500)


class SourceArchiveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    source_id: str
    resource_id: str = Field(min_length=1, max_length=240)
    content: str = Field(min_length=1, max_length=2_000_000)
    media_type: str = Field(default="application/octet-stream", max_length=120)
    published_at: str | None = None
    retrieved_at: str | None = None
    rights: str | None = Field(default=None, max_length=80)
    retention_policy: str = Field(default="local_only", max_length=80)
    schema_version: str | None = Field(default=None, max_length=80)
    parser_version: str | None = Field(default=None, max_length=80)
    evidence_ids: list[str] = Field(default_factory=list, max_length=100)


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
        version="0.3.0",
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
                        "economic_observations": int(db.scalar(
                            "SELECT COUNT(*) FROM economic_observation", default=0
                        ) or 0),
                        "economic_analyses": int(db.scalar(
                            "SELECT COUNT(*) FROM economic_analysis", default=0
                        ) or 0),
                        "application_installations": int(db.scalar(
                            "SELECT COUNT(*) FROM application_installation", default=0
                        ) or 0),
                        "domain_packs": int(db.scalar(
                            "SELECT COUNT(*) FROM domain_pack_installation", default=0
                        ) or 0),
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
            "quant_lab_schema": LAB_SCHEMA,
            "strategy_schema": "atlas.strategy.v1",
            "simulator_version": SIMULATOR_VERSION,
            "institutional_schema": "atlas.institutional.run.v1",
            "institutional_curve_schema": "atlas.finance.yield_curve.v1",
            "learning_schema": LEARNING_SCHEMA,
            "economic_schema": ECONOMIC_SCHEMA,
            "economic_panel_schema": "atlas.economic.panel.v1",
            "economic_graph_schema": "atlas.economic.graph.v1",
            "economic_scenario_schema": "atlas.economic.scenario.v1",
            "application_package_schema": PACKAGE_SCHEMA,
            "application_installation_schema": "atlas.application.installation.v1",
            "domain_pack_schema": "atlas.domain_pack.v1",
            "forecast_schema": "atlas.forecast.v1",
            "learning_features": learning_feature_catalogue()["features"],
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

    @app.post("/api/research/archive", tags=["research"], status_code=201)
    def source_archive_create(
        body: SourceArchiveRequest, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        return SourceArchiveStore(db).archive(
            source_id=body.source_id, resource_id=body.resource_id, content=body.content,
            media_type=body.media_type, published_at=body.published_at,
            retrieved_at=body.retrieved_at, rights=body.rights,
            retention_policy=body.retention_policy, schema_version=body.schema_version,
            parser_version=body.parser_version, evidence_ids=body.evidence_ids,
        )

    @app.get("/api/research/archive/{archive_id}", tags=["research"])
    def source_archive_get(archive_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return SourceArchiveStore(db).get(archive_id)

    @app.get("/api/research/archive-status", tags=["research"])
    def source_archive_status(source_ids: str = "", db: Database = Depends(get_db)) -> dict[str, Any]:
        requested = [item.strip() for item in source_ids.split(",") if item.strip()]
        return SourceArchiveStore(db).status_for_sources(requested)

    @app.get("/api/quant/catalog", tags=["quant"])
    def quant_catalog(db: Database = Depends(get_db)) -> dict[str, Any]:
        lab = QuantLab(db)
        return {
            "schema": LAB_SCHEMA,
            "strategy_schema": "atlas.strategy.v1",
            "simulator_version": SIMULATOR_VERSION,
            "templates": lab.builtin_templates(),
            "universe": quant_universe(db),
            "timing": {"signal": "session close", "fill": "next session open"},
            "limitations": ["single instrument", "long only", "no live trading"],
        }

    @app.get("/api/quant/strategies", tags=["quant"])
    def quant_strategies(limit: int = Query(default=100, ge=1, le=500),
                         db: Database = Depends(get_db)) -> dict[str, Any]:
        items = QuantLab(db).list_strategies(limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.strategy.v1"}

    @app.post("/api/quant/strategies", tags=["quant"], status_code=201)
    def quant_strategy_create(body: StrategyCreateRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        return QuantLab(db).ensure_strategy(body.spec, as_of=body.as_of, mode=body.mode)

    @app.post("/api/quant/features", tags=["quant"])
    def quant_features(body: FeatureRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        mic = body.mic
        if not mic:
            row = db.query_one(
                "SELECT mic FROM listing WHERE security_id = ? ORDER BY is_primary DESC, valid_from LIMIT 1",
                (body.security_id,),
            )
            if row is None:
                raise ValidationError("unknown security", security_id=body.security_id)
            mic = row["mic"]
        result = FeatureEngine(db).compute(
            body.security_id, mic, body.features, start=body.start, end=body.end,
            as_of=body.as_of, missing=body.missing, persist=body.persist,
        )
        return result.to_dict()

    @app.post("/api/quant/preview", tags=["quant"])
    def quant_preview(body: PreviewRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        if body.strategy_id:
            stored = research_objects.ResearchObjectStore(db).get(body.strategy_id)
            if stored["kind"] != "strategy":
                raise ValidationError("preview requires a strategy object", kind=stored["kind"])
            spec = stored["document"]["spec"]
        elif body.spec:
            spec = body.spec
        else:
            raise ValidationError("provide strategy_id or a strategy spec")
        return run_preview(db, spec, VectorizedConfig(
            as_of=body.as_of, start=body.start, end=body.end,
            initial_capital=body.initial_capital,
            commission_bps=body.commission_bps, slippage_bps=body.slippage_bps,
        ))

    @app.post("/api/quant/backtest", tags=["quant"])
    def quant_backtest(body: BacktestRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        if not body.strategy_id and not body.spec:
            raise ValidationError("provide strategy_id or a strategy spec")
        config = SimulationConfig(
            as_of=body.as_of, start=body.start, end=body.end,
            initial_capital=body.initial_capital, commission_bps=body.commission_bps,
            slippage_bps=body.slippage_bps,
        )
        return QuantLab(db).run(
            strategy_id=body.strategy_id, spec=body.spec, config=config,
            persist=body.persist, hypothesis=body.hypothesis,
            experiment_name=body.experiment_name,
        )

    @app.get("/api/quant/runs", tags=["quant"])
    def quant_runs(limit: int = Query(default=50, ge=1, le=200),
                   db: Database = Depends(get_db)) -> dict[str, Any]:
        return {"items": QuantLab(db).list_runs(limit=limit), "schema": LAB_SCHEMA}

    @app.get("/api/quant/runs/{run_id}", tags=["quant"])
    def quant_run_get(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return QuantLab(db).get_run(run_id)

    @app.get("/api/quant/runs/{run_id}/capsule", tags=["quant"])
    def quant_run_capsule(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return QuantLab(db).capsule(run_id)

    @app.post("/api/quant/runs/{run_id}/replay", tags=["quant"])
    def quant_run_replay(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return QuantLab(db).replay(run_id)

    @app.get("/api/quant/experiments", tags=["quant"])
    def quant_experiments(limit: int = Query(default=100, ge=1, le=500),
                          db: Database = Depends(get_db)) -> dict[str, Any]:
        items = QuantLab(db).list_experiments(limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.research_object.v1"}

    # ------------------------------------------------------------ learning lab
    @app.get("/api/learning/catalog", tags=["learning"])
    def learning_catalog(db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).catalog()

    @app.get("/api/learning/dataset", tags=["learning"])
    def learning_dataset(dataset: str | None = None, source_id: str | None = None,
                         start: str | None = None, end: str | None = None,
                         db: Database = Depends(get_db)) -> dict[str, Any]:
        from ..learning.data import load_panel

        return load_panel(db, dataset=dataset, source_id=source_id, start=start, end=end)

    @app.post("/api/learning/experiment", tags=["learning"])
    def learning_experiment(body: LearningExperimentRequest,
                            db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).run(
            dataset=body.dataset, source_id=body.source_id, models=body.models,
            features=body.features, target=body.target, seed=body.seed,
            persist=body.persist, hypothesis=body.hypothesis,
        )

    @app.get("/api/learning/runs", tags=["learning"])
    def learning_runs(limit: int = Query(default=50, ge=1, le=200),
                      db: Database = Depends(get_db)) -> dict[str, Any]:
        items = LearningService(db).list_runs(limit=limit)
        return {"items": items, "count": len(items), "schema": LEARNING_SCHEMA}

    @app.get("/api/learning/runs/{run_id}", tags=["learning"])
    def learning_run_get(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).get_run(run_id)

    @app.get("/api/learning/runs/{run_id}/forecasts", tags=["learning"])
    def learning_run_forecasts(run_id: str, security_id: str | None = None,
                               db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).forecast(run_id, security_id=security_id)

    @app.get("/api/learning/runs/{run_id}/audit", tags=["learning"])
    def learning_run_audit(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        run = LearningService(db).get_run(run_id)
        return {"run_id": run_id, **run.get("audit", {})}

    @app.get("/api/learning/runs/{run_id}/monitor", tags=["learning"])
    def learning_run_monitor(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).monitor(run_id)

    @app.post("/api/learning/runs/{run_id}/portfolio", tags=["learning"])
    def learning_run_portfolio(run_id: str, body: LearningPortfolioRequest,
                               db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).portfolio_experiment(
            run_id, security_id=body.security_id, threshold=body.threshold,
            commission_bps=body.commission_bps, slippage_bps=body.slippage_bps,
        )

    @app.get("/api/learning/models", tags=["learning"])
    def learning_models(limit: int = Query(default=100, ge=1, le=200),
                        db: Database = Depends(get_db)) -> dict[str, Any]:
        items = LearningService(db).models(limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.learning.model.v2"}

    @app.post("/api/learning/memory", tags=["learning"])
    def learning_memory(body: LearningMemoryRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).memory(target=body.target, model=body.model,
                                          conclusion=body.conclusion, limit=body.limit)

    @app.post("/api/learning/discovery", tags=["learning"])
    def learning_discovery(body: LearningDiscoveryRequest,
                           db: Database = Depends(get_db)) -> dict[str, Any]:
        return LearningService(db).discovery(budget=body.budget, dataset=body.dataset)

    @app.post("/api/learning/applications", tags=["learning"], status_code=201)
    def learning_application_create(body: LearningApplicationRequest,
                                    db: Database = Depends(get_db)) -> dict[str, Any]:
        service = LearningService(db)
        run = service.get_run(body.run_id)
        document = {
            "schema_version": "atlas.research_object.v1", "kind": "application",
            "name": body.name, "version": "1.0.0", "status": "validated",
            "description": body.purpose, "as_of": iso(utcnow()),
            "mode": "atlas_ingested", "evidence_ids": [],
            "source_ids": [run["dataset"]["source_id"]],
            "object_ids": [item for item in [run.get("model_object_id"), run.get("experiment_object_id")] if item],
            "assumptions": ["The stored forecasts are frozen artifacts."],
            "limitations": run.get("limitations", []),
            "spec": {"purpose": body.purpose, "views": ["forecast", "audit", "memory"],
                     "learning_run_id": body.run_id, "model_id": run.get("model_id"),
                     "test_metrics": run.get("test"), "audit": run.get("audit")},
        }
        return service.objects.create(document)

    @app.get("/api/learning/applications", tags=["learning"])
    def learning_applications(limit: int = Query(default=50, ge=1, le=200),
                              db: Database = Depends(get_db)) -> dict[str, Any]:
        items = research_objects.ResearchObjectStore(db).list(kind="application", limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.research_object.v1"}

    # ------------------------------------------------------- institutional lab
    # ------------------------------------------------------- economic intelligence
    @app.get("/api/economic/catalog", tags=["economic"])
    def economic_catalog(db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).catalog()

    @app.get("/api/economic/panel", tags=["economic"])
    def economic_panel(as_of: str | None = None,
                       mode: Literal["public_available", "atlas_ingested"] = "public_available",
                       db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).panel(as_of=as_of, mode=mode)

    @app.get("/api/economic/graph", tags=["economic"])
    def economic_graph(as_of: str | None = None, entity_id: str | None = None,
                       depth: int = Query(default=2, ge=1, le=5),
                       db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).graph(as_of=as_of, entity_id=entity_id, depth=depth)

    @app.get("/api/economic/conflicts", tags=["economic"])
    def economic_conflicts(db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).conflicts()

    @app.post("/api/economic/analyze", tags=["economic"])
    def economic_analyze(body: EconomicAnalyzeRequest,
                         db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).analyze(
            as_of=body.as_of, mode=body.mode, seed=body.seed, persist=body.persist,
        )

    @app.get("/api/economic/runs", tags=["economic"])
    def economic_runs(limit: int = Query(default=50, ge=1, le=200),
                      db: Database = Depends(get_db)) -> dict[str, Any]:
        items = EconomicService(db).list_runs(limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.economic.analysis.v1"}

    @app.get("/api/economic/runs/{run_id}", tags=["economic"])
    def economic_run_get(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).get_run(run_id)

    @app.post("/api/economic/runs/{run_id}/scenario", tags=["economic"])
    def economic_scenario(run_id: str, body: EconomicScenarioRequest,
                          db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).scenario(run_id, **body.model_dump())

    @app.get("/api/economic/runs/{run_id}/scenarios", tags=["economic"])
    def economic_scenarios(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return {"run_id": run_id, "items": EconomicService(db).scenarios(run_id),
                "schema": "atlas.economic.scenario.v1"}

    @app.get("/api/economic/runs/{run_id}/replay", tags=["economic"])
    def economic_replay(run_id: str, as_of: str,
                        mode: Literal["public_available", "atlas_ingested"] = "public_available",
                        db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).replay(run_id, as_of=as_of, mode=mode)

    @app.get("/api/economic/memory", tags=["economic"])
    def economic_memory(limit: int = Query(default=100, ge=1, le=200),
                        db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).memory(limit=limit)

    @app.post("/api/economic/applications", tags=["economic"], status_code=201)
    def economic_application(body: EconomicApplicationRequest,
                             db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).save_application(
            body.run_id, name=body.name, purpose=body.purpose, scenario_id=body.scenario_id,
        )

    @app.get("/api/economic/sentinel", tags=["economic"])
    def economic_sentinel(db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).sentinel_refresh()

    @app.post("/api/economic/observations/{observation_id}/revise", tags=["economic"])
    def economic_revision(observation_id: str, body: EconomicRevisionRequest,
                          db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).revise_observation(
            observation_id, value=body.value, published_at=body.published_at, reason=body.reason,
        )

    @app.get("/api/economic/benchmarks", tags=["economic"])
    def economic_benchmarks(db: Database = Depends(get_db)) -> dict[str, Any]:
        return EconomicService(db).benchmarks()

    # ------------------------------------------------------ application gallery
    @app.get("/api/applications", tags=["applications"])
    def application_gallery(db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).gallery()

    @app.post("/api/applications/export", tags=["applications"], status_code=201)
    def application_export(body: ApplicationExportRequest,
                           db: Database = Depends(get_db)) -> dict[str, Any]:
        built = ApplicationService(db).create_economic_package(
            body.run_id, scenario_id=body.scenario_id, version=body.version,
        )
        return {
            "schema": "atlas.application.export.v1",
            "package_id": built["package_id"],
            "package_sha256": built["package_sha256"],
            "application_id": built["application_id"],
            "version": built["version"],
            "reproducibility": built["reproducibility"],
            "package_base64": base64.b64encode(built["payload"]).decode("ascii"),
        }

    @app.post("/api/applications/install", tags=["applications"], status_code=201)
    def application_install(body: ApplicationInstallRequest,
                            db: Database = Depends(get_db)) -> dict[str, Any]:
        try:
            payload = base64.b64decode(body.package_base64, validate=True)
        except (binascii.Error, ValueError) as exc:
            raise ValidationError("package_base64 is not valid base64") from exc
        return ApplicationService(db).install(payload)

    @app.get("/api/applications/{install_id}", tags=["applications"])
    def application_get(install_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).get(install_id)

    @app.get("/api/applications/{install_id}/open", tags=["applications"])
    def application_open(install_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).open(install_id)

    @app.get("/api/applications/{install_id}/verify", tags=["applications"])
    def application_verify(install_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).verify(install_id)

    @app.get("/api/applications/{install_id}/download", tags=["applications"])
    def application_download(install_id: str, db: Database = Depends(get_db)) -> Response:
        payload, filename = ApplicationService(db).export_bytes(install_id)
        return Response(
            content=payload, media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{filename}"',
                     "X-Atlas-Integrity": "unsigned; SHA-256 verified by server"},
        )

    @app.post("/api/applications/{install_id}/execute", tags=["applications"])
    def application_execute(install_id: str, body: ApplicationExecuteRequest,
                            db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).execute(install_id, body.inputs)

    @app.post("/api/applications/{install_id}/fork", tags=["applications"], status_code=201)
    def application_fork(install_id: str, body: ApplicationForkBody,
                         db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).fork(install_id, name=body.name, version=body.version)

    @app.get("/api/applications/{install_id}/compare", tags=["applications"])
    def application_compare(install_id: str, right: str,
                            db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).compare(install_id, right)

    @app.delete("/api/applications/{install_id}", tags=["applications"])
    def application_uninstall(install_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return ApplicationService(db).uninstall(install_id)

    @app.get("/api/domain-packs", tags=["applications"])
    def domain_pack_list(db: Database = Depends(get_db)) -> dict[str, Any]:
        items = DomainPackService(db).list()
        return {"schema": "atlas.domain_pack.list.v1", "items": items, "count": len(items)}

    @app.post("/api/domain-packs/install", tags=["applications"], status_code=201)
    def domain_pack_install(body: DomainPackInstallRequest,
                            db: Database = Depends(get_db)) -> dict[str, Any]:
        packages: dict[str, bytes] = {}
        for path, encoded in body.packages.items():
            try:
                packages[path] = base64.b64decode(encoded, validate=True)
            except (binascii.Error, ValueError) as exc:
                raise ValidationError("domain-pack package is not valid base64", path=path) from exc
        return DomainPackService(db).install(body.manifest, package_bytes=packages)

    @app.get("/api/domain-packs/{pack_id}/{version}", tags=["applications"])
    def domain_pack_get(pack_id: str, version: str,
                        db: Database = Depends(get_db)) -> dict[str, Any]:
        return DomainPackService(db).get(pack_id, version)

    @app.delete("/api/domain-packs/{pack_id}/{version}", tags=["applications"])
    def domain_pack_uninstall(pack_id: str, version: str,
                              db: Database = Depends(get_db)) -> dict[str, Any]:
        return DomainPackService(db).uninstall(pack_id, version)

    # ------------------------------------------------------- institutional lab
    @app.get("/api/institutional/catalog", tags=["institutional"])
    def institutional_catalog(db: Database = Depends(get_db)) -> dict[str, Any]:
        return InstitutionalService(db).catalog()

    @app.get("/api/institutional/universe", tags=["institutional"])
    def institutional_universe() -> dict[str, Any]:
        return aligned_panel()

    @app.get("/api/institutional/curve", tags=["institutional"])
    def institutional_curve_get(
        date: str = Query(default=DEFAULT_CURVE_DATE, pattern=r"^\d{4}-\d{2}-\d{2}$"),
    ) -> dict[str, Any]:
        return institutional_curve(date).to_dict()

    @app.post("/api/institutional/bond", tags=["institutional"])
    def institutional_bond_post(body: BondRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        result = institutional_bond(
            settlement_date=body.settlement_date, maturity_date=body.maturity_date,
            coupon_rate=body.coupon_rate, curve_date=body.curve_date,
            face=body.face, frequency=body.frequency,
        )
        if body.persist:
            result = InstitutionalService(db).save(
                "bond", inputs=body.model_dump(exclude={"persist"}), result=result,
                as_of=body.settlement_date,
            )
        return result

    @app.post("/api/institutional/option", tags=["institutional"])
    def institutional_option_post(body: OptionRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        result = institutional_option(
            spot=body.spot, strike=body.strike, time=body.time, rate=body.rate,
            volatility=body.volatility, dividend_yield=body.dividend_yield,
        )
        if body.persist:
            result = InstitutionalService(db).save(
                "option", inputs=body.model_dump(exclude={"persist"}), result=result,
            )
        return result

    @app.post("/api/institutional/portfolio", tags=["institutional"])
    def institutional_portfolio(body: PortfolioRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        matrix = returns_matrix()
        weights = body.weights or {security: 1.0 / len(matrix["securities"])
                                   for security in matrix["securities"]}
        result = portfolio_analysis(
            weights=weights, lookback=body.lookback, capital=body.capital,
            risk_free=body.risk_free,
        )
        if body.persist:
            result = InstitutionalService(db).save(
                "portfolio_risk", inputs=body.model_dump(exclude={"persist"}), result=result,
                data_class=result.get("data_class"),
            )
        return result

    @app.post("/api/institutional/optimize", tags=["institutional"])
    def institutional_optimize(body: OptimizeRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        matrix = returns_matrix()
        weights = body.weights or {security: 1.0 / len(matrix["securities"])
                                   for security in matrix["securities"]}
        result = optimize_portfolio(
            weights=weights, max_weight=body.max_weight, cash_weight=body.cash_weight,
            target_return=body.target_return, shrinkage=body.shrinkage,
            current_weights=body.current_weights,
        )
        if body.persist:
            result = InstitutionalService(db).save(
                "optimization", inputs=body.model_dump(exclude={"persist"}), result=result,
                data_class=result.get("data_class"),
            )
        return result

    @app.post("/api/institutional/validate", tags=["institutional"])
    def institutional_validate(body: ValidationRequest, db: Database = Depends(get_db)) -> dict[str, Any]:
        result = walk_forward(
            folds=body.folds, train=body.train, validation=body.validation,
            test=body.test, embargo=body.embargo, step=body.step, mode=body.mode,
            lookbacks=tuple(body.lookbacks), rebalance=body.rebalance,
            commission_bps=body.commission_bps,
        )
        if body.persist:
            result = InstitutionalService(db).save_validation(
                result, body.model_dump(exclude={"persist"})
            )
        return result

    @app.get("/api/institutional/runs", tags=["institutional"])
    def institutional_runs(limit: int = Query(default=50, ge=1, le=200),
                           db: Database = Depends(get_db)) -> dict[str, Any]:
        items = InstitutionalService(db).list_runs(limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.institutional.run.v1"}

    @app.get("/api/institutional/runs/{run_id}", tags=["institutional"])
    def institutional_run_get(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        return InstitutionalService(db).get_run(run_id)

    @app.get("/api/institutional/runs/{run_id}/attempts", tags=["institutional"])
    def institutional_run_attempts(run_id: str, db: Database = Depends(get_db)) -> dict[str, Any]:
        service = InstitutionalService(db)
        service.get_run(run_id)
        return {"run_id": run_id, "items": service.validation_attempts(run_id)}

    @app.post("/api/institutional/applications", tags=["institutional"], status_code=201)
    def institutional_application_create(
        body: InstitutionalApplicationRequest, db: Database = Depends(get_db)
    ) -> dict[str, Any]:
        service = InstitutionalService(db)
        document = service.application_document(
            kind=body.kind, name=body.name, inputs=body.inputs, result=body.result,
            object_ids=body.object_ids,
        )
        return service.save_application(document)

    @app.get("/api/institutional/applications", tags=["institutional"])
    def institutional_applications(limit: int = Query(default=50, ge=1, le=200),
                                   db: Database = Depends(get_db)) -> dict[str, Any]:
        items = research_objects.ResearchObjectStore(db).list(kind="application", limit=limit)
        return {"items": items, "count": len(items), "schema": "atlas.research_object.v1"}

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
