"""CLI-facing independent certificate verifier.

Deliberately avoids importing ``FinancialAnswerEngine``, ``ConceptResolver``, or the FEC
execution runtime. Arithmetic comes only from ``financial_verification``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

from .certificate import verify_certificate_payload


def load_certificate(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def verify_certificate_file(
    path: str | Path,
    *,
    trusted_sources: Mapping[str, Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    payload = load_certificate(path)
    result = verify_certificate_payload(payload, trusted_sources=trusted_sources)
    result["path"] = str(path)
    return result


__all__ = ["load_certificate", "verify_certificate_file"]
