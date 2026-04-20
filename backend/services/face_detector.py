"""
Local face detection using OpenCV's Haar cascade. Zero-cost prefilter
that runs before any Claude API call — eliminates photos with no faces
at all so we don't pay Haiku tokens for them.

Haar cascades are crude (some false negatives on side profiles and babies
whose faces are tiny in the frame), so we run on the 400px thumbnail with
lenient parameters and treat errors as "keep" (fail-open).
"""
import asyncio
import base64
import io
import os
from typing import Optional

import numpy as np
from PIL import Image

from services.photo_scanner import PhotoScanResult

FACE_CONCURRENCY = int(os.getenv("FACE_CONCURRENCY", "4"))

_cascade = None
_cascade_init_failed = False


def _get_cascade():
    """Lazy-load the Haar cascade. cv2 import can be slow; defer it."""
    global _cascade, _cascade_init_failed
    if _cascade is not None or _cascade_init_failed:
        return _cascade
    try:
        import cv2
        path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        cascade = cv2.CascadeClassifier(path)
        if cascade.empty():
            _cascade_init_failed = True
            return None
        _cascade = cascade
        return _cascade
    except Exception:
        _cascade_init_failed = True
        return None


def has_face(photo: PhotoScanResult) -> bool:
    """
    Run Haar-cascade face detection on the thumbnail.
    Returns True if at least one face is detected OR if detection failed
    (fail-open — we'd rather pay a Haiku call than miss a milestone).
    """
    if not photo.thumbnail_b64:
        return True
    cascade = _get_cascade()
    if cascade is None:
        return True
    try:
        import cv2
        img_bytes = base64.b64decode(photo.thumbnail_b64)
        img = Image.open(io.BytesIO(img_bytes)).convert("L")  # grayscale
        arr = np.array(img)
        faces = cascade.detectMultiScale(
            arr,
            scaleFactor=1.15,
            minNeighbors=3,
            minSize=(24, 24),
        )
        return len(faces) > 0
    except Exception:
        return True


async def face_filter_batch(
    photos: list[PhotoScanResult],
    progress_callback=None,
    concurrency: int = FACE_CONCURRENCY,
) -> list[PhotoScanResult]:
    """
    Parallel face detection. Returns only photos with at least one detected face.
    Preserves input ordering.
    """
    total = len(photos)
    sem = asyncio.Semaphore(concurrency)
    passed_count = 0
    done = 0

    async def check(p: PhotoScanResult) -> tuple[PhotoScanResult, bool]:
        nonlocal done, passed_count
        async with sem:
            ok = await asyncio.to_thread(has_face, p)
        done += 1
        if ok:
            passed_count += 1
        if progress_callback:
            progress_callback(done, total, p.filename, passed_count)
        return p, ok

    results = await asyncio.gather(*(check(p) for p in photos))
    return [p for p, ok in results if ok]
