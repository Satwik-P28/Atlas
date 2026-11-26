"""The MCP server is tested as a protocol, not as a Python API.

These tests speak JSON-RPC to the real dispatcher and, for the transport tests, to a real
``python -m atlas.mcp`` process over stdio. They cover initialisation, tool discovery, real
tool calls, malformed requests, authorization refusal, concurrency, cancellation, deadlines
and the response bound.

The financial assertions are deliberately about *identity*: every answer must carry the
cell, document, accession, units, scale and availability that produced it. A tool that
returned a bare number would fail these tests.
"""

from __future__ import annotations

import io
import json
import os
import queue
import subprocess
import sys
import threading
import time
from decimal import Decimal
from pathlib import Path

import pytest

from atlas.core.temporal import iso, utcnow
from atlas.mcp.protocol import (
    INVALID_PARAMS,
    METHOD_NOT_FOUND,
    PARSE_ERROR,
    REQUEST_CANCELLED,
)
from atlas.mcp.server import AtlasMCPServer, MCPServerConfig
from atlas.mcp.tools import MAX_DOCUMENT_BYTES, TOOLS, ToolSpec
from atlas.research.knowledge import KnowledgeEngine
from atlas.storage.db import Database

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "src"

ISSUER = "ISS-MCP-FIXTURE"
ACCESSION = "0000000032-24-000100"
CUTOFF = "2024-01-01"

HTML = b"""<html><body>
<p>Item 8. Financial Statements</p>
<p>CONSOLIDATED STATEMENTS OF INCOME</p>
<p>($ in millions)</p>
<table>
<tr><td>Year</td><td>2022</td><td>2021</td></tr>
<tr><td>Net sales</td><td>34,229</td><td>35,355</td></tr>
<tr><td>Cost of sales</td><td>21,000</td><td>21,500</td></tr>
<tr><td>Gross profit</td><td>13,229</td><td>13,855</td></tr>
</table></body></html>"""


def _build(path: Path) -> None:
    database = Database(path)
    database.migrate()
    now = iso(utcnow())
    database.execute(
        "INSERT INTO source (source_id, name, kind, redistribution, created_at) "
        "VALUES ('sec-edgar','SEC EDGAR','sec_edgar','public_domain',?)", (now,))
    database.execute(
        "INSERT INTO issuer (issuer_id, cik, legal_name, entity_type, is_active, "
        "provenance_source, created_at, updated_at) VALUES (?,?,?,'company',1,'test',?,?)",
        (ISSUER, "0000000032", "MCP Fixture Co", now, now))
    KnowledgeEngine(database).ingest_document(
        issuer_id=ISSUER, accession=ACCESSION, form_type="10-K", html=HTML,
        filed_date="2023-02-10", acceptance_time="2023-02-10T12:00:00Z",
        period_of_report="2022-12-31", rights="public_domain",
        primary_document_url=f"https://www.sec.gov/Archives/{ACCESSION}.htm")
    # Model an observed public-release instant. Ingestion itself stores a modelled bound
    # (acceptance plus a publication lag); tests/test_availability_bound_integrity.py pins
    # that behaviour, and this fixture covers the observed branch.
    database.execute(
        "UPDATE knowledge_document SET availability_precision = 'exact', "
        "availability_basis = 'sec_submissions.acceptance_datetime', "
        "availability_time = '2023-02-10T12:00:00Z'"
    )
    database.close()


@pytest.fixture()
def db_path(tmp_path) -> Path:
    path = tmp_path / "mcp.db"
    _build(path)
    return path


@pytest.fixture()
def server(db_path) -> AtlasMCPServer:
    return AtlasMCPServer(config=MCPServerConfig(db_path=str(db_path), call_timeout=10.0))


def _request(method: str, params: dict | None = None, request_id: int = 1) -> dict:
    message = {"jsonrpc": "2.0", "id": request_id, "method": method}
    if params is not None:
        message["params"] = params
    return message


