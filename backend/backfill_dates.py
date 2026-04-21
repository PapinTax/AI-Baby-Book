"""
One-time backfill: populate taken_at on Photo rows where it is NULL.

Priority order (same as the main scan pipeline):
  1. Windows Shell property store (System.Photo.DateTaken) — fast, no file open
  2. EXIF DateTimeOriginal / DateTimeDigitized / DateTime
  3. File mtime — last resort so the field is never left NULL for local files

Run from the backend/ directory:
    python backfill_dates.py

Safe to run multiple times — only touches rows where taken_at IS NULL.
"""
import asyncio
import datetime
import sys
from pathlib import Path

# Ensure backend modules resolve
sys.path.insert(0, str(Path(__file__).parent))

from database import SessionLocal
from models import Photo
from services.photo_scanner import (
    _get_dates_for_paths,
    _read_exif_datetime,
    IMAGE_EXTENSIONS,
    VIDEO_EXTENSIONS,
)

from sqlalchemy import select


async def _get_null_date_photos() -> list[Photo]:
    """
    Return photos that need a date fix: either taken_at is NULL, or it is
    suspiciously recent (past the birth of the app, indicating an mtime
    fallback wrote a sync date instead of a capture date).
    """
    cutoff = datetime.datetime(2026, 1, 1)  # nothing genuine is this recent
    async with SessionLocal() as db:
        stmt = select(Photo).where(
            (Photo.taken_at == None) | (Photo.taken_at >= cutoff)  # noqa: E711
        )
        return list((await db.execute(stmt)).scalars().all())


async def backfill():
    print("Querying photos with NULL taken_at…")
    photos = await _get_null_date_photos()
    if not photos:
        print("Nothing to backfill — all photos already have dates.")
        return

    print(f"Found {len(photos)} photos to backfill.")

    # Separate into images and videos
    image_paths = [
        Path(p.file_path)
        for p in photos
        if Path(p.file_path).suffix.lower() in IMAGE_EXTENSIONS
        and Path(p.file_path).is_file()
    ]
    video_paths = [
        Path(p.file_path)
        for p in photos
        if Path(p.file_path).suffix.lower() in VIDEO_EXTENSIONS
        and Path(p.file_path).is_file()
    ]
    missing_on_disk = [
        p for p in photos
        if not Path(p.file_path).is_file()
    ]

    if missing_on_disk:
        print(f"  {len(missing_on_disk)} files not found on disk — skipping those.")

    dates: dict[str, datetime.datetime | None] = {}

    # Step 1: Shell property store for images (Windows only, single PS call)
    if image_paths:
        print(f"  Reading Shell dates for {len(image_paths)} images…")
        shell_dates = await asyncio.to_thread(_get_dates_for_paths, image_paths)
        dates.update(shell_dates)
        covered = sum(1 for v in shell_dates.values() if v is not None)
        print(f"  Shell returned dates for {covered} / {len(image_paths)} images.")

    # Step 2: EXIF fallback for images Shell didn't cover
    missing_images = [f for f in image_paths if str(f).lower() not in dates or dates[str(f).lower()] is None]
    if missing_images:
        print(f"  EXIF fallback for {len(missing_images)} images…")
        for f in missing_images:
            dt = await asyncio.to_thread(_read_exif_datetime, f)
            if dt is not None:
                dates[str(f).lower()] = dt

    # Step 3: videos — ffprobe then mtime
    if video_paths:
        print(f"  Reading dates for {len(video_paths)} videos…")
        from services.photo_scanner import _extract_video_date
        for f in video_paths:
            dt = await asyncio.to_thread(_extract_video_date, f)
            if dt:
                dates[str(f).lower()] = dt

    # Apply to DB
    updated = 0
    async with SessionLocal() as db:
        for photo in photos:
            key = str(Path(photo.file_path)).lower()
            dt = dates.get(key)
            if dt is not None:
                fresh = await db.get(Photo, photo.id)
                if fresh and fresh.taken_at is None:
                    fresh.taken_at = dt
                    updated += 1
        await db.commit()

    print(f"\nDone. Updated {updated} / {len(photos)} photos with dates.")
    still_null = len(photos) - updated
    if still_null:
        print(f"  {still_null} photos remain with NULL taken_at (files not found or truly undated).")


if __name__ == "__main__":
    asyncio.run(backfill())
