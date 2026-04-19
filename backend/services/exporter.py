"""
Generates a PDF keepsake from approved timeline entries.
Uses reportlab for zero-dependency PDF generation.
"""
import io
import datetime
from typing import Optional

from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Image as RLImage, Table, TableStyle, HRFlowable
)

from services.timeline import TimelineEntry


def _confidence_bar(confidence: float, width: int = 10) -> str:
    filled = round(confidence * width)
    return "█" * filled + "░" * (width - filled)


def generate_pdf(
    entries: list[TimelineEntry],
    child_name: str = "Baby",
    output_path: Optional[str] = None,
) -> bytes:
    """
    Generate a PDF keepsake book from timeline entries.
    Returns PDF bytes. If output_path provided, also writes to disk.
    """
    buf = io.BytesIO()
    doc = SimpleDocTemplate(
        buf,
        pagesize=A4,
        rightMargin=20 * mm,
        leftMargin=20 * mm,
        topMargin=20 * mm,
        bottomMargin=20 * mm,
    )

    styles = getSampleStyleSheet()
    title_style = ParagraphStyle(
        "Title", parent=styles["Title"],
        fontSize=28, textColor=colors.HexColor("#2d3748"), spaceAfter=6
    )
    subtitle_style = ParagraphStyle(
        "Subtitle", parent=styles["Normal"],
        fontSize=13, textColor=colors.HexColor("#718096"), spaceAfter=20
    )
    heading_style = ParagraphStyle(
        "MilestoneHeading", parent=styles["Heading2"],
        fontSize=16, textColor=colors.HexColor("#553c9a"), spaceAfter=4
    )
    body_style = ParagraphStyle(
        "Body", parent=styles["Normal"],
        fontSize=11, textColor=colors.HexColor("#4a5568"), leading=16
    )
    meta_style = ParagraphStyle(
        "Meta", parent=styles["Normal"],
        fontSize=9, textColor=colors.HexColor("#a0aec0"), spaceAfter=4
    )

    story = []

    # Cover
    story.append(Spacer(1, 30 * mm))
    story.append(Paragraph(f"{child_name}'s Baby Book", title_style))
    story.append(Paragraph(
        f"Generated {datetime.datetime.now().strftime('%B %d, %Y')} · {len(entries)} milestones",
        subtitle_style,
    ))
    story.append(HRFlowable(width="100%", thickness=1, color=colors.HexColor("#e2e8f0")))
    story.append(Spacer(1, 10 * mm))

    for entry in entries:
        # Milestone heading
        story.append(Paragraph(entry.label, heading_style))

        # Date + age
        date_str = entry.taken_at.strftime("%B %d, %Y") if entry.taken_at else "Date unknown"
        age_str = f" · {entry.approximate_age}" if entry.approximate_age else ""
        story.append(Paragraph(f"{date_str}{age_str}", meta_style))

        # Thumbnail
        if entry.thumbnail_path:
            try:
                img = RLImage(entry.thumbnail_path, width=80 * mm, height=60 * mm)
                img.hAlign = "LEFT"
                story.append(img)
            except Exception:
                pass

        # Description
        if entry.description:
            story.append(Paragraph(entry.description, body_style))

        # Confidence
        confidence_pct = int(entry.confidence * 100)
        story.append(Paragraph(
            f"Confidence: {_confidence_bar(entry.confidence)} {confidence_pct}%",
            meta_style,
        ))

        story.append(Spacer(1, 6 * mm))
        story.append(HRFlowable(width="100%", thickness=0.5, color=colors.HexColor("#e2e8f0")))
        story.append(Spacer(1, 4 * mm))

    doc.build(story)
    pdf_bytes = buf.getvalue()

    if output_path:
        with open(output_path, "wb") as f:
            f.write(pdf_bytes)

    return pdf_bytes
