"""Render a research memo as a self-contained PDF.

The memo already owns every number: claims, evidence identifiers, availability semantics,
assumptions, scenarios, verification outcomes and limitations. This module only lays that
object out. It never recomputes a figure, and it refuses nothing the other renderers accept,
so a screen, an HTML download and a PDF cannot disagree about the same memo.

No third-party PDF library is used. Base-14 Helvetica/Courier plus WinAnsi text is enough
for a research report and keeps the wheel free of a rendering dependency that would need a
licence review of its own. Content streams are left uncompressed so an auditor can grep the
bytes, and the output carries no timestamp or random identifier: the same memo renders to
the same bytes, which is what makes the content hash in the export manifest meaningful.
"""

from __future__ import annotations

from typing import Any, Iterable, Mapping, Sequence

PAGE_WIDTH = 595.28  # A4 portrait, points
PAGE_HEIGHT = 841.89
MARGIN = 54.0
BODY_WIDTH = PAGE_WIDTH - 2 * MARGIN
FOOTER_BASELINE = 30.0
BOTTOM_LIMIT = MARGIN + 14.0

FONT_REGULAR = "F1"
FONT_BOLD = "F2"
FONT_MONO = "F3"
FONT_ITALIC = "F4"

# Average advance width as a fraction of the font size. Deliberately generous: it is better to
# wrap a line early than to run text past the margin in a document nobody can re-flow.
ADVANCE = {FONT_REGULAR: 0.52, FONT_BOLD: 0.56, FONT_MONO: 0.60, FONT_ITALIC: 0.52}

INK = (0.10, 0.10, 0.10)
MUTED = (0.38, 0.38, 0.38)
RULE = (0.72, 0.72, 0.72)
SHADE = (0.94, 0.94, 0.94)


# --------------------------------------------------------------------------- primitives
def text_width(value: str, *, font: str = FONT_REGULAR, size: float = 10.0) -> float:
    return len(value) * size * ADVANCE[font]


def wrap(value: str, *, font: str = FONT_REGULAR, size: float = 10.0,
         width: float = BODY_WIDTH) -> list[str]:
    """Greedy word wrap, with a hard split for a word wider than the column."""
    limit = max(8, int(width / (size * ADVANCE[font])))
    lines: list[str] = []
    for paragraph in str(value).splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current = ""
        for word in words:
            while len(word) > limit:
                if current:
                    lines.append(current)
                    current = ""
                lines.append(word[:limit])
                word = word[limit:]
            candidate = f"{current} {word}".strip()
            if len(candidate) <= limit:
                current = candidate
            else:
                lines.append(current)
                current = word
        if current:
            lines.append(current)
    return lines or [""]


def _pdf_string(value: str) -> bytes:
    """WinAnsi bytes with PDF string escaping; anything unencodable becomes '?'."""
    out = bytearray()
    for char in str(value):
        try:
            raw = char.encode("cp1252")
        except UnicodeEncodeError:
            raw = b"?"
        for byte in raw:
            if byte in (0x28, 0x29, 0x5C):  # ( ) \
                out.extend(b"\\" + bytes([byte]))
            elif byte < 32 or byte > 126:
                out.extend(f"\\{byte:03o}".encode("ascii"))
            else:
                out.append(byte)
    return bytes(out)


def _colour(values: Sequence[float]) -> str:
    return " ".join(f"{component:.3f}" for component in values)


