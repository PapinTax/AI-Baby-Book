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
THUMBNAIL_SIZE = (400, 400)
MAX_CLAUDE_IMAGE_SIZE = (1024, 1024)


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



    """
    Open the image just enough to read the EXIF date — no thumbnail, no resize.
    Much faster than a full scan. Returns None if date can't be read.
    """
    try:
        with Image.open(file_path) as img:
            dt = _extract_taken_at(img)
            return dt.date() if dt else None
    except Exception:
        return None


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


async def scan_directory(
    directory: str,
    progress_callback=None,
    start_date: Optional[datetime.date] = None,
    end_date: Optional[datetime.date] = None,
) -> list[PhotoScanResult]:
    """
    Walk a directory and scan supported image files.
    When date range is provided, does a fast EXIF-date-only pass first so the
    expensive thumbnail/base64 generation only runs on in-range files.
    """
    dir_path = Path(directory)
    if not dir_path.is_dir():
        raise ValueError(f"Not a directory: {directory}")

    all_files = [
        f for f in dir_path.rglob("*")
        if f.is_file() and f.suffix.lower() in SUPPORTED_EXTENSIONS
    ]
    all_files.sort(key=lambda f: f.stat().st_mtime)

    # Skip iCloud placeholder files — they aren't downloaded yet.
    # Checking file attributes is instant and triggers no downloads.
    local_files = [f for f in all_files if not _is_cloud_placeholder(f)]
    skipped_cloud = len(all_files) - len(local_files)

    # Date filter using EXIF (safe — files are already local)
    if start_date or end_date:
        if progress_callback:
            progress_callback(0, len(local_files), "Checking dates...")
        candidates = []
        for i, f in enumerate(local_files):
            if progress_callback and i % 100 == 0:
                progress_callback(i, len(local_files), f.name)
            d = await asyncio.to_thread(_read_exif_date_only, f)
            if _date_in_range(d, start_date, end_date):
                candidates.append(f)
    else:
        candidates = local_files

    # Full scan (thumbnails + base64) on filtered local files only
    results = []
    for i, file_path in enumerate(candidates):
        if progress_callback:
            progress_callback(i + 1, len(candidates), file_path.name)
        result = await asyncio.to_thread(scan_photo, str(file_path))
        results.append(result)

    return results, skipped_cloud


def sort_by_timestamp(results: list[PhotoScanResult]) -> list[PhotoScanResult]:
    """Sort photos oldest-first, pushing photos with no timestamp to the end."""
    def sort_key(r: PhotoScanResult):
        return r.taken_at or datetime.datetime(9999, 1, 1)
    return sorted(results, key=sort_key)
