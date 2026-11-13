"""Remove licensed benchmark text from committed artifacts.

The Phase 9.6 evaluation artifact embedded the FinanceBench `question` and `answer` fields, which
its own rights manifest said it did not. This script rewrites the artifact to identifiers, ranks,
flags and counts only, and records that it is a sanitized derivative. The original scores and
gates are preserved exactly; only the copied text is removed.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research.evaluation_v2 import PROHIBITED_KEYS  # noqa: E402

ARTIFACTS = [
    Path("artifacts/phase9_6_evaluation.json"),
    Path("artifacts/phase9_6_case_study.json"),
]


def strip(node):
    if isinstance(node, dict):
        return {k: strip(v) for k, v in node.items() if k not in PROHIBITED_KEYS}
    if isinstance(node, list):
        return [strip(item) for item in node]
    return node


def main() -> int:
    removed = {}
    for path in ARTIFACTS:
        payload = json.loads(path.read_text())
        before = sum(1 for _ in json.dumps(payload).split('"question"')) - 1
        cleaned = strip(payload)
        after = sum(1 for _ in json.dumps(cleaned).split('"question"')) - 1
        removed[str(path)] = before - after
        if path.name == "phase9_6_evaluation.json":
            cleaned["sanitized"] = {
                "derivative_of": "commit d8ae4f1",
                "methodology_version": "9.6.0",
                "scores_unchanged": True,
                "removed_fields": sorted(PROHIBITED_KEYS),
                "note": "licensed question and answer text removed; metrics and failed gates are "
                        "the original Phase 9.6.0 values",
            }
        path.write_text(json.dumps(cleaned, indent=2))
    print(json.dumps(removed, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
