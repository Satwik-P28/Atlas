"""Typed workspace configurations.

A workspace is **data**, not a script: a deterministic JSON document describing which
panels exist, what each one shows and how they are arranged. The terminal validates and
renders it; nothing in it can execute code. That is deliberate — the future
Intent-to-Workspace compiler will emit this same schema, so validation is the boundary
between generated and hand-built layouts.

Panel types are declared with the fields they require. Validation rejects unknown
types, unknown config keys, duplicate panel ids, invalid spans and malformed indicator
references, so a saved workspace either renders exactly as reviewed or is refused.
"""

from __future__ import annotations

import copy
import hashlib
import json
import re
from dataclasses import dataclass
from typing import Any

from ..core.errors import ValidationError
from .indicators import REGISTRY as INDICATORS

PANEL_ID = re.compile(r"^[a-z0-9][a-z0-9-]{0,31}$")
WORKSPACE_ID = re.compile(r"^[A-Za-z0-9_-]{1,64}$")

MODES = ("standard", "advanced")
STATEMENTS = ("income", "balance", "cashflow")


@dataclass(frozen=True, slots=True)
class PanelType:
    key: str
    label: str
    description: str
    requires: tuple[str, ...]
    config_keys: tuple[str, ...]
    min_mode: str  # "standard" is available in both; "advanced" only in Advanced mode
    default_config: dict[str, Any]


PANEL_TYPES: dict[str, PanelType] = {
    "market-overview": PanelType(
        key="market-overview",
        label="Market overview",
        description="Watchlist-style table of covered securities with latest prices.",
        requires=(),
        config_keys=("range",),
        min_mode="standard",
        default_config={"range": "6M"},
    ),
    "chart": PanelType(
        key="chart",
        label="Price chart",
        description="Candlestick or line chart with optional indicator overlays.",
        requires=("security_id",),
        config_keys=("view", "range", "indicators", "chart_type"),
        min_mode="standard",
        default_config={"view": "split", "range": "1Y", "indicators": [], "chart_type": "candlestick"},
    ),
    "statements": PanelType(
        key="statements",
        label="Financial statements",
        description="Point-in-time statement table for one issuer.",
        requires=("issuer_id",),
        config_keys=("statement", "period", "limit", "mode"),
        min_mode="standard",
        default_config={"statement": "income", "period": "FY", "limit": 5, "mode": "public_available"},
    ),
    "metrics": PanelType(
        key="metrics",
        label="Key metrics",
        description="Revenue, margins, and valuation metrics with their formulas.",
        requires=("issuer_id",),
        config_keys=("as_of", "mode"),
        min_mode="standard",
        default_config={"as_of": None, "mode": "public_available"},
    ),
    "filings": PanelType(
        key="filings",
        label="Filings and events",
        description="Recent SEC filings, amendments and corporate actions.",
        requires=("issuer_id",),
        config_keys=("limit", "forms"),
        min_mode="standard",
        default_config={"limit": 12, "forms": []},
    ),
    "company-header": PanelType(
        key="company-header",
        label="Company header",
        description="Identity, tickers, fiscal year end and data coverage.",
        requires=("issuer_id",),
        config_keys=(),
        min_mode="standard",
        default_config={},
    ),
    "xray": PanelType(
        key="xray",
        label="Financial X-Ray",
        description="Full provenance for one evidence record.",
        requires=("evidence_id",),
        config_keys=(),
        min_mode="advanced",
        default_config={},
    ),
    "indicator-controls": PanelType(
        key="indicator-controls",
        label="Indicator controls",
        description="Parameter controls for indicators in the workspace.",
        requires=(),
        config_keys=("indicator",),
        min_mode="advanced",
        default_config={"indicator": "sma"},
    ),
    "watchlist": PanelType(
        key="watchlist",
        label="Watchlist",
        description="A saved watchlist with configurable columns.",
        requires=("watchlist_id",),
        config_keys=("columns",),
        min_mode="advanced",
        default_config={"columns": ["ticker", "last", "change_1d", "revenue"]},
    ),
    "screener": PanelType(
        key="screener",
        label="Screener results",
        description="Saved screener configuration and its current matches.",
        requires=(),
        config_keys=("filters", "sort", "match"),
        min_mode="advanced",
        default_config={"filters": [], "sort": None, "match": "AND"},
    ),
}


def _chart_range(value: str) -> bool:
    return value in {"1M", "3M", "6M", "1Y", "2Y", "5Y", "MAX"}


