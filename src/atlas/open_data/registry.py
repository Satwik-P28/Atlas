"""Machine-readable dataset registry with strict validation.

The registry is the single source of truth for what may be acquired, what licence
applies and whether the result may be redistributed. Validation is deliberately
pedantic: an entry that cannot answer every required question is an error, not a
warning, because a missing licence must never be interpreted as permission.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Iterable, Mapping

from .rights import RightsClass, VALID_CLASSES, classify, evaluate, review_is_stale

REGISTRY_VERSION = 1
DEFAULT_REGISTRY = Path(__file__).resolve().parents[3] / "data/open_data/registry.json"

_ID = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z0-9][a-z0-9_-]*)+$")

REQUIRED_FIELDS: dict[str, type | tuple[type, ...]] = {
    "id": str,
    "provider": str,
    "title": str,
    "description": str,
    "official_source_url": str,
    "download_endpoint": (str, type(None)),
    "license_name": str,
    "license_url": (str, type(None)),
    "rights_class": str,
    "rights_verified_at": (str, type(None)),
    "rights_evidence": str,
    "commercial_use": bool,
    "redistribution": bool,
    "modification": bool,
    "attribution_required": bool,
    "attribution_text": str,
    "third_party_exclusions": list,
    "geographic_coverage": str,
    "historical_coverage": dict,
    "update_frequency": str,
    "auth_required": bool,
    "expected_size_bytes": (int, type(None)),
    "schema_version": str,
    "ingestion_status": str,
    "adapter": str,
    "formats": list,
}

#: Values used by the dashboard. They are intentionally separate counters.
INGESTION_STATUSES = {
    "discovered",       # catalogued, endpoint not yet verified end-to-end
    "verified",         # endpoint and licence reviewed
    "implemented",      # an adapter exists
    "acquired",         # at least one snapshot is held
    "validated",        # the latest snapshot passed structural validation
    "integrated",       # observations are queryable through Atlas
    "published",        # a redistributable package has been produced
    "blocked",          # provider or environment prevents acquisition
}

PUBLIC_JOB_CLASSES = {
    RightsClass.PUBLIC_DOMAIN.value,
    RightsClass.PERMISSIVE.value,
    RightsClass.REDISTRIBUTABLE_CONDITIONS.value,
}


class RegistryError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class Dataset:
    raw: Mapping[str, Any]

    @property
    def id(self) -> str:
        return str(self.raw["id"])

    @property
    def provider(self) -> str:
        return str(self.raw["provider"])

    @property
    def rights_class(self) -> RightsClass:
        return classify(str(self.raw["rights_class"]))

    @property
    def download_endpoint(self) -> str | None:
        value = self.raw.get("download_endpoint")
        return str(value) if value else None

    def __getitem__(self, key: str) -> Any:
        return self.raw[key]

    def get(self, key: str, default: Any = None) -> Any:
        return self.raw.get(key, default)

    def to_dict(self) -> dict[str, Any]:
        return dict(self.raw)


class Registry:
    def __init__(self, payload: Mapping[str, Any], *, source: Path | None = None) -> None:
        self.payload = payload
        self.source = source
        self._datasets = {entry["id"]: Dataset(entry) for entry in payload["datasets"]}
        self._order = [entry["id"] for entry in payload["datasets"]]

    @classmethod
    def load(cls, path: str | Path = DEFAULT_REGISTRY) -> "Registry":
        target = Path(path)
        payload = json.loads(target.read_text(encoding="utf-8"))
        errors = validate_payload(payload)
        if errors:
            raise RegistryError("invalid registry:\n" + "\n".join(f"- {error}" for error in errors))
        return cls(payload, source=target)

    def __len__(self) -> int:
        return len(self._datasets)

    def __iter__(self):
        for key in self._order:
            yield self._datasets[key]

    def ids(self) -> list[str]:
        return list(self._order)

    def get(self, dataset_id: str) -> Dataset:
        try:
            return self._datasets[dataset_id]
        except KeyError as exc:
            raise KeyError(f"dataset {dataset_id!r} is not in the approved registry") from exc

    def select(self, ids: Iterable[str] | None = None, *, provider: str | None = None,
               rights: Iterable[str] | None = None, status: str | None = None) -> list[Dataset]:
        wanted = set(ids) if ids else None
        rights_set = {str(item) for item in rights} if rights else None
        result = []
        for dataset in self:
            if wanted is not None and dataset.id not in wanted:
                continue
            if provider and provider.lower() not in dataset.provider.lower() and provider.lower() not in dataset.id:
                continue
            if rights_set and dataset.rights_class.value not in rights_set:
                continue
            if status and dataset.get("ingestion_status") != status:
                continue
            result.append(dataset)
        return result

    def search(self, text: str) -> list[Dataset]:
        needle = text.strip().lower()
        if not needle:
            return list(self)
        fields = ("id", "provider", "title", "description", "geographic_coverage", "license_name")
        return [d for d in self if any(needle in str(d.get(f, "")).lower() for f in fields)]

    def public_job_targets(self) -> list[Dataset]:
        """Datasets an automated public-distribution job may touch."""
        return [
            d for d in self
            if d.rights_class.value in PUBLIC_JOB_CLASSES
            and d.get("redistribution") is True
            and d.get("commercial_use") is True
            and not review_is_stale(str(d.get("rights_verified_at") or ""))
        ]


def validate_payload(payload: Mapping[str, Any]) -> list[str]:
    errors: list[str] = []
    if payload.get("registry_version") != REGISTRY_VERSION:
        errors.append(f"registry_version must be {REGISTRY_VERSION}")
    datasets = payload.get("datasets")
    if not isinstance(datasets, list) or not datasets:
        return errors + ["datasets must be a non-empty list"]
    seen: set[str] = set()
    for index, entry in enumerate(datasets):
        prefix = f"datasets[{index}]"
        if not isinstance(entry, dict):
            errors.append(f"{prefix}: must be an object")
            continue
        dataset_id = entry.get("id")
        if isinstance(dataset_id, str):
            prefix = dataset_id
        for field, expected in REQUIRED_FIELDS.items():
            if field not in entry:
                errors.append(f"{prefix}: missing required field {field!r}")
                continue
            value = entry[field]
            if expected is bool:
                if not isinstance(value, bool):
                    errors.append(f"{prefix}: {field} must be a boolean, got {type(value).__name__}")
            elif not isinstance(value, expected):
                errors.append(f"{prefix}: {field} has wrong type {type(value).__name__}")
        if not isinstance(dataset_id, str) or not _ID.match(dataset_id):
            errors.append(f"{prefix}: id must look like 'provider.dataset' (lowercase, dot separated)")
            continue
        if dataset_id in seen:
            errors.append(f"{prefix}: duplicate id")
            continue
        seen.add(dataset_id)

        rights_raw = entry.get("rights_class")
        if isinstance(rights_raw, str) and rights_raw not in VALID_CLASSES:
            errors.append(f"{prefix}: rights_class {rights_raw!r} is not one of {sorted(VALID_CLASSES)}")
            continue
        rights = classify(str(rights_raw)) if isinstance(rights_raw, str) and rights_raw in VALID_CLASSES else None

        # 17 USC 105 covers works prepared by federal employees. A filing archive is a
        # compilation of registrant-authored documents, so the class and the licence text
        # must agree: neither may call issuer-authored content a government work.
        if entry.get("issuer_authored") is True and rights is RightsClass.PUBLIC_DOMAIN:
            errors.append(
                f"{prefix}: issuer-authored content cannot be classified public_domain; "
                "17 USC 105 covers agency-authored works only"
            )
        if entry.get("issuer_authored") is True and "public domain" in str(
            entry.get("license_name") or ""
        ).lower():
            errors.append(
                f"{prefix}: issuer-authored content cannot carry a public-domain licence claim"
            )

        verified = entry.get("rights_verified_at")
        if verified is not None:
            try:
                date.fromisoformat(str(verified))
            except ValueError:
                errors.append(f"{prefix}: rights_verified_at must be YYYY-MM-DD")

        if rights is not None:
            if rights.may_distribute:
                if not entry.get("license_name"):
                    errors.append(f"{prefix}: redistributable class needs a license_name")
                if not entry.get("license_url"):
                    errors.append(f"{prefix}: redistributable class needs a license_url")
                if entry.get("redistribution") is not True:
                    errors.append(f"{prefix}: redistributable class must assert redistribution=true")
                if entry.get("commercial_use") is not True:
                    errors.append(f"{prefix}: redistributable class must assert commercial_use=true")
                if not entry.get("rights_verified_at"):
                    errors.append(f"{prefix}: redistributable class needs rights_verified_at")
            else:
                if entry.get("redistribution") is True and rights is RightsClass.UNVERIFIED:
                    errors.append(f"{prefix}: unverified rights cannot assert redistribution=true")
                if rights is RightsClass.RESTRICTED and entry.get("redistribution") is True:
                    errors.append(f"{prefix}: restricted rights cannot assert redistribution=true")
        if entry.get("attribution_required") is True and not str(entry.get("attribution_text") or "").strip():
            errors.append(f"{prefix}: attribution_required=true needs attribution_text")
        if entry.get("ingestion_status") not in INGESTION_STATUSES:
            errors.append(f"{prefix}: unknown ingestion_status {entry.get('ingestion_status')!r}")
        if not isinstance(entry.get("formats"), list) or not entry.get("formats"):
            errors.append(f"{prefix}: formats must be a non-empty list")
        if entry.get("download_endpoint") and not str(entry["download_endpoint"]).startswith("https://"):
            errors.append(f"{prefix}: download_endpoint must be https")
        if not str(entry.get("official_source_url") or "").startswith("https://"):
            errors.append(f"{prefix}: official_source_url must be https")
        exclusions = entry.get("third_party_exclusions")
        if isinstance(exclusions, list) and any(not isinstance(item, str) or not item.strip() for item in exclusions):
            errors.append(f"{prefix}: third_party_exclusions must be non-empty strings")
        coverage = entry.get("historical_coverage")
        if isinstance(coverage, dict):
            for key in ("start", "end"):
                if key not in coverage:
                    errors.append(f"{prefix}: historical_coverage.{key} is required (use null when unknown)")
    return errors


def audit_rights(payload: Mapping[str, Any], *, today: date | None = None) -> list[dict[str, Any]]:
    """Return one decision-oriented row per dataset, including stale reviews."""
    rows: list[dict[str, Any]] = []
    for entry in payload.get("datasets", []):
        decision = evaluate(entry, "publish", public_distribution=True, today=today)
        rows.append({
            "id": entry.get("id"),
            "provider": entry.get("provider"),
            "rights_class": entry.get("rights_class"),
            "issuer_authored": bool(entry.get("issuer_authored")),
            "license_semantics_consistent": not (
                entry.get("issuer_authored") is True and "public domain" in str(
                    entry.get("license_name") or "").lower()
            ),
            "redistribution": entry.get("redistribution"),
            "commercial_use": entry.get("commercial_use"),
            "rights_verified_at": entry.get("rights_verified_at"),
            "review_stale": review_is_stale(str(entry.get("rights_verified_at") or ""), today=today),
            "distribution_allowed": decision.allowed,
            "reason": decision.reason,
            "license_name": entry.get("license_name"),
            "license_url": entry.get("license_url"),
            "third_party_exclusions": entry.get("third_party_exclusions") or [],
        })
    return rows


def summarize(payload: Mapping[str, Any]) -> dict[str, Any]:
    datasets = payload.get("datasets", [])
    by_class: dict[str, int] = {}
    by_provider: dict[str, int] = {}
    by_status: dict[str, int] = {}
    for entry in datasets:
        key = str(entry.get("rights_class"))
        by_class[key] = by_class.get(key, 0) + 1
        provider = str(entry.get("provider"))
        by_provider[provider] = by_provider.get(provider, 0) + 1
        status = str(entry.get("ingestion_status"))
        by_status[status] = by_status.get(status, 0) + 1
    return {
        "total": len(datasets),
        "by_rights_class": dict(sorted(by_class.items())),
        "by_provider": dict(sorted(by_provider.items())),
        "by_ingestion_status": dict(sorted(by_status.items())),
        "approved_for_public_distribution": sum(
            1 for entry in datasets
            if evaluate(entry, "publish", public_distribution=True).allowed
        ),
    }
