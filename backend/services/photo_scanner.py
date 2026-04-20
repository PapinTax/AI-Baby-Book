"""
Scans a directory for photos, extracts EXIF metadata, generates thumbnails.
Returns structured PhotoScanResult objects — no DB writes happen here.
"""
import asyncio
import base64
import datetime
import hashlib
import io
import json
import os
import platform
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ExifTags
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

SUPPORTED_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif", ".webp"}
IMAGE_EXTENSIONS = SUPPORTED_EXTENSIONS
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
THUMBNAIL_SIZE = (400, 400)
MAX_CLAUDE_IMAGE_SIZE = (1024, 1024)

# Concurrency for local I/O+CPU work (EXIF reads, thumbnail gen, face detection).
# Tunable via env for users on low-RAM machines.
SCAN_CONCURRENCY = int(os.getenv("SCAN_CONCURRENCY", "8"))


# ── PowerShell Shell property reader (Windows / iCloud) ───────────────────────

_PS_DATE_SCRIPT = r"""
$dir = $env:SCAN_DIR
$shell = New-Object -ComObject Shell.Application
$nsCache = @{}
$out = [System.Collections.Generic.List[object]]::new()
Get-ChildItem $dir -Recurse -File | Where-Object {
    $_.Extension -match '(?i)\.(heic|heif|jpg|jpeg|png|tiff|tif|webp)$'
} | ForEach-Object {
    $d = $_.DirectoryName
    if (-not $nsCache.ContainsKey($d)) { $nsCache[$d] = $shell.NameSpace($d) }
    $ns = $nsCache[$d]
    $item = if ($ns) { $ns.ParseName($_.Name) } else { $null }
    $dt = if ($item) { $item.ExtendedProperty('System.Photo.DateTaken') } else { $null }
    $out.Add([PSCustomObject]@{
        p = $_.FullName
        d = if ($dt) { $dt.ToString('yyyy-MM-dd') } else { '' }
    })
}
$out | ConvertTo-Json -Compress -Depth 1
"""


def _get_dates_via_shell_sync(directory: str) -> Optional[dict[str, Optional[datetime.date]]]:
    """
    Windows-only: read System.Photo.DateTaken from the Shell property store.
    iCloud populates this from its local index — no file download triggered.
    Returns None if not on Windows or if PowerShell fails.
    """
    if platform.system() != "Windows":
        return None
    try:
        env = os.environ.copy()
        env["SCAN_DIR"] = directory
        proc = subprocess.run(
            ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_DATE_SCRIPT],
            capture_output=True, text=True, timeout=300, env=env,
        )
        if proc.returncode != 0 or not proc.stdout.strip():
            return None
        raw = json.loads(proc.stdout)
        if isinstance(raw, dict):
            raw = [raw]
        result: dict[str, Optional[datetime.date]] = {}
        for item in raw:
            path = item.get("p", "").lower()
            date_str = item.get("d", "")
            if path:
                result[path] = (
                    datetime.datetime.strptime(date_str, "%Y-%m-%d").date()
                    if date_str else None
                )
        return result
    except Exception:
        return None



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


def scan_photo(file_path: str, include_full: bool = False) -> PhotoScanResult:
    """
    Synchronous scan of a single photo. Always generates the 400px thumbnail.
    Only generates the 1024px full_b64 when include_full=True — defer that
    for photos that will actually be sent to Claude for detection.
    Call via asyncio.to_thread for async.
    """
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
            if include_full:
                result.full_b64 = _image_to_b64(img, MAX_CLAUDE_IMAGE_SIZE)
    except Exception as e:
        result.error = str(e)

    return result


