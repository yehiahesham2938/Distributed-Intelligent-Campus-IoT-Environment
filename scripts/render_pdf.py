"""Render docs/phase2_report.md to docs/phase2_report.pdf.

Pure-Python pipeline (fpdf2) — no system pandoc/xelatex needed.
The script walks the markdown line-by-line and translates the subset
of syntax we actually use in the report:

    # / ## / ### headings
    paragraphs
    fenced code blocks
    tables (GFM)
    images ![alt](path)
    bullet lists

If you want a prettier output, install pandoc + xelatex and run:

    pandoc docs/phase2_report.md -o docs/phase2_report.pdf \
        --pdf-engine=xelatex --toc

But this script is good enough for an ungraded-but-submittable PDF.
"""

import re
import sys
from pathlib import Path

from fpdf import FPDF

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "docs" / "phase2_report.md"
OUT = ROOT / "docs" / "phase2_report.pdf"


class Report(FPDF):
    def header(self):
        if self.page_no() == 1:
            return
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        # Use plain ASCII in header to avoid Latin-1 edge cases.
        self.cell(0, 6, "Phase 2 Performance and Reliability Report", align="L")
        self.cell(0, 6, f"Page {self.page_no()}", align="R")
        self.ln(8)
        self.set_text_color(0, 0, 0)

    def footer(self):
        self.set_y(-12)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(120, 120, 120)
        self.cell(0, 6, "Distributed Intelligent Campus IoT Environment", align="C")
        self.set_text_color(0, 0, 0)


def strip_front_matter(text):
    if text.startswith("---"):
        end = text.find("---", 3)
        if end > 0:
            return text[end + 3 :].lstrip()
    return text


