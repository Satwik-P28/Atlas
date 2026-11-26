"""A citation must not repeat a column label the parser cannot vouch for.

Real filings put currency symbols in their own table columns, so a flattened header can read
`2026 |  | 2025` while the value under it belongs to 2026. The resolver's period is the
authority; the parsed label is reported as ambiguous when the two disagree.
"""

from __future__ import annotations

import pytest

pytest.importorskip("fastapi", reason="the terminal API requires the terminal extra")

from atlas.terminal.answers_api import classify_citation  # noqa: E402


@pytest.mark.parametrize(
    ("column_label", "period", "agrees", "quality"),
    [
        ("2026", "2026", True, "exact"),
        ("Years ended September 26, 2026", "2026", True, "exact"),
        ("2025", "2026", False, "ambiguous_column_label"),
        ("FY2025", "2026", False, "ambiguous_column_label"),
        ("Current period", "2026", None, "unchecked"),
        (None, "2026", None, "unchecked"),
    ],
)
def test_citation_quality(column_label, period, agrees, quality) -> None:
    assert classify_citation(column_label, period) == (agrees, quality)
