"""Loopback host and origin enforcement for the unauthenticated local API.

The terminal API has no login and accepts writes. Loopback binding keeps it off the
network, but it does not stop *DNS rebinding*: a hostile page can serve its own JavaScript
from ``evil.example`` and re-resolve that name to ``127.0.0.1``. The browser then treats
requests to ``http://evil.example:8000/api/...`` as same-origin, so CORS never applies and
the page can read research data and mutate watchlists.

The defence is to validate the ``Host`` header against the names this deployment may
legitimately answer for, and to reject state-changing requests that arrive with a foreign
``Origin``. Both checks fail closed with a machine-readable error.

Allowed hosts are the loopback names plus anything the operator lists in
``ATLAS_TERMINAL_ALLOWED_HOSTS`` (comma-separated). ``testserver`` is accepted because it is
the in-process ``TestClient`` pseudo-host: it is not a public DNS name, so it cannot be
rebound, and accepted tests use it to exercise the API without a socket.
"""

from __future__ import annotations

import json
import os
from typing import Any, Iterable, Mapping, Sequence

LOOPBACK_HOSTNAMES = frozenset({"127.0.0.1", "127.0.0.2", "localhost", "::1"})
TEST_CLIENT_HOSTNAME = "testserver"
ALLOWED_HOSTS_ENV = "ATLAS_TERMINAL_ALLOWED_HOSTS"

UNSAFE_METHODS = frozenset({"POST", "PUT", "PATCH", "DELETE"})


def hostname_of(host_header: str | None) -> str:
    """Extract the bare hostname from a ``Host`` header, tolerating ports and IPv6."""
    value = str(host_header or "").strip().lower()
    if not value:
        return ""
    if value.startswith("["):
        end = value.find("]")
        return value[1:end] if end != -1 else value
    if value.count(":") == 1:
        return value.split(":", 1)[0]
    return value


def allowed_hostnames(
    *, environ: Mapping[str, str] | None = None, extra: Iterable[str] = ()
) -> frozenset[str]:
    source = os.environ if environ is None else environ
    configured = {
        hostname_of(item)
        for item in str(source.get(ALLOWED_HOSTS_ENV, "")).split(",")
        if item.strip()
    }
    configured.update(hostname_of(item) for item in extra if str(item).strip())
    return frozenset(LOOPBACK_HOSTNAMES | {TEST_CLIENT_HOSTNAME} | configured)


def host_allowed(host_header: str | None, *, allowed: Sequence[str] | frozenset[str]) -> bool:
    return hostname_of(host_header) in set(allowed)


def origin_of(origin_header: str | None) -> str:
    return str(origin_header or "").strip().lower()


def origin_allowed(
    origin_header: str | None,
    *,
    allowed_origins: Sequence[str],
    host_header: str | None,
    allowed_hosts: Sequence[str] | frozenset[str],
) -> bool:
    """A state-changing request may come from this origin or a configured one.

    ``Origin`` is compared as scheme+host+port. A same-host origin is accepted only when
    that host is itself permitted, so rebinding to a foreign name cannot pass as "same".
    """
    origin = origin_of(origin_header)
    if not origin:
        return True  # non-browser clients send no Origin; the Host check still applies
    if origin in {str(item).strip().lower() for item in allowed_origins if str(item).strip()}:
        return True
    bare = origin.split("://", 1)[1] if "://" in origin else origin
    same_host = hostname_of(bare) == hostname_of(host_header)
    return bool(same_host and hostname_of(host_header) in set(allowed_hosts))


def _reject_payload(code: str, message: str, context: dict[str, Any]) -> bytes:
    return json.dumps(
        {"error": {"code": code, "message": message, "context": context}},
        separators=(",", ":"),
    ).encode("utf-8")


class LocalOriginGuardMiddleware:
    """Reject a foreign ``Host`` and cross-origin state-changing requests."""

    def __init__(
        self,
        app: Any,
        *,
        allowed_origins: Sequence[str] = (),
        extra_hosts: Sequence[str] = (),
        environ: Mapping[str, str] | None = None,
    ) -> None:
        self.app = app
        self.allowed_origins = tuple(allowed_origins)
        self.allowed_hosts = allowed_hostnames(environ=environ, extra=extra_hosts)

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return
        headers = {
            name.decode("latin-1").lower(): value.decode("latin-1")
            for name, value in scope.get("headers", [])
        }
        host = headers.get("host")
        if not host_allowed(host, allowed=self.allowed_hosts):
            await self._reject(
                send,
                421,
                "host_not_allowed",
                "the Host header is not one this local Atlas instance answers for; a "
                "browser request rebound from another name is refused",
                {"host": host, "allowed": sorted(self.allowed_hosts)},
            )
            return
        method = str(scope.get("method", "GET")).upper()
        if method in UNSAFE_METHODS and not origin_allowed(
            headers.get("origin"),
            allowed_origins=self.allowed_origins,
            host_header=host,
            allowed_hosts=self.allowed_hosts,
        ):
            await self._reject(
                send,
                403,
                "cross_origin_write_refused",
                "a state-changing request from another origin is refused; the local API "
                "accepts writes only from its own page or a configured development origin",
                {"origin": headers.get("origin"), "allowed_origins": list(self.allowed_origins)},
            )
            return
        await self.app(scope, receive, send)

    async def _reject(
        self, send: Any, status: int, code: str, message: str, context: dict[str, Any]
    ) -> None:
        body = _reject_payload(code, message, context)
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json"),
                    (b"content-length", str(len(body)).encode("ascii")),
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})