class _Canvas:
    """A page list plus the current cursor. All coordinates are PDF user space."""

    def __init__(self) -> None:
        self.pages: list[list[bytes]] = []
        self._ops: list[bytes] = []
        self.y = PAGE_HEIGHT - MARGIN

    # -- page flow -----------------------------------------------------------------
    def new_page(self) -> None:
        if self._ops:
            self.pages.append(self._ops)
        self._ops = []
        self.y = PAGE_HEIGHT - MARGIN

    def finish(self) -> None:
        """Close the last page; without this its content never reaches the file."""
        if self._ops:
            self.pages.append(self._ops)
            self._ops = []

    def space_left(self) -> float:
        return self.y - BOTTOM_LIMIT

    def ensure(self, height: float) -> None:
        if height > self.space_left():
            self.new_page()

    # -- drawing -------------------------------------------------------------------
    def text(self, value: str, *, x: float = MARGIN, size: float = 10.0,
             font: str = FONT_REGULAR, colour: Sequence[float] = INK) -> None:
        if not value:
            return
        self._ops.append(
            b"BT /" + font.encode("ascii") + f" {size:.2f} Tf ".encode("ascii")
            + _colour(colour).encode("ascii")
            + f" rg 1 0 0 1 {x:.2f} {self.y:.2f} Tm (".encode("ascii")
            + _pdf_string(value) + b") Tj ET\n"
        )

    def paragraph(self, value: str, *, size: float = 10.0, font: str = FONT_REGULAR,
                  colour: Sequence[float] = INK, x: float = MARGIN,
                  width: float = BODY_WIDTH, leading: float = 1.42,
                  indent: float = 0.0) -> None:
        for line in wrap(value, font=font, size=size, width=width - indent):
            self.ensure(size * leading)
            self.y -= size * leading
            self.text(line, x=x + indent, size=size, font=font, colour=colour)
        # Descender space: without it the next heading lands on the same baseline as the last
        # line of body text and the two overlap in the rendered page.
        self.y -= size * 0.6

    def rule(self, *, colour: Sequence[float] = RULE, width: float = 0.7,
             x: float = MARGIN, span: float = BODY_WIDTH) -> None:
        # A separator must never break the page: doing so opened the next page with a stray
        # rule and pushed the table past the row-break check, so the header never repeated.
        if self.y - 8 < BOTTOM_LIMIT:
            return
        self.y -= 3
        self._ops.append(
            f"{width:.2f} w {_colour(colour)} RG {x:.2f} {self.y:.2f} m "
            f"{x + span:.2f} {self.y:.2f} l S\n".encode("ascii")
        )
        self.y -= 3

    def filled_rect(self, *, x: float, y: float, width: float, height: float,
                    colour: Sequence[float] = SHADE) -> None:
        self._ops.append(
            f"{_colour(colour)} rg {x:.2f} {y:.2f} {width:.2f} {height:.2f} re f\n".encode("ascii")
        )

    def box(self, value: str, *, size: float = 9.5, font: str = FONT_ITALIC,
            colour: Sequence[float] = MUTED) -> None:
        lines = wrap(value, font=font, size=size, width=BODY_WIDTH - 16)
        height = len(lines) * size * 1.42 + 12
        self.ensure(height + 4)
        top = self.y
        self.filled_rect(x=MARGIN, y=top - height, width=BODY_WIDTH, height=height)
        self.y = top - 4
        for line in lines:
            self.y -= size * 1.42
            self.text(line, x=MARGIN + 8, size=size, font=font, colour=colour)
        self.y = top - height - 8

    def table(self, headers: Sequence[str], rows: Iterable[Sequence[str]], *,
              weights: Sequence[float], size: float = 8.6, mono_columns: Sequence[int] = ()) -> None:
        """A wrapped table that repeats its header when it crosses a page break."""
        columns = len(headers)
        widths = [BODY_WIDTH * weight for weight in weights]
        padding = 3.0
        line_height = size * 1.34

        def draw_header() -> None:
            self.ensure(line_height + padding * 2 + 2)
            self.filled_rect(x=MARGIN, y=self.y - line_height - padding * 2,
                             width=BODY_WIDTH, height=line_height + padding * 2)
            x = MARGIN + padding
            self.y -= line_height + padding
            for index, header in enumerate(headers):
                self.text(header, x=x, size=size, font=FONT_BOLD, colour=MUTED)
                x += widths[index]
            self.y -= padding

        draw_header()
        for row in rows:
            cells = [wrap(str(value or ""), font=FONT_MONO if index in mono_columns else FONT_REGULAR,
                          size=size, width=widths[index] - padding * 2) for index, value in
                     enumerate(list(row)[:columns])]
            height = max(len(cell) for cell in cells) * line_height + padding
            if height > self.space_left():
                self.new_page()
                draw_header()
            x = MARGIN + padding
            top = self.y
            for index, cell in enumerate(cells):
                cursor = top
                for line in cell:
                    cursor -= line_height
                    self._ops.append(
                        b"BT /" + (FONT_MONO if index in mono_columns else FONT_REGULAR).encode("ascii")
                        + f" {size:.2f} Tf ".encode("ascii") + _colour(INK).encode("ascii")
                        + f" rg 1 0 0 1 {x:.2f} {cursor:.2f} Tm (".encode("ascii")
                        + _pdf_string(line) + b") Tj ET\n"
                    )
                x += widths[index]
            self.y = top - height
            self.rule(colour=(0.88, 0.88, 0.88), width=0.4)
            self.y -= 1

    def bar_chart(self, title: str, series: Sequence[tuple[str, float]], *,
                  value_label: str = "") -> None:
        if len(series) < 2:
            return
        height = 18 + len(series) * 18 + 10
        self.ensure(height + 26)
        self.y -= 11
        self.text(title, size=9.5, font=FONT_BOLD)
        self.y -= 6
        label_width = 0.34 * BODY_WIDTH
        bar_area = BODY_WIDTH - label_width - 62
        lowest = min([0.0] + [value for _, value in series])
        highest = max([0.0] + [value for _, value in series])
        span = max(highest - lowest, 1e-9)
        zero_x = MARGIN + label_width + (bar_area * (0.0 - lowest) / span)
        for label, value in series:
            self.ensure(18)
            self.y -= 14
            self.text(label[:26], size=8.4, colour=MUTED)
            end = MARGIN + label_width + bar_area * (value - lowest) / span
            left, right = min(zero_x, end), max(zero_x, end)
            self.filled_rect(x=left, y=self.y - 1, width=max(right - left, 1.0), height=8,
                             colour=(0.30, 0.35, 0.45) if value >= 0 else (0.62, 0.33, 0.33))
            self.text(f"{value:,.2f}", x=MARGIN + label_width + bar_area + 6, size=8.4)
        self.ensure(8)
        self.y -= 2
        self.rule(colour=RULE, width=0.5)
        if value_label:
            self.paragraph(value_label, size=8.2, font=FONT_ITALIC, colour=MUTED)


