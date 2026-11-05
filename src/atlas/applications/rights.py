"""Enforced source-rights decisions for ingestion, research and distribution.

Possession of bytes never implies permission to redistribute them. The policy is
deliberately conservative: only public-domain or explicitly redistribution-permitted
sources may enter a portable package. Derived analytics retain the restrictions of their
source unless a provider explicitly grants more.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..storage.db import Database
from .contracts import (
    REDISTRIBUTION_ALLOWED,
    RightsViolation,
    SOURCE_ACTIONS,
)

_RESTRICTED_ALLOWED = {"ingest", "local_storage", "analysis"}
_USER_RESPONSIBILITY_ALLOWED = {"ingest", "local_storage", "analysis"}
_LOCAL_ASSUMPTION_ALLOWED = {"ingest", "local_storage", "analysis"}


def _source_metadata(source: Any) -> dict[str, Any]:
    if isinstance(source, dict):
        return dict(source)
    return dict(source)


class DataRightsEngine:
    def __init__(self, db: Database | None = None) -> None:
        self.db = db

    @classmethod
    def decisions_for_metadata(cls, sources: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        decisions = []
        for raw in sources:
            source = _source_metadata(raw)
            source_id = str(source.get("source_id") or source.get("id") or "").strip()
            if not source_id:
                raise RightsViolation("source rights record is missing source_id")
            redistribution = str(source.get("redistribution") or "restricted").strip().lower()
            licence = source.get("license") or source.get("licence") or source.get("rights") or "unspecified"
            allowed_actions = (
                set(SOURCE_ACTIONS) if redistribution in REDISTRIBUTION_ALLOWED
                else _RESTRICTED_ALLOWED if redistribution == "restricted"
                else _USER_RESPONSIBILITY_ALLOWED if redistribution == "user_responsibility"
                else _LOCAL_ASSUMPTION_ALLOWED
            )
            actions = {}
            for action in SOURCE_ACTIONS:
                allowed = action in allowed_actions
                if allowed:
                    reason = (
                        "public-domain or explicit redistribution permission"
                        if redistribution in REDISTRIBUTION_ALLOWED
                        else "local research only; no redistribution permission"
                    )
                elif redistribution == "user_responsibility":
                    reason = "a user grant is required; the package does not contain one"
                else:
                    reason = "provider terms restrict this action"
                actions[action] = {"allowed": allowed, "reason": reason}
            packaging = actions["packaging"]["allowed"] and actions["export"]["allowed"] \
                and actions["redistribution"]["allowed"]
            decisions.append({
                "source_id": source_id,
                "name": source.get("name"),
                "license": str(licence),
                "redistribution": redistribution,
                "actions": actions,
                "packaging_allowed": packaging,
                "requires_user_grant": redistribution in {"restricted", "user_responsibility"},
                "policy_note": (
                    "Transforming or aggregating source data does not remove contractual obligations."
                ),
            })
        return decisions

    def decisions_for_sources(self, source_ids: list[str]) -> list[dict[str, Any]]:
        if self.db is None:
            raise RightsViolation("a database is required to resolve source rights")
        unique = sorted(set(source_ids))
        if not unique:
            return []
        marks = ",".join("?" for _ in unique)
        rows = self.db.query(
            f"SELECT source_id, name, kind, homepage, licence, redistribution, notes "
            f"FROM source WHERE source_id IN ({marks}) ORDER BY source_id",
            unique,
        )
        by_id = {row["source_id"]: dict(row) for row in rows}
        missing = [source_id for source_id in unique if source_id not in by_id]
        if missing:
            raise RightsViolation("source rights record is missing", source_ids=missing)
        metadata = []
        for source_id in unique:
            row = by_id[source_id]
            metadata.append({
                **row,
                "license": row.get("licence"),
            })
        return self.decisions_for_metadata(metadata)

    def packaging_allowed(self, source_ids: list[str]) -> bool:
        decisions = self.decisions_for_sources(source_ids)
        return all(item["packaging_allowed"] for item in decisions)

    def assert_packaging(self, source_ids: list[str]) -> list[dict[str, Any]]:
        decisions = self.decisions_for_sources(source_ids)
        denied = [item for item in decisions if not item["packaging_allowed"]]
        if denied:
            raise RightsViolation(
                "one or more sources do not permit packaging or redistribution",
                source_ids=[item["source_id"] for item in denied],
                decisions=denied,
            )
        return decisions

    def assert_file_rights(self, files: Iterable[dict[str, Any]],
                           decisions: list[dict[str, Any]]) -> None:
        allowed = {
            item["source_id"]: item["packaging_allowed"]
            for item in decisions if item["packaging_allowed"]
        }
        for item in files:
            if item.get("role") not in {"approved_source_snapshot", "raw_source_snapshot",
                                        "analysis_result", "scenario_result"}:
                continue
            source_ids = item.get("source_ids") or []
            if not source_ids:
                raise RightsViolation("data-bearing package file has no source identity",
                                      path=item.get("path"))
            denied = [source_id for source_id in source_ids if not allowed.get(source_id)]
            if denied:
                raise RightsViolation("data-bearing package file has restricted source bytes",
                                      path=item.get("path"), source_ids=denied)
            if item.get("rights") not in REDISTRIBUTION_ALLOWED:
                raise RightsViolation("data-bearing package file is not redistributable",
                                      path=item.get("path"), rights=item.get("rights"))


__all__ = ["DataRightsEngine", "RightsViolation"]
