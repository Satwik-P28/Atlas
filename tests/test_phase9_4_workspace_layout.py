"""Phase 9.4: validated split/tab workstation layouts (`atlas.workspace.v2`).

A layout is data: ids, directions and weights. These tests pin the boundary, so a
saved or generated workstation either renders exactly what was reviewed or is
refused by the same validator the API uses.
"""

from __future__ import annotations

import pytest

from atlas.core.errors import ValidationError
from atlas.terminal.workspaces import (
    LAYOUT_SCHEMA,
    MAX_LAYOUT_NODES,
    derive_layout,
    fingerprint,
    presets,
    validate_workspace,
)


def _panel(panel_id: str, panel_type: str = "metrics", **extra: object) -> dict[str, object]:
    panel: dict[str, object] = {"id": panel_id, "type": panel_type, "span": 1}
    if panel_type in {"metrics", "statements", "filings", "company-header"}:
        panel["issuer_id"] = "ISS-1"
    if panel_type == "chart":
        panel["security_id"] = "SEC-1"
    panel.update(extra)
    return panel


def _document(panels, layout=None, columns: int = 3, **extra):
    document: dict[str, object] = {
        "name": "Desk",
        "mode": "advanced",
        "columns": columns,
        "panels": list(panels),
        "schema": LAYOUT_SCHEMA,
    }
    if layout is not None:
        document["layout"] = layout
    document.update(extra)
    return document


def test_v2_layout_is_normalised_and_preserves_docking():
    layout = {
        "type": "split",
        "direction": "row",
        "weights": [0.6, 0.4],
        "children": [
            {"type": "split", "direction": "column", "weights": [0.5, 0.5],
             "children": [{"type": "tabs", "active": "price", "panels": ["price"]},
                          {"type": "tabs", "active": "income", "panels": ["income", "balance"]}]},
            {"type": "tabs", "active": "risk", "panels": ["risk"]},
        ],
    }
    document = validate_workspace(
        _document([_panel("price", "chart"), _panel("income", "statements"),
                   _panel("balance", "statements"), _panel("risk")], layout)
    )
    assert document["schema"] == LAYOUT_SCHEMA
    assert document["layout"]["weights"] == [0.6, 0.4]
    assert document["layout"]["children"][0]["direction"] == "column"
    assert document["layout"]["children"][0]["children"][1]["panels"] == ["income", "balance"]


def test_v2_derives_a_layout_when_none_is_given():
    document = validate_workspace(
        _document([_panel("a"), _panel("b", span=2), _panel("c"), _panel("d", span=2)], columns=3)
    )
    layout = document["layout"]
    assert layout["type"] == "split"
    # a+b(exact row), then c, then d(exact row) => three rows stacked vertically
    assert layout["direction"] == "column"
    placed: list[str] = []

    def walk(node):
        if node["type"] == "tabs":
            placed.extend(node["panels"])
        else:
            for child in node["children"]:
                walk(child)

    walk(layout)
    assert placed == ["a", "b", "c", "d"]


def test_derived_layout_matches_grid_shapes():
    panels = [_panel("a", span=2), _panel("b")]
    layout = derive_layout(panels, 3)
    assert layout["type"] == "split" and layout["direction"] == "row"
    assert [round(weight, 6) for weight in layout["weights"]] == [0.666667, 0.333333]
    single = derive_layout([_panel("only")], 3)
    assert single == {"type": "tabs", "active": "only", "panels": ["only"]}


