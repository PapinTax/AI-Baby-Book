"""
Milestone review and management endpoints.
GET    /milestones/pending        — queue for user review (approve/reject)
POST   /milestones/rescan         — re-run detection with Sonnet on low-confidence items
PATCH  /milestones/{id}           — approve or reject
GET    /milestones                — all milestones
DELETE /milestones/{id}           — remove
"""
import asyncio
import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db, SessionLocal
from models import Milestone, Photo, Child
from services.timeline import get_pending_review

router = APIRouter(prefix="/milestones", tags=["milestones"])


class MilestoneReview(BaseModel):
    approved: bool
    child_id: Optional[int] = None
    label: Optional[str] = None


class RescanRequest(BaseModel):
    max_confidence: float = 0.75   # re-scan items below this threshold
    limit: int = 50
    model: str = "claude-sonnet-4-6"


class MilestoneOut(BaseModel):
    id: int
    photo_id: int
    child_id: Optional[int]
    milestone_type: str
    label: str
    description: Optional[str]
    confidence: float
    approximate_age: Optional[str]
    approved: Optional[bool]
    photo_filename: Optional[str]
    photo_taken_at: Optional[datetime.datetime]
    thumbnail_url: Optional[str]
    evidence: Optional[list]

    class Config:
        from_attributes = True


def _thumb_url(thumbnail_path: Optional[str]) -> Optional[str]:
    if thumbnail_path:
        return f"/thumbnails/{thumbnail_path}"
    return None


@router.get("/pending", response_model=list[MilestoneOut])
async def pending_review(limit: int = 50, db: AsyncSession = Depends(get_db)):
    """Return milestones awaiting user approval, highest confidence first."""
    entries = await get_pending_review(db, limit=limit)
    return [
        MilestoneOut(
            id=e.milestone_id,
            photo_id=e.photo_id,
            child_id=None,
            milestone_type=e.milestone_type,
            label=e.label,
            description=e.description,
            confidence=e.confidence,
            approximate_age=e.approximate_age,
            approved=e.approved,
            photo_filename=e.photo_path.split("/")[-1],
            photo_taken_at=e.taken_at,
            thumbnail_url=_thumb_url(e.thumbnail_path),
            evidence=e.evidence,
        )
        for e in entries
    ]


async def _run_rescan(max_confidence: float, limit: int, model: str):
    """Background task: re-detect milestones below confidence threshold using a stronger model."""
    from services.photo_scanner import scan_photo
    from services.milestone_detector import detect_milestone

    async with SessionLocal() as db:
        stmt = (
            select(Milestone, Photo)
            .join(Photo, Milestone.photo_id == Photo.id)
            .where(Milestone.confidence < max_confidence)
            .where(Milestone.approved == None)
            .order_by(Milestone.confidence.asc())
            .limit(limit)
        )
        rows = (await db.execute(stmt)).all()

        for milestone, photo in rows:
            scan_result = await asyncio.to_thread(scan_photo, photo.file_path)
            if scan_result.error:
                continue
            detection = await asyncio.to_thread(detect_milestone, scan_result, model)
            if detection.has_milestone and detection.confidence > milestone.confidence:
                milestone.confidence = detection.confidence
                milestone.label = detection.label
                milestone.description = detection.description
                milestone.milestone_type = detection.milestone_type or milestone.milestone_type
                milestone.approximate_age = detection.approximate_age or milestone.approximate_age
                milestone.evidence = detection.evidence

        await db.commit()


@router.post("/rescan", status_code=202)
async def rescan_low_confidence(req: RescanRequest, background_tasks: BackgroundTasks):
    """
    Re-run milestone detection on items below max_confidence using a stronger model.
    Updates in-place if the new confidence is higher.
    """
    background_tasks.add_task(_run_rescan, req.max_confidence, req.limit, req.model)
    return {
        "message": f"Re-scanning up to {req.limit} milestones below {req.max_confidence:.0%} confidence with {req.model}"
    }


@router.patch("/{milestone_id}", response_model=MilestoneOut)
async def review_milestone(
    milestone_id: int,
    review: MilestoneReview,
    db: AsyncSession = Depends(get_db),
):
    """Approve or reject a milestone detection."""
    milestone = await db.get(Milestone, milestone_id)
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    milestone.approved = review.approved
    if review.child_id is not None:
        milestone.child_id = review.child_id
    if review.label:
        milestone.label = review.label

    await db.commit()
    await db.refresh(milestone)

    photo = await db.get(Photo, milestone.photo_id)
    return MilestoneOut(
        id=milestone.id,
        photo_id=milestone.photo_id,
        child_id=milestone.child_id,
        milestone_type=milestone.milestone_type,
        label=milestone.label,
        description=milestone.description,
        confidence=milestone.confidence,
        approximate_age=milestone.approximate_age,
        approved=milestone.approved,
        photo_filename=photo.filename if photo else None,
        photo_taken_at=photo.taken_at if photo else None,
        thumbnail_url=_thumb_url(photo.thumbnail_path if photo else None),
        evidence=milestone.evidence,
    )


@router.get("", response_model=list[MilestoneOut])
async def list_milestones(
    approved_only: bool = False,
    child_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = select(Milestone, Photo).join(Photo, Milestone.photo_id == Photo.id)
    if approved_only:
        stmt = stmt.where(Milestone.approved == True)
    if child_id is not None:
        stmt = stmt.where(Milestone.child_id == child_id)
    stmt = stmt.order_by(Photo.taken_at.asc().nulls_last())

    rows = (await db.execute(stmt)).all()
    return [
        MilestoneOut(
            id=m.id,
            photo_id=m.photo_id,
            child_id=m.child_id,
            milestone_type=m.milestone_type,
            label=m.label,
            description=m.description,
            confidence=m.confidence,
            approximate_age=m.approximate_age,
            approved=m.approved,
            photo_filename=p.filename,
            photo_taken_at=p.taken_at,
            thumbnail_url=_thumb_url(p.thumbnail_path),
            evidence=m.evidence,
        )
        for m, p in rows
    ]


@router.delete("/{milestone_id}", status_code=204)
async def delete_milestone(milestone_id: int, db: AsyncSession = Depends(get_db)):
    milestone = await db.get(Milestone, milestone_id)
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")
    await db.delete(milestone)
    await db.commit()