# ----------------------------------------------------------------------------- report
def _outcome(claim: Mapping[str, Any]) -> str:
    return str((claim.get("verification") or {}).get("outcome"))


def _as_mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _issuer_line(issuer: Mapping[str, Any]) -> str:
    parts = [str(issuer.get("legal_name") or "")]
    if issuer.get("cik"):
        parts.append(f"CIK {issuer['cik']}")
    if issuer.get("ticker"):
        parts.append(f"ticker {issuer['ticker']}")
    return ", ".join(part for part in parts if part)


def _title_page(canvas: _Canvas, memo: Mapping[str, Any]) -> None:
    issuer = _as_mapping(memo.get("issuer"))
    canvas.y -= 6
    canvas.text("ATLAS  ·  EVIDENCE-FIRST FINANCIAL RESEARCH", size=8.6, font=FONT_BOLD, colour=MUTED)
    canvas.y -= 28
    canvas.paragraph(str(issuer.get("legal_name") or "Research memo"), size=21, font=FONT_BOLD,
                     leading=1.2)
    canvas.y -= 4
    canvas.paragraph("Research memo", size=13, font=FONT_REGULAR, colour=MUTED)
    canvas.rule(span=140, width=1.1)
    canvas.y -= 10

    mode = str(memo.get("mode") or "")
    rows = [
        ("Memo id", str(memo.get("memo_id") or "computed at save")),
        ("Memo version", str(memo.get("memo_version") or "")),
        ("Issuer", _issuer_line(issuer)),
        ("Information cutoff", f"{memo.get('cutoff') or '—'} ({mode or 'unspecified'} availability)"),
        ("Content hash", str(memo.get("content_hash") or "computed at save")),
        ("Schema", str(memo.get("schema") or "atlas.research_memo.v1")),
    ]
    canvas.table(("Field", "Value"), rows, weights=(0.26, 0.74), size=9.0,
                 mono_columns=(1,))
    canvas.y -= 12
    canvas.paragraph(str(memo.get("objective") or ""), size=10.4)
    canvas.y -= 8
    for note in (
        "Every factual and numeric claim in this report resolves to a stored evidence record "
        "or a reproducible transformation of one. No language model generated a fact.",
        "Verification proves that a claim matches its cited evidence and that the arithmetic "
        "reproduces. It does not prove that the underlying economic interpretation is the only "
        "correct one, and an internally consistent report is not an investment recommendation.",
    ):
        canvas.box(note)
    if "estimated" in mode.lower() or "modelled" in mode.lower():
        canvas.box(
            "Availability in this report is a modelled publication-time bound, not an observed "
            "public-release instant. Treat it as the earliest defensible information cutoff, "
            "never as verified historical availability."
        )
    _at_a_glance(canvas, memo)


