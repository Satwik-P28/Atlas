"""The MCP surface over a columnar full-universe build.

The server refuses to accept a filesystem path from a caller, so the dataset root is
operator configuration. These tests drive the tool handlers directly with a synthetic
build, including the refusal when no build is configured.
"""
from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from atlas.mcp.server import build_server
from atlas.mcp.tools import TOOLS, ToolContext, ToolError
from atlas.open_data.columnar import build_from_archive


def _observation(value: int, accession: str, *, form: str = "10-K") -> dict:
    return {"end": "2023-12-31", "start": "2023-01-01", "val": value, "accn": accession,
            "fy": 2023, "fp": "FY", "form": form, "filed": "2024-02-01"}


def _build(tmp_path: Path) -> Path:
    archive = tmp_path / "companyfacts.zip"
    payloads = {
        1: {"cik": 1, "entityName": "Alpha Industries", "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [_observation(1000, "1-24-1")]}}}}},
        2: {"cik": 2, "entityName": "Beta Holdings", "facts": {"us-gaap": {
            "Revenues": {"units": {"USD": [_observation(2000, "2-24-1"),
                                           _observation(1800, "2-24-2", form="10-K/A")]}}}}},
        3: {"cik": 3, "entityName": "Gamma AG", "facts": {"us-gaap": {
            "Revenues": {"units": {"EUR": [_observation(5000, "3-24-1")]}}}}},
    }
    with zipfile.ZipFile(archive, "w") as bundle:
        for cik, payload in payloads.items():
            bundle.writestr(f"CIK{cik:010d}.json", json.dumps(payload))
    root = tmp_path / "columnar"
    build_from_archive(archive, root, snapshot_id="snap", bucket_count=2)
    return root


def test_columnar_tools_require_an_operator_configured_root() -> None:
    with pytest.raises(ToolError) as refusal:
        TOOLS["screen_columnar"].handler(ToolContext(db_path="unused.db"), {"concept": "revenue"})
    assert refusal.value.code == "columnar_unavailable"
    assert "--columnar-root" in refusal.value.message


def test_columnar_search_and_point_in_time_evidence(tmp_path: Path) -> None:
    root = _build(tmp_path)
    context = ToolContext(db_path="unused.db", columnar_root=str(root))
    found = TOOLS["search_columnar_companies"].handler(context, {"q": "beta"})
    assert [item["cik"] for item in found["items"]] == ["0000000002"]
    assert found["schema"] == "atlas.mcp.columnar_company_search.v1"

    payload = TOOLS["query_columnar_evidence"].handler(
        context, {"cik": "2", "as_of": "2025-01-01T00:00:00Z"})
    assert payload["concepts"]["revenue"] == "1800"
    assert payload["availability"]["excluded_from_history"] == 0
    assert payload["scope"] == "consolidated"
    assert payload["selection_policy"] == "kernel_parity_v1"


def test_columnar_screen_refuses_a_mixed_currency_ranking(tmp_path: Path) -> None:
    root = _build(tmp_path)
    context = ToolContext(db_path="unused.db", columnar_root=str(root))
    with pytest.raises(ToolError) as refusal:
        TOOLS["screen_columnar"].handler(context, {"concept": "revenue", "fiscal_year": 2023,
                                                   "period": "annual"})
    assert refusal.value.code == "incomparable_screen"
    assert {group["currency"] for group in refusal.value.context["groups"]} == {"USD", "EUR"}

    usd = TOOLS["screen_columnar"].handler(context, {
        "concept": "revenue", "fiscal_year": 2023, "period": "annual",
        "currency": "USD", "unit": "USD"})
    assert [row["cik"] for row in usd["selected"]] == ["0000000002", "0000000001"]
    assert usd["selected"][0]["value"] == "1800"
    assert usd["excluded"]["wrong_currency"] + usd["excluded"]["wrong_unit"] >= 1


def test_the_server_threads_the_root_into_tool_context(tmp_path: Path) -> None:
    server = build_server("unused.db", columnar_root=str(tmp_path))
    assert server.context().columnar_root == str(tmp_path)
