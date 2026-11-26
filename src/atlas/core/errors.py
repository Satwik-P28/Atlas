"""Typed errors used across Atlas.

Every failure the platform can raise deliberately is a subclass of
:class:`AtlasError` carrying a stable machine-readable ``code`` and a ``context``
mapping. Callers (CLI, future API) can serialize them without string parsing.
"""

from __future__ import annotations

from typing import Any


class AtlasError(Exception):
    """Base class for deliberate Atlas failures."""

    code = "atlas_error"
    retryable = False

    def __init__(self, message: str, **context: Any) -> None:
        super().__init__(message)
        self.message = message
        self.context: dict[str, Any] = context

    def to_dict(self) -> dict[str, Any]:
        return {"code": self.code, "message": self.message, "context": self.context}

    def __str__(self) -> str:  # pragma: no cover - formatting only
        if not self.context:
            return self.message
        rendered = ", ".join(f"{k}={v!r}" for k, v in sorted(self.context.items()))
        return f"{self.message} ({rendered})"


# --------------------------------------------------------------------------- #
# Validation / domain contract violations
# --------------------------------------------------------------------------- #
class ValidationError(AtlasError):
    """Input or stored data violates a declared invariant."""

    code = "validation_error"


class UnitMismatchError(ValidationError):
    """Two values with economically incompatible units were combined."""

    code = "unit_mismatch"


class CurrencyMismatchError(UnitMismatchError):
    """Monetary values in different currencies were combined without conversion."""

    code = "currency_mismatch"


class TemporalError(AtlasError):
    """Time semantics were misused (unknown availability, invalid interval, ...)."""

    code = "temporal_error"


class LookAheadError(TemporalError):
    """A query would have returned information not available under its time semantics."""

    code = "look_ahead"


class ParseError(AtlasError):
    """A source payload could not be interpreted."""

    code = "parse_error"


# --------------------------------------------------------------------------- #
# Storage
# --------------------------------------------------------------------------- #
class StorageError(AtlasError):
    code = "storage_error"


class MigrationError(StorageError):
    code = "migration_error"


class IntegrityViolation(StorageError):
    """A dataset integrity check failed."""

    code = "integrity_violation"

    def __init__(self, message: str, issues: list[Any] | None = None, **context: Any) -> None:
        super().__init__(message, **context)
        self.issues = issues or []


# --------------------------------------------------------------------------- #
# Providers (connectors)
# --------------------------------------------------------------------------- #
class ProviderError(AtlasError):
    code = "provider_error"


class ProviderRateLimited(ProviderError):
    code = "provider_rate_limited"
    retryable = True


class ProviderUnavailable(ProviderError):
    code = "provider_unavailable"
    retryable = True


class ProviderPayloadError(ProviderError):
    code = "provider_payload_error"


class SecPolicyError(ProviderError):
    """SEC fair-access policy requirement not satisfied (e.g. missing contact UA)."""

    code = "sec_policy_error"


# --------------------------------------------------------------------------- #
# Entity resolution
# --------------------------------------------------------------------------- #
class ResolutionError(AtlasError):
    code = "resolution_error"


class AmbiguousResolution(ResolutionError):
    """More than one security matches and Atlas refuses to guess."""

    code = "ambiguous_resolution"

    def __init__(self, message: str, candidates: list[Any] | None = None, **context: Any) -> None:
        super().__init__(message, **context)
        self.candidates = candidates or []


class UnknownEntity(ResolutionError):
    code = "unknown_entity"


# --------------------------------------------------------------------------- #
# Feature boundaries
# --------------------------------------------------------------------------- #
class NotSupportedError(AtlasError):
    """The requested capability is deliberately out of Phase 1 scope."""

    code = "not_supported"


class UnsupportedActionError(NotSupportedError):
    """Corporate-action type is represented in the schema but not computed on."""

    code = "unsupported_action"


class MissingDataError(AtlasError):
    """Data required for the operation is absent (never silently substituted)."""

    code = "missing_data"


class ConfigError(AtlasError):
    code = "config_error"