def main():
    md = SRC.read_text()
    md = strip_front_matter(md)

    pdf = Report(orientation="P", unit="mm", format="A4")
    pdf.set_auto_page_break(auto=True, margin=15)
    pdf.add_page()
    pdf.set_margins(18, 15, 18)

    # Title block
    pdf.set_font("Helvetica", "B", 18)
    pdf.cell(0, 10, _sanitize("Phase 2 - Performance & Reliability Report"), ln=1)
    pdf.set_font("Helvetica", "", 11)
    pdf.set_text_color(90, 90, 90)
    pdf.cell(0, 6, _sanitize("Distributed Intelligent Campus IoT Environment"), ln=1)
    pdf.cell(0, 6, _sanitize("SWAPD453 IoT Apps Dev - Spring 2026"), ln=1)
    pdf.set_text_color(0, 0, 0)
    pdf.ln(6)

    lines = md.splitlines()
    i = 0
    in_code = False
    code_buf = []

    def emit_code(lines_):
        pdf.set_font("Courier", "", 7)
        pdf.set_fill_color(240, 240, 240)
        for raw in lines_:
            safe = _sanitize(raw if raw else " ")
            safe = safe.replace("\t", "    ")
            chunks = [safe[j : j + 95] for j in range(0, max(len(safe), 1), 95)]
            for chunk in chunks:
                pdf.set_x(pdf.l_margin)
                try:
                    pdf.multi_cell(0, 3.5, chunk or " ", fill=True, new_x="LMARGIN", new_y="NEXT")
                except Exception as exc:
                    print(f"FAIL emit_code chunk len={len(chunk)} content={chunk!r}")
                    raise
        pdf.ln(2)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_fill_color(255, 255, 255)

    def emit_paragraph(text):
        text = re.sub(r"`([^`]+)`", r"\1", text)
        text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
        text = re.sub(r"\*([^*]+)\*", r"\1", text)
        text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)
        pdf.set_font("Helvetica", "", 10)
        pdf.set_x(pdf.l_margin)
        pdf.multi_cell(0, 5, _sanitize(text), new_x="LMARGIN", new_y="NEXT")
        pdf.ln(1)

    def emit_image(alt, rel_path):
        p = (ROOT / "docs" / rel_path).resolve()
        if p.exists():
            try:
                pdf.image(str(p), w=160)
                pdf.ln(2)
            except Exception as exc:
                pdf.set_font("Helvetica", "I", 9)
                pdf.cell(0, 5, f"[image failed: {exc}]", ln=1)
        else:
            pdf.set_font("Helvetica", "I", 9)
            pdf.cell(0, 5, f"[missing image: {rel_path}]", ln=1)

    def emit_table(rows):
        if not rows:
            return
        ncol = len(rows[0])
        avail = 174
        col_w = avail / ncol
        pdf.set_font("Helvetica", "B", 8)
        pdf.set_x(pdf.l_margin)
        # Header — use multi_cell layout safely
        try:
            header = rows[0]
            for cell in header:
                pdf.cell(col_w, 6, _sanitize(cell)[:24], border=1, align="C")
            pdf.ln(6)
            pdf.set_font("Helvetica", "", 8)
            for row in rows[1:]:
                pdf.set_x(pdf.l_margin)
                for cell in row:
                    text = _sanitize(re.sub(r"\*\*([^*]+)\*\*", r"\1", cell))
                    pdf.cell(col_w, 6, text[:24], border=1, align="C")
                pdf.ln(6)
            pdf.ln(2)
        except Exception as exc:
            print(f"FAIL emit_table: {exc}")
            print(f"  rows: {rows!r}")
            raise

    while i < len(lines):
        line = lines[i]

        # Fenced code
        if line.strip().startswith("```"):
            if in_code:
                emit_code(code_buf)
                code_buf = []
                in_code = False
            else:
                in_code = True
            i += 1
            continue
        if in_code:
            code_buf.append(line)
            i += 1
            continue

        # Image
        m = re.match(r"^!\[([^\]]*)\]\(([^)]+)\)\s*$", line)
        if m:
            emit_image(m.group(1), m.group(2))
            i += 1
            continue

        # Table
        if "|" in line and i + 1 < len(lines) and re.match(r"^\s*\|?\s*:?-+", lines[i + 1]):
            table_rows = []
            while i < len(lines) and "|" in lines[i]:
                if re.match(r"^\s*\|?\s*:?-+", lines[i]):
                    i += 1
                    continue
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                table_rows.append(cells)
                i += 1
            emit_table(table_rows)
            continue

        # Headings
        if line.startswith("### "):
            pdf.ln(2)
            pdf.set_font("Helvetica", "B", 11)
            pdf.cell(0, 6, _sanitize(line[4:]), ln=1)
            i += 1
            continue
        if line.startswith("## "):
            pdf.ln(3)
            pdf.set_font("Helvetica", "B", 13)
            pdf.set_text_color(20, 60, 120)
            pdf.cell(0, 7, _sanitize(line[3:]), ln=1)
            pdf.set_text_color(0, 0, 0)
            i += 1
            continue
        if line.startswith("# "):
            pdf.ln(4)
            pdf.set_font("Helvetica", "B", 16)
            pdf.cell(0, 9, _sanitize(line[2:]), ln=1)
            i += 1
            continue

        # Horizontal rule
        if line.strip() == "---":
            pdf.ln(2)
            pdf.set_draw_color(180, 180, 180)
            pdf.line(pdf.get_x(), pdf.get_y(), 210 - 18, pdf.get_y())
            pdf.ln(3)
            i += 1
            continue

        # Bullet
        if line.lstrip().startswith("- "):
            pdf.set_font("Helvetica", "", 10)
            pdf.set_x(pdf.l_margin)
            text = re.sub(r"`([^`]+)`", r"\1", line.lstrip()[2:])
            text = re.sub(r"\*\*([^*]+)\*\*", r"\1", text)
            pdf.multi_cell(170, 5, "  - " + _sanitize(text), new_x="LMARGIN", new_y="NEXT")
            i += 1
            continue

        # Blank
        if not line.strip():
            pdf.ln(2)
            i += 1
            continue

        try:
            emit_paragraph(line)
        except Exception as exc:
            print(f"FAIL at line {i}: {exc}")
            print(f"  content: {line!r}")
            raise
        i += 1

    OUT.parent.mkdir(parents=True, exist_ok=True)
    pdf.output(str(OUT))
    print(f"wrote {OUT}")
    print(f"size: {OUT.stat().st_size // 1024} KB")


def _sanitize(s):
    # fpdf2 default font is Latin-1; strip anything it can't encode.
    return s.encode("latin-1", errors="replace").decode("latin-1")


if __name__ == "__main__":
    main()
