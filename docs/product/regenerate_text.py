"""Regenerate text/*.md from the .docx files in this folder (standard library only).

    python docs/product/regenerate_text.py
"""

import html
import os
import re
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))

W = "{http://schemas.openxmlformats.org/wordprocessingml/2006/main}"


def to_markdown(path: str) -> str:
    """Paragraphs, headings, list items and tables from word/document.xml (no external libraries)."""
    import xml.etree.ElementTree as ET

    root = ET.fromstring(zipfile.ZipFile(path).read("word/document.xml"))
    body = root.find(f"{W}body")
    out: list[str] = []

    def para_text(p) -> str:
        parts = []
        for node in p.iter():
            if node.tag == f"{W}t" and node.text:
                parts.append(node.text)
            elif node.tag == f"{W}tab":
                parts.append(" ")
            elif node.tag == f"{W}br":
                parts.append("\n")
        return "".join(parts).strip()

    def para_md(p) -> str | None:
        text = para_text(p)
        if not text:
            return None
        ppr = p.find(f"{W}pPr")
        style = ppr.find(f"{W}pStyle").get(f"{W}val") if ppr is not None and ppr.find(f"{W}pStyle") is not None else ""
        m = re.match(r"(?i)heading\s*(\d)|title", style or "")
        if m:
            level = int(m.group(1)) if m.group(1) else 1
            return "#" * min(level + (0 if m.group(1) else 0), 6) + " " + text
        if ppr is not None and ppr.find(f"{W}numPr") is not None:
            return "- " + text
        return text

    for child in body:
        if child.tag == f"{W}p":
            md = para_md(child)
            if md:
                out.append(md)
        elif child.tag == f"{W}tbl":
            rows = []
            for tr in child.iter(f"{W}tr"):
                cells = [" ".join(filter(None, (para_text(p) for p in tc.iter(f"{W}p")))).replace("|", "\\|")
                         for tc in tr.iter(f"{W}tc")]
                rows.append(cells)
            if rows:
                width = max(len(r) for r in rows)
                rows = [r + [""] * (width - len(r)) for r in rows]
                table = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
                table += ["| " + " | ".join(r) + " |" for r in rows[1:]]
                out.append(chr(10).join(table))  # one block: rows must not be separated by blank lines
    return "\n\n".join(line for line in out)



if __name__ == "__main__":
    os.makedirs(os.path.join(HERE, "text"), exist_ok=True)
    for name in sorted(os.listdir(HERE)):
        if not name.endswith(".docx"):
            continue
        slug = name[:-5]
        md = to_markdown(os.path.join(HERE, name))
        old = os.path.join(HERE, "text", slug + ".md")
        title = slug.replace("-", " ").title()
        if os.path.exists(old):  # keep the existing title line
            m = re.search(r"^# (.+)$", open(old, encoding="utf-8").read(), re.M)
            title = m.group(1) if m else title
        with open(old, "w", encoding="utf-8") as f:
            header = f"<!-- Generated from {slug}.docx — edit the .docx, not this file. -->"
            f.write(f"{header}\n\n# {title}\n\n{html.unescape(md)}\n")
        print("regenerated", slug)
