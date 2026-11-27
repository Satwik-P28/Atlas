"""HTTP transport with explicit retries, rate limits, conditionals and resume.

The transport is the only place network I/O happens. It refuses cross-host redirects
unless the destination is explicitly listed, never silently follows an HTTPS to HTTP
downgrade, and treats a short read as a failed download rather than a valid snapshot.

Resumable downloads use HTTP Range. A server that ignores the range and answers 200
restarts from zero; a 206 continues the partial file. ETag / Last-Modified are
persisted by the engine so an unchanged upstream archive is not downloaded again.
"""

from __future__ import annotations

import hashlib
import os
import random
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Mapping

DEFAULT_USER_AGENT = "Atlas-Data-Engine/1.0 (open financial data acquisition; contact: admin@example.org)"


class TransportError(RuntimeError):
    def __init__(self, message: str, *, status: int | None = None, url: str | None = None,
                 retryable: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.url = url
        self.retryable = retryable


class RedirectRefused(TransportError):
    pass


class DownloadTooLarge(TransportError):
    pass


class IntegrityError(TransportError):
    pass


@dataclass(frozen=True, slots=True)
class RateLimit:
    requests_per_second: float
    burst: int = 1

    def interval(self) -> float:
        return 1.0 / self.requests_per_second if self.requests_per_second > 0 else 0.0


class HostRateLimiter:
    """Per-host token bucket. Deliberately simple and deterministic under test."""

    def __init__(self, limits: Mapping[str, RateLimit] | None = None, *, default: RateLimit | None = None,
                 clock=time.monotonic, sleep=time.sleep) -> None:
        self.limits = {host.lower(): limit for host, limit in (limits or {}).items()}
        self.default = default
        self._tokens: dict[str, float] = {}
        self._updated: dict[str, float] = {}
        self._last: dict[str, float] = {}
        self._clock = clock
        self._sleep = sleep

    def acquire(self, url: str) -> float:
        host = (urllib.parse.urlsplit(url).hostname or "").lower()
        limit = self.limits.get(host, self.default)
        if limit is None:
            return 0.0
        now = self._clock()
        tokens = self._tokens.get(host, float(limit.burst))
        updated = self._updated.get(host, now)
        tokens = min(float(limit.burst), tokens + (now - updated) * limit.requests_per_second)
        self._tokens[host] = tokens
        self._updated[host] = now
        if tokens < 1.0:
            wait = (1.0 - tokens) / limit.requests_per_second
            self._sleep(wait)
            now = self._clock()
            tokens = 0.0
            self._updated[host] = now
        else:
            tokens -= 1.0
        self._tokens[host] = max(0.0, tokens)
        last = self._last.get(host, 0.0)
        spacing = max(0.0, limit.interval() - (now - last))
        if spacing:
            self._sleep(spacing)
            now = self._clock()
        self._last[host] = now
        return spacing


@dataclass(slots=True)
class DownloadResult:
    url: str
    final_url: str
    status: int
    path: Path | None
    bytes_downloaded: int
    sha256: str | None
    etag: str | None = None
    last_modified: str | None = None
    content_type: str | None = None
    content_length: int | None = None
    not_modified: bool = False
    resumed_from: int = 0
    elapsed_seconds: float = 0.0
    attempts: int = 0

    def to_dict(self) -> dict:
        return {
            "url": self.url,
            "final_url": self.final_url,
            "status": self.status,
            "bytes_downloaded": self.bytes_downloaded,
            "sha256": self.sha256,
            "etag": self.etag,
            "last_modified": self.last_modified,
            "content_type": self.content_type,
            "content_length": self.content_length,
            "not_modified": self.not_modified,
            "resumed_from": self.resumed_from,
            "elapsed_seconds": round(self.elapsed_seconds, 3),
            "attempts": self.attempts,
        }


@dataclass(slots=True)
class TransportConfig:
    user_agent: str = DEFAULT_USER_AGENT
    timeout_seconds: float = 60.0
    max_retries: int = 4
    backoff_base: float = 1.0
    backoff_max: float = 60.0
    retry_budget_seconds: float = 900.0
    chunk_size: int = 1 << 20
    allowed_redirect_hosts: frozenset[str] = field(default_factory=frozenset)
    rate_limits: Mapping[str, RateLimit] = field(default_factory=dict)
    default_rate_limit: RateLimit | None = RateLimit(2.0, 2)


class HttpTransport:
    def __init__(self, config: TransportConfig | None = None, *, opener=None, clock=time.monotonic,
                 sleep=time.sleep) -> None:
        self.config = config or TransportConfig()
        self._opener = opener or urllib.request.build_opener()
        self._clock = clock
        self._sleep = sleep
        self._limiter = HostRateLimiter(self.config.rate_limits, default=self.config.default_rate_limit,
                                        clock=clock, sleep=sleep)

    def _validate_redirect(self, original: str, final: str) -> None:
        before = urllib.parse.urlsplit(original)
        after = urllib.parse.urlsplit(final)
        if after.scheme != "https":
            raise RedirectRefused(f"refusing non-HTTPS redirect to {final}", url=final)
        if after.hostname == before.hostname:
            return
        if (after.hostname or "").lower() not in self.config.allowed_redirect_hosts:
            raise RedirectRefused(
                f"refusing cross-host redirect {before.hostname} -> {after.hostname}", url=final
            )

    def download(
        self,
        url: str,
        destination: str | Path,
        *,
        max_bytes: int | None = None,
        resume: bool = True,
        etag: str | None = None,
        last_modified: str | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> DownloadResult:
        dest = Path(destination)
        dest.parent.mkdir(parents=True, exist_ok=True)
        part = dest.with_name(dest.name + ".part")
        started = self._clock()
        attempt = 0
        budget_started = started

        while True:
            attempt += 1
            if attempt > self.config.max_retries + 1:
                raise TransportError("retry budget exhausted", url=url)
            conditional: dict[str, str] = {"User-Agent": self.config.user_agent, "Accept-Encoding": "identity"}
            if headers:
                conditional.update({k: v for k, v in headers.items() if k.lower() not in {"host", "user-agent"}})
            if etag:
                conditional["If-None-Match"] = etag
            if last_modified:
                conditional["If-Modified-Since"] = last_modified

            existing = part.stat().st_size if resume and part.exists() else 0
            if existing:
                conditional["Range"] = f"bytes={existing}-"
            self._limiter.acquire(url)
            request = urllib.request.Request(url, headers=conditional)
            try:
                with self._opener.open(request, timeout=self.config.timeout_seconds) as response:
                    self._validate_redirect(url, response.geturl())
                    if response.status == 304:
                        return DownloadResult(url, response.geturl(), 304, None, 0, None,
                                              etag=response.headers.get("ETag"),
                                              last_modified=response.headers.get("Last-Modified"),
                                              content_type=response.headers.get("Content-Type"),
                                              not_modified=True, attempts=attempt,
                                              elapsed_seconds=self._clock() - started)
                    resumed_from = 0
                    if response.status == 206 and existing:
                        content_range = response.headers.get("Content-Range") or ""
                        if not content_range.startswith(f"bytes {existing}-"):
                            raise IntegrityError(f"unexpected Content-Range {content_range!r}", url=url)
                        resumed_from = existing
                        mode = "ab"
                    else:
                        mode = "wb"
                        existing = 0
                    declared = response.headers.get("Content-Length")
                    content_length = int(declared) if declared and declared.isdigit() else None
                    total_expected = (content_length + resumed_from) if content_length is not None else None
                    if max_bytes is not None and total_expected is not None and total_expected > max_bytes:
                        raise DownloadTooLarge(
                            f"declared size {total_expected} exceeds limit {max_bytes}", url=url
                        )
                    digest = hashlib.sha256()
                    if resumed_from:
                        with part.open("rb") as current:
                            while chunk := current.read(self.config.chunk_size):
                                digest.update(chunk)
                    written = resumed_from
                    with part.open(mode) as sink:
                        while chunk := response.read(self.config.chunk_size):
                            written += len(chunk)
                            if max_bytes is not None and written > max_bytes:
                                raise DownloadTooLarge(f"download exceeds limit {max_bytes}", url=url)
                            digest.update(chunk)
                            sink.write(chunk)
                        sink.flush()
                        os.fsync(sink.fileno())
                    if written == resumed_from and not content_length:
                        raise IntegrityError("empty download", url=url)
                    if total_expected is not None and written != total_expected:
                        raise IntegrityError(
                            f"short read: got {written} of {total_expected} bytes", url=url
                        )
                    os.replace(part, dest)
                    return DownloadResult(
                        url=url, final_url=response.geturl(), status=response.status, path=dest,
                        bytes_downloaded=written, sha256=digest.hexdigest(),
                        etag=response.headers.get("ETag"),
                        last_modified=response.headers.get("Last-Modified"),
                        content_type=response.headers.get("Content-Type"),
                        content_length=written, resumed_from=resumed_from, attempts=attempt,
                        elapsed_seconds=self._clock() - started,
                    )
            except urllib.error.HTTPError as exc:
                if exc.code == 304:
                    return DownloadResult(url, url, 304, None, 0, None, not_modified=True,
                                          attempts=attempt, elapsed_seconds=self._clock() - started)
                retryable = exc.code in {408, 425, 429, 500, 502, 503, 504}
                if not retryable or attempt > self.config.max_retries:
                    raise TransportError(f"HTTP {exc.code} for {url}", status=exc.code, url=url,
                                         retryable=retryable) from exc
                retry_after = exc.headers.get("Retry-After") if exc.headers else None
                delay = self._delay(attempt, retry_after)
                if self._clock() - budget_started + delay > self.config.retry_budget_seconds:
                    raise TransportError(f"retry budget exhausted after HTTP {exc.code}", status=exc.code,
                                         url=url, retryable=True) from exc
                self._sleep(delay)
            except (urllib.error.URLError, socket.timeout, TimeoutError, ConnectionError) as exc:
                if attempt > self.config.max_retries:
                    raise TransportError(f"network failure for {url}: {exc}", url=url, retryable=True) from exc
                delay = self._delay(attempt, None)
                if self._clock() - budget_started + delay > self.config.retry_budget_seconds:
                    raise TransportError(f"retry budget exhausted for {url}", url=url, retryable=True) from exc
                self._sleep(delay)
            except TransportError:
                raise

    def _delay(self, attempt: int, retry_after: str | None) -> float:
        if retry_after:
            try:
                return min(float(retry_after), self.config.backoff_max)
            except ValueError:
                pass
        base = min(self.config.backoff_max, self.config.backoff_base * (2 ** (attempt - 1)))
        return base * (0.5 + random.random() / 2)

    def head(self, url: str, *, headers: Mapping[str, str] | None = None) -> dict[str, object]:
        request = urllib.request.Request(url, method="HEAD",
                                         headers={"User-Agent": self.config.user_agent, **(headers or {})})
        self._limiter.acquire(url)
        try:
            with self._opener.open(request, timeout=self.config.timeout_seconds) as response:
                self._validate_redirect(url, response.geturl())
                length = response.headers.get("Content-Length")
                return {
                    "status": response.status,
                    "final_url": response.geturl(),
                    "content_length": int(length) if length and length.isdigit() else None,
                    "etag": response.headers.get("ETag"),
                    "last_modified": response.headers.get("Last-Modified"),
                    "content_type": response.headers.get("Content-Type"),
                }
        except urllib.error.HTTPError as exc:
            return {"status": exc.code, "final_url": url, "content_length": None, "etag": None,
                    "last_modified": None, "content_type": None}
