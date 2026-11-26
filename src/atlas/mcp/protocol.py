"""JSON-RPC 2.0 framing and argument validation for the Atlas MCP server.

MCP's stdio transport is one JSON-RPC 2.0 message per line of UTF-8 JSON. This module owns
only the wire contract: message parsing, protocol errors and strict argument validation
against a small JSON Schema subset. It never touches a database or a filesystem.

Unknown arguments are refused rather than ignored: a caller that misspells ``as_of`` must
be told, not silently given the latest available data.
"""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

PROTOCOL_VERSION = "2024-11-05"
#: Versions this server will echo back. The tool surface is identical across them.
SUPPORTED_PROTOCOL_VERSIONS = ("2024-11-05", "2025-06-18")

PARSE_ERROR = -32700
INVALID_REQUEST = -32600
METHOD_NOT_FOUND = -32601
INVALID_PARAMS = -32602
INTERNAL_ERROR = -32603
SERVER_ERROR = -32000
REQUEST_CANCELLED = -32800


class ProtocolError(Exception):
    """A JSON-RPC protocol violation, not a tool failure."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.data = data


def success_response(request_id: Any, result: Mapping[str, Any]) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": dict(result)}


def error_response(request_id: Any, code: int, message: str, data: Any = None) -> dict[str, Any]:
    payload: dict[str, Any] = {"code": code, "message": message}
    if data is not None:
        payload["data"] = data
    return {"jsonrpc": "2.0", "id": request_id, "error": payload}


def parse_message(line: str) -> dict[str, Any]:
    """Parse one transport line into a JSON-RPC message object."""
    try:
        message = json.loads(line)
    except ValueError as exc:
        raise ProtocolError(PARSE_ERROR, "invalid JSON", {"detail": str(exc)}) from exc
    if not isinstance(message, dict):
        raise ProtocolError(INVALID_REQUEST, "message must be a JSON object")
    if message.get("jsonrpc") != "2.0":
        raise ProtocolError(INVALID_REQUEST, "jsonrpc must be \"2.0\"")
    method = message.get("method")
    if not isinstance(method, str) or not method:
        raise ProtocolError(INVALID_REQUEST, "method must be a non-empty string")
    return message


# --------------------------------------------------------------------- validation

_JSON_TYPES: dict[str, tuple[type, ...]] = {
    "string": (str,),
    "boolean": (bool,),
    "object": (dict,),
    "array": (list,),
}


def _type_ok(value: Any, expected: str) -> bool:
    if expected == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if expected == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if expected == "null":
        return value is None
    return isinstance(value, _JSON_TYPES.get(expected, (object,)))


def _check(value: Any, schema: Mapping[str, Any], path: str) -> Any:
    expected = schema.get("type")
    if expected is not None:
        allowed = expected if isinstance(expected, list) else [expected]
        if not any(_type_ok(value, item) for item in allowed):
            raise ProtocolError(
                INVALID_PARAMS,
                f"{path}: expected {' or '.join(allowed)}",
                {"path": path, "received": type(value).__name__},
            )
        if value is None:
            return None
    if "enum" in schema and value not in schema["enum"]:
        raise ProtocolError(
            INVALID_PARAMS,
            f"{path}: value not permitted",
            {"path": path, "supported": list(schema["enum"])},
        )
    if isinstance(value, str):
        if "minLength" in schema and len(value) < schema["minLength"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: too short", {"path": path})
        if "maxLength" in schema and len(value) > schema["maxLength"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: too long", {"path": path})
        if "pattern" in schema and not re.search(schema["pattern"], value):
            raise ProtocolError(INVALID_PARAMS, f"{path}: does not match the expected format",
                                {"path": path, "pattern": schema["pattern"]})
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: below minimum", {"path": path})
        if "maximum" in schema and value > schema["maximum"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: above maximum", {"path": path})
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: too few items", {"path": path})
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            raise ProtocolError(INVALID_PARAMS, f"{path}: too many items", {"path": path})
        item_schema = schema.get("items")
        if isinstance(item_schema, Mapping):
            value = [_check(item, item_schema, f"{path}[{index}]")
                     for index, item in enumerate(value)]
    if isinstance(value, dict):
        properties = schema.get("properties") or {}
        required = schema.get("required") or []
        for key in required:
            if key not in value:
                raise ProtocolError(
                    INVALID_PARAMS, f"{path}.{key}: required argument is missing", {"path": path}
                )
        if schema.get("additionalProperties") is False:
            unknown = [key for key in value if key not in properties]
            if unknown:
                raise ProtocolError(
                    INVALID_PARAMS,
                    f"{path}: unknown argument(s) {', '.join(sorted(unknown))}",
                    {"path": path, "unknown": sorted(unknown), "supported": sorted(properties)},
                )
        value = {
            key: (_check(item, properties[key], f"{path}.{key}")
                  if key in properties else item)
            for key, item in value.items()
        }
    return value


def validate_arguments(schema: Mapping[str, Any], arguments: Any) -> dict[str, Any]:
    """Validate and normalise tool arguments against the tool's input schema."""
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise ProtocolError(INVALID_PARAMS, "arguments must be an object")
    return _check(arguments, schema, "arguments")


__all__ = [
    "PROTOCOL_VERSION",
    "SUPPORTED_PROTOCOL_VERSIONS",
    "PARSE_ERROR",
    "INVALID_REQUEST",
    "METHOD_NOT_FOUND",
    "INVALID_PARAMS",
    "INTERNAL_ERROR",
    "SERVER_ERROR",
    "REQUEST_CANCELLED",
    "ProtocolError",
    "parse_message",
    "success_response",
    "error_response",
    "validate_arguments",
]