def _call(server: AtlasMCPServer, name: str, arguments: dict | None = None,
          request_id: int = 7) -> dict:
    return server.handle_message(
        _request("tools/call", {"name": name, "arguments": arguments or {}}, request_id)
    )


# ------------------------------------------------------------------- lifecycle
def test_initialize_negotiates_a_supported_protocol_version(server: AtlasMCPServer) -> None:
    response = server.handle_message(_request("initialize", {
        "protocolVersion": "2025-06-18", "capabilities": {},
        "clientInfo": {"name": "harness", "version": "1"},
    }))
    result = response["result"]
    assert result["protocolVersion"] == "2025-06-18"
    assert result["capabilities"]["tools"] == {"listChanged": False}
    assert result["serverInfo"]["name"] == "atlas"
    assert "refuses" in result["instructions"]

    fallback = server.handle_message(_request("initialize", {"protocolVersion": "1999-01-01"}))
    assert fallback["result"]["protocolVersion"] == "2024-11-05"


def test_notifications_get_no_response(server: AtlasMCPServer) -> None:
    assert server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None


def test_tool_discovery_marks_every_tool_read_only_except_the_mutator(
        server: AtlasMCPServer) -> None:
    response = server.handle_message(_request("tools/list", {}))
    tools = {tool["name"]: tool for tool in response["result"]["tools"]}
    assert set(tools) == set(TOOLS)
    assert len(tools) == 14
    for name, tool in tools.items():
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False, name
        assert tool["annotations"]["readOnlyHint"] is (name != "save_research_object"), name
        assert tool["annotations"]["openWorldHint"] is False, name


# ------------------------------------------------------------------- real calls
def test_search_companies_returns_only_database_issuers(server: AtlasMCPServer) -> None:
    payload = _call(server, "search_companies", {"limit": 5})["result"]["structuredContent"]
    ids = [item["issuer_id"] for item in payload["items"]]
    assert ids == [ISSUER]

    absent = _call(server, "search_companies", {"q": "ZZZZ", "limit": 5})
    assert absent["result"]["structuredContent"]["count"] == 0
    assert absent["result"]["isError"] is False


def test_resolve_financial_question_carries_the_full_evidence_chain(
        server: AtlasMCPServer) -> None:
    response = _call(server, "resolve_financial_question", {
        "issuer_id": ISSUER, "concept": "revenue", "period": "2022", "as_of": CUTOFF,
    })
    payload = response["result"]["structuredContent"]
    assert response["result"]["isError"] is False
    assert payload["answered"] is True
    assert Decimal(payload["answer"]["value"]) == Decimal("34229")
    evidence = payload["evidence"]
    assert evidence["accession"] == ACCESSION
    assert evidence["cell_id"]
    assert evidence["scale"] == 6
    assert evidence["currency"] == "USD"
    assert evidence["row_label"].lower() == "net sales"
    assert payload["availability"]["availability_precision"] == "exact"
    assert payload["availability"]["is_estimated"] is False
    assert payload["semantics"]["verified_but_not_proven_correct"] is True


def test_resolve_financial_question_refuses_an_unresolvable_period(
        server: AtlasMCPServer) -> None:
    response = _call(server, "resolve_financial_question", {
        "issuer_id": ISSUER, "concept": "revenue", "period": "2019", "as_of": CUTOFF,
    })
    payload = response["result"]["structuredContent"]
    assert response["result"]["isError"] is False
    assert payload["answered"] is False
    assert payload["refused"] is True
    assert payload["refusal"]["reason"]
    assert "approximate" in payload["refusal"]["explanation"]


def test_get_company_financials_does_not_invent_values(server: AtlasMCPServer) -> None:
    payload = _call(server, "get_company_financials", {
        "identifier": ISSUER, "statement": "income", "period": "FY",
    })["result"]["structuredContent"]
    statement = payload["statement"]
    assert statement["issuer"]["issuer_id"] == ISSUER
    # The knowledge corpus has no XBRL facts for this fixture, so the statement is empty.
    # An empty statement is the honest answer; a populated one would be fabricated.
    assert statement["rows"] == []
    assert payload["provenance"]["magnitudes_as_reported"] is True


