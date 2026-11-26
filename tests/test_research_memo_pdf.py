"""The PDF renderer: structure, pagination, disclosures and byte-level determinism.

These are contract tests over a hand-built memo, so they exercise the layout engine without
a database: the memo object is the same shape the service produces.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any

import pytest

from atlas.research.memo import EXPORT_FORMATS, verify_export
from atlas.research.pdf import PAGE_HEIGHT, PAGE_WIDTH, render_pdf, wrap


def _claim(index: int, *, outcome: str = "verified") -> dict[str, Any]:
    return {
        "claim_id": f"CLM-{index:016x}",
        "claim_type": "observed_fact",
        "statement": f"Revenue was {1000 + index} USD for the period.",
        "evidence_ids": [f"EVD-{index}"],
        "verification": {"outcome": outcome},
    }


def _memo(count: int = 4, *, mode: str = "public_available") -> dict[str, Any]:
    claims = [_claim(index) for index in range(count)]
    claims.append(_claim(999, outcome="missing_evidence"))
    return {
        "schema": "atlas.research_memo.v1",
        "memo_version": "1.0.0",
        "memo_id": "RMO-0123456789abcdef",
        "content_hash": "a" * 64,
        "cutoff": "2024-06-30T00:00:00Z",
        "mode": mode,
        "objective": "Establish what the stored statements imply for value.",
        "issuer": {"legal_name": "Example Industries", "issuer_id": "ISS-1",
                   "cik": "0000000001", "ticker": "EXM"},
        "sections": [
            {"id": "identity", "title": "Report identity", "claim_ids": [], "items": [], "notes": []},
            {"id": "financial_summary", "title": "Financial summary",
             "claim_ids": [claim["claim_id"] for claim in claims[:-1]],
             "items": [], "notes": []},
            {"id": "scenarios", "title": "Scenario results",
             "claim_ids": [], "notes": [],
             "items": [{"label": "base", "value": 71.35}, {"label": "bull", "value": 104.14},
                       {"label": "bear", "value": 49.65}]},
            {"id": "numerical_validation", "title": "Numerical validation", "claim_ids": [],
             "items": [{"label": "Value per share", "value": "pass"}],
             "notes": ["Verdict supported"]},
        ],
        "claims": claims,
        "citations": {"evidence": [], "model": [], "market_observation": None},
        "manifest": {"evidence_dependencies": ["EVD-0"], "observation_pins": [],
                     "model_fingerprints": ["fp-1"]},
        "integrity": {"dimensions": {"evidence": {"outcome": "complete", "detail": "ok"}}},
        "rights": {"redistributable": True, "blocked_sources": [],
                   "note": "All cited sources permit redistribution."},
    }


def _streams(pdf: bytes) -> list[bytes]:
    return re.findall(rb"stream\n(.*?)endstream", pdf, re.DOTALL)


def _assert_offsets_point_at_objects(pdf: bytes) -> None:
    marker = pdf.rindex(b"startxref")
    start = int(pdf[marker + 9:].split()[0])
    assert pdf[start:start + 4] == b"xref"
    declared = int(pdf[start + 5:].split()[0])
    lines = pdf[start:].split(b"\n")
    for index in range(1, declared):
        offset = int(lines[index + 1].split()[0])
        header = pdf[offset:offset + 64].split(b"\n")[0]
        assert header.split()[1:3] == [b"0", b"obj"]


def test_pdf_structure_and_offsets_are_valid():
    pdf = render_pdf(_memo())
    assert pdf.startswith(b"%PDF-1.4")
    assert pdf.rstrip().endswith(b"%%EOF")
    _assert_offsets_point_at_objects(pdf)
    # MediaBox must be the page size the layout assumed, or every coordinate is off-page.
    assert f"/MediaBox [0 0 {PAGE_WIDTH:.2f} {PAGE_HEIGHT:.2f}]".encode() in pdf


def test_footer_numbers_every_page():
    pdf = render_pdf(_memo(count=40))
    streams = _streams(pdf)
    assert len(streams) > 1
    for index, stream in enumerate(streams, start=1):
        assert f"page {index} of {len(streams)}".encode() in stream


def test_a_table_that_crosses_a_page_repeats_its_header():
    memo = _memo(count=40)
    # No sections, so the only place a claim id can appear is the claim register.
    memo["sections"] = []
    pdf = render_pdf(memo)
    claim_pages = [stream for stream in _streams(pdf) if b"(CLM-" in stream]
    assert len(claim_pages) > 1
    for stream in claim_pages:
        assert b"(Primary evidence)" in stream


def test_render_is_byte_stable():
    assert render_pdf(_memo()) == render_pdf(_memo())


def test_pdf_carries_the_disclosures_and_the_availability_warning():
    pdf = render_pdf(_memo(mode="estimated_availability"))
    text = b" ".join(_streams(pdf))
    assert b"not an investment recommendation" in text.replace(b"  ", b" ")
    assert b"modelled publication-time bound" in text
    assert b"missing_evidence" in text  # a failed claim is reported, never dropped


def test_pdf_export_hash_is_checked_over_the_bytes():
    content = render_pdf(_memo())
    export = {"content": content,
              "manifest": {"content_hash": hashlib.sha256(content).hexdigest()}}
    assert verify_export(export)["content_hash_matches"] is True
    export["content"] = content + b"tampered"
    assert verify_export(export)["content_hash_matches"] is False


def test_pdf_is_an_export_format():
    assert "pdf" in EXPORT_FORMATS


@pytest.mark.parametrize("word", ["A" * 300, "supercalifragilisticexpialidocious" * 4])
def test_long_words_are_split_rather_than_overflowing(word):
    lines = wrap(word, size=10.0, width=200.0)
    assert len(lines) > 1
    assert "".join(lines).replace(" ", "") == word
    limit = int(200.0 / (10.0 * 0.52))
    assert all(len(line) <= limit for line in lines)
