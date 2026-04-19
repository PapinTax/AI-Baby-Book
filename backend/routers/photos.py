"""
Photo import and scanning endpoints.
POST /photos/scan  — scan a local directory
GET  /photos       — list all imported photos
GET  /photos/{id}  — single photo detail
"""
import asyncio
import uuid
import datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Photo, Milestone
from services.photo_scanner import scan_directory, sort_by_timestamp
from services.milestone_detector import detect_milestones_batch

router = APIRouter(prefix="/photos", tags=["photos"])

# In-memory scan progress (good enough for MVP; swap to Redis later)
_scan_jobs: dict[str, dict] = {}


class ScanRequest(BaseModel):
    directory: str
    min_confidence: float = 0.5
    model: str = "claude-haiku-4-5-20251001"


class ScanResponse(BaseModel):
    session_id: str
    message: str


class PhotoResponse(BaseModel):
    id: int
    filename: str
    file_path: str
    taken_at: Optional[datetime.datetime]
    width: Optional[int]
    height: Optional[int]
    processed: bool
    milestone_count: int

    class Config:
        from_attributes = True


async def _run_scan(
    session_id: str,
    directory: str,
    min_confidence: float,
    model: str,
):
    """Background task: scan dir → detect milestones → persist to DB."""
    from database import SessionLocal

    _scan_jobs[session_id] = {"status": "scanning", "scanned": 0, "total": 0, "detected": 0}

    try:
        # Phase 1: scan photos
        def on_scan_progress(current, total, filename):
            _scan_jobs[session_id].update({"scanned": current, "total": total, "current_file": filename})

        photos = await scan_directory(directory, progress_callback=on_scan_progress)
        photos = sort_by_timestamp(photos)
        _scan_jobs[session_id]["status"] = "detecting"

        # Phase 2: detect milestones
        def on_detect_progress(current, total, filename):
            _scan_jobs[session_id].update({"detected": current, "total": total, "current_file": filename})

        detections = await detect_milestones_batch(
            photos,
            model=model,
            min_confidence=min_confidence,
            progress_callback=on_detect_progress,
        )

        # Phase 3: persist
        _scan_jobs[session_id]["status"] = "saving"
        async with SessionLocal() as db:
            for scan_result in photos:
                # Upsert photo
                stmt = select(Photo).where(Photo.file_path == scan_result.file_path)
                existing = (await db.execute(stmt)).scalar_one_or_none()
                if not existing:
                    photo = Photo(
                        file_path=scan_result.file_path,
                        filename=scan_result.filename,
                        taken_at=scan_result.taken_at,
                        file_size=scan_result.file_size,
                        width=scan_result.width,
                        height=scan_result.height,
                        processed=True,
                        scan_session_id=session_id,
                    )
                    db.add(photo)
                else:
                    existing.processed = True

            await db.flush()

            # Persist detections
            for det in detections:
                stmt = select(Photo).where(Photo.file_path == det.photo_path)
                photo = (await db.execute(stmt)).scalar_one_or_none()
                if photo:
                    milestone = Milestone(
                        photo_id=photo.id,
                        milestone_type=det.milestone_type or "memorable_moment",
                        label=det.label,
                        description=det.description,
                        confidence=det.confidence,
                        approximate_age=det.approximate_age,
                        evidence=det.evidence,
                    )
                    db.add(milestone)

            await db.commit()

        _scan_jobs[session_id]["status"] = "complete"
        _scan_jobs[session_id]["milestone_count"] = len(detections)

    except Exception as e:
        _scan_jobs[session_id]["status"] = "error"
        _scan_jobs[session_id]["error"] = str(e)


@router.post("/scan", response_model=ScanResponse)
async def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    """Start an async directory scan. Poll /photos/scan/{session_id} for progress."""
    session_id = str(uuid.uuid4())
    background_tasks.add_task(
        _run_scan, session_id, req.directory, req.min_confidence, req.model
    )
    return ScanResponse(session_id=session_id, message="Scan started")


@router.get("/scan/{session_id}")
async def scan_status(session_id: str):
    """Poll scan job status."""
    if session_id not in _scan_jobs:
        raise HTTPException(status_code=404, detail="Session not found")
    return _scan_jobs[session_id]


@router.get("", response_model=list[PhotoResponse])
async def list_photos(db: AsyncSession = Depends(get_db)):
    stmt = select(Photo).order_by(Photo.taken_at.asc().nulls_last())
    photos = (await db.execute(stmt)).scalars().all()

    result = []
    for photo in photos:
        stmt2 = select(Milestone).where(Milestone.photo_id == photo.id)
        milestones = (await db.execute(stmt2)).scalars().all()
        result.append(PhotoResponse(
            id=photo.id,
            filename=photo.filename,
            file_path=photo.file_path,
            taken_at=photo.taken_at,
            width=photo.width,
            height=photo.height,
            processed=photo.processed,
            milestone_count=len(milestones),
        ))
    return result


@router.get("/{photo_id}")
async def get_photo(photo_id: int, db: AsyncSession = Depends(get_db)):
    photo = await db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    stmt = select(Milestone).where(Milestone.photo_id == photo_id)
    milestones = (await db.execute(stmt)).scalars().all()
    return {
        "id": photo.id,
        "filename": photo.filename,
        "file_path": photo.file_path,
        "taken_at": photo.taken_at,
        "width": photo.width,
        "height": photo.height,
        "milestones": [
            {
                "id": m.id,
                "type": m.milestone_type,
                "label": m.label,
                "confidence": m.confidence,
                "approved": m.approved,
            }
            for m in milestones
        ],
    }
