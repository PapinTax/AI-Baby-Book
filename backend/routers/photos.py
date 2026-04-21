"""
Photo import and scanning endpoints.
POST /photos/scan            — scan a local directory (background job)
POST /photos/upload          — upload a single photo file (synchronous, returns detection)
GET  /photos                 — list imported photos (filterable by date, milestones, no-date)
PATCH /photos/{id}           — update photo metadata (taken_at)
DELETE /photos/{id}          — remove photo + its milestones from the DB
GET  /photos/{id}            — single photo detail
GET  /photos/{id}/image      — serve the original photo file
"""
import asyncio
import mimetypes
import os
import tempfile
import uuid
import datetime
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, BackgroundTasks, UploadFile, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, computed_field
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import Photo, Milestone
from services.photo_scanner import (
    list_photo_files,
    read_dates_bulk,
    cluster_bursts,
    scan_files,
    scan_file,
    scan_photo,
    sort_by_timestamp,
    save_thumbnail_to_disk,
    hydrate_full_b64,
)
from services.milestone_detector import (
    detect_milestones_batch,
    detect_milestone,
    prefilter_has_child,
    prefilter_batch,
)
from services.face_detector import face_filter_batch


async def _already_processed_keys(db: AsyncSession, paths: list[str]) -> set[tuple[str, int]]:
    """
    Look up which of the given file paths are already fully processed in the DB.
    Returns the set of (file_path, file_size) tuples for processed rows.
    Chunked to stay under SQLite's 999-parameter limit.
    """
    found: set[tuple[str, int]] = set()
    CHUNK = 500
    for i in range(0, len(paths), CHUNK):
        chunk = paths[i:i + CHUNK]
        stmt = select(Photo.file_path, Photo.file_size).where(
            Photo.file_path.in_(chunk),
            Photo.processed == True,  # noqa: E712 — SQLA wants ==
        )
        rows = (await db.execute(stmt)).all()
        for path, size in rows:
            if size is not None:
                found.add((path, size))
    return found

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
    child_id: Optional[int] = None   # when set, auto-assigns all detections to this child


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


class PhotoUpdate(BaseModel):
    taken_at: Optional[datetime.datetime] = None


def _passes_date_filter(
    dt: Optional[datetime.datetime],
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
) -> bool:
    d = dt.date() if dt else None
    if d is None:
        return True  # fail-open
    if start_date and d < start_date:
        return False
    if end_date and d > end_date:
        return False
    return True