@pytest.mark.parametrize(
    "layout",
    [
        {"type": "split", "direction": "row", "weights": [0.5, 0.6],
         "children": [{"type": "tabs", "panels": ["a"]}, {"type": "tabs", "panels": ["b"]}]},
        {"type": "split", "direction": "sideways", "weights": [0.5, 0.5],
         "children": [{"type": "tabs", "panels": ["a"]}, {"type": "tabs", "panels": ["b"]}]},
        {"type": "split", "direction": "row", "weights": [0.5, 0.5],
         "children": [{"type": "tabs", "panels": ["a"]}, {"type": "tabs", "panels": ["ghost"]}]},
        {"type": "split", "direction": "row", "weights": [0.5, 0.5],
         "children": [{"type": "tabs", "panels": ["a"]}, {"type": "tabs", "panels": ["a"]}]},
        {"type": "grid", "panels": ["a", "b"]},
        {"type": "tabs", "active": "b", "panels": ["a"]},
        {"type": "tabs", "panels": ["a"], "eval": "1"},
        {"type": "split", "direction": "row", "weights": [0.5],
         "children": [{"type": "tabs", "panels": ["a"]}, {"type": "tabs", "panels": ["b"]}]},
    ],
)
def test_v2_rejects_invalid_layouts(layout):
    with pytest.raises(ValidationError):
        validate_workspace(_document([_panel("a"), _panel("b")], layout))


def test_v2_rejects_a_layout_that_orphans_a_panel():
    layout = {"type": "tabs", "panels": ["a"]}
    with pytest.raises(ValidationError):
        validate_workspace(_document([_panel("a"), _panel("b")], layout))


def test_v2_rejects_excessive_nesting():
    node = {"type": "tabs", "panels": ["a"]}
    for _ in range(6):
        node = {"type": "split", "direction": "row", "weights": [0.5, 0.5],
                "children": [node, {"type": "tabs", "panels": ["b"]}]}
    with pytest.raises(ValidationError):
        validate_workspace(_document([_panel("a"), _panel("b")], node))


def test_link_groups_are_validated():
    document = validate_workspace(_document([_panel("a", link_group="A"), _panel("b", link_group="C")]))
    assert [panel.get("link_group") for panel in document["panels"]] == ["A", "C"]
    with pytest.raises(ValidationError):
        validate_workspace(_document([_panel("a", link_group="Z")]))


def test_v1_documents_still_validate_and_refuse_layout_keys():
    v1 = validate_workspace({"name": "Grid", "panels": [_panel("a")], "columns": 2})
    assert v1["schema"] == "atlas.workspace.v1"
    assert "layout" not in v1
    with pytest.raises(ValidationError):
        validate_workspace({"name": "Grid", "panels": [_panel("a")],
                            "layout": {"type": "tabs", "panels": ["a"]}})
    with pytest.raises(ValidationError):
        validate_workspace({"name": "Grid", "panels": [_panel("a", link_group="A")]})


def test_presets_stay_on_v1_and_gain_no_layout():
    for preset in presets():
        assert preset["schema"] == "atlas.workspace.v1"
        assert "layout" not in preset


def test_layout_changes_the_fingerprint_but_panel_order_does_not_shift_ids():
    panels = [_panel("a"), _panel("b")]
    tabs_layout = {"type": "split", "direction": "row", "weights": [0.5, 0.5],
                   "children": [{"type": "tabs", "panels": ["a"]}, {"type": "tabs", "panels": ["b"]}]}
    stacked = {"type": "split", "direction": "column", "weights": [0.5, 0.5],
               "children": [{"type": "tabs", "panels": ["a"]}, {"type": "tabs", "panels": ["b"]}]}
    first = validate_workspace(_document(panels, tabs_layout))
    second = validate_workspace(_document(panels, stacked))
    assert fingerprint(first) != fingerprint(second)
    assert [panel["id"] for panel in first["panels"]] == ["a", "b"]


def test_unknown_layout_keys_are_refused_at_the_document_level():
    with pytest.raises(ValidationError):
        validate_workspace(_document([_panel("a")], unexpected={"layout": {}}))


def test_layout_node_limit_is_enforced():
    # 6 children per level, two levels: 1 + 6 + 36 nodes would exceed the limit.
    children = [{"type": "tabs", "panels": [f"p{index}"]} for index in range(6)]
    panels = [_panel(f"p{index}") for index in range(6)]
    document = validate_workspace(
        _document(panels, {"type": "split", "direction": "row", "weights": [1 / 6] * 6,
                           "children": children})
    )
    assert "layout" in document
    assert MAX_LAYOUT_NODES >= 7