def _at_a_glance(canvas: _Canvas, memo: Mapping[str, Any]) -> None:
    """A front-page summary built only from claims the memo already carries."""
    sections = {str(section.get("id")): section for section in memo.get("sections") or []}
    claims = {str(claim.get("claim_id")): claim for claim in memo.get("claims") or []}
    summary = sections.get("financial_summary") or {}
    statements = [str(claims[str(claim_id)].get("statement"))
                  for claim_id in summary.get("claim_ids") or [] if str(claim_id) in claims]
    series = _scenario_series(memo)
    if not statements and not series:
        return
    canvas.y -= 10
    canvas.text("At a glance", size=9.5, font=FONT_BOLD)
    canvas.y -= 2
    for statement in statements[:4]:
        canvas.paragraph(f"· {statement}", size=9.0, indent=9)
    if series:
        canvas.bar_chart("Scenario value per share", series)
    validation = sections.get("numerical_validation") or {}
    verdict = next((str(note) for note in validation.get("notes") or []
                    if str(note).lower().startswith("verdict")), "")
    if verdict:
        canvas.paragraph(f"Model audit: {verdict}.", size=8.6, font=FONT_ITALIC, colour=MUTED)


def _table_repeats_the_claims(section: Mapping[str, Any],
                              claims: Mapping[str, Mapping[str, Any]]) -> bool:
    """True when the table merely restates the claims already listed above it.

    Financial-summary items are the claim statements themselves; printing both doubled the
    length of the report without adding a single fact.
    """
    items = section.get("items") or []
    statements = [str(claims[str(claim_id)].get("statement") or "").strip()
                  for claim_id in section.get("claim_ids") or [] if str(claim_id) in claims]
    if not items or not statements:
        return False
    repeated = 0
    for item in items:
        label = str(item.get("label") or "").strip()
        if label and any(label in statement or statement in label for statement in statements):
            repeated += 1
    return repeated >= max(1, int(len(items) * 0.6))


def _section_rows(section: Mapping[str, Any]) -> list[tuple[str, str, str]]:
    rows: list[tuple[str, str, str]] = []
    for item in section.get("items") or []:
        label = str(item.get("label") or "")
        value = item.get("value")
        detail = item.get("detail") or item.get("formula") or item.get("type") \
            or item.get("outcome") or ""
        rendered = "—" if value is None or value == "" else str(value)
        if isinstance(value, bool):
            rendered = "yes" if value else "no"
        rows.append((label, rendered, str(detail)))
    return rows


def _claim_lines(canvas: _Canvas, section: Mapping[str, Any],
                 claims: Mapping[str, Mapping[str, Any]]) -> None:
    for claim_id in section.get("claim_ids") or []:
        claim = claims.get(str(claim_id))
        if not claim:
            continue
        canvas.paragraph(f"· {claim.get('statement', '')}", size=9.4, indent=10)
        evidence = claim.get("evidence_ids") or []
        tag = (f"{claim_id} · {claim.get('claim_type')} · {_outcome(claim)} · "
               f"{len(evidence)} evidence record(s)")
        canvas.paragraph(tag, size=7.8, font=FONT_MONO, colour=MUTED, indent=12)


def _scenario_series(memo: Mapping[str, Any]) -> list[tuple[str, float]]:
    for section in memo.get("sections") or []:
        if section.get("id") != "scenarios":
            continue
        series: list[tuple[str, float]] = []
        for item in section.get("items") or []:
            value = item.get("value")
            if isinstance(value, (int, float)) and not isinstance(value, bool):
                series.append((str(item.get("label") or "scenario"), float(value)))
        return series
    return []


