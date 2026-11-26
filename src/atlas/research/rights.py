"""Data-rights classification for market fixtures and imported observations.

Two different questions are routinely conflated:

**Copyright licence** — what the copyright holder permits a licensee to do with the
expression (Apache-2.0, CC0, a vendor entitlement, nothing at all).

**Redistribution permission** — whether a recipient of an Atlas artefact may receive the
bytes. A permissive copyright licence is one way to obtain that permission, never the
other way round: project authorship under Apache-2.0 does not dedicate the work to the
public domain, and "we wrote it" is not a synonym for "public domain".

The classification below keeps the two separate and fails closed. An unclassified or
unknown grant is never treated as redistributable, and only an explicit public-domain
dedication or an explicit redistribution grant may enter a portable package.
"""

from __future__ import annotations

from typing import Any, Mapping

#: Redistribution classes. These describe permission to redistribute the bytes.
PUBLIC_DOMAIN = "public_domain"
PROJECT_AUTHORED = "project_authored"
PERMITTED = "permitted"
USER_RESPONSIBILITY = "user_responsibility"
RESTRICTED = "restricted"
PRIVATE = "private"
UNKNOWN = "unknown"

#: Classes the importer accepts. ``unknown`` is deliberately absent: an unknown grant is
#: rejected outright rather than stored and hoped about.
INGESTIBLE = {
    PUBLIC_DOMAIN, PROJECT_AUTHORED, PERMITTED, USER_RESPONSIBILITY, RESTRICTED, PRIVATE,
}

#: Classes whose bytes may travel inside an exported research package or fixture set.
EXPORTABLE = {PUBLIC_DOMAIN, PROJECT_AUTHORED, PERMITTED}

#: Classes that are locally usable but never redistributable.
LOCAL_ONLY = {USER_RESPONSIBILITY, RESTRICTED, PRIVATE}

LABELS = {
    PUBLIC_DOMAIN: "Public domain (an explicit dedication, not merely a permissive licence)",
    PROJECT_AUTHORED: "Project-authored original content under a permissive licence",
    PERMITTED: "Explicit redistribution permission granted by the rights holder",
    USER_RESPONSIBILITY: "User-supplied; the operator is responsible for redistribution",
    RESTRICTED: "Restricted vendor data; local research only",
    PRIVATE: "Private data; never redistributable",
    UNKNOWN: "Unknown rights; treated as non-redistributable",
}

#: Licence strings that are commonly mistaken for a public-domain dedication.
_PERMISSIVE_COPYRIGHT_LICENCES = ("apache", "mit", "bsd", "mpl", "cc by", "cc-by")


class RightsError(ValueError):
    """A rights declaration is missing, contradictory or unknown."""


def classify(
    redistribution: str | None,
    *,
    copyright_licence: str | None = None,
    copyright_holder: str | None = None,
) -> dict[str, Any]:
    """Classify one source's rights without inferring a grant that was not made.

    Returns a decision record rather than raising: callers that must fail closed (imports,
    package export, fixture verification) check ``trusted`` and ``export_allowed``.
    """
    raw = str(redistribution or "").strip().lower()
    licence = str(copyright_licence or "").strip()
    holder = str(copyright_holder or "").strip()
    warnings: list[str] = []

    if not raw:
        raw = UNKNOWN
        warnings.append("no redistribution class was declared")
    if raw not in INGESTIBLE and raw != UNKNOWN:
        warnings.append(f"unrecognised redistribution class {raw!r} is treated as unknown")
        raw = UNKNOWN
    if raw == UNKNOWN:
        warnings.append("unknown rights fail closed: the data is not trusted or exportable")
    if raw == PROJECT_AUTHORED and not licence:
        warnings.append("project-authored content must declare its copyright licence")
        raw = UNKNOWN
    if raw == PUBLIC_DOMAIN and licence and any(
        token in licence.lower() for token in _PERMISSIVE_COPYRIGHT_LICENCES
    ) and "public domain" not in licence.lower() and "cc0" not in licence.lower():
        warnings.append(
            "a permissive copyright licence is not a public-domain dedication; "
            "declare project_authored or permitted instead"
        )
        raw = PROJECT_AUTHORED
    if raw == PROJECT_AUTHORED and holder and "atlas" not in holder.lower():
        warnings.append(
            f"project-authored content names {holder!r} as holder; verify the project owns it"
        )
    trusted = raw in INGESTIBLE
    return {
        "schema": "atlas.data_rights.classification.v1",
        "redistribution": raw,
        "copyright_licence": licence or None,
        "copyright_holder": holder or None,
        "trusted": trusted,
        "export_allowed": raw in EXPORTABLE,
        "local_use_only": raw in LOCAL_ONLY,
        "label": LABELS[raw],
        "warnings": warnings,
        "policy": (
            "Redistribution permission is never inferred from copyright licence, project "
            "authorship or possession. Public-domain status requires an explicit dedication."
        ),
    }


def require_exportable(classification: Mapping[str, Any], *, what: str) -> dict[str, Any]:
    """Fail closed unless the classified rights permit redistribution."""
    if not classification.get("trusted"):
        raise RightsError(
            f"{what}: rights are unknown or incomplete; Atlas does not redistribute data "
            "whose grant it cannot establish"
        )
    if not classification.get("export_allowed"):
        raise RightsError(
            f"{what}: redistribution class {classification.get('redistribution')!r} does not "
            "permit inclusion in an exported artefact"
        )
    return dict(classification)
