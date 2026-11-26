"""Render report tables from the canonical corpus data.

The evaluation report used to carry a hand-typed accession table. Eight of its twelve rows
drifted from ``fixtures/answer_semantics/corpus.json`` — the corpus, the manifest and the
questions still agreed, but a reader copying the published table would fetch filings that were
never evaluated. The table is therefore generated, and the generator refuses to run when the
corpus, the manifest and the question set disagree about which filing is which.

``render_corpus_table`` is the single source of the published rows; the regression test asserts
the report contains exactly its output.
"""

from __future__ import annotations

import json
from pathlib import Path

from .answer_semantics import CORPUS_PATH, MANIFEST_PATH, QUESTIONS_PATH

BEGIN = "<!-- corpus-table:begin -->"
END = "<!-- corpus-table:end -->"


class CorpusInconsistency(ValueError):
    """The corpus, manifest and questions do not describe the same frozen filings."""


def _cik(value: object) -> str:
    return str(value).lstrip("0").zfill(10)


def render_corpus_table(corpus_path: Path = CORPUS_PATH,
                        manifest_path: Path = MANIFEST_PATH,
                        questions_path: Path = QUESTIONS_PATH) -> str:
    corpus = json.loads(Path(corpus_path).read_text())
    manifest = json.loads(Path(manifest_path).read_text())
    questions = json.loads(Path(questions_path).read_text())["questions"]

    declared = {filing["accession"]: filing for filing in corpus["filings"]}
    archived = {filing["accession"]: filing for filing in manifest["filings"]}
    if set(declared) != set(archived):
        missing = sorted(set(declared) - set(archived))
        extra = sorted(set(archived) - set(declared))
        raise CorpusInconsistency(f"manifest/corpus accession mismatch: missing={missing} extra={extra}")
    for accession, filing in declared.items():
        if _cik(filing["cik"]) != _cik(archived[accession]["cik"]):
            raise CorpusInconsistency(f"CIK mismatch for {accession}")
    for question in questions:
        if question["accession"] not in declared:
            raise CorpusInconsistency(
                f"question {question['id']} cites an accession outside the corpus")

    lines = ["| key | issuer | FY | accession | layout property exercised |",
             "| --- | --- | --- | --- | --- |"]
    for filing in corpus["filings"]:
        note = filing.get("report_note") or filing["layout"]
        fiscal_year = str(filing["period_of_report"])[:4]
        lines.append(f"| {filing['key']} | {filing['issuer']} | {fiscal_year} | "
                     f"{filing['accession']} | {note} |")
    return "\n".join(lines)


def extract_block(text: str) -> str:
    if BEGIN not in text or END not in text:
        raise CorpusInconsistency("report is missing the corpus-table markers")
    body = text.split(BEGIN, 1)[1].split(END, 1)[0]
    return body.strip("\n")


def replace_block(text: str, table: str) -> str:
    if BEGIN not in text or END not in text:
        raise CorpusInconsistency("report is missing the corpus-table markers")
    head, rest = text.split(BEGIN, 1)
    _old, tail = rest.split(END, 1)
    return f"{head}{BEGIN}\n{table}\n{END}{tail}"


__all__ = ["BEGIN", "END", "CorpusInconsistency", "extract_block", "render_corpus_table",
           "replace_block"]