def _validate_config(panel_type: PanelType, config: Any) -> dict[str, Any]:
    if config is None:
        return copy.deepcopy(panel_type.default_config)
    if not isinstance(config, dict):
        raise ValidationError("panel config must be an object", panel=panel_type.key)
    unknown = set(config) - set(panel_type.config_keys)
    if unknown:
        raise ValidationError(
            "unknown panel config key",
            panel=panel_type.key,
            unknown=sorted(unknown),
            supported=list(panel_type.config_keys),
        )
    merged = copy.deepcopy(panel_type.default_config)
    merged.update(config)

    if panel_type.key == "chart":
        if merged["view"] not in {"raw", "split", "total_return"}:
            raise ValidationError("unknown chart view", view=merged["view"])
        if not _chart_range(str(merged["range"])):
            raise ValidationError("unknown chart range", range=merged["range"])
        if merged["chart_type"] not in {"candlestick", "line", "area"}:
            raise ValidationError("unknown chart type", chart_type=merged["chart_type"])
        indicators = merged["indicators"]
        if not isinstance(indicators, list) or len(indicators) > 6:
            raise ValidationError("indicators must be a list of at most 6 entries")
        normalized = []
        for item in indicators:
            if not isinstance(item, dict) or item.get("key") not in INDICATORS:
                raise ValidationError("unknown indicator reference", item=item)
            params = item.get("params") or {}
            if not isinstance(params, dict):
                raise ValidationError("indicator params must be an object", indicator=item.get("key"))
            # Reuse the indicator registry's own validation by computing on a tiny series
            # is wasteful; validate parameter names/ranges structurally instead.
            spec = INDICATORS[item["key"]]
            known = {p.name for p in spec.params}
            unknown_params = set(params) - known
            if unknown_params:
                raise ValidationError(
                    "unknown indicator parameter",
                    indicator=item["key"],
                    unknown=sorted(unknown_params),
                )
            normalized.append({"key": item["key"], "params": dict(params)})
        merged["indicators"] = normalized
    elif panel_type.key == "statements":
        if merged["statement"] not in STATEMENTS:
            raise ValidationError("unknown statement", statement=merged["statement"])
        if merged["period"] not in {"FY", "Q"}:
            raise ValidationError("unknown statement period", period=merged["period"])
        if not isinstance(merged["limit"], int) or not (1 <= merged["limit"] <= 20):
            raise ValidationError("statement limit must be between 1 and 20")
    elif panel_type.key == "filings":
        if not isinstance(merged["limit"], int) or not (1 <= merged["limit"] <= 100):
            raise ValidationError("filing limit must be between 1 and 100")
        if not isinstance(merged["forms"], list):
            raise ValidationError("forms must be a list")
    elif panel_type.key == "watchlist":
        allowed = {"ticker", "last", "change_1d", "change_1y", "revenue", "net_margin", "pe"}
        if not isinstance(merged["columns"], list) or not set(merged["columns"]) <= allowed:
            raise ValidationError("unknown watchlist column", allowed=sorted(allowed))
    elif panel_type.key == "screener":
        if merged["match"] not in {"AND", "OR"}:
            raise ValidationError("screener match must be AND or OR")
        if not isinstance(merged["filters"], list):
            raise ValidationError("screener filters must be a list")
    elif panel_type.key == "indicator-controls":
        if merged["indicator"] not in INDICATORS:
            raise ValidationError("unknown indicator", indicator=merged["indicator"])
    elif panel_type.key == "market-overview":
        if not _chart_range(str(merged["range"])):
            raise ValidationError("unknown range", range=merged["range"])
    return merged


def validate_workspace(payload: Any, *, workspace_id: str | None = None) -> dict[str, Any]:
    """Validate and normalise a workspace document (strict, no unknown keys)."""
    if not isinstance(payload, dict):
        raise ValidationError("workspace must be an object")
    allowed = {"name", "mode", "columns", "panels", "description", "schema"}
    unknown = set(payload) - allowed
    if "schema" in payload and payload["schema"] != "atlas.workspace.v1":
        raise ValidationError(
            "unsupported workspace schema", schema=payload["schema"], supported="atlas.workspace.v1"
        )
    if unknown:
        raise ValidationError("unknown workspace key", unknown=sorted(unknown), supported=sorted(allowed))
    name = payload.get("name")
    if not isinstance(name, str) or not name.strip() or len(name) > 80:
        raise ValidationError("workspace name is required and must be at most 80 characters")
    mode = payload.get("mode", "advanced")
    if mode not in MODES:
        raise ValidationError("unknown workspace mode", mode=mode)
    columns = payload.get("columns", 3)
    if not isinstance(columns, int) or not (1 <= columns <= 4):
        raise ValidationError("workspace columns must be between 1 and 4")
    panels = payload.get("panels")
    if not isinstance(panels, list) or not (1 <= len(panels) <= 12):
        raise ValidationError("workspace needs between 1 and 12 panels")
    seen: set[str] = set()
    normalized_panels: list[dict[str, Any]] = []
    for index, panel in enumerate(panels):
        if not isinstance(panel, dict):
            raise ValidationError("panel must be an object", index=index)
        panel_allowed = {"id", "type", "title", "span", "config"} | set(PANEL_TYPES.get(str(panel.get("type")), PANEL_TYPES["chart"]).requires)
        unknown_panel = set(panel) - panel_allowed
        if unknown_panel:
            raise ValidationError("unknown panel key", index=index, unknown=sorted(unknown_panel))
        panel_id = panel.get("id")
        if not isinstance(panel_id, str) or not PANEL_ID.match(panel_id):
            raise ValidationError("panel id must match [a-z0-9-], 1-32 characters", index=index)
        if panel_id in seen:
            raise ValidationError("duplicate panel id", panel_id=panel_id)
        seen.add(panel_id)
        type_key = panel.get("type")
        panel_type = PANEL_TYPES.get(str(type_key))
        if panel_type is None:
            raise ValidationError("unknown panel type", type=type_key, supported=sorted(PANEL_TYPES))
        if mode == "standard" and panel_type.min_mode == "advanced":
            raise ValidationError(
                "panel type requires advanced mode", type=type_key, mode=mode
            )
        for required in panel_type.requires:
            value = panel.get(required)
            if not isinstance(value, str) or not value:
                raise ValidationError("panel is missing a required field", type=type_key, field=required)
        span = panel.get("span", 1)
        if not isinstance(span, int) or not (1 <= span <= columns):
            raise ValidationError("panel span must be between 1 and the column count", panel=panel_id)
        title = panel.get("title") or panel_type.label
        if not isinstance(title, str) or len(title) > 80:
            raise ValidationError("panel title must be a string of at most 80 characters")
        normalized = {
            "id": panel_id,
            "type": type_key,
            "title": title,
            "span": span,
            "config": _validate_config(panel_type, panel.get("config")),
        }
        for required in panel_type.requires:
            normalized[required] = panel[required]
        normalized_panels.append(normalized)
    document = {
        "name": name.strip(),
        "mode": mode,
        "columns": columns,
        "description": (payload.get("description") or "").strip()[:400] or None,
        "panels": normalized_panels,
    }
    if workspace_id is not None:
        document["workspace_id"] = workspace_id
    document["schema"] = "atlas.workspace.v1"
    return document


