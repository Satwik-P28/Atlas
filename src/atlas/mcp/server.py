"""The Atlas MCP server: JSON-RPC 2.0 dispatch, bounded execution and cancellation.

Transport is stdio by default (the local transport MCP clients expect). The server has no
listener, so nothing is reachable from another host. Persistent mutations are refused
unless the operator started it with ``--allow-mutations``; the refusal is a normal tool
result carrying ``authorization_required``, not a silent no-op.

Every tool call runs with a deadline and a second connection to the database, because
SQLite connections are not safe to share across threads. A call that exceeds its deadline
returns ``tool_timeout``; a call cancelled by the client returns JSON-RPC -32800.
"""

from __future__ import annotations

import json
import sys
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeoutError
from dataclasses import dataclass, field
from threading import Lock
from typing import Any, Callable, Mapping, TextIO

from .. import __version__
from ..core.errors import AtlasError
from .protocol import (
    INTERNAL_ERROR,
    INVALID_PARAMS,
    INVALID_REQUEST,
    METHOD_NOT_FOUND,
    PROTOCOL_VERSION,
    REQUEST_CANCELLED,
    SUPPORTED_PROTOCOL_VERSIONS,
    ProtocolError,
    error_response,
    parse_message,
    success_response,
    validate_arguments,
)
from .tools import TOOLS, ToolContext, ToolError, ToolSpec

SERVER_INSTRUCTIONS = (
    "Atlas is an evidence-first financial research system. Every financial value returned here "
    "carries the evidence identifiers, availability semantics, units and scale that produced it. "
    "Quote those identifiers rather than restating numbers, and never treat a refusal as a "
    "missing answer to be filled in: Atlas refuses when it cannot resolve exactly one verified "
    "source cell. Availability reported as an estimate is a modelled bound, not an observed "
    "public-release instant. This server is local and read-only by default."
)


@dataclass(slots=True)
class MCPServerConfig:
    db_path: str
    allow_mutations: bool = False
    call_timeout: float = 20.0
    max_workers: int = 4
    server_name: str = "atlas"
    server_version: str = __version__


