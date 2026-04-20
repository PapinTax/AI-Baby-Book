"""
Photo import and scanning endpoints.
POST /photos/scan       — scan a local directory (background job)
POST /photos/upload     — upload a single photo file (synchronous, returns detection)
GET  /photos            — list all imported photos
GET  /photos/{id}       — single photo detail
GET  /photos/{id}/image — serve the original photo file
"""
import asyncio
import mimetypes
import os
import tempfile
import uuid
import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, BackgroundTasks, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, computed_field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Photo, Milestone
from services.photo_scanner import (
    list_photo_files,
    filter_files_by_exif_date,
    scan_files,
    scan_photo,
    sort_by_timestamp,
    save_thumbnail_to_disk,
)
from services.milestone_detector import detect_milestones_batch, detect_milestone, prefilter_has_child

THUMBNAILS_DIR = os.getenv("THUMBNAILS_DIR", "./thumbnails")
UPLOADS_DIR = os.getenv("UPLOADS_DIR", "./uploads")

router = APIRouter(prefix="/photos", tags=["photos"])

# In-memory scan progress (good enough for MVP; swap to Redis later)
_scan_jobs: dict[str, dict] = {}


class ScanRequest(BaseModel):
    directory: str
    min_confidence: float = 0.5
    model: str = "claude-haiku-4-5-20251001"
    start_date: Optional[datetime.date] = None
    end_date: Optional[datetime.date] = None
    use_prefilter: bool = True


class ScanResponse(BaseModel):
    session_id: str
    message: str


class PhotoResponse(BaseModel):
    id: int
    filename: str
    file_path: str
    thumbnail_path: Optional[str]
    taken_at: Optional[datetime.datetime]
    width: Optional[int]
    height: Optional[int]
    processed: bool
    milestone_count: int

    @computed_field
    @property
    def thumbnail_url(self) -> Optional[str]:
        if self.thumbnail_path:
            return f"/thumbnails/{self.thumbnail_path}"
        return None

    class Config:
        from_attributes = True


async def _run_scan(
    session_id: str,
    directory: str,
    min_confidence: float,
    model: str,
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
    use_prefilter: bool,
):
    """Background task: list → date filter → read → prefilter → detect → persist."""
    from database import SessionLocal

    job = {
        "status": "listing", "scanned": 0, "total": 0, "detected": 0,
        "date_filtered": 0, "prefilter_passed": 0, "prefilter_total": 0,
        "cloud_skipped": 0,
    }
    _scan_jobs[session_id] = job

    try:
        # ── Phase 1: enumerate files + skip iCloud placeholders ──────────────
        local_files, cloud_skipped = await asyncio.to_thread(list_photo_files, directory)
        job["cloud_skipped"] = cloud_skipped

        # ── Phase 2: fast EXIF date filter (no thumbnail work) ───────────────
        if start_date or end_date:
            job["status"] = "date_checking"
            job["total"] = len(local_files)
            job["scanned"] = 0

            def on_date_progress(current, total, filename):
                job["scanned"] = current
                job["total"] = total
                job["current_file"] = filename

            candidates = await filter_files_by_exif_date(
                local_files, start_date, end_date,
                progress_callback=on_date_progress,
            )
            job["date_filtered"] = len(local_files) - len(candidates)
        else:
            candidates = local_files

        # ── Phase 3: read filtered photos (thumbnail + base64) ───────────────
        job["status"] = "scanning"
        job["total"] = len(candidates)
        job["scanned"] = 0
        job["current_file"] = ""

        def on_scan_progress(current, total, filename):
            job["scanned"] = current
            job["total"] = total
            job["current_file"] = filename

        photos = await scan_files(candidates, progress_callback=on_scan_progress)
        photos = sort_by_timestamp(photos)

        # ── Phase 4: prefilter — cheap "does this contain a child?" check ────
        if use_prefilter and photos:
            job["status"] = "prefiltering"
            job["prefilter_total"] = len(photos)
            job["prefilter_checked"] = 0
            job["prefilter_passed"] = 0
            passed = []
            for i, photo in enumerate(photos):
                job["prefilter_checked"] = i + 1
                job["current_file"] = photo.filename
                has_child = await asyncio.to_thread(prefilter_has_child, photo, model)
                if has_child:
                    passed.append(photo)
                    job["prefilter_passed"] = len(passed)
            job["total"] = len(passed)
            photos = passed

        # ── Phase 5: detect milestones ───────────────────────────────────────
        job["status"] = "detecting"
        job["detected"] = 0
        job["total"] = len(photos)

        def on_detect_progress(current, total, filename):
            job["detected"] = current
            job["total"] = total
            job["current_file"] = filename

        detections = await detect_milestones_batch(
            photos,
            model=model,
            min_confidence=min_confidence,
            progress_callback=on_detect_progress,
        )

        # ── Phase 6: persist ─────────────────────────────────────────────────
        job["status"] = "saving"
        async with SessionLocal() as db:
            for scan_result in photos:
                thumb_filename = await asyncio.to_thread(
                    save_thumbnail_to_disk, scan_result, THUMBNAILS_DIR
                )
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
                        thumbnail_path=thumb_filename,
                        processed=True,
                        scan_session_id=session_id,
                    )
                    db.add(photo)
                else:
                    existing.processed = True
                    if thumb_filename and not existing.thumbnail_path:
                        existing.thumbnail_path = thumb_filename

            await db.flush()

            # Persist detections — skip photos that already have a milestone
            # to avoid duplicates on re-scan
            for det in detections:
                stmt = select(Photo).where(Photo.file_path == det.photo_path)
                photo = (await db.execute(stmt)).scalar_one_or_none()
                if not photo:
                    continue
                already_exists = (
                    await db.execute(
                        select(Milestone).where(Milestone.photo_id == photo.id).limit(1)
                    )
                ).scalar_one_or_none()
                if already_exists:
                    continue
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

        job["status"] = "complete"
        job["milestone_count"] = len(detections)

    except Exception as e:
        job["status"] = "error"
        job["error"] = str(e)