def test_compare_companies_refuses_incompatible_periods(server: AtlasMCPServer) -> None:
    response = _call(server, "compare_companies", {
        "left": ISSUER, "right": ISSUER, "statement": "income", "period": "Q",
    })
    payload = response["result"]["structuredContent"]
    assert response["result"]["isError"] is True
    assert payload["error"]["code"] == "incompatible_periods"


def test_verify_research_artifact_recomputes_the_canonical_hash(
        server: AtlasMCPServer) -> None:
    artifact = {
        "schema_version": "atlas.research_object.v1",
        "kind": "application",
        "name": "mcp-fixture",
        "version": "0.1.0",
        "status": "draft",
        "description": "an application object that declares no executable code",
        "as_of": "2024-01-01T00:00:00Z",
        "mode": "public_available",
        "evidence_ids": [],
        "object_ids": [],
        "spec": {"purpose": "verify the artifact contract", "views": ["summary"]},
    }
    payload = _call(server, "verify_research_artifact", {"artifact": artifact})
    result = payload["result"]["structuredContent"]
    assert payload["result"]["isError"] is False
    assert result["verified"] is True
    assert result["computed_content_hash"]
    assert result["cites_unknown_evidence"] == []

    declared = _call(server, "verify_research_artifact",
                     {"artifact": artifact,
                      "content_hash": result["computed_content_hash"]})
    assert declared["result"]["structuredContent"]["verified"] is True
    tampered = _call(server, "verify_research_artifact",
                     {"artifact": artifact, "content_hash": "0" * 64})
    assert tampered["result"]["structuredContent"]["verified"] is False


def test_inspect_model_and_data_health(server: AtlasMCPServer) -> None:
    models = _call(server, "inspect_model", {"model": "add"})["result"]["structuredContent"]
    assert [item["key"] for item in models["items"]] == ["add"]
    assert models["items"][0]["arity"] == 2

    health = _call(server, "inspect_data_health")["result"]["structuredContent"]
    assert health["integrity_check"] == "ok"
    assert health["counts"]["knowledge_document"] == 1


# -------------------------------------------------------------- malformed input
def test_unknown_tool_is_a_protocol_error(server: AtlasMCPServer) -> None:
    response = _call(server, "delete_everything")
    assert response["error"]["code"] == INVALID_PARAMS
    assert "delete_everything" in response["error"]["data"]["received"]


def test_unknown_argument_is_refused_rather_than_ignored(server: AtlasMCPServer) -> None:
    response = _call(server, "search_companies", {"limit": 3, "as_of": "2024-01-01"})
    assert response["error"]["code"] == INVALID_PARAMS
    assert response["error"]["data"]["unknown"] == ["as_of"]


def test_wrong_argument_type_is_refused(server: AtlasMCPServer) -> None:
    response = _call(server, "search_companies", {"limit": "three"})
    assert response["error"]["code"] == INVALID_PARAMS


def test_unknown_method_is_reported(server: AtlasMCPServer) -> None:
    response = server.handle_message(_request("tools/execute", {}))
    assert response["error"]["code"] == METHOD_NOT_FOUND


def test_malformed_json_produces_a_parse_error(server: AtlasMCPServer) -> None:
    out = io.StringIO()
    server.serve(io.StringIO("{not json\n"), out)
    response = json.loads(out.getvalue().strip())
    assert response["error"]["code"] == PARSE_ERROR
    assert response["id"] is None


def test_wrong_jsonrpc_version_is_rejected(server: AtlasMCPServer) -> None:
    response = server.handle_message({"jsonrpc": "1.0", "id": 1, "method": "tools/list"})
    assert response["error"]["code"] == -32600


