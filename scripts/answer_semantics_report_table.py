"""Print or rewrite the report's corpus table from the canonical fixture data.

``--check`` exits 1 when the report block differs from what the corpus, manifest and questions
currently describe; ``--write`` rewrites it in place. No network, no database.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from atlas.research import report_tables  # noqa: E402

ROOT = Path(__file__).resolve().parents[1]
REPORT = ROOT / "docs" / "ANSWER_SEMANTICS_EVALUATION.md"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--report", default=str(REPORT))
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args(argv)
    table = report_tables.render_corpus_table()
    path = Path(args.report)
    text = path.read_text()
    if args.write:
        path.write_text(report_tables.replace_block(text, table))
        print(f"rewrote corpus table in {path}")
        return 0
    current = report_tables.extract_block(text)
    if args.check:
        if current != table:
            print("report corpus table differs from the canonical corpus data")
            return 1
        print("report corpus table matches the canonical corpus data")
        return 0
    print(table)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
