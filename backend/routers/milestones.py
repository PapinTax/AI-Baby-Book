"""
Milestone review and management endpoints.
GET    /milestones/pending        — queue for user review (approve/reject)
POST   /milestones/rescan         — re-run detection with Sonnet on low-confidence items
POST   /milestones/deduplicate    — keep only earliest per (child_id, milestone_type)
PATCH  /milestones/{id}           — approve/reject and/or reassign child
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

# Milestone types where only the first occurrence matters per child.
# birthday / vacation / holiday / memorable_moment repeat by design.
_DEDUP_TYPES = {
    "first_smile", "first_laugh", "tummy_time", "first_roll", "sitting_up",
    "first_crawl", "first_pull_to_stand", "first_stand", "first_steps",
    "first_walk", "first_solid_food", "first_birthday", "first_bath",
    "first_tooth", "first_words",
}


class MilestoneReview(BaseModel):
    approved: Optional[bool] = None   # None → don't change approved status
    child_id: Optional[int] = None
    label: Optional[str] = None


class RescanRequest(BaseModel):
    max_confidence: float = 0.75
    limit: int = 50
    model: str = "claude-sonnet-4-6"


class MilestoneOut(BaseModel):
    id: int
    photo_id: int
    child_id: Optional[int]
    child_name: Optional[str] = None
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
    return f"/thumbnails/{thumbnail_path}" if thumbnail_path else None


def _compute_age(birth_date: datetime.date, taken_at: datetime.datetime) -> Optional[str]:
    """Return a human-readable age string like '3 months' or '1 year, 2 months'."""
    delta_days = (taken_at.date() - birth_date).days
    if delta_days < 0:
        return None
    years, rem = divmod(delta_days, 365)
    months = rem // 30
    if years == 0 and months == 0:
        return "newborn"
    if years == 0:
        return f"{months} month{'s' if months != 1 else ''}"
    if months == 0:
        return f"{years} year{'s' if years != 1 else ''}"
    return f"{years} year{'s' if years != 1 else ''}, {months} month{'s' if months != 1 else ''}"


@router.get("/pending", response_model=list[MilestoneOut])
async def pending_review(limit: int = 500, db: AsyncSession = Depends(get_db)):
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
    """Approve/reject a milestone and/or reassign its child."""
    milestone = await db.get(Milestone, milestone_id)
    if not milestone:
        raise HTTPException(status_code=404, detail="Milestone not found")

    if review.approved is not None:
        milestone.approved = review.approved
    if "child_id" in review.model_fields_set:
        milestone.child_id = review.child_id
    if review.label:
        milestone.label = review.label

    # Recompute age whenever child is known and photo has a date
    child_name: Optional[str] = None
    if milestone.child_id is not None:
        child = await db.get(Child, milestone.child_id)
        photo = await db.get(Photo, milestone.photo_id)
        if child:
            child_name = child.name
            if child.birth_date and photo and photo.taken_at:
                age = _compute_age(
                    child.birth_date.date()
                    if isinstance(child.birth_date, datetime.datetime)
                    else child.birth_date,
                    photo.taken_at,
                )
                if age:
                    milestone.approximate_age = age

    await db.commit()
    await db.refresh(milestone)

    photo = await db.get(Photo, milestone.photo_id)
    return MilestoneOut(
        id=milestone.id,
        photo_id=milestone.photo_id,
        child_id=milestone.child_id,
        child_name=child_name,
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


@router.post("/deduplicate")
async def deduplicate_milestones(db: AsyncSession = Depends(get_db)):
    """
    For each (child_id, milestone_type) pair where the type is a once-per-child event,
    keep only the milestone from the earliest photo and delete later duplicates.
    Only operates on approved milestones with an assigned child.
    """
    stmt = (
        select(Milestone, Photo)
        .join(Photo, Milestone.photo_id == Photo.id)
        .where(
            Milestone.approved == True,  # noqa: E712
            Milestone.child_id.isnot(None),
            Milestone.milestone_type.in_(_DEDUP_TYPES),
        )
        .order_by(Photo.taken_at.asc().nulls_last())
    )
    rows = (await db.execute(stmt)).all()

    seen: set[tuple] = set()
    to_delete: list[int] = []
    for m, _ in rows:
        key = (m.child_id, m.milestone_type)
        if key in seen:
            to_delete.append(m.id)
        else:
            seen.add(key)

    for mid in to_delete:
        obj = await db.get(Milestone, mid)
        if obj:
            await db.delete(obj)
    await db.commit()
    return {"deleted": len(to_delete), "message": f"Removed {len(to_delete)} duplicate milestone{'s' if len(to_delete) != 1 else ''}"}


@router.get("", response_model=list[MilestoneOut])
async def list_milestones(
    approved_only: bool = False,
    child_id: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
):
    stmt = (
        select(Milestone, Photo)
        .join(Photo, Milestone.photo_id == Photo.id)
    )
    if approved_only:
        stmt = stmt.where(Milestone.approved == True)  # noqa: E712
    if child_id is not None:
        stmt = stmt.where(Milestone.child_id == child_id)
    stmt = stmt.order_by(Photo.taken_at.asc().nulls_last())

    rows = (await db.execute(stmt)).all()

    # Build child name lookup
    child_ids = {m.child_id for m, _ in rows if m.child_id is not None}
    child_names: dict[int, str] = {}
    for cid in child_ids:
        c = await db.get(Child, cid)
        if c:
            child_names[cid] = c.name

    return [
        MilestoneOut(
            id=m.id,
            photo_id=m.photo_id,
            child_id=m.child_id,
            child_name=child_names.get(m.child_id) if m.child_id else None,
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