def _sections(canvas: _Canvas, memo: Mapping[str, Any]) -> None:
    claims = {str(claim.get("claim_id")): claim for claim in memo.get("claims") or []}
    series = _scenario_series(memo)
    charted = False
    for section in memo.get("sections") or []:
        if section.get("id") in {"identity", "issuer_security", "objective"}:
            continue
        canvas.ensure(56)
        canvas.y -= 20
        canvas.text(str(section.get("title") or section.get("id") or ""), size=12.4, font=FONT_BOLD)
        canvas.rule(colour=(0.45, 0.45, 0.45), width=0.8)
        canvas.y -= 4
        _claim_lines(canvas, section, claims)
        if section.get("id") == "scenarios" and series and not charted:
            canvas.bar_chart("Scenario value per share", series,
                             value_label="Conditional arithmetic from one shared model definition, "
                                          "not a forecast. Values are per share unless the memo "
                                          "states otherwise.")
            charted = True
        rows = [] if _table_repeats_the_claims(section, claims) else _section_rows(section)
        if rows:
            has_detail = any(detail for _, _, detail in rows)
            if has_detail:
                canvas.table(("Item", "Value", "Detail"), rows, weights=(0.34, 0.16, 0.50))
            else:
                canvas.table(("Item", "Value"), [(label, value) for label, value, _ in rows],
                             weights=(0.62, 0.38))
        for note in section.get("notes") or []:
            canvas.paragraph(str(note), size=8.6, font=FONT_ITALIC, colour=MUTED, indent=6)


def _claim_register(canvas: _Canvas, memo: Mapping[str, Any]) -> None:
    claims = list(memo.get("claims") or [])
    if not claims:
        return
    canvas.ensure(60)
    # A register that would fit on the current page does not get one of its own.
    if canvas.space_left() < 260:
        canvas.new_page()
    else:
        canvas.y -= 16
    canvas.text("Claim register", size=12.4, font=FONT_BOLD)
    canvas.rule(colour=(0.45, 0.45, 0.45), width=0.8)
    canvas.y -= 4
    canvas.paragraph(
        "Each row is one claim with its verification outcome and its primary evidence record. "
        "A claim that did not verify stays in the register.", size=9.0, colour=MUTED)
    canvas.y -= 2
    rows = []
    for claim in claims:
        evidence = claim.get("evidence_ids") or []
        rows.append((
            str(claim.get("claim_id")),
            str(claim.get("claim_type")),
            _outcome(claim),
            str(evidence[0]) if evidence else "no evidence",
            str(len(evidence)),
        ))
    # The identifier column must hold an 18-character claim id on one line: a viewer cannot
    # copy an identifier that the layout split across a wrap.
    canvas.table(("Claim", "Type", "Outcome", "Primary evidence", "Records"), rows,
                 weights=(0.20, 0.20, 0.17, 0.31, 0.12), size=7.4, mono_columns=(0, 3))


def _disclosures(canvas: _Canvas, memo: Mapping[str, Any]) -> None:
    manifest = _as_mapping(memo.get("manifest"))
    rights = _as_mapping(memo.get("rights"))
    integrity = _as_mapping(memo.get("integrity"))
    # Keep the disclosure heading, its statements and the reproduction table on one page: a
    # table split from the heading that explains it is worse than a page break.
    canvas.ensure(330)
    canvas.y -= 10
    canvas.text("Verification and limitations disclosure", size=11.4, font=FONT_BOLD)
    canvas.rule(colour=(0.45, 0.45, 0.45), width=0.8)
    canvas.y -= 4
    for note in (
        "A verified claim means the value matches the cited evidence cell and, where derived, "
        "that the stated arithmetic reproduces. It remains possible for a verified figure to be "
        "economically misread; this report does not claim otherwise.",
        "Availability is reported with the semantics stored on the evidence: an estimate is a "
        "modelled bound and is never presented as an observed release time.",
        "Refusals and abstentions are results. A section that reports an unavailable input means "
        "Atlas declined to substitute a fabricated value.",
    ):
        canvas.paragraph(note, size=8.8, colour=MUTED, indent=4)
    canvas.y -= 4
    rows = [
        ("Evidence dependencies", str(len(manifest.get("evidence_dependencies") or []))),
        ("Observation pins", str(len(manifest.get("observation_pins") or []))),
        ("Model fingerprints", str(len(manifest.get("model_fingerprints") or []))),
        ("Integrity dimensions", ", ".join(sorted(_as_mapping(integrity.get("dimensions")).keys()))),
        ("Redistributable", "yes" if rights.get("redistributable") else "no"),
    ]
    canvas.table(("Reproduction record", "Value"), rows, weights=(0.42, 0.58), size=8.4,
                 mono_columns=(1,))
    canvas.y -= 4
    canvas.paragraph(str(rights.get("note") or ""), size=8.4, font=FONT_ITALIC, colour=MUTED)


