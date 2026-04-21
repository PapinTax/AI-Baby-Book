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
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from PIL import Image, ExifTags
try:
    from pillow_heif import register_heif_opener
    register_heif_opener()
except ImportError:
    pass

IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".heic", ".heif", ".tiff", ".tif", ".webp"}
VIDEO_EXTENSIONS = {".mov", ".mp4", ".m4v", ".avi", ".mkv", ".3gp"}
SUPPORTED_EXTENSIONS = IMAGE_EXTENSIONS | VIDEO_EXTENSIONS
THUMBNAIL_SIZE = (400, 400)
MAX_CLAUDE_IMAGE_SIZE = (1024, 1024)

# Tunable concurrency — lower on low-RAM machines via env
SCAN_CONCURRENCY = int(os.getenv("SCAN_CONCURRENCY", "8"))


# ── Windows Shell property reader (targeted file list) ───────────────────────
# Reads System.Photo.DateTaken via the Windows Shell API for a specific list
# of paths (written to a temp file to avoid command-line length limits).
# iCloud populates this from its local index — no file download triggered.

_PS_DATE_SCRIPT = r"""
$pathsFile = $env:PATHS_FILE
$paths = Get-Content -Path $pathsFile -Encoding UTF8
$shell = New-Object -ComObject Shell.Application
$nsCache = @{}
$out = [System.Collections.Generic.List[object]]::new()
foreach ($p in $paths) {
    if ([string]::IsNullOrWhiteSpace($p)) { continue }
    $dir = [System.IO.Path]::GetDirectoryName($p)
    $fname = [System.IO.Path]::GetFileName($p)
    if (-not $nsCache.ContainsKey($dir)) { $nsCache[$dir] = $shell.NameSpace($dir) }
    $ns = $nsCache[$dir]
    $item = if ($ns) { $ns.ParseName($fname) } else { $null }
    $dt = if ($item) { $item.ExtendedProperty('System.Photo.DateTaken') } else { $null }
    $out.Add([PSCustomObject]@{
        p = $p
        d = if ($dt) { $dt.ToString('yyyy-MM-ddTHH:mm:ss') } else { '' }
    })
}
if ($out.Count -eq 0) { '[]' } else { $out | ConvertTo-Json -Compress -Depth 1 }
"""


def _get_dates_for_paths(paths: list[Path]) -> dict[str, Optional[datetime.datetime]]:
    """
    Windows-only: read System.Photo.DateTaken for a specific list of image paths.
    Returns {str(path).lower(): datetime or None}. Returns {} on failure or non-Windows.
    """
    if platform.system() != "Windows" or not paths:
        return {}
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".txt", delete=False, encoding="utf-8"
        ) as f:
            f.write("\n".join(str(p) for p in paths))
            tmp_path = f.name
        try:
            env = os.environ.copy()
            env["PATHS_FILE"] = tmp_path
            proc = subprocess.run(
                ["powershell", "-NoProfile", "-NonInteractive", "-Command", _PS_DATE_SCRIPT],
                capture_output=True, text=True, timeout=300, env=env,
            )
            if proc.returncode != 0 or not proc.stdout.strip():
                return {}
            raw = json.loads(proc.stdout)
            if isinstance(raw, dict):
                raw = [raw]
            result: dict[str, Optional[datetime.datetime]] = {}
            for item in raw:
                path_str = item.get("p", "")
                date_str = item.get("d", "")
                if path_str:
                    result[path_str.lower()] = (
                        datetime.datetime.strptime(date_str, "%Y-%m-%dT%H:%M:%S")
                        if date_str else None
                    )
            return result
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass
    except Exception:
        return {}


# ── PhotoScanResult ───────────────────────────────────────────────────────────

@dataclass
class PhotoScanResult:
    file_path: str
    filename: str
    taken_at: Optional[datetime.datetime]
    file_size: int
    width: Optional[int]
    height: Optional[int]
    thumbnail_b64: Optional[str]        # base64 JPEG for API calls
    full_b64: Optional[str]             # base64 JPEG resized for Claude
    media_type: str = "image/jpeg"
    error: Optional[str] = None


# ── EXIF / image helpers ──────────────────────────────────────────────────────

def _parse_exif_datetime(raw: str) -> Optional[datetime.datetime]:
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


def _read_exif_datetime(file_path: Path) -> Optional[datetime.datetime]:
    """Open an image and return its EXIF datetime. Lighter than a full scan."""
    try:
        with Image.open(file_path) as img:
            return _extract_taken_at(img)
    except Exception:
        return None


def _image_to_bytes(img: Image.Image, max_size: tuple[int, int], quality: int = 85) -> bytes:
    img = img.copy()
    img.thumbnail(max_size, Image.LANCZOS)
    if img.mode in ("RGBA", "P", "LA"):
        img = img.convert("RGB")
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=quality)
    return buf.getvalue()


