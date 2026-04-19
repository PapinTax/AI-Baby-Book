"""
Timeline and export endpoints.
GET  /timeline         — ordered timeline of approved milestones
GET  /timeline/export  — download PDF keepsake
"""
import io
from typing import Optional

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from services.timeline import get_timeline, deduplicate_timeline
from services.exporter import generate_pdf

router = APIRouter(prefix="/timeline", tags=["timeline"])


@router.get("")
async def get_timeline_view(
    child_id: Optional[int] = None,
    approved_only: bool = True,
    deduplicate: bool = True,
    min_confidence: float = 0.0,
    db: AsyncSession = Depends(get_db),
):
    """Return the chronological milestone timeline."""
    entries = await get_timeline(
        db,
        child_id=child_id,
        approved_only=approved_only,
        min_confidence=min_confidence,
    )
    if deduplicate:
        entries = deduplicate_timeline(entries)
    return [
        {
            "milestone_id": e.milestone_id,
            "photo_id": e.photo_id,
            "milestone_type": e.milestone_type,
            "label": e.label,
            "description": e.description,
            "confidence": e.confidence,
            "approximate_age": e.approximate_age,
            "taken_at": e.taken_at.isoformat() if e.taken_at else None,
            "child_name": e.child_name,
            "thumbnail_url": f"/thumbnails/{e.thumbnail_path}" if e.thumbnail_path else None,
        }
        for e in entries
    ]


@router.get("/export/pdf")
async def export_pdf(
    child_name: str = Query(default="Baby"),
    child_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    """Generate and download a PDF keepsake book."""
    entries = await get_timeline(db, child_id=child_id, approved_only=True)
    entries = deduplicate_timeline(entries)
    pdf_bytes = generate_pdf(entries, child_name=child_name)
    return StreamingResponse(
        io.BytesIO(pdf_bytes),
        media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{child_name}_baby_book.pdf"'},
    )


@router.get("/stats")
async def timeline_stats(db: AsyncSession = Depends(get_db)):
    """Summary stats for the dashboard."""
    from sqlalchemy import select, func
    from models import Milestone, Photo

    total_photos = (await db.execute(select(func.count(Photo.id)))).scalar()
    total_milestones = (await db.execute(select(func.count(Milestone.id)))).scalar()
    pending = (await db.execute(
        select(func.count(Milestone.id)).where(Milestone.approved == None)
    )).scalar()
    approved = (await db.execute(
        select(func.count(Milestone.id)).where(Milestone.approved == True)
    )).scalar()

    return {
        "total_photos": total_photos,
        "total_milestones": total_milestones,
        "pending_review": pending,
        "approved": approved,
        "rejected": total_milestones - (pending or 0) - (approved or 0),
    }
