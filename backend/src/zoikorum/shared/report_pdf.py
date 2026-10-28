"""Small paginated PDF writer for plain financial report rows."""
def render_pdf(lines: list[str]) -> bytes:
    pages = [lines[i:i + 48] for i in range(0, len(lines), 48)] or [[]]
    objects = [b"<< /Type /Catalog /Pages 2 0 R >>", b"", b"<< /Type /Font /Subtype /Type1 /BaseFont /Courier >>"]
    kids = []
    for page in pages:
        page_id, stream_id = len(objects) + 1, len(objects) + 2
        kids.append(f"{page_id} 0 R")
        objects.append(f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 842 595] /Resources << /Font << /F1 3 0 R >> >> /Contents {stream_id} 0 R >>".encode())
        escaped = [s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)").replace("\r", " ").replace("\n", " ") for s in page]
        content = ("BT /F1 9 Tf 30 570 Td 11 TL " + " ".join(f"({s}) Tj T*" for s in escaped) + " ET").encode("latin-1", "replace")
        objects.append(f"<< /Length {len(content)} >>\nstream\n".encode() + content + b"\nendstream")
    objects[1] = f"<< /Type /Pages /Count {len(pages)} /Kids [{' '.join(kids)}] >>".encode()
    result, offsets = bytearray(b"%PDF-1.4\n"), [0]
    for index, obj in enumerate(objects, 1):
        offsets.append(len(result)); result.extend(f"{index} 0 obj\n".encode() + obj + b"\nendobj\n")
    xref = len(result)
    result.extend(f"xref\n0 {len(offsets)}\n0000000000 65535 f \n".encode())
    for offset in offsets[1:]: result.extend(f"{offset:010d} 00000 n \n".encode())
    result.extend(f"trailer << /Size {len(offsets)} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode())
    return bytes(result)


def render_table_pdf(title: str, subtitle: str, rows: list[dict]) -> bytes:
    """Aligned landscape table: fixed column widths, right-aligned numbers, wrapped event names, header repeated per page."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from zoikorum.shared.pdf import FONTS, MUTED, INK, RULE

    class _Report(FPDF):
        def footer(self):
            self.set_y(-12); self.set_font("DejaVu", "", 8); self.set_text_color(*MUTED)
            self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    pdf = _Report(orientation="L", format="A4")
    pdf.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf")); pdf.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
    pdf.set_margins(15, 15, 15); pdf.set_auto_page_break(True, margin=16); pdf.alias_nb_pages()
    cols = [("Date", 42, "L"), ("Event", 85, "L"), ("Currency", 22, "C"), ("Gross", 39, "R"), ("Fee", 39, "R"), ("Net", 40, "R")]
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 15); pdf.set_text_color(*INK); pdf.cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 9); pdf.set_text_color(*MUTED); pdf.cell(0, 5, subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT); pdf.ln(3)

    def head():
        pdf.set_font("DejaVu", "B", 9); pdf.set_text_color(*INK); pdf.set_draw_color(*INK)
        for name, w, a in cols:
            pdf.cell(w, 7, name, border="B", align=a)
        pdf.ln(7)

    head()
    pdf.set_font("DejaVu", "", 9); pdf.set_draw_color(*RULE)
    for r in rows:
        values = [str(r["date"])[:19].replace("T", " "), str(r["eventType"]), r["currency"] or "-",
                  f"{r['grossMinor']:,}", f"{r['feeMinor']:,}", f"{r['netMinor']:,}"]
        height = 6 * max(1, len(pdf.multi_cell(cols[1][1], 6, values[1], dry_run=True, output="LINES")))
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page(); head(); pdf.set_font("DejaVu", "", 9); pdf.set_draw_color(*RULE)
        y = pdf.get_y(); x = pdf.l_margin
        for (name, w, a), v in zip(cols, values):
            pdf.set_xy(x, y)
            pdf.multi_cell(w, 6, v, align=a, max_line_height=6, new_x=XPos.RIGHT, new_y=YPos.TOP)
            x += w
        pdf.set_xy(pdf.l_margin, y + height)
        pdf.line(pdf.l_margin, y + height, pdf.w - pdf.r_margin, y + height)
    if not rows:
        pdf.set_text_color(*MUTED); pdf.cell(0, 8, "No activity in this period.")
    return bytes(pdf.output())


def render_grid_pdf(title: str, subtitle: str, columns: list[tuple[str, int, str]], rows: list[dict], keys: list[str],
                    empty: str = "Nothing to show.") -> bytes:
    """Generic landscape table: columns are (heading, width in mm, alignment L/C/R); each row is a dict read by ``keys``.
    Long values wrap, the header repeats on every page, and the page footer counts pages."""
    from fpdf import FPDF
    from fpdf.enums import XPos, YPos
    from zoikorum.shared.pdf import FONTS, MUTED, INK, RULE

    class _Report(FPDF):
        def footer(self):
            self.set_y(-12); self.set_font("DejaVu", "", 8); self.set_text_color(*MUTED)
            self.cell(0, 5, f"Page {self.page_no()} of {{nb}}", align="R")

    pdf = _Report(orientation="L", format="A4")
    pdf.add_font("DejaVu", "", str(FONTS / "DejaVuSans.ttf")); pdf.add_font("DejaVu", "B", str(FONTS / "DejaVuSans-Bold.ttf"))
    pdf.set_margins(15, 15, 15); pdf.set_auto_page_break(True, margin=16); pdf.alias_nb_pages()
    pdf.add_page()
    pdf.set_font("DejaVu", "B", 15); pdf.set_text_color(*INK); pdf.cell(0, 8, title, new_x=XPos.LMARGIN, new_y=YPos.NEXT)
    pdf.set_font("DejaVu", "", 9); pdf.set_text_color(*MUTED); pdf.cell(0, 5, subtitle, new_x=XPos.LMARGIN, new_y=YPos.NEXT); pdf.ln(3)

    def head():
        pdf.set_font("DejaVu", "B", 9); pdf.set_text_color(*INK); pdf.set_draw_color(*INK)
        for name, w, a in columns:
            pdf.cell(w, 7, name, border="B", align=a)
        pdf.ln(7)

    head()
    pdf.set_font("DejaVu", "", 8); pdf.set_draw_color(*RULE)
    for r in rows:
        values = [("" if r.get(k) is None else str(r.get(k))) for k in keys]
        height = 5 * max(1, *(len(pdf.multi_cell(w, 5, v, dry_run=True, output="LINES")) for (_, w, _), v in zip(columns, values)))
        if pdf.get_y() + height > pdf.page_break_trigger:
            pdf.add_page(); head(); pdf.set_font("DejaVu", "", 8); pdf.set_draw_color(*RULE)
        y = pdf.get_y(); x = pdf.l_margin
        for (_, w, a), v in zip(columns, values):
            pdf.set_xy(x, y)
            pdf.multi_cell(w, 5, v, align=a, max_line_height=5, new_x=XPos.RIGHT, new_y=YPos.TOP)
            x += w
        pdf.set_xy(pdf.l_margin, y + height)
        pdf.line(pdf.l_margin, y + height, pdf.w - pdf.r_margin, y + height)
    if not rows:
        pdf.set_text_color(*MUTED); pdf.cell(0, 8, empty)
    return bytes(pdf.output())