def _image_to_b64(img: Image.Image, max_size: tuple[int, int]) -> str:
    return base64.b64encode(_image_to_bytes(img, max_size)).decode()


def _thumbnail_filename(file_path: str) -> str:
    """Deterministic filename for a photo's thumbnail: sha256[:16].jpg"""
    return hashlib.sha256(file_path.encode()).hexdigest()[:16] + ".jpg"


def save_thumbnail_to_disk(result: "PhotoScanResult", thumbnails_dir: str) -> Optional[str]:
    """Write thumbnail bytes to disk. Idempotent — skips if already exists."""
    if not result.thumbnail_b64:
        return None
    filename = _thumbnail_filename(result.file_path)
    dest = Path(thumbnails_dir) / filename
    if not dest.exists():
        dest.write_bytes(base64.b64decode(result.thumbnail_b64))
    return filename


# ── Image scanning ────────────────────────────────────────────────────────────

def scan_photo(
    file_path: str,
    include_full: bool = False,
    pre_read_date: Optional[datetime.datetime] = None,
) -> PhotoScanResult:
    """
    Scan a single image. Always generates the 400px thumbnail.
    pre_read_date: if provided (from bulk Shell/EXIF pre-read), used directly —
    skips redundant in-file EXIF parsing. Falls back: EXIF → file mtime.
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
            if pre_read_date is not None:
                result.taken_at = pre_read_date
            else:
                result.taken_at = _extract_taken_at(img)  # None if no EXIF — no mtime fallback
            result.width, result.height = img.size
            result.thumbnail_b64 = _image_to_b64(img, THUMBNAIL_SIZE)
            if include_full:
                result.full_b64 = _image_to_b64(img, MAX_CLAUDE_IMAGE_SIZE)
    except Exception as e:
        result.error = str(e)
    return result


def hydrate_full_b64(result: PhotoScanResult) -> PhotoScanResult:
    """Populate full_b64 on a scan result that was scanned without it. No-op if already set."""
    if result.full_b64 or result.error:
        return result
    ext = Path(result.file_path).suffix.lower()
    if ext in VIDEO_EXTENSIONS:
        try:
            import cv2
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


# ── Video scanning ────────────────────────────────────────────────────────────

def _extract_video_date(path: Path) -> Optional[datetime.datetime]:
    """Try ffprobe for QuickTime creation_time, then fall back to file mtime."""
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
    """Return the sharpest frame from 5 evenly-spaced samples via Laplacian variance."""
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


def scan_video(
    file_path: str,
    include_full: bool = False,
    pre_read_date: Optional[datetime.datetime] = None,
) -> PhotoScanResult:
    """Extract the sharpest frame from a video and return as a PhotoScanResult."""
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
        result.taken_at = pre_read_date if pre_read_date is not None else _extract_video_date(path)
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


def scan_file(
    file_path: str,
    include_full: bool = False,
    pre_read_date: Optional[datetime.datetime] = None,
) -> PhotoScanResult:
    """Dispatch to scan_video or scan_photo based on file extension."""
    if Path(file_path).suffix.lower() in VIDEO_EXTENSIONS:
        return scan_video(file_path, include_full=include_full, pre_read_date=pre_read_date)
    return scan_photo(file_path, include_full=include_full, pre_read_date=pre_read_date)


# ── iCloud placeholder detection ──────────────────────────────────────────────

def _is_cloud_placeholder(path: Path) -> bool:
    """
    Windows-only: True if file is an iCloud placeholder not yet downloaded.
    Checks FILE_ATTRIBUTE_RECALL_ON_DATA_ACCESS / RECALL_ON_OPEN. Instant.
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