# ------------------------------------------------------------- authorization
def test_mutation_is_refused_without_explicit_authorization(server: AtlasMCPServer) -> None:
    response = _call(server, "save_research_object", {"document": {}})
    result = response["result"]
    assert result["isError"] is True
    assert result["structuredContent"]["error"]["code"] == "authorization_required"


def test_mutation_with_authorization_still_validates_the_document(db_path) -> None:
    authorised = AtlasMCPServer(config=MCPServerConfig(db_path=str(db_path),
                                                       allow_mutations=True))
    response = _call(authorised, "save_research_object", {"document": {"kind": "nope"}})
    result = response["result"]
    assert result["isError"] is True
    assert "error" in result["structuredContent"]
    assert result["structuredContent"]["error"]["code"] != "authorization_required"


def test_persisting_a_model_run_requires_authorization(server: AtlasMCPServer) -> None:
    response = _call(server, "run_supported_model", {
        "spec": {"schema": "atlas.model.v1", "nodes": []}, "inputs": {}, "persist": True,
    })
    assert response["result"]["structuredContent"]["error"]["code"] == "authorization_required"


# ---------------------------------------------------------------- robustness
def _slow(_context, _arguments):
    time.sleep(0.6)
    return {"schema": "test.slow"}


def test_a_call_that_exceeds_its_deadline_is_bounded(db_path) -> None:
    spec = ToolSpec(
        name="slow_tool", title="Slow", description="sleeps",
        input_schema={"type": "object", "properties": {}, "additionalProperties": False},
        handler=_slow,
    )
    server = AtlasMCPServer(
        config=MCPServerConfig(db_path=str(db_path), call_timeout=0.05),
        tools={"slow_tool": spec},
    )
    started = time.monotonic()
    response = _call(server, "slow_tool")
    elapsed = time.monotonic() - started
    assert response["result"]["isError"] is True
    assert response["result"]["structuredContent"]["error"]["code"] == "tool_timeout"
    assert elapsed < 0.5


def test_a_cancelled_request_returns_the_cancel_error(server: AtlasMCPServer) -> None:
    server.cancel(11)
    response = server.handle_message(_request(
        "tools/call", {"name": "inspect_data_health", "arguments": {}}, 11))
    assert response["error"]["code"] == REQUEST_CANCELLED
    # The cancellation is consumed: a later call with the same id runs normally.
    assert _call(server, "inspect_data_health", request_id=11)["result"]["isError"] is False


def test_oversized_document_is_refused(server: AtlasMCPServer) -> None:
    spec = {"schema": "atlas.model.v1", "nodes": [], "padding": "x" * (MAX_DOCUMENT_BYTES + 10)}
    response = _call(server, "run_supported_model", {"spec": spec})
    assert response["result"]["structuredContent"]["error"]["code"] == "document_too_large"


def test_serve_handles_notifications_and_requests_in_one_stream(server: AtlasMCPServer) -> None:
    stream = io.StringIO(
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        + json.dumps(_request("tools/list", {}, 1)) + "\n"
        + json.dumps(_request("ping", {}, 2)) + "\n"
    )
    out = io.StringIO()
    assert server.serve(stream, out) == 0
    responses = [json.loads(line) for line in out.getvalue().splitlines()]
    assert [response["id"] for response in responses] == [1, 2]


# ------------------------------------------------------------------- transport
class StdioClient:
    """A real MCP client: one subprocess, one reader thread, correlated responses."""

    def __init__(self, db_path: Path) -> None:
        env = dict(os.environ)
        env["PYTHONPATH"] = str(SOURCE) + os.pathsep + env.get("PYTHONPATH", "")
        self.process = subprocess.Popen(
            [sys.executable, "-m", "atlas.mcp", "--db", str(db_path),
             "--call-timeout", "20"],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            text=True, bufsize=1, env=env,
        )
        self.queue: queue.Queue[str] = queue.Queue()
        threading.Thread(target=self._pump, daemon=True).start()

    def _pump(self) -> None:
        assert self.process.stdout is not None
        for line in self.process.stdout:
            self.queue.put(line)

    def send(self, *messages: dict) -> None:
        assert self.process.stdin is not None
        for message in messages:
            self.process.stdin.write(json.dumps(message) + "\n")
        self.process.stdin.flush()

    def read(self, count: int, timeout: float = 30.0) -> list[dict]:
        out: list[dict] = []
        deadline = time.monotonic() + timeout
        while len(out) < count:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            try:
                out.append(json.loads(self.queue.get(timeout=remaining)))
            except queue.Empty:  # pragma: no cover - only on a hung server
                break
        return out

    def close(self) -> None:
        self.process.kill()
        self.process.wait(timeout=10)


