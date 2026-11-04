"""Persistence for terminal user data: watchlists, workspaces, preferences.

These records are deliberately outside the evidence layer. They describe what a user
wants to look at, never what a company reported, so writing one cannot affect a
point-in-time reconstruction. Items store stable ``security_id`` values rather than
ticker strings, because a symbol can be reassigned and a saved list must keep its
meaning.

``owner_id`` defaults to ``'local'`` and every query filters on it. Local operation
needs no authentication, and adding accounts later means supplying a different owner
rather than reshaping tables.
"""

from __future__ import annotations

import json
import uuid
from typing import Any, Sequence

from ..core.errors import StorageError, ValidationError
from ..core.temporal import iso, utcnow
from ..storage.db import Database
from .workspaces import fingerprint, validate_workspace

OWNER_LOCAL = "local"


def _now() -> str:
    return iso(utcnow())


def _new_id(prefix: str) -> str:
    return f"{prefix}-{uuid.uuid4().hex[:12]}"


class WatchlistStore:
    def __init__(self, db: Database, *, owner_id: str = OWNER_LOCAL) -> None:
        self.db = db
        self.owner_id = owner_id

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM watchlist WHERE owner_id = ? ORDER BY name COLLATE NOCASE",
            (self.owner_id,),
        )
        return [self._hydrate(row) for row in rows]

    def get(self, watchlist_id: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM watchlist WHERE watchlist_id = ? AND owner_id = ?",
            (watchlist_id, self.owner_id),
        )
        if row is None:
            raise ValidationError("unknown watchlist", watchlist_id=watchlist_id)
        return self._hydrate(row)

    def create(self, name: str, *, notes: str | None = None, security_ids: Sequence[str] = ()) -> dict[str, Any]:
        cleaned = self._name(name)
        watchlist_id = _new_id("WL")
        now = _now()
        with self.db.transaction():
            existing = self.db.query_one(
                "SELECT 1 FROM watchlist WHERE owner_id = ? AND name = ?", (self.owner_id, cleaned)
            )
            if existing is not None:
                raise StorageError("a watchlist with that name already exists", name=cleaned)
            self.db.execute(
                "INSERT INTO watchlist (watchlist_id, owner_id, name, notes, created_at, updated_at) "
                "VALUES (?,?,?,?,?,?)",
                (watchlist_id, self.owner_id, cleaned, notes, now, now),
            )
            for position, security_id in enumerate(security_ids):
                self._insert_item(watchlist_id, security_id, position)
        return self.get(watchlist_id)

    def update(
        self,
        watchlist_id: str,
        *,
        name: str | None = None,
        notes: str | None = None,
    ) -> dict[str, Any]:
        current = self.get(watchlist_id)
        cleaned = self._name(name) if name is not None else current["name"]
        with self.db.transaction():
            duplicate = self.db.query_one(
                "SELECT 1 FROM watchlist WHERE owner_id = ? AND name = ? AND watchlist_id != ?",
                (self.owner_id, cleaned, watchlist_id),
            )
            if duplicate is not None:
                raise StorageError("a watchlist with that name already exists", name=cleaned)
            self.db.execute(
                "UPDATE watchlist SET name = ?, notes = ?, updated_at = ? WHERE watchlist_id = ?",
                (cleaned, notes if notes is not None else current["notes"], _now(), watchlist_id),
            )
        return self.get(watchlist_id)

    def delete(self, watchlist_id: str) -> None:
        self.get(watchlist_id)
        with self.db.transaction():
            self.db.execute("DELETE FROM watchlist WHERE watchlist_id = ?", (watchlist_id,))

    def add_item(self, watchlist_id: str, security_id: str) -> dict[str, Any]:
        self.get(watchlist_id)
        with self.db.transaction():
            position = int(
                self.db.scalar(
                    "SELECT COALESCE(MAX(position), -1) + 1 FROM watchlist_item WHERE watchlist_id = ?",
                    (watchlist_id,),
                    default=0,
                )
                or 0
            )
            self._insert_item(watchlist_id, security_id, position, ignore_duplicate=True)
            self.db.execute(
                "UPDATE watchlist SET updated_at = ? WHERE watchlist_id = ?", (_now(), watchlist_id)
            )
        return self.get(watchlist_id)

    def remove_item(self, watchlist_id: str, security_id: str) -> dict[str, Any]:
        self.get(watchlist_id)
        with self.db.transaction():
            self.db.execute(
                "DELETE FROM watchlist_item WHERE watchlist_id = ? AND security_id = ?",
                (watchlist_id, security_id),
            )
            self.db.execute(
                "UPDATE watchlist SET updated_at = ? WHERE watchlist_id = ?", (_now(), watchlist_id)
            )
        return self.get(watchlist_id)

    def reorder(self, watchlist_id: str, security_ids: Sequence[str]) -> dict[str, Any]:
        current = self.get(watchlist_id)
        known = [item["security_id"] for item in current["items"]]
        if sorted(known) != sorted(security_ids):
            raise ValidationError(
                "reorder must list exactly the watchlist's current securities",
                expected=sorted(known),
                received=sorted(security_ids),
            )
        with self.db.transaction():
            for position, security_id in enumerate(security_ids):
                self.db.execute(
                    "UPDATE watchlist_item SET position = ? WHERE watchlist_id = ? AND security_id = ?",
                    (position, watchlist_id, security_id),
                )
            self.db.execute(
                "UPDATE watchlist SET updated_at = ? WHERE watchlist_id = ?", (_now(), watchlist_id)
            )
        return self.get(watchlist_id)

    def _insert_item(
        self, watchlist_id: str, security_id: str, position: int, *, ignore_duplicate: bool = False
    ) -> None:
        if not isinstance(security_id, str) or not security_id.startswith("SEC-"):
            raise ValidationError("security_id must be a stable Atlas security id", security_id=security_id)
        if self.db.query_one("SELECT 1 FROM security WHERE security_id = ?", (security_id,)) is None:
            raise ValidationError("unknown security", security_id=security_id)
        if ignore_duplicate:
            self.db.execute(
                "INSERT OR IGNORE INTO watchlist_item (watchlist_id, security_id, position, added_at) "
                "VALUES (?,?,?,?)",
                (watchlist_id, security_id, position, _now()),
            )
        else:
            self.db.execute(
                "INSERT INTO watchlist_item (watchlist_id, security_id, position, added_at) VALUES (?,?,?,?)",
                (watchlist_id, security_id, position, _now()),
            )

    def _hydrate(self, row: Any) -> dict[str, Any]:
        items = self.db.query(
            "SELECT wi.security_id, wi.position, wi.added_at, s.class_designation, s.security_type, "
            "s.issuer_id FROM watchlist_item wi JOIN security s ON s.security_id = wi.security_id "
            "WHERE wi.watchlist_id = ? ORDER BY wi.position, wi.security_id",
            (row["watchlist_id"],),
        )
        hydrated: list[dict[str, Any]] = []
        for item in items:
            ticker = self.db.query_one(
                "SELECT ta.ticker, l.mic FROM ticker_assignment ta "
                "JOIN listing l ON l.listing_id = ta.listing_id "
                "WHERE l.security_id = ? ORDER BY ta.valid_from DESC, ta.ticker LIMIT 1",
                (item["security_id"],),
            )
            issuer = self.db.query_one(
                "SELECT legal_name FROM issuer WHERE issuer_id = ?", (item["issuer_id"],)
            )
            hydrated.append(
                {
                    "security_id": item["security_id"],
                    "position": item["position"],
                    "added_at": item["added_at"],
                    "ticker": ticker["ticker"] if ticker else None,
                    "mic": ticker["mic"] if ticker else None,
                    "legal_name": issuer["legal_name"] if issuer else None,
                    "class_designation": item["class_designation"],
                    "security_type": item["security_type"],
                    "issuer_id": item["issuer_id"],
                }
            )
        return {
            "watchlist_id": row["watchlist_id"],
            "name": row["name"],
            "notes": row["notes"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "items": hydrated,
        }

    @staticmethod
    def _name(name: str) -> str:
        if not isinstance(name, str) or not name.strip():
            raise ValidationError("watchlist name is required")
        cleaned = name.strip()
        if len(cleaned) > 80:
            raise ValidationError("watchlist name must be at most 80 characters")
        return cleaned


class WorkspaceStore:
    def __init__(self, db: Database, *, owner_id: str = OWNER_LOCAL) -> None:
        self.db = db
        self.owner_id = owner_id

    def list(self) -> list[dict[str, Any]]:
        rows = self.db.query(
            "SELECT * FROM workspace WHERE owner_id = ? ORDER BY updated_at DESC, name",
            (self.owner_id,),
        )
        return [self._hydrate(row) for row in rows]

    def get(self, workspace_id: str) -> dict[str, Any]:
        row = self.db.query_one(
            "SELECT * FROM workspace WHERE workspace_id = ? AND owner_id = ?",
            (workspace_id, self.owner_id),
        )
        if row is None:
            raise ValidationError("unknown workspace", workspace_id=workspace_id)
        return self._hydrate(row)

    def create(self, payload: Any) -> dict[str, Any]:
        document = validate_workspace(payload)
        workspace_id = _new_id("WS")
        now = _now()
        with self.db.transaction():
            duplicate = self.db.query_one(
                "SELECT 1 FROM workspace WHERE owner_id = ? AND name = ?",
                (self.owner_id, document["name"]),
            )
            if duplicate is not None:
                raise StorageError("a workspace with that name already exists", name=document["name"])
            self.db.execute(
                "INSERT INTO workspace (workspace_id, owner_id, name, mode, columns, schema_version, "
                "config_json, fingerprint, created_at, updated_at) VALUES (?,?,?,?,?,?,?,?,?,?)",
                (
                    workspace_id,
                    self.owner_id,
                    document["name"],
                    document["mode"],
                    document["columns"],
                    document["schema"],
                    json.dumps(document["panels"], sort_keys=True),
                    fingerprint(document),
                    now,
                    now,
                ),
            )
        return self.get(workspace_id)

    def update(self, workspace_id: str, payload: Any) -> dict[str, Any]:
        self.get(workspace_id)
        document = validate_workspace(payload, workspace_id=workspace_id)
        with self.db.transaction():
            duplicate = self.db.query_one(
                "SELECT 1 FROM workspace WHERE owner_id = ? AND name = ? AND workspace_id != ?",
                (self.owner_id, document["name"], workspace_id),
            )
            if duplicate is not None:
                raise StorageError("a workspace with that name already exists", name=document["name"])
            self.db.execute(
                "UPDATE workspace SET name = ?, mode = ?, columns = ?, config_json = ?, fingerprint = ?, "
                "updated_at = ? WHERE workspace_id = ?",
                (
                    document["name"],
                    document["mode"],
                    document["columns"],
                    json.dumps(document["panels"], sort_keys=True),
                    fingerprint(document),
                    _now(),
                    workspace_id,
                ),
            )
        return self.get(workspace_id)

    def delete(self, workspace_id: str) -> None:
        self.get(workspace_id)
        with self.db.transaction():
            self.db.execute("DELETE FROM workspace WHERE workspace_id = ?", (workspace_id,))

    def _hydrate(self, row: Any) -> dict[str, Any]:
        try:
            panels = json.loads(row["config_json"])
        except json.JSONDecodeError:  # pragma: no cover - defensive
            raise StorageError("stored workspace is not valid JSON", workspace_id=row["workspace_id"])
        document = {
            "name": row["name"],
            "mode": row["mode"],
            "columns": int(row["columns"]),
            "panels": panels,
            "schema": row["schema_version"],
        }
        return {
            "workspace_id": row["workspace_id"],
            "name": row["name"],
            "mode": row["mode"],
            "schema": row["schema_version"],
            "fingerprint": row["fingerprint"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
            "document": document,
        }


class SettingsStore:
    ALLOWED = {"theme", "mode", "default_workspace", "chart_view", "density"}

    def __init__(self, db: Database, *, owner_id: str = OWNER_LOCAL) -> None:
        self.db = db
        self.owner_id = owner_id

    def all(self) -> dict[str, Any]:
        rows = self.db.query(
            "SELECT key, value FROM app_setting WHERE owner_id = ? ORDER BY key", (self.owner_id,)
        )
        result: dict[str, Any] = {}
        for row in rows:
            try:
                result[row["key"]] = json.loads(row["value"])
            except json.JSONDecodeError:
                result[row["key"]] = row["value"]
        return result

    def set(self, key: str, value: Any) -> dict[str, Any]:
        if key not in self.ALLOWED:
            raise ValidationError("unknown setting", key=key, supported=sorted(self.ALLOWED))
        if key == "theme" and value not in {"dark", "light"}:
            raise ValidationError("theme must be dark or light", value=value)
        if key == "mode" and value not in {"standard", "advanced"}:
            raise ValidationError("mode must be standard or advanced", value=value)
        if key == "density" and value not in {"comfortable", "compact"}:
            raise ValidationError("density must be comfortable or compact", value=value)
        if key == "chart_view" and value not in {"raw", "split", "total_return"}:
            raise ValidationError("chart_view is invalid", value=value)
        self.db.execute(
            "INSERT INTO app_setting (owner_id, key, value, updated_at) VALUES (?,?,?,?) "
            "ON CONFLICT(owner_id, key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
            (self.owner_id, key, json.dumps(value), _now()),
        )
        return self.all()