def list_photo_files(directory: str) -> tuple[list[Path], int]:
    """
    Enumerate supported files under directory, excluding iCloud placeholders.
    Returns (local_files, skipped_cloud_count). Sorted by mtime oldest-first.
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


# ── Bulk date reading ─────────────────────────────────────────────────────────

async def read_dates_bulk(
    files: list[Path],
    concurrency: int = SCAN_CONCURRENCY,
) -> dict[str, Optional[datetime.datetime]]:
    """
    Read taken_at datetime for all files. Primary source on Windows is the Shell
    property store (single PS call, no file opens, works for iCloud-indexed HEIC).
    Falls back to EXIF then file mtime — Photo.taken_at should never be NULL
    for a file that exists locally.

    Returns {str(path).lower(): datetime or None}.
    """
    result: dict[str, Optional[datetime.datetime]] = {}

    image_files = [f for f in files if f.suffix.lower() in IMAGE_EXTENSIONS]
    video_files = [f for f in files if f.suffix.lower() in VIDEO_EXTENSIONS]

    # Windows primary: one Shell property-store call for all image paths
    if platform.system() == "Windows" and image_files:
        shell_dates = await asyncio.to_thread(_get_dates_for_paths, image_files)
        result.update(shell_dates)

    # Parallel EXIF + mtime fallback for images Shell didn't cover
    missing_images = [f for f in image_files if str(f).lower() not in result]
    if missing_images:
        sem = asyncio.Semaphore(concurrency)

        async def _exif_one(f: Path) -> None:
            async with sem:
                dt = await asyncio.to_thread(_read_exif_datetime, f)
            result[str(f).lower()] = dt  # None if EXIF unreadable — no mtime fallback

        await asyncio.gather(*(_exif_one(f) for f in missing_images))

    # Videos: ffprobe / mtime
    if video_files:
        async def _video_date(f: Path) -> None:
            dt = await asyncio.to_thread(_extract_video_date, f)
            result[str(f).lower()] = dt

        await asyncio.gather(*(_video_date(f) for f in video_files))

    # Guarantee every file has an entry
    for f in files:
        result.setdefault(str(f).lower(), None)

    return result


# ── Burst clustering ──────────────────────────────────────────────────────────

def cluster_bursts(
    files: list[Path],
    dates: dict[str, Optional[datetime.datetime]],
    window_seconds: int = 60,
) -> list[Path]:
    """
    Group files taken within window_seconds of each other into burst clusters.
    Returns one representative per cluster — the largest file by byte size,
    a free proxy for image quality that requires no file opens.
    Files without a timestamp each form their own single-file cluster.
    Input should be sorted chronologically (oldest first).
    """
    if not files:
        return files

    clusters: list[list[Path]] = []
    current: list[Path] = []
    anchor: Optional[datetime.datetime] = None

    for f in files:
        dt = dates.get(str(f).lower())
        if dt is None or anchor is None:
            if current:
                clusters.append(current)
            current = [f]
            anchor = dt
        elif abs((dt - anchor).total_seconds()) <= window_seconds:
            current.append(f)
        else:
            clusters.append(current)
            current = [f]
            anchor = dt

    if current:
        clusters.append(current)

    return [max(cluster, key=lambda p: p.stat().st_size) for cluster in clusters]


# ── Parallel scan ─────────────────────────────────────────────────────────────

async def scan_files(
    files: list[Path],
    dates: Optional[dict[str, Optional[datetime.datetime]]] = None,
    progress_callback=None,
    include_full: bool = False,
    concurrency: int = SCAN_CONCURRENCY,
) -> list[PhotoScanResult]:
    """
    Parallel scan (thumbnail + optional full_b64) on each file.
    Pass dates to skip redundant in-file EXIF parsing for pre-read dates.
    Output preserves input ordering.
    """
    total = len(files)
    sem = asyncio.Semaphore(concurrency)
    done = 0

    async def one(f: Path) -> PhotoScanResult:
        nonlocal done
        pre_date = dates.get(str(f).lower()) if dates else None
        async with sem:
            r = await asyncio.to_thread(scan_file, str(f), include_full, pre_date)
        done += 1
        if progress_callback and (done % 5 == 0 or done == total):
            progress_callback(done, total, f.name)
        return r

    return list(await asyncio.gather(*(one(f) for f in files)))


# ── Date range helper ─────────────────────────────────────────────────────────

def _date_in_range(
    d: Optional[datetime.date],
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
) -> bool:
    if d is None:
        return True  # fail-open: include files whose date is unreadable
    if start_date and d < start_date:
        return False
    if end_date and d > end_date:
        return False
    return True


# ── Legacy entry points ───────────────────────────────────────────────────────

async def filter_files_by_exif_date(
    files: list[Path],
    start_date: Optional[datetime.date],
    end_date: Optional[datetime.date],
    progress_callback=None,
    concurrency: int = SCAN_CONCURRENCY,
) -> list[Path]:
    """Legacy EXIF-date filter. New code should use read_dates_bulk + inline filter."""
    if not (start_date or end_date):
        return files
    total = len(files)
    sem = asyncio.Semaphore(concurrency)
    done = 0

    def _read_date_only(file_path: Path) -> Optional[datetime.date]:
        if file_path.suffix.lower() in VIDEO_EXTENSIONS:
            dt = _extract_video_date(file_path)
            return dt.date() if dt else None
        dt = _read_exif_datetime(file_path)
        return dt.date() if dt else None

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


async def scan_directory(
    directory: str,
    progress_callback=None,
    start_date: Optional[datetime.date] = None,
    end_date: Optional[datetime.date] = None,
) -> tuple[list[PhotoScanResult], int]:
    """Legacy combined entry — kept for any callers still using it."""
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
    return sorted(results, key=lambda r: r.taken_at or datetime.datetime(9999, 1, 1))
