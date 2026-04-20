"""
Scans a directory for photos, extracts EXIF metadata, generates thumbnails.
Returns structured PhotoScanResult objects — no DB writes happen here.
"""
import asyncio
import base64
import datetime
import hashlib
import io
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ExifTags

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif", ".webp"}
THUMBNAIL_SIZE = (400, 400)
MAX_CLAUDE_IMAGE_SIZE = (1024, 1024)  # keeps API cost low


@dataclass
class PhotoScanResult:
    file_path: str
    filename: str
    taken_at: Optional[datetime.datetime]
    file_size: int
    width: Optional[int]
    height: Optional[int]
    thumbnail_b64: Optional[str]           # base64 JPEG for API calls
    full_b64: Optional[str]                # base64 JPEG resized for Claude
    media_type: str = "image/jpeg"
    error: Optional[str] = None


def _parse_exif_datetime(raw: str) -> Optional[datetime.datetime]:
    """Parse EXIF datetime string '2023:06:15 14:30:00'."""
    try:
        return datetime.datetime.strptime(raw.strip(), "%Y:%m:%d %H:%M:%S")
    except (ValueError, AttributeError):
        return None


def _extract_taken_at(img: Image.Image) -> Optional[datetime.datetime]:
    """Try multiple EXIF fields in priority order."""
    try:
        exif_data = img._getexif()
        if not exif_data:
            return None
        tag_map = {v: k for k, v in ExifTags.TAGS.items()}
        for field_name in ("DateTimeOriginal", "DateTimeDigitized", "DateTime"):
            tag_id = tag_map.get(field_name)
            if tag_id and tag_id in exif_data:
                dt = _parse_exif_datetime(str(exif_data[tag_id]))
                if dt:
                    return dt
    except Exception:
        pass
    return None


def _image_to_bytes(img: Image.Image, max_size: tuple[int, int], quality: int = 85) -> bytes:
    """Resize image and return JPEG bytes."""
    img = img.copy()
    img.thumbnail(max_size, Image.LANCZOS)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _image_to_b64(img: Image.Image, max_size: tuple[int, int]) -> str:
    """Resize image, convert to JPEG base64."""
    return base64.b64encode(_image_to_bytes(img, max_size)).decode()


def _thumbnail_filename(file_path: str) -> str:
    """Deterministic filename for a photo's thumbnail: sha256[:16].jpg"""
    return hashlib.sha256(file_path.encode()).hexdigest()[:16] + ".jpg"


def save_thumbnail_to_disk(result: "PhotoScanResult", thumbnails_dir: str) -> Optional[str]:
    """
    Write the thumbnail bytes for a scan result to disk.
    Returns the filename (not full path) or None on failure.
    Idempotent — skips write if file already exists.
    """
    if not result.thumbnail_b64:
        return None
    filename = _thumbnail_filename(result.file_path)
    dest = Path(thumbnails_dir) / filename
    if not dest.exists():
        dest.write_bytes(base64.b64decode(result.thumbnail_b64))
    return filename


def scan_photo(file_path: str) -> PhotoScanResult:
    """Synchronous scan of a single photo. Call via asyncio.to_thread for async."""
    path = Path(file_path)
    result = PhotoScanResult(
        file_path=file_path,
        filename=path.name,
        taken_at=None,
        file_size=0,
        width=None,
        height=None,
        thumbnail_b64=None,
        full_b64=None,
    )

    try:
        result.file_size = path.stat().st_size
        with Image.open(file_path) as img:
            result.taken_at = _extract_taken_at(img)
            result.width, result.height = img.size
            result.thumbnail_b64 = _image_to_b64(img, THUMBNAIL_SIZE)
            result.full_b64 = _image_to_b64(img, MAX_CLAUDE_IMAGE_SIZE)
    except Exception as e:
        result.error = str(e)

    return result


def _file_date_in_range(
    path: Path,
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
) -> bool:
    """
    Quick file-system date check using st_mtime and st_ctime.
    No image opening needed — used to skip files before the expensive PIL scan.
    Returns True if the file MIGHT be in range (fail-open).
    """
    if not start_date and not end_date:
        return True
    try:
        stat = path.stat()
        dates = [
            datetime.datetime.fromtimestamp(stat.st_mtime).date(),
            datetime.datetime.fromtimestamp(stat.st_ctime).date(),
        ]
        for d in dates:
            in_range = True
            if start_date and d < start_date:
                in_range = False
            if end_date and d > end_date:
                in_range = False
            if in_range:
                return True
        return False
    except OSError:
        return True  # can't stat → include it


async def scan_directory(
    directory: str,
    progress_callback=None,
    start_date: Optional[datetime.date] = None,
    end_date: Optional[datetime.date] = None,
) -> list[PhotoScanResult]:
    """
    Walk a directory and scan supported image files.
    start_date/end_date do a fast file-system pre-check before opening images,
    so only in-range files pay the PIL cost.
    progress_callback(current, total, filename) called for each file processed.
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    all_files = [
        f for f in dir_path.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    all_files.sort(key=lambda f: f.stat().st_mtime)

    # Fast file-system date pre-filter — no image opening
    candidates = [f for f in all_files if _file_date_in_range(f, start_date, end_date)]

    results = []
    for i, file_path in enumerate(candidates):
        if progress_callback:
            progress_callback(i + 1, len(candidates), file_path.name)
        result = await asyncio.to_thread(scan_photo, str(file_path))
        results.append(result)

    return results


def sort_by_timestamp(results: list[PhotoScanResult]) -> list[PhotoScanResult]:
    """Sort photos oldest-first, pushing photos with no timestamp to the end."""
    def sort_key(r: PhotoScanResult):
        return r.taken_at or datetime.datetime(9999, 1, 1)
    return sorted(results, key=sort_key)