def hydrate_full_b64(result: PhotoScanResult) -> PhotoScanResult:
    """
    Populate full_b64 on an existing scan result that was scanned without it.
    Dispatches to video or image path automatically. No-op if already hydrated.
    """
    if result.full_b64 or result.error:
        return result
    ext = Path(result.file_path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        try:
            import cv2
            import numpy as np
            cap = cv2.VideoCapture(result.file_path)
            try:
                frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
                cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_count // 2))
                ret, frame = cap.read()
                if ret and frame is not None:
                    rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                    img = Image.fromarray(rgb)
                    result.full_b64 = _image_to_b64(img, MAX_CLAUDE_IMAGE_SIZE)
            finally:
                cap.release()
        except Exception as e:
            result.error = str(e)
    else:
        try:
            with Image.open(result.file_path) as img:
                result.full_b64 = _image_to_b64(img, MAX_CLAUDE_IMAGE_SIZE)
        except Exception as e:
            result.error = str(e)
    return result


def _extract_video_date(path: Path) -> Optional[datetime.datetime]:
    """
    Try ffprobe for the QuickTime/MP4 creation_time tag, then fall back to
    the file's mtime. ffprobe is optional — if absent, mtime is used silently.
    """
    try:
        proc = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_entries", "format_tags=creation_time",
                str(path),
            ],
            capture_output=True, text=True, timeout=10,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            data = json.loads(proc.stdout)
            ct = (data.get("format") or {}).get("tags", {}).get("creation_time")
            if ct:
                return datetime.datetime.fromisoformat(
                    ct.replace("Z", "+00:00")
                ).replace(tzinfo=None)
    except Exception:
        pass
    try:
        return datetime.datetime.fromtimestamp(path.stat().st_mtime)
    except Exception:
        return None


def _best_video_frame(file_path: str) -> Optional[Image.Image]:
    """
    Open a video and return the sharpest frame from 5 evenly-spaced samples.
    Returns None if the file cannot be read.
    """
    try:
        import cv2
        import numpy as np
        cap = cv2.VideoCapture(file_path)
        if not cap.isOpened():
            return None
        try:
            frame_count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
            if frame_count <= 0:
                return None
            positions = [max(0, int(frame_count * p)) for p in (0.20, 0.35, 0.50, 0.65, 0.80)]
            best_frame, best_score = None, -1.0
            for pos in positions:
                cap.set(cv2.CAP_PROP_POS_FRAMES, pos)
                ret, frame = cap.read()
                if not ret or frame is None:
                    continue
                gray = cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY)
                score = float(cv2.Laplacian(gray, cv2.CV_64F).var())
                if score > best_score:
                    best_score = score
                    best_frame = frame
            if best_frame is None:
                return None
            rgb = cv2.cvtColor(best_frame, cv2.COLOR_BGR2RGB)
            return Image.fromarray(rgb)
        finally:
            cap.release()
    except Exception:
        return None


def scan_video(file_path: str, include_full: bool = False) -> PhotoScanResult:
    """
    Extract the sharpest frame from a video and return it as a PhotoScanResult.
    Date comes from QuickTime/MP4 metadata (via ffprobe) or file mtime.
    """
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
        result.taken_at = _extract_video_date(path)
        img = _best_video_frame(file_path)
        if img is None:
            result.error = "Could not extract frame from video"
            return result
        result.width, result.height = img.size
        result.thumbnail_b64 = _image_to_b64(img, THUMBNAIL_SIZE)
        if include_full:
            result.full_b64 = _image_to_b64(img, MAX_CLAUDE_IMAGE_SIZE)
    except Exception as e:
        result.error = str(e)
    return result


def scan_file(file_path: str, include_full: bool = False) -> PhotoScanResult:
    """Dispatch to scan_video or scan_photo based on file extension."""
    if Path(file_path).suffix.lower() in VIDEO_EXTENSIONS:
        return scan_video(file_path, include_full=include_full)
    return scan_photo(file_path, include_full=include_full)


def _is_cloud_placeholder(path: Path) -> bool:
    """
    Windows-only: returns True if the file is an iCloud placeholder
    (not yet downloaded). Checks FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS.
    Instant — no file open, no download triggered.
    """
    if platform.system() != "Windows":
        return False
    try:
        import ctypes
        RECALL_ON_DATA_ACCESS = 0x00400000
        RECALL_ON_OPEN = 0x00040000
        attrs = ctypes.windll.kernel32.GetFileAttributesW(str(path))
        if attrs == 0xFFFFFFFF:
            return False
        return bool(attrs & (RECALL_ON_DATA_ACCESS | RECALL_ON_OPEN))
    except Exception:
        return False



