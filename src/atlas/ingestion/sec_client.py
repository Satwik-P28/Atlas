"""SEC EDGAR HTTP client.

Fair-access compliance is implemented, not assumed:

* A descriptive ``User-Agent`` with a contact address is **required**. The client
  refuses to make a request without one (:class:`SecPolicyError`), because SEC
  returns 403 and can block an IP for policy violations.
* Requests are rate limited to a configurable ceiling (default 5/s, below the SEC's
  10/s guidance) using a monotonic token bucket, so bursts cannot exceed the limit.
* ``429``/``5xx`` responses are retried with exponential backoff and jitter, honouring
  ``Retry-After`` when present. Retries are bounded; a failure is reported, not hidden.
* Every successful response is stored as a *raw document* with its SHA-256, ETag and
  retrieval timestamp. Conditional requests (``If-None-Match``) avoid re-downloading
  unchanged payloads, and the stored bytes are what evidence records point at, so a
  value can always be traced to the exact document Atlas received.

Unauthenticated, undocumented endpoints are not used. Only ``data.sec.gov`` and
``www.sec.gov`` public JSON APIs are queried.
"""

from __future__ import annotations

import gzip
import json
import random
import time
import urllib.error
import urllib.request
import zlib
from dataclasses import dataclass, field
from typing import Any, Callable, Mapping

from ..core.errors import (
    ProviderPayloadError,
    ProviderRateLimited,
    ProviderUnavailable,
    SecPolicyError,
    ValidationError,
)
from ..core.ids import raw_document_id
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from ..storage.sources import SEC_EDGAR, SourceRegistry

SEC_DATA_HOST = "data.sec.gov"
SEC_WWW_HOST = "www.sec.gov"
_ALLOWED_HOSTS = {SEC_DATA_HOST, SEC_WWW_HOST}
_MAX_BODY_BYTES = 64 * 1024 * 1024


@dataclass(slots=True)
class FetchResult:
    url: str
    status: int
    body: bytes
    not_modified: bool
    from_cache: bool
    attempts: int
    latency_ms: int
    doc_id: str | None = None
    etag: str | None = None
    last_modified: str | None = None

    def json(self) -> Any:
        return decode_json(self.body, url=self.url)


class TokenBucket:
    """Monotonic-clock token bucket; sleeps only when the bucket is empty."""

    def __init__(self, rate_per_second: float, *, capacity: float | None = None,
                 clock: Callable[[], float] = time.monotonic,
                 sleep: Callable[[float], None] = time.sleep) -> None:
        if rate_per_second <= 0:
            raise ValidationError("rate must be positive", rate=rate_per_second)
        self.rate = rate_per_second
        self.capacity = capacity if capacity is not None else max(1.0, rate_per_second)
        self._tokens = self.capacity
        self._clock = clock
        self._sleep = sleep
        self._last = clock()

    def acquire(self) -> None:
        now = self._clock()
        elapsed = max(0.0, now - self._last)
        self._last = now
        self._tokens = min(self.capacity, self._tokens + elapsed * self.rate)
        if self._tokens < 1.0:
            wait = (1.0 - self._tokens) / self.rate
            self._sleep(wait)
            self._tokens = 0.0
            self._last = self._clock()
        else:
            self._tokens -= 1.0


def validate_user_agent(user_agent: str | None) -> str:
    """SEC requires an identifiable agent. Enforced before any request."""
    if not user_agent or not user_agent.strip():
        raise SecPolicyError(
            "SEC requires a User-Agent identifying the requester with a contact address",
            hint="set ATLAS_SEC_USER_AGENT='AtlasQuant/0.1 you@example.com'",
        )
    value = user_agent.strip()
    if "@" not in value:
        raise SecPolicyError(
            "SEC User-Agent must include a contact email address",
            user_agent=value,
            hint="e.g. 'AtlasQuant/0.1 research@example.com'",
        )
    return value


def decode_json(body: bytes, *, url: str = "") -> Any:
    if not body:
        raise ProviderPayloadError("empty response body", url=url)
    try:
        return json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ProviderPayloadError("response is not valid JSON", url=url, error=str(exc)) from exc