def fingerprint(document: dict[str, Any]) -> str:
    body = {k: v for k, v in document.items() if k != "workspace_id"}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()[:16]


def presets() -> list[dict[str, Any]]:
    """Built-in workspaces, expressed in the identical validated schema."""
    return [
        validate_workspace(
            {
                "name": "Equity research",
                "mode": "advanced",
                "columns": 3,
                "description": "Price context, statements, valuation metrics and filings for one company.",
                "panels": [
                    {"id": "header", "type": "company-header", "span": 3, "issuer_id": "{issuer}"},
                    {
                        "id": "price",
                        "type": "chart",
                        "span": 2,
                        "security_id": "{security}",
                        "title": "Price",
                        "config": {"view": "split", "range": "1Y", "chart_type": "candlestick",
                                   "indicators": [{"key": "sma", "params": {"window": 50}},
                                                  {"key": "sma", "params": {"window": 200}}]},
                    },
                    {"id": "metrics", "type": "metrics", "span": 1, "issuer_id": "{issuer}"},
                    {"id": "income", "type": "statements", "span": 2, "issuer_id": "{issuer}",
                     "title": "Income statement", "config": {"statement": "income", "period": "FY", "limit": 5}},
                    {"id": "events", "type": "filings", "span": 1, "issuer_id": "{issuer}"},
                ],
            }
        ),
        validate_workspace(
            {
                "name": "Technical analysis",
                "mode": "advanced",
                "columns": 2,
                "description": "Chart, volume and momentum indicators for one security.",
                "panels": [
                    {
                        "id": "chart",
                        "type": "chart",
                        "span": 2,
                        "security_id": "{security}",
                        "title": "Price and indicators",
                        "config": {
                            "view": "raw",
                            "range": "2Y",
                            "chart_type": "candlestick",
                            "indicators": [
                                {"key": "sma", "params": {"window": 50}},
                                {"key": "bollinger", "params": {"window": 20, "num_std": 2.0}},
                                {"key": "rsi", "params": {"window": 14}},
                                {"key": "macd", "params": {"fast": 12, "slow": 26, "signal": 9}},
                            ],
                        },
                    },
                    {"id": "controls", "type": "indicator-controls", "span": 1, "config": {"indicator": "rsi"}},
                    {"id": "header", "type": "company-header", "span": 1, "issuer_id": "{issuer}"},
                ],
            }
        ),
        validate_workspace(
            {
                "name": "Historical research",
                "mode": "advanced",
                "columns": 3,
                "description": "As-of financials, provenance and revision history.",
                "panels": [
                    {"id": "header", "type": "company-header", "span": 3, "issuer_id": "{issuer}"},
                    {"id": "balance", "type": "statements", "span": 2, "issuer_id": "{issuer}",
                     "title": "Balance sheet (as of)", "config": {"statement": "balance", "period": "FY", "limit": 5}},
                    {"id": "metrics", "type": "metrics", "span": 1, "issuer_id": "{issuer}"},
                    {"id": "events", "type": "filings", "span": 3, "issuer_id": "{issuer}"},
                ],
            }
        ),
    ]
