"""``python -m atlas.mcp`` — run the Atlas MCP server over stdio.

The server is local by construction: it reads JSON-RPC from stdin and writes responses to
stdout. Nothing is bound to a port, so there is no network surface to protect.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ..storage.db import Database
from ..storage.migrations import LATEST_VERSION
from .server import build_server


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="atlas-mcp",
        description="Atlas MCP server (stdio, read-only by default)",
    )
    parser.add_argument("--db", default=None, help="Atlas database path (default: ATLAS_DB or var/atlas.db)")
    parser.add_argument(
        "--allow-mutations", action="store_true",
        help="authorise the mutating tools for this session (default: read-only)",
    )
    parser.add_argument(
        "--call-timeout", type=float, default=20.0,
        help="per-call deadline in seconds (default 20)",
    )
    args = parser.parse_args(argv)

    import os

    path = Path(args.db or os.environ.get("ATLAS_DB", "var/atlas.db"))
    if not path.exists():
        print(
            f"atlas mcp: database not found at {path}. Run `atlas init` or `atlas demo` first; "
            "an MCP server without evidence would be able to answer nothing.",
            file=sys.stderr,
        )
        return 2
    try:
        db = Database(path, create=False)
        try:
            version = db.schema_version()
        finally:
            db.close()
    except Exception as exc:  # noqa: BLE001 - report the reason, do not start
        print(f"atlas mcp: cannot open {path}: {exc}", file=sys.stderr)
        return 2
    if version < LATEST_VERSION:
        print(
            f"atlas mcp: schema {version} is older than {LATEST_VERSION}; run `atlas migrate` first",
            file=sys.stderr,
        )
        return 2
    if args.allow_mutations:
        print("atlas mcp: mutations authorised for this session", file=sys.stderr)
    server = build_server(path, allow_mutations=args.allow_mutations,
                          call_timeout=args.call_timeout)
    return server.serve()


if __name__ == "__main__":  # pragma: no cover - process entry point
    raise SystemExit(main())