def _read_exif_date_only(file_path: Path) -> Optional[datetime.date]:
    """Read EXIF date from an image without generating a thumbnail."""
    try:
        with Image.open(file_path) as img:
            dt = _extract_taken_at(img)
            return dt.date() if dt else None
    except Exception:
        return None


def _read_date_only(file_path: Path) -> Optional[datetime.date]:
    """Date-only read for any supported file type (image or video)."""
    if file_path.suffix.lower() in VIDEO_EXTENSIONS:
        dt = _extract_video_date(file_path)
        return dt.date() if dt else None
    return _read_exif_date_only(file_path)


def _date_in_range(
    d: Optional[datetime.date],
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
) -> bool:
    if d is None:
        return True  # no date → include (fail-open)
    if start_date and d < start_date:
        return False
    if end_date and d > end_date:
        return False
    return True


def list_photo_files(directory: str) -> tuple[list[Path], int]:
    """
    Enumerate supported image files under `directory`, excluding iCloud placeholders.
    Returns (local_files, skipped_cloud_count).
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    all_files = [
        f for f in dir_path.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    all_files.sort(key=lambda f: f.stat().st_mtime)

    local_files = [f for f in all_files if not _is_cloud_placeholder(f)]
    skipped_cloud = len(all_files) - len(local_files)
    return local_files, skipped_cloud


async def filter_files_by_exif_date(
    files: list[Path],
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
    progress_callback=None,
    concurrency: int = SCAN_CONCURRENCY,
) -> list[Path]:
    """
    Parallel EXIF-date-only pass. Files with unreadable dates are kept (fail-open).
    Uses asyncio.gather + semaphore; preserves input ordering in the output.
    """
    if not (start_date or end_date):
        return files
    total = len(files)
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def check(f: Path) -> tuple[Path, bool]:
        nonlocal done
        async with sem:
            d = await asyncio.to_thread(_read_date_only, f)
        done += 1
        if progress_callback and (done % 25 == 0 or done == total):
            progress_callback(done, total, f.name)
        return f, _date_in_range(d, start_date, end_date)

    results = await asyncio.gather(*(check(f) for f in files))
    return [f for f, ok in results if ok]


async def scan_files(
    files: list[Path],
    progress_callback=None,
    include_full: bool = False,
    concurrency: int = SCAN_CONCURRENCY,
) -> list[PhotoScanResult]:
    """
    Parallel scan (thumbnail + optional full_b64) on each file.
    Output preserves input ordering so downstream sort stays stable.
    """
    total = len(files)
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(f: Path) -> PhotoScanResult:
        nonlocal done
        async with sem:
            r = await asyncio.to_thread(scan_file, str(f), include_full)
        done += 1
        if progress_callback and (done % 5 == 0 or done == total):
            progress_callback(done, total, f.name)
        return r

    return list(await asyncio.gather(*(one(f) for f in files)))


# Legacy combined entry — kept for any callers still using it.
async def scan_directory(
    directory: str,
    progress_callback=None,
    start_date: Optional[datetime.date] = None,
    end_date: Optional[datetime.date] = None,
) -> tuple[list[PhotoScanResult], int]:
    local_files, skipped_cloud = list_photo_files(directory)
    candidates = await filter_files_by_exif_date(
        local_files, start_date, end_date,
        progress_callback=(
            (lambda c, t, n: progress_callback(c, t, n, "date_checking"))
            if progress_callback else None
        ),
    )
    results = await scan_files(
        candidates,
        progress_callback=(
            (lambda c, t, n: progress_callback(c, t, n, "scanning"))
            if progress_callback else None
        ),
    )
    return results, skipped_cloud


def sort_by_timestamp(results: list[PhotoScanResult]) -> list[PhotoScanResult]:
    """Sort photos oldest-first, pushing photos with no timestamp to the end."""
    def sort_key(r: PhotoScanResult):
        return r.taken_at or datetime.datetime(9999, 1, 1)
    return sorted(results, key=sort_key)
