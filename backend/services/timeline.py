"""
Timeline builder: takes approved milestones and organizes them into a
chronological timeline, deduplicates, and prepares export data.
"""
import datetime
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select, and_
from sqlalchemy.ext.asyncio import AsyncSession

from models import Milestone, Photo, Child


@dataclass
class TimelineEntry:
    milestone_id: int
    photo_id: int
    photo_path: str
    thumbnail_path: Optional[str]
    milestone_type: str
    label: str
    description: Optional[str]
    confidence: float
    approximate_age: Optional[str]
    taken_at: Optional[datetime.datetime]
    child_name: Optional[str]
    approved: Optional[bool]
    evidence: Optional[list] = None


async def get_timeline(
    db: AsyncSession,
    child_id: Optional[int] = None,
    approved_only: bool = True,
    min_confidence: float = 0.0,
) -> list[TimelineEntry]:
    """Fetch milestones ordered by photo timestamp."""
    stmt = (
        select(Milestone, Photo, Child)
        .join(Photo, Milestone.photo_id == Photo.id)
        .outerjoin(Child, Milestone.child_id == Child.id)
    )

    filters = [Milestone.confidence >= min_confidence]
    if approved_only:
        filters.append(Milestone.approved == True)
    if child_id is not None:
        filters.append(Milestone.child_id == child_id)
    stmt = stmt.where(and_(*filters))
    stmt = stmt.order_by(Photo.taken_at.asc().nulls_last())

    rows = (await db.execute(stmt)).all()
    entries = []
    for milestone, photo, child in rows:
        entries.append(TimelineEntry(
            milestone_id=milestone.id,
            photo_id=photo.id,
            photo_path=photo.file_path,
            thumbnail_path=photo.thumbnail_path,
            milestone_type=milestone.milestone_type,
            label=milestone.label,
            description=milestone.description,
            confidence=milestone.confidence,
            approximate_age=milestone.approximate_age,
            taken_at=photo.taken_at,
            child_name=child.name if child else None,
            approved=milestone.approved,
            evidence=milestone.evidence,
        ))
    return entries


def deduplicate_timeline(entries: list[TimelineEntry], window_days: int = 3) -> list[TimelineEntry]:
    """
    Remove duplicate milestone types that occur within window_days of each other.
    Keeps the highest-confidence entry within each cluster.
    """
    if not entries:
        return entries

    seen: dict[str, TimelineEntry] = {}
    result: list[TimelineEntry] = []

    for entry in entries:
        key = entry.milestone_type
        if key not in seen:
            seen[key] = entry
            result.append(entry)
        else:
            prev = seen[key]
            if entry.taken_at and prev.taken_at:
                delta = abs((entry.taken_at - prev.taken_at).days)
                if delta <= window_days:
                    # Keep higher confidence entry
                    if entry.confidence > prev.confidence:
                        result.remove(prev)
                        result.append(entry)
                        seen[key] = entry
                    continue
            # Different time cluster — treat as distinct milestone
            result.append(entry)

    return sorted(result, key=lambda e: e.taken_at or datetime.datetime(9999, 1, 1))


async def get_pending_review(
    db: AsyncSession,
    limit: int = 50,
) -> list[TimelineEntry]:
    """Get milestones awaiting user approval."""
    stmt = (
        select(Milestone, Photo, Child)
        .join(Photo, Milestone.photo_id == Photo.id)
        .outerjoin(Child, Milestone.child_id == Child.id)
        .where(Milestone.approved == None)
        .order_by(Milestone.confidence.desc())
        .limit(limit)
    )
    rows = (await db.execute(stmt)).all()
    return [
        TimelineEntry(
            milestone_id=m.id,
            photo_id=p.id,
            photo_path=p.file_path,
            thumbnail_path=p.thumbnail_path,
            milestone_type=m.milestone_type,
            label=m.label,
            description=m.description,
            confidence=m.confidence,
            approximate_age=m.approximate_age,
            taken_at=p.taken_at,
            child_name=c.name if c else None,
            approved=m.approved,
            evidence=m.evidence,
        )
        for m, p, c in rows
    ]
