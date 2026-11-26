"""Inventory every SQL string that is built by interpolation, with its interpolated parts.

SQL values are always bound as parameters. The remaining risk is *structure*: a table name, a
column name, an ORDER BY or a placeholder list spliced into the statement text. This script
walks the source, finds every f-string that contains a SQL keyword, and reports each
interpolated expression so a reviewer can decide whether it can carry user input. It never
executes anything.

    python scripts/audit_sql_interpolation.py --out docs/SECURITY_SQL_INTERPOLATION.json
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SQL_START = re.compile(r"^\s*(SELECT|INSERT|UPDATE|DELETE|WITH|PRAGMA|CREATE|ALTER|DROP)\b", re.IGNORECASE)


def _sql_literal(node: ast.JoinedStr) -> str:
    parts = []
    for value in node.values:
        if isinstance(value, ast.Constant):
            parts.append(str(value.value))
    return "".join(parts)


def _expression(node: ast.AST) -> str:
    try:
        return ast.unparse(node)
    except Exception:  # pragma: no cover - unparse is available on 3.9+
        return ast.dump(node)


def scan(path: Path) -> list[dict]:
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):  # pragma: no cover - sources parse
        return []
    found: list[dict] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        text = _sql_literal(node)
        if not SQL_START.search(text):
            continue
        expressions = [_expression(value.value) for value in node.values
                       if isinstance(value, ast.FormattedValue)]
        found.append({
            "file": str(path.relative_to(ROOT)),
            "line": node.lineno,
            "sql": " ".join(text.split())[:220],
            "interpolated": expressions,
        })
    return found


def classify(site: dict) -> str:
    """Classify by what is spliced in, not by whether the code looks careful."""
    joined = " ".join(site["interpolated"])
    if all(re.fullmatch(r"(marks|placeholders|qs|\",\".join\(\"?\" for _ in \w+\))", item.strip())
           for item in site["interpolated"]) or "for _ in" in joined:
        return "placeholders_only"
    if re.search(r"\bwhere\b", site["sql"].lower()) and not site["interpolated"]:
        return "static"
    if any(token in joined for token in ("order", "columns", "column", "table", "limit", "offset")):
        return "structure_named"
    return "review"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path,
                        default=ROOT / "docs" / "SECURITY_SQL_INTERPOLATION.json")
    arguments = parser.parse_args(argv)
    sites: list[dict] = []
    for path in sorted((ROOT / "src" / "atlas").rglob("*.py")):
        sites.extend(scan(path))
    for site in sites:
        site["classification"] = classify(site)
    summary: dict[str, int] = {}
    for site in sites:
        summary[site["classification"]] = summary.get(site["classification"], 0) + 1
    report = {"schema": "atlas.security.sql_interpolation.v1", "total": len(sites),
              "summary": summary, "sites": sites}
    arguments.out.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    print(f"{len(sites)} interpolated SQL sites -> {arguments.out}")
    for key, count in sorted(summary.items()):
        print(f"  {key}: {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