def test_stdio_process_speaks_mcp_end_to_end(db_path) -> None:
    client = StdioClient(db_path)
    try:
        client.send(
            _request("initialize", {"protocolVersion": "2024-11-05", "capabilities": {}}, 1),
            _request("tools/list", {}, 2),
            _request("tools/call",
                     {"name": "resolve_financial_question",
                      "arguments": {"issuer_id": ISSUER, "concept": "revenue",
                                    "period": "2022", "as_of": CUTOFF}}, 3),
        )
        responses = {response["id"]: response for response in client.read(3)}
        assert set(responses) == {1, 2, 3}
        assert responses[1]["result"]["serverInfo"]["name"] == "atlas"
        assert len(responses[2]["result"]["tools"]) == 14
        answer = responses[3]["result"]["structuredContent"]
        assert answer["answered"] is True
        assert answer["evidence"]["accession"] == ACCESSION
    finally:
        client.close()


def test_stdio_process_answers_concurrent_calls(db_path) -> None:
    client = StdioClient(db_path)
    try:
        client.send(_request("initialize", {"protocolVersion": "2024-11-05"}, 1))
        assert client.read(1)[0]["id"] == 1

        calls = [
            _request("tools/call",
                     {"name": "resolve_financial_question",
                      "arguments": {"issuer_id": ISSUER, "concept": concept,
                                    "period": "2022", "as_of": CUTOFF}}, 100 + index)
            for index, concept in enumerate(
                ["revenue", "gross_profit", "net_income", "revenue", "gross_profit"])
        ]
        client.send(*calls)
        responses = {response["id"]: response for response in client.read(5)}
        assert set(responses) == {100, 101, 102, 103, 104}
        for response in responses.values():
            assert "result" in response, response
            assert response["result"]["isError"] is False
    finally:
        client.close()


def test_stdio_process_cancels_and_keeps_serving(db_path) -> None:
    client = StdioClient(db_path)
    try:
        client.send(_request("tools/call",
                             {"name": "resolve_financial_question",
                              "arguments": {"issuer_id": ISSUER, "concept": "revenue",
                                            "period": "2022", "as_of": CUTOFF}}, 40))
        client.send({"jsonrpc": "2.0", "method": "$/cancelRequest",
                     "params": {"requestId": 40}})
        # Whatever the race, the server must answer id 40 exactly once and still answer 41.
        client.send(_request("tools/call", {"name": "inspect_data_health", "arguments": {}},
                             41))
        responses = client.read(2)
        ids = [response["id"] for response in responses]
        assert ids.count(40) == 1 and ids.count(41) == 1
        first = next(response for response in responses if response["id"] == 40)
        assert "result" in first or first.get("error", {}).get("code") == REQUEST_CANCELLED
        later = next(response for response in responses if response["id"] == 41)
        assert later["result"]["isError"] is False
    finally:
        client.close()


def test_the_server_refuses_to_start_without_a_database(tmp_path) -> None:
    env = dict(os.environ)
    env["PYTHONPATH"] = str(SOURCE) + os.pathsep + env.get("PYTHONPATH", "")
    result = subprocess.run(
        [sys.executable, "-m", "atlas.mcp", "--db", str(tmp_path / "absent.db")],
        input="", capture_output=True, text=True, env=env, timeout=60,
    )
    assert result.returncode == 2
    assert "database not found" in result.stderr