def _stamp_footers(canvas: _Canvas, memo: Mapping[str, Any]) -> None:
    issuer = _as_mapping(memo.get("issuer"))
    identifier = str(memo.get("memo_id") or issuer.get("issuer_id") or "unsaved memo")
    total = len(canvas.pages)
    for index, ops in enumerate(canvas.pages, start=1):
        label = f"Atlas research memo · {identifier} · page {index} of {total}"
        ops.append(
            b"BT /" + FONT_MONO.encode("ascii") + b" 7.5 Tf " + _colour(MUTED).encode("ascii")
            + f" rg 1 0 0 1 {MARGIN:.2f} {FOOTER_BASELINE:.2f} Tm (".encode("ascii")
            + _pdf_string(label) + b") Tj ET\n"
        )


def _serialize(pages: Sequence[Sequence[bytes]], *, title: str, subject: str,
               author: str = "Atlas") -> bytes:
    count = len(pages)
    catalog_id = 1
    pages_id = 2
    page_ids = [3 + index for index in range(count)]
    content_ids = [3 + count + index for index in range(count)]
    font_base = 3 + 2 * count
    font_ids = {FONT_REGULAR: font_base, FONT_BOLD: font_base + 1,
                FONT_MONO: font_base + 2, FONT_ITALIC: font_base + 3}
    info_id = font_base + 4

    out = bytearray(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []

    def add(body: bytes) -> None:
        offsets.append(len(out))
        out.extend(f"{len(offsets)} 0 obj\n".encode("ascii"))
        out.extend(body)
        out.extend(b"\nendobj\n")

    resources = " ".join(f"/{name} {identifier} 0 R" for name, identifier in font_ids.items())
    add(f"<< /Type /Catalog /Pages {pages_id} 0 R >>".encode("ascii"))
    kids = " ".join(f"{identifier} 0 R" for identifier in page_ids)
    add(f"<< /Type /Pages /Kids [{kids}] /Count {count} >>".encode("ascii"))
    for index, page_id in enumerate(page_ids):
        add(
            (f"<< /Type /Page /Parent {pages_id} 0 R /MediaBox [0 0 {PAGE_WIDTH:.2f} {PAGE_HEIGHT:.2f}] "
             f"/Resources << /Font << {resources} >> >> /Contents {content_ids[index]} 0 R >>")
            .encode("ascii")
        )
    for index, ops in enumerate(pages):
        stream = b"".join(ops)
        add(f"<< /Length {len(stream)} >>\nstream\n".encode("ascii") + stream + b"endstream")
    for name, identifier in font_ids.items():
        base = {FONT_REGULAR: "Helvetica", FONT_BOLD: "Helvetica-Bold",
                FONT_MONO: "Courier", FONT_ITALIC: "Helvetica-Oblique"}[name]
        add((f"<< /Type /Font /Subtype /Type1 /BaseFont /{base} /Encoding /WinAnsiEncoding >>")
            .encode("ascii"))
    add(
        "<< /Title (".encode("ascii") + _pdf_string(title) + b") /Author ("
        + _pdf_string(author) + b") /Subject (" + _pdf_string(subject)
        + b") /Creator (Atlas) /Producer (Atlas research memo renderer) >>"
    )

    start_xref = len(out)
    out.extend(f"xref\n0 {len(offsets) + 1}\n".encode("ascii"))
    out.extend(b"0000000000 65535 f \n")
    for offset in offsets:
        out.extend(f"{offset:010d} 00000 n \n".encode("ascii"))
    out.extend(
        f"trailer\n<< /Size {len(offsets) + 1} /Root {catalog_id} 0 R /Info {info_id} 0 R >>\n"
        f"startxref\n{start_xref}\n%%EOF\n".encode("ascii")
    )
    return bytes(out)


def render_pdf(memo: Mapping[str, Any]) -> bytes:
    """Render one memo object as a PDF. Byte-stable for the same memo."""
    canvas = _Canvas()
    _title_page(canvas, memo)
    canvas.new_page()
    _sections(canvas, memo)
    _claim_register(canvas, memo)
    _disclosures(canvas, memo)
    canvas.finish()
    _stamp_footers(canvas, memo)
    issuer = _as_mapping(memo.get("issuer"))
    title = f"{issuer.get('legal_name') or 'Research memo'} - research memo"
    return _serialize(
        canvas.pages,
        title=str(title),
        subject=str(memo.get("memo_id") or "Atlas research memo"),
    )


__all__ = ["render_pdf", "wrap", "text_width", "PAGE_WIDTH", "PAGE_HEIGHT", "MARGIN"]
