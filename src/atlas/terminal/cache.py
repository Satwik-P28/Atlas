"""Generation-keyed read cache for terminal read models.

Read models are pure functions of the database, but recomputing an issuer's metrics or
a screen on every keystroke is wasteful. This cache stores results under a *generation
token* built from cheap aggregates that change whenever the facts a terminal view depends
on change:

* ``MAX(evidence.ingest_seq)`` — any new evidence (facts, restatements, derived values);
* ``COUNT(bar)`` — a new or revised market observation;
* ``COUNT(filing)`` and ``COUNT(corporate_action)`` — filing/action ingestion;
* the newest ``workspace``/``watchlist``/``app_setting`` timestamps — user-data edits.

A cache entry from an older generation is never returned, so a restatement or a new bar
cannot be masked by a stale screen. This is deliberately not a TTL cache: correctness
comes from invalidation, and the optional ``ttl`` is only used for time-relative views
(a screen run without an explicit as-of) where the server itself chooses the instant.

Entries are per-process and bounded. There is no cross-process invalidation problem
because the generation is recomputed from the database on every lookup.
"""

from __future__ import annotations

import json
import threading
import time
from collections import OrderedDict
from typing import Any, Callable

from ..storage.db import Database

_MAX_ENTRIES = 256
_CACHE: "OrderedDict[str, tuple[str, float | None, Any]]" = OrderedDict()
_LOCK = threading.Lock()
_STATS = {"hits": 0, "misses": 0, "evictions": 0}


def generation(db: Database) -> str:
    """A cheap token that changes when terminal-visible data changes."""
    row = db.query_one(
        "SELECT "
        "(SELECT COALESCE(MAX(ingest_seq), 0) FROM evidence) AS evidence_seq, "
        "(SELECT COUNT(*) FROM bar) AS bars, "
        "(SELECT COUNT(*) FROM filing) AS filings, "
        "(SELECT COUNT(*) FROM corporate_action) AS actions, "
        "(SELECT COALESCE(MAX(updated_at), '') FROM workspace) AS workspace_updated, "
        "(SELECT COALESCE(MAX(updated_at), '') FROM watchlist) AS watchlist_updated, "
        "(SELECT COALESCE(MAX(updated_at), '') FROM app_setting) AS setting_updated"
    )
    if row is None:  # pragma: no cover - schema guarantees these tables
        return "empty"
    # The database identity is part of the token: two databases in one process can have
    # identical counts and ingest sequences, and must never share a cached read model.
    # In-memory databases have no stable path, so their object identity scopes them.
    identity = f"mem:{id(db)}" if db.path == ":memory:" else db.path
    return f"{identity}|" + "|".join(str(row[key]) for key in row.keys())


def _key(namespace: str, params: dict[str, Any], token: str) -> str:
    return f"{namespace}:{json.dumps(params, sort_keys=True, default=str)}:{token}"


def get_or_compute(
    db: Database,
    namespace: str,
    params: dict[str, Any],
    compute: Callable[[], Any],
    *,
    ttl: float | None = None,
) -> Any:
    """Return a cached value for ``(namespace, params, generation)`` or compute it.

    ``ttl`` is only appropriate for views whose own output states the instant it used.
    """
    token = generation(db)
    key = _key(namespace, params, token)
    now = time.monotonic()
    with _LOCK:
        entry = _CACHE.get(key)
        if entry is not None:
            stored_token, expires, value = entry
            if stored_token == token and (expires is None or expires > now):
                _CACHE.move_to_end(key)
                _STATS["hits"] += 1
                return value
            _CACHE.pop(key, None)
    value = compute()
    with _LOCK:
        _STATS["misses"] += 1
        _CACHE[key] = (token, (now + ttl) if ttl is not None else None, value)
        _CACHE.move_to_end(key)
        while len(_CACHE) > _MAX_ENTRIES:
            _CACHE.popitem(last=False)
            _STATS["evictions"] += 1
    return value


def clear() -> None:
    """Drop every entry (used by tests and diagnostics)."""
    with _LOCK:
        _CACHE.clear()


def stats() -> dict[str, Any]:
    with _LOCK:
        return {"entries": len(_CACHE), **_STATS}
