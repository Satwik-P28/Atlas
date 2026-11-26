"""The unauthenticated local API must refuse rebound hosts and foreign-origin writes.

These tests pin the DNS-rebinding defence: a page served from ``evil.example`` can
re-resolve itself to 127.0.0.1, at which point the browser considers its requests
same-origin and CORS never runs. Validating ``Host`` and the ``Origin`` of state-changing
requests is what stops that, so both are tested through the real application.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the terminal API requires the terminal extra")

from fastapi.testclient import TestClient  # noqa: E402

from atlas.storage.db import Database  # noqa: E402
from atlas.terminal.api import create_app  # noqa: E402
from atlas.terminal.local_guard import (  # noqa: E402
    ALLOWED_HOSTS_ENV,
    allowed_hostnames,
    hostname_of,
)


@pytest.fixture()
def client(tmp_path) -> TestClient:
    db = Database(tmp_path / "guard.db")
    db.migrate()
    db.close()
    return TestClient(create_app(tmp_path / "guard.db"), raise_server_exceptions=False)


def test_hostname_parsing_handles_ports_and_ipv6() -> None:
    assert hostname_of("127.0.0.1:8000") == "127.0.0.1"
    assert hostname_of("[::1]:8000") == "::1"
    assert hostname_of("LOCALHOST") == "localhost"
    assert hostname_of(None) == ""


def test_configured_extra_hosts_are_added_to_the_allowlist() -> None:
    allowed = allowed_hostnames(environ={ALLOWED_HOSTS_ENV: "atlas.internal, desk.local:8080"})
    assert "atlas.internal" in allowed
    assert "desk.local" in allowed
    assert "127.0.0.1" in allowed


def test_loopback_host_is_served(client: TestClient) -> None:
    response = client.get("/api/health", headers={"host": "127.0.0.1:8000"})
    assert response.status_code != 421
    assert response.status_code == 200


def test_rebound_foreign_host_is_refused_before_the_handler(client: TestClient) -> None:
    response = client.get("/api/health", headers={"host": "evil.example:8000"})
    assert response.status_code == 421
    body = response.json()
    assert body["error"]["code"] == "host_not_allowed"
    assert "127.0.0.1" in body["error"]["context"]["allowed"]


def test_cross_origin_write_is_refused(client: TestClient) -> None:
    response = client.post(
        "/api/settings",
        headers={"host": "127.0.0.1:8000", "origin": "http://evil.example"},
        json={"key": "theme", "value": "dark"},
    )
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "cross_origin_write_refused"


def test_configured_development_origin_may_write(client: TestClient) -> None:
    # The default development origin is the Vite dev server on 5173.
    response = client.post(
        "/api/settings",
        headers={"host": "127.0.0.1:8000", "origin": "http://localhost:5173"},
        json={"key": "theme", "value": "dark"},
    )
    assert response.status_code != 403
    assert response.status_code != 421


def test_same_origin_write_is_allowed(client: TestClient) -> None:
    response = client.post(
        "/api/settings",
        headers={"host": "127.0.0.1:8000", "origin": "http://127.0.0.1:8000"},
        json={"key": "theme", "value": "dark"},
    )
    assert response.status_code not in (403, 421)


def test_reads_from_a_foreign_origin_still_need_a_valid_host(client: TestClient) -> None:
    # A cross-origin read is not a write, so it is left to CORS; but rebinding is refused.
    assert client.get(
        "/api/health", headers={"host": "127.0.0.1:8000", "origin": "http://evil.example"}
    ).status_code == 200
    assert client.get(
        "/api/health", headers={"host": "evil.example", "origin": "http://evil.example"}
    ).status_code == 421