def _check_host(url: str) -> None:
    from urllib.parse import urlparse

    host = (urlparse(url).hostname or "").lower()
    if host not in _ALLOWED_HOSTS:
        raise ValidationError(
            "refusing to query a host outside the SEC public API domain",
            url=url,
            allowed=sorted(_ALLOWED_HOSTS),
        )


class SecClient:
    """Rate-limited, caching, retrying SEC JSON client."""

    def __init__(
        self,
        *,
        user_agent: str | None,
        db: Database | None = None,
        requests_per_second: float = 5.0,
        timeout: float = 30.0,
        max_retries: int = 4,
        max_retry_wait: float = 60.0,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
        transport: Callable[[urllib.request.Request, float], tuple[int, Mapping[str, str], bytes]] | None = None,
        jitter: Callable[[], float] | None = None,
    ) -> None:
        self.user_agent = validate_user_agent(user_agent)
        self.db = db
        self.timeout = timeout
        self.max_retries = max_retries
        self.max_retry_wait = max_retry_wait
        self._sleep = sleep
        self._jitter = jitter or (lambda: random.uniform(0.0, 0.5))
        self._limiter = TokenBucket(requests_per_second, clock=clock, sleep=sleep)
        self._transport = transport or _urllib_transport
        self.sources = SourceRegistry(db) if db is not None else None
        self.request_count = 0

    # ------------------------------------------------------------------ public
    def get_json(self, url: str) -> tuple[Any, FetchResult]:
        result = self.get(url)
        return result.json(), result

    def get(self, url: str, *, allow_cache: bool = True) -> FetchResult:
        _check_host(url)
        cached = self._cached(url) if (allow_cache and self.db is not None) else None
        headers = {
            "User-Agent": self.user_agent,
            "Accept": "application/json",
            "Accept-Encoding": "gzip, deflate",
            "Host": _host_of(url),
        }
        if cached and cached.get("etag"):
            headers["If-None-Match"] = cached["etag"]
        if cached and cached.get("last_modified"):
            headers["If-Modified-Since"] = cached["last_modified"]

        attempts = 0
        while True:
            attempts += 1
            self._limiter.acquire()
            self.request_count += 1
            request = urllib.request.Request(url, headers=headers, method="GET")
            started = time.perf_counter()
            try:
                status, response_headers, body = self._transport(request, self.timeout)
            except urllib.error.HTTPError as exc:  # pragma: no cover - transport dependent
                status, response_headers, body = exc.code, dict(exc.headers or {}), b""
            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                if attempts > self.max_retries:
                    raise ProviderUnavailable(
                        "SEC request failed after retries", url=url, attempts=attempts, error=str(exc)
                    ) from exc
                self._sleep(self._backoff(attempts, None))
                continue
            latency_ms = int((time.perf_counter() - started) * 1000)

            if status == 304 and cached is not None:
                return FetchResult(
                    url=url,
                    status=304,
                    body=cached["body"],
                    not_modified=True,
                    from_cache=True,
                    attempts=attempts,
                    latency_ms=latency_ms,
                    doc_id=cached["doc_id"],
                    etag=cached.get("etag"),
                    last_modified=cached.get("last_modified"),
                )
            if status == 200:
                body = _decompress(body, response_headers)
                if len(body) > _MAX_BODY_BYTES:
                    raise ProviderPayloadError("response exceeds size limit", url=url, bytes=len(body))
                doc_id = self._store(url, body, response_headers, status)
                return FetchResult(
                    url=url,
                    status=200,
                    body=body,
                    not_modified=False,
                    from_cache=False,
                    attempts=attempts,
                    latency_ms=latency_ms,
                    doc_id=doc_id,
                    etag=response_headers.get("ETag") or response_headers.get("etag"),
                    last_modified=response_headers.get("Last-Modified") or response_headers.get("last-modified"),
                )
            if status == 403:
                raise SecPolicyError(
                    "SEC rejected the request (403). Fair-access policy requires a descriptive "
                    "User-Agent with contact details and a request rate of at most 10/s.",
                    url=url,
                    user_agent=self.user_agent,
                )
            if status == 429:
                if attempts > self.max_retries:
                    raise ProviderRateLimited("SEC rate limit persisted after retries", url=url, attempts=attempts)
                self._sleep(self._backoff(attempts, response_headers))
                continue
            if status >= 500:
                if attempts > self.max_retries:
                    raise ProviderUnavailable("SEC service error after retries", url=url, status=status,
                                              attempts=attempts)
                self._sleep(self._backoff(attempts, response_headers))
                continue
            raise ProviderPayloadError("unexpected SEC response", url=url, status=status)

    # ---------------------------------------------------------------- internals
    def _backoff(self, attempt: int, headers: Mapping[str, str] | None) -> float:
        retry_after = None
        if headers:
            for key, value in headers.items():
                if key.lower() == "retry-after":
                    try:
                        retry_after = float(str(value).strip())
                    except ValueError:
                        retry_after = None
                    break
        if retry_after is not None:
            return min(retry_after, self.max_retry_wait)
        base = min(2.0 ** (attempt - 1), self.max_retry_wait)
        return base + self._jitter()

    def _cached(self, url: str) -> dict[str, Any] | None:
        assert self.db is not None
        row = self.db.query_one(
            "SELECT doc_id, body, etag, last_modified FROM raw_document WHERE url = ? "
            "ORDER BY retrieved_at DESC LIMIT 1",
            (url,),
        )
        if row is None:
            return None
        return {
            "doc_id": row["doc_id"],
            "body": row["body"],
            "etag": row["etag"],
            "last_modified": row["last_modified"],
        }

    def _store(self, url: str, body: bytes, headers: Mapping[str, str] | None, status: int) -> str | None:
        if self.db is None:
            return None
        assert self.sources is not None
        self.sources.ensure(SEC_EDGAR)
        import hashlib

        content_hash = hashlib.sha256(body).hexdigest()
        doc_id = raw_document_id(SEC_EDGAR.source_id, content_hash)
        lower = {str(k).lower(): v for k, v in (headers or {}).items()}
        self.db.execute(
            "INSERT INTO raw_document (doc_id, source_id, url, content_hash, media_type, http_status, byte_size, "
            "retrieved_at, etag, last_modified, body) VALUES (?,?,?,?,?,?,?,?,?,?,?) "
            "ON CONFLICT(source_id, content_hash) DO UPDATE SET url=excluded.url, retrieved_at=excluded.retrieved_at, "
            "etag=COALESCE(excluded.etag, raw_document.etag), "
            "last_modified=COALESCE(excluded.last_modified, raw_document.last_modified)",
            (
                doc_id,
                SEC_EDGAR.source_id,
                url,
                content_hash,
                lower.get("content-type"),
                status,
                len(body),
                iso(utcnow()),
                lower.get("etag"),
                lower.get("last-modified"),
                body,
            ),
        )
        return doc_id


def _host_of(url: str) -> str:
    from urllib.parse import urlparse

    return (urlparse(url).hostname or "").lower()


def _decompress(body: bytes, headers: Mapping[str, str] | None) -> bytes:
    encoding = ""
    for key, value in (headers or {}).items():
        if str(key).lower() == "content-encoding":
            encoding = str(value).lower()
            break
    try:
        if "gzip" in encoding:
            return gzip.decompress(body)
        if "deflate" in encoding:
            return zlib.decompress(body)
    except (OSError, zlib.error) as exc:  # pragma: no cover - transport dependent
        raise ProviderPayloadError("cannot decompress SEC response", error=str(exc)) from exc
    return body


def _urllib_transport(request: urllib.request.Request, timeout: float) -> tuple[int, Mapping[str, str], bytes]:
    with urllib.request.urlopen(request, timeout=timeout) as response:  # noqa: S310 - allowlisted hosts
        return response.status, dict(response.headers), response.read()
