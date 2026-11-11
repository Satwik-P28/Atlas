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

# v1 is the grid document (columns + spans). v2 adds an explicit split/tab layout
# tree and panel link groups, so a workstation can dock, tab and maximize panels
# without the client inventing structure the server cannot check.
WORKSPACE_SCHEMAS = ("atlas.workspace.v1", "atlas.workspace.v2")
LAYOUT_SCHEMA = "atlas.workspace.v2"
LINK_GROUPS = ("A", "B", "C", "D")
MAX_LAYOUT_DEPTH = 5
MAX_LAYOUT_NODES = 40
MAX_TABS_PER_GROUP = 8


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
    "filing": PanelType(
        key="filing",
        label="Document evidence",
        description="Passages retrieved from archived filings under the desk information cutoff.",
        requires=(),
        config_keys=("query", "forms", "limit"),
        min_mode="advanced",
        default_config={"query": "risk factors", "forms": [], "limit": 5},
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
    "evidence": PanelType(
        key="evidence",
        label="Evidence inspector",
        description="Provenance inspector that shows whichever observation the analyst selects.",
        requires=(),
        config_keys=(),
        min_mode="advanced",
        default_config={},
    ),
    "memo": PanelType(
        key="memo",
        label="Research memo",
        description="Saved memo versions, content hashes and change detection.",
        requires=(),
        config_keys=("limit",),
        min_mode="advanced",
        default_config={"limit": 5},
    ),
    "model": PanelType(
        key="model",
        label="Model registry",
        description="Registered model and indicator versions read from the service contract.",
        requires=(),
        config_keys=(),
        min_mode="advanced",
        default_config={},
    ),
    "diagnostics": PanelType(
        key="diagnostics",
        label="Diagnostics",
        description="Database, schema, integrity and desk context for this session.",
        requires=(),
        config_keys=(),
        min_mode="advanced",
        default_config={},
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
    elif panel_type.key == "memo":
        if not isinstance(merged["limit"], int) or not (1 <= merged["limit"] <= 20):
            raise ValidationError("memo limit must be between 1 and 20")
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
    schema = payload.get("schema", WORKSPACE_SCHEMAS[0])
    if schema not in WORKSPACE_SCHEMAS:
        raise ValidationError(
            "unsupported workspace schema", schema=schema, supported=list(WORKSPACE_SCHEMAS)
        )
    allows_layout = schema == LAYOUT_SCHEMA
    allowed = {"name", "mode", "columns", "panels", "description", "schema"}
    if allows_layout:
        allowed.add("layout")
    unknown = set(payload) - allowed
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
        if allows_layout:
            panel_allowed.add("link_group")
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
        if allows_layout:
            link_group = panel.get("link_group")
            if link_group is not None:
                if link_group not in LINK_GROUPS:
                    raise ValidationError(
                        "unknown link group", panel=panel_id, link_group=link_group, supported=list(LINK_GROUPS)
                    )
                normalized["link_group"] = link_group
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
    if allows_layout:
        layout = payload.get("layout")
        if layout is None:
            # A v2 document without a layout still has to render: derive the grid
            # arrangement from columns and spans so nothing can be orphaned.
            layout = derive_layout(normalized_panels, columns)
        document["layout"] = validate_layout(layout, [panel["id"] for panel in normalized_panels])
    if workspace_id is not None:
        document["workspace_id"] = workspace_id
    document["schema"] = schema
    return document


def _tabs(panel_id: str) -> dict[str, Any]:
    return {"type": "tabs", "active": panel_id, "panels": [panel_id]}


def _validate_weights(weights: Any, count: int) -> list[float]:
    if not isinstance(weights, list) or len(weights) != count:
        raise ValidationError("split weights must match the number of children", expected=count)
    numbers: list[float] = []
    for weight in weights:
        if isinstance(weight, bool) or not isinstance(weight, (int, float)):
            raise ValidationError("split weight must be a number", weight=weight)
        value = float(weight)
        if not (0.05 <= value <= 0.95):
            raise ValidationError("split weight must be between 0.05 and 0.95", weight=value)
        numbers.append(value)
    total = sum(numbers)
    if abs(total - 1.0) > 1e-6:
        raise ValidationError("split weights must sum to 1", total=round(total, 9))
    rounded = [round(value / total, 6) for value in numbers]
    rounded[-1] = round(1.0 - sum(rounded[:-1]), 6)
    return rounded


def validate_layout(layout: Any, panel_ids: list[str]) -> dict[str, Any]:
    """Validate a split/tabs layout tree.

    Every panel appears exactly once, ids and node shapes are checked, weights are
    normalised, and unknown keys are refused. A layout can therefore describe any
    docking arrangement without carrying anything the renderer would have to trust.
    """
    known = set(panel_ids)
    placed: list[str] = []
    nodes = 0

    def walk(node: Any, depth: int) -> dict[str, Any]:
        nonlocal nodes
        if depth > MAX_LAYOUT_DEPTH:
            raise ValidationError("layout is nested too deeply", limit=MAX_LAYOUT_DEPTH)
        if not isinstance(node, dict):
            raise ValidationError("layout node must be an object")
        nodes += 1
        if nodes > MAX_LAYOUT_NODES:
            raise ValidationError("layout has too many nodes", limit=MAX_LAYOUT_NODES)
        kind = node.get("type")
        if kind == "tabs":
            unknown = set(node) - {"type", "active", "panels"}
            if unknown:
                raise ValidationError("unknown tabs key", unknown=sorted(unknown))
            panels = node.get("panels")
            if not isinstance(panels, list) or not (1 <= len(panels) <= MAX_TABS_PER_GROUP):
                raise ValidationError("tab group needs between 1 and 8 panels")
            for panel_id in panels:
                if not isinstance(panel_id, str) or panel_id not in known:
                    raise ValidationError("layout references an unknown panel", panel=panel_id)
                if panel_id in placed:
                    raise ValidationError("panel appears twice in layout", panel=panel_id)
                placed.append(panel_id)
            if len(set(panels)) != len(panels):
                raise ValidationError("tab group repeats a panel", panels=panels)
            active = node.get("active", panels[0])
            if active not in panels:
                raise ValidationError("active tab is not in its group", active=active)
            return {"type": "tabs", "active": active, "panels": list(panels)}
        if kind == "split":
            unknown = set(node) - {"type", "direction", "weights", "children"}
            if unknown:
                raise ValidationError("unknown split key", unknown=sorted(unknown))
            direction = node.get("direction")
            if direction not in {"row", "column"}:
                raise ValidationError("split direction must be row or column", direction=direction)
            children = node.get("children")
            if not isinstance(children, list) or not (2 <= len(children) <= 6):
                raise ValidationError("split needs between 2 and 6 children")
            weights = _validate_weights(node.get("weights"), len(children))
            return {
                "type": "split",
                "direction": direction,
                "weights": weights,
                "children": [walk(child, depth + 1) for child in children],
            }
        raise ValidationError("unknown layout node type", type=kind)

    normalized = walk(layout, 1)
    missing = known - set(placed)
    if missing:
        raise ValidationError("layout does not place every panel", missing=sorted(missing))
    return normalized


def derive_layout(panels: list[dict[str, Any]], columns: int) -> dict[str, Any]:
    """Arrangement implied by a v1 grid: rows of panels, each row split by span."""
    if not panels:
        raise ValidationError("workspace needs at least one panel")
    rows: list[list[tuple[str, int]]] = []
    current: list[tuple[str, int]] = []
    used = 0
    for panel in panels:
        span = max(1, min(int(panel.get("span", 1)), columns))
        if current and used + span > columns:
            rows.append(current)
            current, used = [], 0
        current.append((str(panel["id"]), span))
        used += span
        if used >= columns:
            rows.append(current)
            current, used = [], 0
    if current:
        rows.append(current)

    def row_node(entries: list[tuple[str, int]]) -> dict[str, Any]:
        if len(entries) == 1:
            return _tabs(entries[0][0])
        total = float(sum(span for _, span in entries))
        return {
            "type": "split",
            "direction": "row",
            "weights": [span / total for _, span in entries],
            "children": [_tabs(panel_id) for panel_id, _ in entries],
        }

    if len(rows) == 1:
        return row_node(rows[0])
    weights = [float(len(row)) / float(sum(len(row) for row in rows)) for row in rows]
    return {
        "type": "split",
        "direction": "column",
        "weights": weights,
        "children": [row_node(row) for row in rows],
    }


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
