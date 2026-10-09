"""Server-generated PDF documents (contracts, invoices) with fpdf2 and an embedded Unicode font (DejaVu Sans, free
licence in ``fonts/``), so names and currency symbols print as typed.

Output is reproducible: the PDF's creation date is the document's own date, so the same record always gives the same
file. Every page carries the reference and the fingerprint of the record it was made from (a contract's agreement
text SHA-256), so a printed copy can be checked against the platform.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from fpdf import FPDF
from fpdf.enums import XPos, YPos

FONTS = Path(__file__).resolve().parent / "fonts"
INK, MUTED, RULE, BRAND = (17, 24, 39), (100, 116, 139), (226, 232, 240), (15, 118, 110)


@dataclass
class Section:
    heading: str | None = None
    rows: list[tuple[str, str]] = field(default_factory=list)  # label, value
    table: list[tuple[str, str]] = field(default_factory=list)  # description, amount (right-aligned)
    total: tuple[str, str] | None = None
    text: str | None = None  # body text; blank lines separate paragraphs


@dataclass
class PdfDocument:
    title: str
    reference: str
    issued: datetime
    sections: list[Section]
    fingerprint: str | None = None  # shown in the footer of every page
    subtitle: str | None = None


class _Pdf(FPDF):
    def __init__(self, doc: PdfDocument):
        super().__init__(format="A4")
        self.doc = doc
        self.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf"))
        self.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
        self.set_auto_page_break(auto=True, margin=22)
        self.set_margins(18, 18, 18)
        self.set_title(f"{doc.title} {doc.reference}")
        self.set_author("Zoikorum")
        self.set_creator("Zoikorum")
        self.set_creation_date(doc.issued)

    def header(self):
        self.set_font("DejaVu", "B", 13)
        self.set_text_color(*BRAND)
        self.cell(0, 7, "Zoikorum", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.set_draw_color(*RULE)
        self.line(self.l_margin, self.get_y() + 1, self.w - self.r_margin, self.get_y() + 1)
        self.ln(5)

    def footer(self):
        self.set_y(-16)
        self.set_font("DejaVu", "", 7)
        self.set_text_color(*MUTED)
        left = f"{self.doc.title} {self.doc.reference}"
        if self.doc.fingerprint:
            left += f"  ·  SHA-256 {self.doc.fingerprint}"
        self.cell(0, 4, left, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        self.cell(0, 4, f"Page {self.page_no()} of {{nb}}", align="R")


def render(doc: PdfDocument) -> bytes:
    pdf = _Pdf(doc)
    pdf.alias_nb_pages()
    pdf.add_page()
    width = pdf.w - pdf.l_margin - pdf.r_margin

    pdf.set_text_color(*INK)
    pdf.set_font("DejaVu", "B", 18)
    pdf.cell(0, 9, doc.title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 9)
    pdf.set_text_color(*MUTED)
    pdf.cell(0, 5, f"{doc.reference}  ·  {doc.issued:%d %B %Y}", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    if doc.subtitle:
        pdf.multi_cell(width, 5, doc.subtitle, align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.ln(4)

    for s in doc.sections:
        if s.heading:
            pdf.set_font("DejaVu", "B", 11)
            pdf.set_text_color(*INK)
            pdf.cell(0, 7, s.heading, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        pdf.set_font("DejaVu", "", 9.5)
        for label, value in s.rows:
            pdf.set_text_color(*MUTED)
            pdf.cell(45, 5.5, label)
            pdf.set_text_color(*INK)
            pdf.multi_cell(width - 45, 5.5, value or "—", align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
        if s.table:
            pdf.set_draw_color(*RULE)
            for description, amount in s.table:
                # Measure first, so a description that wraps never runs into the next row.
                lines = len(pdf.multi_cell(width - 40, 6, description, align="L", dry_run=True, output="LINES"))
                if pdf.get_y() + 6 * lines > pdf.page_break_trigger:
                    pdf.add_page()
                y = pdf.get_y()
                pdf.set_text_color(*INK)
                pdf.multi_cell(width - 40, 6, description, align="L", new_x=XPos.RIGHT, new_y=YPos.TOP)
                pdf.cell(40, 6, amount, align="R")
                pdf.set_xy(pdf.l_margin, y + 6 * lines)
                pdf.line(pdf.l_margin, pdf.get_y(), pdf.w - pdf.r_margin, pdf.get_y())
        if s.total:
            pdf.set_font("DejaVu", "B", 10.5)
            pdf.cell(width - 40, 8, s.total[0])
            pdf.cell(40, 8, s.total[1], align="R", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
            pdf.set_font("DejaVu", "", 9.5)
        if s.text:
            pdf.set_text_color(*INK)
            for paragraph in s.text.strip().split("\n\n"):
                pdf.multi_cell(width, 5, paragraph.strip(), align="L", new_x=XPos.LMARGIN, new_y=YPos.NEXT)
                pdf.ln(2)
        pdf.ln(3)
    return bytes(pdf.output())


def money(amount_minor: int, currency: str) -> str:
    return f"{currency} {amount_minor / 100:,.2f}"
