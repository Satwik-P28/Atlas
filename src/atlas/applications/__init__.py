"""Portable research applications, declarative extensions and enforced data rights.

Phase 8 packages *declarations* and approved data snapshots. It never ships executable
third-party code and it never replaces the Financial-Economic Compiler or economic model
runtime. See ``docs/APPLICATION_PACKAGE_SPEC.md``.
"""

from .contracts import (
    APPLICATION_SCHEMA,
    PACKAGE_SCHEMA,
    PACK_SCHEMA,
    RUNTIME_VERSION,
    PackageIntegrityError,
    PackageValidationError,
    build_package,
    dependency_diagnostics,
    read_package,
    validate_application,
)
from .rights import DataRightsEngine, RightsViolation
from .service import ApplicationService
from .packs import DomainPackService

__all__ = [
    "APPLICATION_SCHEMA",
    "PACKAGE_SCHEMA",
    "PACK_SCHEMA",
    "RUNTIME_VERSION",
    "ApplicationService",
    "DataRightsEngine",
    "DomainPackService",
    "PackageIntegrityError",
    "PackageValidationError",
    "RightsViolation",
    "build_package",
    "dependency_diagnostics",
    "read_package",
    "validate_application",
]
