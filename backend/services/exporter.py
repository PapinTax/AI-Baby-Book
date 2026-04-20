"""
Generates PDF keepsakes from approved timeline entries.
Uses reportlab for zero-dependency PDF generation.
"""
import io
import datetime
from pathlib import Path
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage,
    HRFlowable, PageBreak,
)

from services.timeline import TimelineEntry

THUMBNAILS_DIR = "./thumbnails"


def _confidence_bar(confidence: float, width: int = 10) -> str:
    filled = round(confidence * width)
    return "█" * filled + "░" * (width - filled)


def _make_styles() -> dict:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "BBTitle", parent=base["Title"],
            fontSize=28, textColor=colors.HexColor("#2d3748"), spaceAfter=6,
        ),
        "subtitle": ParagraphStyle(
            "BBSubtitle", parent=base["Normal"],
            fontSize=13, textColor=colors.HexColor("#718096"), spaceAfter=20,
        ),
        "chapter": ParagraphStyle(
            "BBChapter", parent=base["Heading1"],
            fontSize=22, textColor=colors.HexColor("#553c9a"), spaceAfter=8,
        ),
        "heading": ParagraphStyle(
            "BBHeading", parent=base["Heading2"],
            fontSize=16, textColor=colors.HexColor("#553c9a"), spaceAfter=4,
        ),
        "body": ParagraphStyle(
            "BBBody", parent=base["Normal"],
            fontSize=11, textColor=colors.HexColor("#4a5568"), leading=16,
        ),
        "meta": ParagraphStyle(
            "BBMeta", parent=base["Normal"],
            fontSize=9, textColor=colors.HexColor("#a0aec0"), spaceAfter=4,
        ),
    }


def _entry_flowables(entry: TimelineEntry, styles: dict, thumbnails_dir: str) -> list:
    """Return reportlab flowables for a single milestone entry."""
    items = []
    items.append(Paragraph(entry.label, styles["heading"]))

    date_str = entry.taken_at.strftime("%B %d, %Y") if entry.taken_at else "Date unknown"
    age_str = f" · {entry.approximate_age}" if entry.approximate_age else ""
    items.append(Paragraph(f"{date_str}{age_str}", styles["meta"]))

    if entry.thumbnail_path:
        thumb_file = Path(thumbnails_dir) / entry.thumbnail_path
        if thumb_file.is_file():
            try:
                img = RLImage(str(thumb_file), width=80 * mm, height=60 * mm)
                img.hAlign = "LEFT"
                items.append(img)
            except Exception:
                pass

    if entry.description:
        items.append(Paragraph(entry.description, styles["body"]))

    pct = int(entry.confidence * 100)
    items.append(Paragraph(
        f"Confidence: {_confidence_bar(entry.confidence)} {pct}%", styles["meta"]
    ))
    items.append(Spacer(1, 6 * mm))
    items.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
    items.append(Spacer(1, 4 * mm))
    return items


def generate_pdf(
    entries: list[TimelineEntry],
    child_name: str = "Baby",
    thumbnails_dir: str = THUMBNAILS_DIR,
    output_path: Optional[str] = None,
) -> bytes:
    """Generate a single-child PDF keepsake."""
    buf = io.BytesIO()
    styles = _make_styles()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    story: list = []
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph(f"{child_name}'s Baby Book", styles["title"]))
    story.append(Paragraph(
        f"Generated {datetime.datetime.now().strftime('%B %d, %Y')} · {len(entries)} milestones",
        styles["subtitle"],
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 10 * mm))

    for entry in entries:
        story.extend(_entry_flowables(entry, styles, thumbnails_dir))

    doc.build(story)
    pdf_bytes = buf.getvalue()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    return pdf_bytes


def generate_full_pdf(
    sections: list[tuple[str, list[TimelineEntry]]],
    thumbnails_dir: str = THUMBNAILS_DIR,
    output_path: Optional[str] = None,
) -> bytes:
    """
    Generate a combined PDF with a chapter per child.
    sections: list of (child_name, entries) tuples, ordered as desired.
    """
    buf = io.BytesIO()
    styles = _make_styles()
    doc = SimpleDocTemplate(
        buf, pagesize=A4,
        rightMargin=20 * mm, leftMargin=20 * mm,
        topMargin=20 * mm, bottomMargin=20 * mm,
    )

    total = sum(len(e) for _, e in sections)
    story: list = []

    # Cover page
    story.append(Spacer(1, 35 * mm))
    story.append(Paragraph("Our Baby Book", styles["title"]))
    story.append(Paragraph(
        f"Generated {datetime.datetime.now().strftime('%B %d, %Y')} · {total} milestones",
        styles["subtitle"],
    ))
    names = " · ".join(name for name, _ in sections if name)
    if names:
        story.append(Paragraph(names, styles["subtitle"]))
    story.append(PageBreak())

    for child_name, entries in sections:
        if not entries:
            continue
        story.append(Paragraph(f"{child_name}'s Milestones", styles["chapter"]))
        story.append(Paragraph(
            f"{len(entries)} milestone{'s' if len(entries) != 1 else ''}",
            styles["meta"],
        ))
        story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
        story.append(Spacer(1, 6 * mm))
        for entry in entries:
            story.extend(_entry_flowables(entry, styles, thumbnails_dir))
        story.append(PageBreak())

    doc.build(story)
    pdf_bytes = buf.getvalue()
    if output_path:
        Path(output_path).write_bytes(pdf_bytes)
    return pdf_bytes