async def _run_scan(
    session_id: str,
    directory: str,
    min_confidence: float,
    model: str,
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
    use_prefilter: bool,
    child_id: Optional[int] = None,
):
    """Background task: list → date filter → read → prefilter → detect → persist."""
    from database import SessionLocal
    from models import Child

    job = {
        "status": "listing", "scanned": 0, "total": 0, "detected": 0,
        "date_filtered": 0, "prefilter_passed": 0, "prefilter_total": 0,
        "cloud_skipped": 0, "cached_skipped": 0,
        "face_total": 0, "face_passed": 0, "burst_collapsed": 0,
    }
    _scan_jobs[session_id] = job

    try:
        # ── Phase 1: enumerate files + skip iCloud placeholders ──────────────
        local_files, cloud_skipped = await asyncio.to_thread(list_photo_files, directory)
        job["cloud_skipped"] = cloud_skipped

        # ── Phase 2: DB cache filter — skip already-processed files ──────────
        async with SessionLocal() as db:
            cached = await _already_processed_keys(db, [str(f) for f in local_files])
        before_cache = len(local_files)
        local_files = [
            f for f in local_files
            if (str(f), f.stat().st_size) not in cached
        ]
        job["cached_skipped"] = before_cache - len(local_files)

        # ── Phase 3: bulk date read ───────────────────────────────────────────
        # Windows: single Shell property-store call (fast, no file opens).
        # Fallback: parallel EXIF reads + mtime. Dates are used for filtering,
        # clustering, and populating Photo.taken_at — no second EXIF pass needed.
        job["status"] = "reading_dates"
        job["total"] = len(local_files)
        dates = await read_dates_bulk(local_files)

        # Sort by taken_at so date filter and burst clustering are accurate
        local_files.sort(
            key=lambda f: dates.get(str(f).lower()) or datetime.datetime(9999, 1, 1)
        )

        # ── Phase 4: date range filter ────────────────────────────────────────
        if start_date or end_date:
            job["status"] = "date_checking"
            before_date = len(local_files)
            local_files = [
                f for f in local_files
                if _passes_date_filter(dates.get(str(f).lower()), start_date, end_date)
            ]
            job["date_filtered"] = before_date - len(local_files)

        # ── Phase 5: burst deduplication (before thumbnail generation) ────────
        # Groups photos taken within 60s of each other; keeps the largest file
        # per cluster (free size proxy for quality, no file opens). This runs
        # before scan_files so we never generate thumbnails for discarded siblings.
        job["status"] = "clustering"
        before_cluster = len(local_files)
        local_files = cluster_bursts(local_files, dates)
        job["burst_collapsed"] = before_cluster - len(local_files)

        # ── Phase 6: scan files (thumbnails only, representatives only) ───────
        job["status"] = "scanning"
        job["total"] = len(local_files)
        job["scanned"] = 0
        job["current_file"] = ""

        def on_scan_progress(current, total, filename):
            job["scanned"] = current
            job["total"] = total
            job["current_file"] = filename

        photos = await scan_files(
            local_files,
            dates=dates,                # skip redundant EXIF re-parse
            progress_callback=on_scan_progress,
            include_full=False,         # lazy — only for photos that reach detection
        )
        photos = [p for p in photos if not p.error]
        photos = sort_by_timestamp(photos)

        # ── Phase 7: local face detection (free) ─────────────────────────────
        if photos:
            job["status"] = "face_check"
            job["face_total"] = len(photos)
            job["face_passed"] = 0
            job["scanned"] = 0
            job["total"] = len(photos)

            def on_face_progress(current, total, filename, passed):
                job["scanned"] = current
                job["total"] = total
                job["current_file"] = filename
                job["face_passed"] = passed

            photos = await face_filter_batch(photos, progress_callback=on_face_progress)

        # ── Phase 8: Haiku prefilter — "does this contain a child?" ──────────
        if use_prefilter and photos:
            job["status"] = "prefiltering"
            job["prefilter_total"] = len(photos)
            job["prefilter_checked"] = 0
            job["prefilter_passed"] = 0

            def on_prefilter_progress(current, total, filename, passed):
                job["prefilter_checked"] = current
                job["current_file"] = filename
                job["prefilter_passed"] = passed

            photos = await prefilter_batch(
                photos, model=model,
                progress_callback=on_prefilter_progress,
            )
            job["total"] = len(photos)

        # ── Phase 9: detect milestones (parallel, lazy full_b64 hydration) ───
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
            hydrate=True,
        )

        # ── Phase 10: persist ────────────────────────────────────────────────
        job["status"] = "saving"
        async with SessionLocal() as db:
            # Pre-load child birth date once (used for age computation below)
            child_birth_date: Optional[datetime.date] = None
            if child_id is not None:
                child_obj = await db.get(Child, child_id)
                if child_obj and child_obj.birth_date:
                    bd = child_obj.birth_date
                    child_birth_date = bd.date() if isinstance(bd, datetime.datetime) else bd

            for scan_result in photos:
                thumb_filename = await asyncio.to_thread(
                    save_thumbnail_to_disk, scan_result, THUMBNAILS_DIR
                )
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

                # Compute exact age if child + birth date + photo date are all known
                age_str = det.approximate_age
                if child_birth_date and photo.taken_at:
                    delta = (photo.taken_at.date() - child_birth_date).days
                    if delta >= 0:
                        years, rem = divmod(delta, 365)
                        months = rem // 30
                        if years == 0 and months == 0:
                            age_str = "newborn"
                        elif years == 0:
                            age_str = f"{months} month{'s' if months != 1 else ''}"
                        elif months == 0:
                            age_str = f"{years} year{'s' if years != 1 else ''}"
                        else:
                            age_str = (
                                f"{years} year{'s' if years != 1 else ''}, "
                                f"{months} month{'s' if months != 1 else ''}"
                            )

                milestone = Milestone(
                    photo_id=photo.id,
                    child_id=child_id,
                    milestone_type=det.milestone_type or "memorable_moment",
                    label=det.label,
                    description=det.description,
                    confidence=det.confidence,
                    approximate_age=age_str,
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
        req.start_date, req.end_date, req.use_prefilter, req.child_id,
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
async def list_photos(
    start_date: Optional[datetime.date] = Query(None),
    end_date: Optional[datetime.date] = Query(None),
    has_milestones: Optional[bool] = Query(None),
    no_date: bool = Query(False),
    limit: int = Query(500, ge=1, le=5000),
    offset: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
):
    """
    List photos with optional filters. Uses a single query with milestone count
    subquery — no N+1. Filters:
      start_date / end_date  — taken_at range (inclusive)
      has_milestones         — true=only photos with milestones, false=only without
      no_date                — true=only photos with no taken_at
      limit / offset         — pagination (default 500)
    """
    cnt_sq = (
        select(Milestone.photo_id, func.count(Milestone.id).label("cnt"))
        .group_by(Milestone.photo_id)
        .subquery()
    )
    stmt = (
        select(Photo, func.coalesce(cnt_sq.c.cnt, 0).label("milestone_count"))
        .outerjoin(cnt_sq, Photo.id == cnt_sq.c.photo_id)
    )

    if no_date:
        stmt = stmt.where(Photo.taken_at.is_(None))
    else:
        if start_date:
            stmt = stmt.where(
                Photo.taken_at >= datetime.datetime.combine(start_date, datetime.time.min)
            )
        if end_date:
            stmt = stmt.where(
                Photo.taken_at <= datetime.datetime.combine(end_date, datetime.time.max)
            )

    if has_milestones is True:
        stmt = stmt.where(cnt_sq.c.cnt.isnot(None))
    elif has_milestones is False:
        stmt = stmt.where(cnt_sq.c.cnt.is_(None))

    stmt = stmt.order_by(Photo.taken_at.asc().nulls_last()).limit(limit).offset(offset)

    rows = (await db.execute(stmt)).all()
    return [
        PhotoResponse(
            id=photo.id,
            filename=photo.filename,
            file_path=photo.file_path,
            thumbnail_path=photo.thumbnail_path,
            taken_at=photo.taken_at,
            width=photo.width,
            height=photo.height,
            processed=photo.processed,
            milestone_count=count,
        )
        for photo, count in rows
    ]


@router.patch("/{photo_id}", response_model=PhotoResponse)
async def update_photo(
    photo_id: int,
    update: PhotoUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update photo metadata. Currently supports setting taken_at."""
    photo = await db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    if "taken_at" in update.model_fields_set:
        photo.taken_at = update.taken_at
    await db.commit()
    await db.refresh(photo)
    stmt = select(func.count(Milestone.id)).where(Milestone.photo_id == photo_id)
    count = (await db.execute(stmt)).scalar_one() or 0
    return PhotoResponse(
        id=photo.id,
        filename=photo.filename,
        file_path=photo.file_path,
        thumbnail_path=photo.thumbnail_path,
        taken_at=photo.taken_at,
        width=photo.width,
        height=photo.height,
        processed=photo.processed,
        milestone_count=count,
    )


@router.delete("/{photo_id}", status_code=204)
async def delete_photo(photo_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a photo and all its milestones from the DB. Does not delete the file on disk."""
    photo = await db.get(Photo, photo_id)
    if not photo:
        raise HTTPException(status_code=404, detail="Photo not found")
    milestones = (await db.execute(
        select(Milestone).where(Milestone.photo_id == photo_id)
    )).scalars().all()
    for m in milestones:
        await db.delete(m)
    await db.delete(photo)
    await db.commit()


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

    # Scan & detect — include_full=True since we're sending to Claude immediately
    scan_result = await asyncio.to_thread(scan_file, dest_path, True)
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