@dataclass(slots=True)
class AtlasMCPServer:
    config: MCPServerConfig
    tools: Mapping[str, ToolSpec] = field(default_factory=lambda: dict(TOOLS))
    _cancelled: set[str] = field(default_factory=set)
    _lock: Lock = field(default_factory=Lock)

    # ------------------------------------------------------------------ lifecycle
    def context(self) -> ToolContext:
        return ToolContext(db_path=self.config.db_path,
                           allow_mutations=self.config.allow_mutations)

    def cancel(self, request_id: Any) -> None:
        key = _key(request_id)
        if key is None:
            return
        with self._lock:
            self._cancelled.add(key)

    def is_cancelled(self, request_id: Any) -> bool:
        key = _key(request_id)
        if key is None:
            return False
        with self._lock:
            return key in self._cancelled

    def _clear_cancel(self, request_id: Any) -> None:
        key = _key(request_id)
        if key is None:
            return
        with self._lock:
            self._cancelled.discard(key)

    # -------------------------------------------------------------------- protocol
    def handle_message(self, message: Mapping[str, Any]) -> dict[str, Any] | None:
        """Handle one parsed JSON-RPC message. Returns a response, or None for notifications."""
        if message.get("jsonrpc") != "2.0" or not isinstance(message.get("method"), str):
            return error_response(message.get("id"), INVALID_REQUEST,
                                  "not a valid JSON-RPC 2.0 request")
        request_id = message.get("id")
        method = str(message["method"])
        params = message.get("params") or {}
        is_notification = request_id is None

        if method in {"notifications/initialized", "notifications/cancelled"}:
            return None
        if method == "$/cancelRequest":
            self.cancel((params or {}).get("requestId", (params or {}).get("id")))
            return None
        if method == "ping":
            return None if is_notification else success_response(request_id, {})

        if not isinstance(params, dict):
            return error_response(request_id, INVALID_PARAMS, "params must be an object")

        if method == "initialize":
            return None if is_notification else success_response(
                request_id, self._initialize(params)
            )
        if method == "tools/list":
            return None if is_notification else success_response(
                request_id, {"tools": [self._tool_descriptor(spec) for spec in self.tools.values()]}
            )
        if method == "resources/list":
            return None if is_notification else success_response(request_id, {"resources": []})
        if method == "prompts/list":
            return None if is_notification else success_response(request_id, {"prompts": []})
        if method == "tools/call":
            if is_notification:
                return None
            return self._call_tool(request_id, params)

        return error_response(request_id, METHOD_NOT_FOUND, f"unknown method {method!r}")

    def _initialize(self, params: Mapping[str, Any]) -> dict[str, Any]:
        requested = params.get("protocolVersion")
        version = requested if requested in SUPPORTED_PROTOCOL_VERSIONS else PROTOCOL_VERSION
        return {
            "protocolVersion": version,
            "capabilities": {
                "tools": {"listChanged": False},
                "resources": {"listChanged": False, "subscribe": False},
            },
            "serverInfo": {
                "name": self.config.server_name,
                "version": self.config.server_version,
            },
            "instructions": SERVER_INSTRUCTIONS,
        }

    def _tool_descriptor(self, spec: ToolSpec) -> dict[str, Any]:
        descriptor = {
            "name": spec.name,
            "title": spec.title,
            "description": spec.description,
            "inputSchema": spec.input_schema,
            "annotations": {
                "title": spec.title,
                "readOnlyHint": not spec.mutating,
                "destructiveHint": False,
                "idempotentHint": not spec.mutating,
                "openWorldHint": False,
            },
        }
        return descriptor

    # ------------------------------------------------------------------ tool calls
    def _call_tool(self, request_id: Any, params: Mapping[str, Any]) -> dict[str, Any]:
        if self.is_cancelled(request_id):
            self._clear_cancel(request_id)
            return error_response(request_id, REQUEST_CANCELLED, "request cancelled by the client")
        name = params.get("name")
        if not isinstance(name, str) or name not in self.tools:
            return error_response(
                request_id, INVALID_PARAMS, "unknown tool",
                {"received": name, "supported": sorted(self.tools)},
            )
        spec = self.tools[name]
        try:
            arguments = validate_arguments(spec.input_schema, params.get("arguments"))
        except ProtocolError as exc:
            return error_response(request_id, exc.code, exc.message, exc.data)
        try:
            payload = self.execute(spec, arguments)
        except AtlasError as exc:
            # Domain errors (unknown issuer, ambiguous identity, missing data) are answers to
            # the caller: report the code and context rather than a transport failure.
            return success_response(request_id, _tool_result(
                {"error": {"code": exc.code, "message": str(exc), "context": exc.context}},
                is_error=True,
            ))
        except ToolError as exc:
            return success_response(request_id, _tool_result(exc.as_payload(), is_error=True))
        except ProtocolError as exc:
            return error_response(request_id, exc.code, exc.message, exc.data)
        if self.is_cancelled(request_id):
            self._clear_cancel(request_id)
            return error_response(request_id, REQUEST_CANCELLED, "request cancelled by the client")
        return success_response(request_id, _tool_result(payload))

    def execute(self, spec: ToolSpec, arguments: dict[str, Any]) -> dict[str, Any]:
        """Run one tool with a deadline. Raises ToolError on failure or timeout."""
        pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"atlas-mcp-{spec.name}")
        try:
            future = pool.submit(spec.handler, self.context(), arguments)
            try:
                return future.result(timeout=self.config.call_timeout)
            except FutureTimeoutError as exc:
                future.cancel()
                raise ToolError(
                    "tool_timeout",
                    f"{spec.name} exceeded the {self.config.call_timeout:g}s call deadline",
                ) from exc
        finally:
            # Do not wait for a hung handler: the response has already been decided.
            pool.shutdown(wait=False, cancel_futures=True)

    # ---------------------------------------------------------------------- stdio
    def serve(self, stdin: TextIO | None = None, stdout: TextIO | None = None) -> int:
        source = stdin or sys.stdin
        sink = stdout or sys.stdout
        write_lock = Lock()
        pool = ThreadPoolExecutor(max_workers=self.config.max_workers,
                                  thread_name_prefix="atlas-mcp-call")

        def emit(payload: dict[str, Any] | None) -> None:
            if payload is None:
                return
            line = json.dumps(payload, ensure_ascii=False, default=str)
            with write_lock:
                sink.write(line + "\n")
                sink.flush()

        def finish(message: Mapping[str, Any], future: Any) -> None:
            request_id = message.get("id")
            try:
                emit(future.result())
            except Exception as exc:  # noqa: BLE001 - a dispatcher must not die on one call
                emit(error_response(request_id, INTERNAL_ERROR, "internal error",
                                    {"detail": str(exc)}))

        try:
            for line in source:
                if not line.strip():
                    continue
                try:
                    message = parse_message(line)
                except ProtocolError as exc:
                    emit(error_response(None, exc.code, exc.message, exc.data))
                    continue
                method = message.get("method")
                if method in {"$/cancelRequest", "notifications/cancelled"}:
                    params = message.get("params") or {}
                    self.cancel(params.get("requestId", params.get("id")))
                    continue
                request_id = message.get("id")
                if method == "tools/call" and request_id is not None:
                    future = pool.submit(self.handle_message, message)
                    future.add_done_callback(lambda done, msg=message: finish(msg, done))
                    continue
                emit(self.handle_message(message))
        finally:
            pool.shutdown(wait=False, cancel_futures=True)
        return 0


def _key(request_id: Any) -> str | None:
    if request_id is None or isinstance(request_id, bool):
        return None
    return f"{type(request_id).__name__}:{request_id}"


def _tool_result(payload: Mapping[str, Any], *, is_error: bool = False) -> dict[str, Any]:
    return {
        "content": [{"type": "text", "text": json.dumps(payload, indent=2, default=str)}],
        "structuredContent": dict(payload),
        "isError": is_error,
    }


def build_server(db_path: str, *, allow_mutations: bool = False,
                 call_timeout: float = 20.0) -> AtlasMCPServer:
    return AtlasMCPServer(config=MCPServerConfig(
        db_path=str(db_path), allow_mutations=allow_mutations, call_timeout=call_timeout
    ))


__all__ = ["AtlasMCPServer", "MCPServerConfig", "SERVER_INSTRUCTIONS", "build_server"]
