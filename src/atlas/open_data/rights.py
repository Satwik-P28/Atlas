"""Rights classification and default-deny distribution policy.

A dataset is never assumed reusable because it is downloadable. Every acquisition
target carries a reviewed rights class and an explicit evidence date; anything that
has not been reviewed is ``unverified`` and is excluded from distributed packages and
from automated public-distribution jobs.

The six classes mirror the acquisition brief:

1. ``public_domain``             - no copyright (for example 17 USC 105 works)
2. ``permissive``                - an explicit permissive licence (CC0, CC BY, OGL)
3. ``redistributable_conditions``- redistribution allowed with documented conditions
4. ``local_use_only``            - we may analyse it locally, never redistribute it
5. ``restricted``                - contractual/vendor restrictions forbid redistribution
6. ``unverified``                - not reviewed, or the review is inconclusive

Only the first three may enter a public data package. ``local_use_only`` data may be
acquired for internal analysis, but the engine refuses to publish a snapshot whose
rights class does not permit it.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum
from typing import Any, Mapping


class RightsClass(str, Enum):
    PUBLIC_DOMAIN = "public_domain"
    PERMISSIVE = "permissive"
    REDISTRIBUTABLE_CONDITIONS = "redistributable_conditions"
    LOCAL_USE_ONLY = "local_use_only"
    RESTRICTED = "restricted"
    UNVERIFIED = "unverified"

    @property
    def may_distribute(self) -> bool:
        return self in {
            RightsClass.PUBLIC_DOMAIN,
            RightsClass.PERMISSIVE,
            RightsClass.REDISTRIBUTABLE_CONDITIONS,
        }

    @property
    def may_acquire_locally(self) -> bool:
        return self is not RightsClass.UNVERIFIED

    @property
    def may_run_in_public_job(self) -> bool:
        """Automated jobs that publish artefacts must never touch these classes."""
        return self.may_distribute

    @property
    def rank(self) -> int:
        return _ORDER.index(self)


_ORDER = [
    RightsClass.PUBLIC_DOMAIN,
    RightsClass.PERMISSIVE,
    RightsClass.REDISTRIBUTABLE_CONDITIONS,
    RightsClass.LOCAL_USE_ONLY,
    RightsClass.RESTRICTED,
    RightsClass.UNVERIFIED,
]

#: Classes that a reviewer may use. Kept explicit so a typo cannot silently pass.
VALID_CLASSES = {member.value for member in RightsClass}


class RightsViolation(PermissionError):
    """Raised whenever a distribution or acquisition action is not permitted."""

    def __init__(self, dataset_id: str, action: str, reason: str) -> None:
        super().__init__(f"{dataset_id}: cannot {action}: {reason}")
        self.dataset_id = dataset_id
        self.action = action
        self.reason = reason

    def to_dict(self) -> dict[str, str]:
        return {"dataset_id": self.dataset_id, "action": self.action, "reason": self.reason}


@dataclass(frozen=True, slots=True)
class RightsDecision:
    dataset_id: str
    action: str
    allowed: bool
    reason: str
    rights_class: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "dataset_id": self.dataset_id,
            "action": self.action,
            "allowed": self.allowed,
            "reason": self.reason,
            "rights_class": self.rights_class,
        }


def classify(value: str) -> RightsClass:
    try:
        return RightsClass(value)
    except ValueError as exc:
        raise ValueError(f"unknown rights class {value!r}; expected one of {sorted(VALID_CLASSES)}") from exc


def review_is_stale(verified_at: str, *, today: date | None = None, max_age_days: int = 365) -> bool:
    """A rights review older than a year is treated as stale for automated jobs."""
    try:
        stamped = date.fromisoformat(verified_at)
    except (TypeError, ValueError):
        return True
    return ((today or date.today()) - stamped).days > max_age_days


def evaluate(
    dataset: Mapping[str, Any],
    action: str,
    *,
    automated: bool = False,
    public_distribution: bool = False,
    today: date | None = None,
) -> RightsDecision:
    """Return an explicit, reasoned decision; fail closed on every ambiguity.

    ``action`` is one of ``acquire``, ``analyse``, ``package``, ``publish`` or
    ``mirror``. The function never guesses a licence from the provider name.
    """
    dataset_id = str(dataset.get("id") or "<unknown>")
    raw_class = dataset.get("rights_class")
    try:
        rights = classify(str(raw_class))
    except ValueError as exc:
        return RightsDecision(dataset_id, action, False, str(exc), str(raw_class))

    if action in {"acquire", "download"}:
        if not rights.may_acquire_locally:
            return RightsDecision(
                dataset_id,
                action,
                False,
                "rights class is unverified; a reviewer must record a licence before acquisition",
                rights.value,
            )
        if automated and public_distribution and not rights.may_run_in_public_job:
            return RightsDecision(
                dataset_id,
                action,
                False,
                "automated public-distribution jobs may only acquire public_domain, permissive "
                "or redistributable_conditions datasets",
                rights.value,
            )
        if automated and review_is_stale(str(dataset.get("rights_verified_at") or ""), today=today):
            return RightsDecision(
                dataset_id,
                action,
                False,
                "rights review is missing or older than 365 days; automated acquisition is blocked",
                rights.value,
            )
        return RightsDecision(dataset_id, action, True, "rights class permits local acquisition", rights.value)

    if action == "analyse":
        if rights is RightsClass.UNVERIFIED:
            return RightsDecision(dataset_id, action, False, "unverified rights: analysis not permitted", rights.value)
        return RightsDecision(dataset_id, action, True, "analysis of a locally held snapshot is permitted", rights.value)

    if action in {"package", "publish", "distribute", "mirror"}:
        if not rights.may_distribute:
            return RightsDecision(
                dataset_id,
                action,
                False,
                f"rights class {rights.value} does not permit public redistribution",
                rights.value,
            )
        if dataset.get("redistribution") is not True:
            return RightsDecision(
                dataset_id,
                action,
                False,
                "registry does not assert redistribution permission",
                rights.value,
            )
        if dataset.get("commercial_use") is not True and public_distribution:
            return RightsDecision(
                dataset_id,
                action,
                False,
                "commercial use is not confirmed for a public package",
                rights.value,
            )
        if review_is_stale(str(dataset.get("rights_verified_at") or ""), today=today):
            return RightsDecision(
                dataset_id,
                action,
                False,
                "rights review is stale; re-verify before distribution",
                rights.value,
            )
        exclusions = dataset.get("third_party_exclusions") or []
        if exclusions and not dataset.get("exclusions_cleared"):
            return RightsDecision(
                dataset_id,
                action,
                False,
                "dataset has third-party exclusions that have not been cleared for this package",
                rights.value,
            )
        return RightsDecision(
            dataset_id,
            action,
            True,
            "rights class and asserted permissions permit public distribution",
            rights.value,
        )

    return RightsDecision(dataset_id, action, False, f"unknown action {action!r}", rights.value)


def assert_allowed(dataset: Mapping[str, Any], action: str, **kwargs: Any) -> RightsDecision:
    decision = evaluate(dataset, action, **kwargs)
    if not decision.allowed:
        raise RightsViolation(str(dataset.get("id") or "<unknown>"), action, decision.reason)
    return decision