@router.post("/scan", response_model=ScanResponse)
async def start_scan(req: ScanRequest, background_tasks: BackgroundTasks):
    """Start an async directory scan. Poll /photos/scan/{session_id} for progress."""
    session_id = str(uuid.uuid4())
    background_tasks.add_task(
        _run_scan, session_id, req.directory, req.min_confidence, req.model,
        req.start_date, req.end_date, req.use_prefilter,
    )
    return ScanResponse(session_id=session_id, message="Scan started")


@router.get("/scan/{session_id}")
async def scan_status(session_id: str):
    """Poll scan job status (single snapshot)."""
    if session_id not in _scan_jobs:
        raise HTTPException(status_code=404, detail="Session not found")
    return _scan_jobs[session_id]


@router.get("/scan/{session_id}/stream")
async def scan_stream(session_id: str):
    """
    Server-Sent Events stream for real-time scan progress.
    Client connects once and receives state updates at ~500 ms intervals
    until status is 'complete' or 'error'.
    """
    import asyncio
    import json
    from fastapi.responses import StreamingResponse

    async def generator():
        # Wait briefly for the job to be registered by the background task
        for _ in range(20):
            if session_id in _scan_jobs:
                break
            await asyncio.sleep(0.1)

        if session_id not in _scan_jobs:
            yield f"data: {json.dumps({'error': 'session not found'})}\n\n"
            return

        while True:
            state = _scan_jobs.get(session_id, {})
            yield f"data: {json.dumps(state)}\n\n"
            if state.get("status") in ("complete", "error"):
                return
            await asyncio.sleep(0.5)

    return StreamingResponse(
        generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",   # prevent nginx buffering
            "Connection": "keep-alive",
        },
    )


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
            thumbnail_path=photo.thumbnail_path,
            taken_at=photo.taken_at,
            width=photo.width,
            height=photo.height,
            processed=photo.processed,
            milestone_count=len(milestones),
        ))
    return result


@router.post("/upload")
async def upload_photo(
    file: UploadFile = File(...),
    min_confidence: float = Form(0.5),
    model: str = Form("claude-haiku-4-5-20251001"),
    db: AsyncSession = Depends(get_db),
):
    """
    Upload a single photo, run milestone detection, and return the result.
    Synchronous — suitable for one-off photo testing.
    """
    Path(UPLOADS_DIR).mkdir(parents=True, exist_ok=True)

    # Save the upload to a stable path so the Photo record has a real file_path
    ext = Path(file.filename or "photo.jpg").suffix or ".jpg"
    dest_filename = f"{uuid.uuid4().hex}{ext}"
    dest_path = str(Path(UPLOADS_DIR) / dest_filename)

    content = await file.read()
    with open(dest_path, "wb") as f:
        f.write(content)

    # Scan & detect
    scan_result = await asyncio.to_thread(scan_photo, dest_path)
    if scan_result.error:
        raise HTTPException(status_code=422, detail=f"Could not read image: {scan_result.error}")

    detection = await asyncio.to_thread(detect_milestone, scan_result, model)
    thumb_filename = await asyncio.to_thread(save_thumbnail_to_disk, scan_result, THUMBNAILS_DIR)

    # Persist
    photo = Photo(
        file_path=dest_path,
        filename=file.filename or dest_filename,
        taken_at=scan_result.taken_at,
        file_size=scan_result.file_size,
        width=scan_result.width,
        height=scan_result.height,
        thumbnail_path=thumb_filename,
        processed=True,
    )
    db.add(photo)
    await db.flush()

    milestone_saved = None
    if detection.has_milestone and detection.confidence >= min_confidence:
        milestone_saved = Milestone(
            photo_id=photo.id,
            milestone_type=detection.milestone_type or "memorable_moment",
            label=detection.label,
            description=detection.description,
            confidence=detection.confidence,
            approximate_age=detection.approximate_age,
            evidence=detection.evidence,
        )
        db.add(milestone_saved)

    await db.commit()
    await db.refresh(photo)

    return {
        "photo_id": photo.id,
        "filename": photo.filename,
        "taken_at": photo.taken_at,
        "thumbnail_url": f"/thumbnails/{thumb_filename}" if thumb_filename else None,
        "detection": {
            "has_milestone": detection.has_milestone,
            "milestone_type": detection.milestone_type,
            "label": detection.label,
            "description": detection.description,
            "confidence": detection.confidence,
            "approximate_age": detection.approximate_age,
            "evidence": detection.evidence,
        } if detection.has_milestone else None,
        "milestone_id": milestone_saved.id if milestone_saved else None,
    }


@router.get("/{photo_id}/image")
async def serve_photo_image(photo_id: int, db: AsyncSession = Depends(get_db)):
    """Stream the original photo file for lightbox display."""
    photo = await db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    if not Path(photo.file_path).is_file():
        raise HTTPException(status_code=404, detail="Image file not found on disk")
    media_type = mimetypes.guess_type(photo.file_path)[0] or "image/jpeg"
    return FileResponse(photo.file_path, media_type=media_type)


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
