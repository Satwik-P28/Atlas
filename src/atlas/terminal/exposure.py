"""Whether a bind address may be used, given that the API has no authentication.

The terminal API can read company research and write watchlists, workspaces and saved
objects. It has no login, no token and no per-user boundary, so it is a local service by
design. A warning printed while the server already listens on an external interface is not
a safety mechanism: by the time the operator sees it, the service is reachable.

Binding outside loopback therefore requires an explicit acknowledgement (``serve
--allow-non-loopback`` or ``ATLAS_ALLOW_NON_LOOPBACK=1``). The acknowledgement is a
statement that the operator has placed the service behind their own controls; it is *not*
authentication, and the report says so. Nothing here weakens ordinary local use: every
loopback form stays permitted with no flag.
"""

from __future__ import annotations

import os
from typing import Mapping

LOOPBACK_HOSTS = {"127.0.0.1", "127.0.0.2", "::1", "[::1]", "localhost"}
WILDCARD_HOSTS = {"0.0.0.0", "::", "[::]", "*", ""}
TRUTHY = {"1", "true", "yes", "on"}

ACK_FLAG = "--allow-non-loopback"
ACK_ENV = "ATLAS_ALLOW_NON_LOOPBACK"

WARNING = (
    "WARNING: this API has no authentication and accepts write requests. Binding a "
    "non-loopback address exposes it to anyone who can reach the interface. An "
    "acknowledgement is not authentication: put an authenticating proxy in front of it."
)


def assessed_env(environ: Mapping[str, str] | None = None) -> bool:
    source = os.environ if environ is None else environ
    return str(source.get(ACK_ENV, "")).strip().lower() in TRUTHY


def assess_bind(
    host: str,
    *,
    allow_non_loopback: bool = False,
    environ: Mapping[str, str] | None = None,
) -> dict[str, object]:
    """Decide whether ``host`` may be bound, and explain the decision."""
    normalised = str(host or "").strip()
    loopback = normalised in LOOPBACK_HOSTS
    acknowledged = bool(allow_non_loopback) or assessed_env(environ)
    wildcard = normalised in WILDCARD_HOSTS
    permitted = loopback or acknowledged
    if loopback:
        reason = "loopback binding; the unauthenticated service is reachable only locally"
    elif permitted:
        reason = (
            "non-loopback binding explicitly acknowledged; the service is still "
            "unauthenticated and must not be exposed without an authenticating proxy"
        )
    else:
        reason = (
            f"refusing to bind {normalised!r}: the terminal API has no authentication and "
            f"accepts write requests. Re-run with {ACK_FLAG} (or {ACK_ENV}=1) only if you "
            "have placed an authenticated boundary in front of it."
        )
    return {
        "host": normalised,
        "loopback": loopback,
        "wildcard": wildcard,
        "acknowledged": acknowledged,
        "permitted": permitted,
        "authentication": "absent",
        "warning": None if loopback else WARNING,
        "reason": reason,
        "policy": (
            "The default service is loopback-only. A non-loopback bind requires an explicit "
            "acknowledgement and remains unauthenticated; remote deployment needs a separate "
            "authentication and security design."
        ),
    }


__all__ = ["ACK_ENV", "ACK_FLAG", "LOOPBACK_HOSTS", "assess_bind", "assessed_env"]
