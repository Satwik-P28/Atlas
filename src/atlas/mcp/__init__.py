"""Atlas Model Context Protocol server.

The MCP surface is a local, read-only-by-default adapter over the same services the HTTP
API and the browser use. It exists so an external assistant can *cite* Atlas evidence
rather than paraphrase a number; it is deliberately not a second implementation of any
financial computation.
"""

from __future__ import annotations

from .protocol import PROTOCOL_VERSION
from .server import AtlasMCPServer, MCPServerConfig
from .tools import TOOLS, ToolContext, ToolError

__all__ = [
    "AtlasMCPServer",
    "MCPServerConfig",
    "PROTOCOL_VERSION",
    "TOOLS",
    "ToolContext",
    "ToolError",
]
