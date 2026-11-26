"""The MCP server must work with an independently maintained client.

Our own harness talking to our own server cannot establish interoperability: it shares the
project's assumptions. These tests use the official `mcp` Python SDK as the client, and skip
with a clear reason when it is not installed (it is deliberately not a project dependency).

What they pin down, and what they found: the SDK negotiates protocol `2024-11-05`, discovers
14 tools, reads structured content, and surfaces an invalid enum as a JSON-RPC error carrying
the permitted values. A concept that is valid but has no evidence for the period is *not* an
error: it comes back as a typed `not_found` resolution, which is what a model should see.
"""

from __future__ import annotations

import asyncio
import json
import os
import sys
from pathlib import Path
from typing import Any

import pytest

pytest.importorskip("mcp", reason="official mcp SDK not installed")

from mcp import ClientSession, StdioServerParameters  # noqa: E402
from mcp.client.stdio import stdio_client  # noqa: E402
from mcp.shared.exceptions import MCPError  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
ISSUER = "ISS-CIK0001900003"


def _demo_database(tmp_path: Path) -> Path:
    from atlas.demo import run_demo

    path = tmp_path / "mcp.db"
    run_demo(db_path=str(path), stream=lambda _message: None)
    return path


def _parameters(database: Path, *extra: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "atlas", "--db", str(database), "mcp", *extra],
        env={**os.environ, "PYTHONPATH": str(ROOT / "src")},
    )


def _call(session: ClientSession, name: str, arguments: dict[str, Any]):
    """Call a tool, returning either the result or the protocol error the server sent."""

    async def run():
        try:
            return await session.call_tool(name, arguments)
        except MCPError as error:
            return error

    return run


def test_official_sdk_initialises_discovers_and_reads_structured_content(tmp_path: Path) -> None:
    database = _demo_database(tmp_path)

    async def run() -> dict[str, Any]:
        async with stdio_client(_parameters(database)) as (read, write):
            async with ClientSession(read, write) as session:
                init = await session.initialize()
                tools = await session.list_tools()
                result = await session.call_tool(
                    "resolve_financial_question",
                    {"issuer_id": ISSUER, "concept": "gross_profit", "period": "2023"},
                )
                return {
                    "protocol": init.protocol_version,
                    "server": init.server_info.name,
                    "version": init.server_info.version,
                    "instructions": bool(init.instructions),
                    "tools": sorted(tool.name for tool in tools.tools),
                    "schema": {tool.name: tool.input_schema for tool in tools.tools},
                    "is_error": result.is_error,
                    "structured": result.structured_content,
                    "text": result.content[0].text if result.content else "",
                }

    outcome = asyncio.run(run())
    assert outcome["protocol"].startswith("20")
    assert outcome["server"] == "atlas"
    assert outcome["tools"] == [
        "compare_companies", "get_company_financials", "get_evidence",
        "get_research_workspace", "inspect_data_health", "inspect_model",
        "resolve_financial_question", "run_scenario", "run_supported_model",
        "save_research_object", "search_companies", "search_filings",
        "verify_financial_answer", "verify_research_artifact",
    ]
    assert outcome["is_error"] is False
    payload = outcome["structured"] or json.loads(outcome["text"])
    assert payload["schema"] == "atlas.mcp.financial_answer.v1"
    answer = payload["answer"]
    assert float(answer["value"]) == 21690
    citation = answer["inputs"][0]
    for field in ("cell_id", "unit_id", "table_id", "document_id", "accession",
                  "row_label", "column_label", "raw", "value"):
        assert citation.get(field), f"the source-cell citation is missing {field}"
    assert citation["row_label"] == "Gross profit"
    assert citation["raw"] == "21,690"
    assert answer["reproducibility_fingerprint"]
    assert payload["question"]["issuer_id"] == ISSUER


def test_official_sdk_distinguishes_protocol_errors_from_typed_refusals(tmp_path: Path) -> None:
    database = _demo_database(tmp_path)

    async def run() -> dict[str, Any]:
        async with stdio_client(_parameters(database)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                outcome: dict[str, Any] = {}
                for label, name, arguments in (
                    ("unknown_tool", "not_a_tool", {}),
                    ("invalid_enum", "resolve_financial_question",
                     {"issuer_id": ISSUER, "concept": "ebitda_magic", "period": "2023"}),
                    ("read_only", "save_research_object",
                     {"document": {"kind": "memo", "name": "interop"}}),
                    ("no_evidence", "resolve_financial_question",
                     {"issuer_id": ISSUER, "concept": "revenue", "period": "1999"}),
                ):
                    try:
                        outcome[label] = await session.call_tool(name, arguments)
                    except MCPError as error:
                        outcome[label] = error
                return outcome

    outcome = asyncio.run(run())
    assert isinstance(outcome["unknown_tool"], MCPError)
    invalid = outcome["invalid_enum"]
    assert isinstance(invalid, MCPError)
    assert "gross_profit" in json.dumps(invalid.data), "the error lists the permitted concepts"

    mutation = outcome["read_only"]
    assert not isinstance(mutation, MCPError), "a refused mutation is a tool result, not a crash"
    assert mutation.is_error is True, "read-only mode must not execute a mutating tool"
    detail = mutation.content[0].text
    assert "authorization_required" in detail and "--allow-mutations" in detail

    refusal = outcome["no_evidence"]
    assert not isinstance(refusal, MCPError), "missing evidence is a result, not a protocol error"
    assert refusal.is_error is False
    payload = refusal.structured_content or json.loads(refusal.content[0].text)
    assert payload["resolution"]["status"] == "not_found"
    assert payload["answered"] is False
    assert payload["refused"], "the result states why the question was not answered"
    assert "answer" not in payload, "a refused question carries no fabricated answer"


def test_official_sdk_closes_the_server_cleanly(tmp_path: Path) -> None:
    database = _demo_database(tmp_path)

    async def run() -> int:
        async with stdio_client(_parameters(database)) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                return len((await session.list_tools()).tools)

    assert asyncio.run(run()) == 14
