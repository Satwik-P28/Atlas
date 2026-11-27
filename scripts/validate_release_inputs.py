#!/usr/bin/env python3
"""Validate release workflow inputs and write the plan every later step reads.

The workflow passes raw ``workflow_dispatch`` values through environment
variables into this script. Nothing else in the workflow interpolates them into
a shell, so a value that reaches a filename or an HTTP call has necessarily
passed :mod:`atlas.open_data.release` validation first.

Exit status is non-zero for any rejected input, which fails the job before a
download starts.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from atlas.open_data.registry import Registry  # noqa: E402
from atlas.open_data.release import (  # noqa: E402
    ReleaseInputError, build_plan, validate_tag,
)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default="dist/release-plan.json")
    parser.add_argument("--registry", default=None)
    args = parser.parse_args(argv)

    datasets = os.environ.get("ATLAS_RELEASE_DATASETS", "")
    tag = os.environ.get("ATLAS_RELEASE_TAG", "")
    oversized = os.environ.get("ATLAS_RELEASE_OVERSIZED", "")
    mode = os.environ.get("ATLAS_RELEASE_MODE", "draft")

    if mode not in {"draft", "public"}:
        print(f"invalid mode {mode!r}; expected draft or public", file=sys.stderr)
        return 2
    try:
        validate_tag(tag)
        registry = Registry.load(args.registry) if args.registry else Registry.load()
        plan = build_plan(datasets, tag, oversized, registry)
    except (ReleaseInputError, ValueError) as exc:
        print(f"REJECTED: {exc}", file=sys.stderr)
        return 1
    plan["mode"] = mode
    target = Path(args.out)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(plan, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "plan": str(target),
        "tag": plan["release_tag"],
        "mode": mode,
        "datasets": [item["dataset_id"] for item in plan["datasets"]],
        "oversized": [item["dataset_id"] for item in plan["oversized"]],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
