# resume_builder.py
from __future__ import annotations
import html as html_mod
import re
from pathlib import Path
from typing import Any

from reportlab.lib import colors
from reportlab.lib.enums import TA_JUSTIFY
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.platypus import HRFlowable, Paragraph, SimpleDocTemplate, Spacer

NAVY = colors.HexColor("#1F3A4D")
GRAY = colors.HexColor("#4A5568")


def _S(name: str, **kw: Any) -> ParagraphStyle:
    defaults: dict[str, Any] = dict(fontName="Helvetica", fontSize=9, leading=13, textColor=colors.black)
    defaults.update(kw)
    return ParagraphStyle(name, **defaults)


H1 = _S("h1", fontName="Helvetica-Bold", fontSize=16, textColor=NAVY, leading=20)
H2 = _S("h2", fontName="Helvetica-Bold", fontSize=11, textColor=NAVY, leading=14, spaceBefore=8)
BODY = _S("body", fontSize=9, leading=13, alignment=TA_JUSTIFY)
BULLET = _S("bullet", fontSize=9, leading=12, leftIndent=12)
META = _S("meta", fontSize=8, textColor=GRAY, leading=11)
BOLD_BODY = _S("bold_body", fontName="Helvetica-Bold", fontSize=9, leading=13)


def _safe(text: str) -> str:
    text = html_mod.unescape(text)
    return text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def _md_to_flowables(text: str) -> list:
    story: list = []
    for line in text.split("\n"):
        line = line.rstrip()
        if not line:
            story.append(Spacer(1, 4))
        elif line.startswith("# "):
            story.append(Paragraph(_safe(line[2:]), H1))
        elif line.startswith("## "):
            story.append(HRFlowable(width="100%", thickness=0.5, color=NAVY, spaceAfter=2))
            story.append(Paragraph(_safe(line[3:].upper()), H2))
        elif line.startswith("### "):
            story.append(Paragraph(_safe(line[4:]), BOLD_BODY))
        elif line.startswith("- ") or line.startswith("* "):
            content = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _safe(line[2:]))
            story.append(Paragraph(f"• {content}", BULLET))
        elif line.startswith("**") and line.endswith("**"):
            story.append(Paragraph(_safe(line[2:-2]), BOLD_BODY))
        elif line.startswith("*") and line.endswith("*"):
            story.append(Paragraph(f"<i>{_safe(line[1:-1])}</i>", META))
        else:
            content = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", _safe(line))
            story.append(Paragraph(content, BODY))
    return story


def build_resume_pdf(md_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    out_path = output_dir / (md_path.stem + ".pdf")
    text = md_path.read_text(encoding="utf-8")
    doc = SimpleDocTemplate(
        str(out_path),
        pagesize=letter,
        topMargin=0.6 * inch,
        bottomMargin=0.6 * inch,
        leftMargin=0.75 * inch,
        rightMargin=0.75 * inch,
    )
    doc.build(_md_to_flowables(text))
    return out_path
