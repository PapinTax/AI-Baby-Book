"""Tests for the photo scanner service."""
import datetime
import io
import os
import tempfile

import pytest
from PIL import Image

from services.photo_scanner import (
    PhotoScanResult,
    scan_photo,
    sort_by_timestamp,
    SUPPORTED_EXTENSIONS,
)


def _make_test_image(path: str, size=(100, 100)):
    """Create a minimal test JPEG."""
    img = Image.new("RGB", size, color=(100, 150, 200))
    img.save(path, format="JPEG")


class TestScanPhoto:
    def test_scans_valid_jpeg(self, tmp_path):
        img_path = str(tmp_path / "test.jpg")
        _make_test_image(img_path)
        result = scan_photo(img_path)

        assert result.filename == "test.jpg"
        assert result.file_path == img_path
        assert result.width == 100
        assert result.height == 100
        assert result.file_size > 0
        assert result.thumbnail_b64 is not None
        assert result.full_b64 is not None
        assert result.error is None

    def test_handles_missing_file(self, tmp_path):
        result = scan_photo(str(tmp_path / "nonexistent.jpg"))
        assert result.error is not None

    def test_no_exif_returns_none_timestamp(self, tmp_path):
        img_path = str(tmp_path / "no_exif.jpg")
        _make_test_image(img_path)
        result = scan_photo(img_path)
        # Plain PIL images have no EXIF — taken_at should be None
        assert result.taken_at is None


class TestSortByTimestamp:
    def test_sorts_oldest_first(self):
        older = PhotoScanResult(
            file_path="/a.jpg", filename="a.jpg",
            taken_at=datetime.datetime(2020, 1, 1),
            file_size=100, width=100, height=100,
            thumbnail_b64=None, full_b64=None,
        )
        newer = PhotoScanResult(
            file_path="/b.jpg", filename="b.jpg",
            taken_at=datetime.datetime(2022, 6, 15),
            file_size=100, width=100, height=100,
            thumbnail_b64=None, full_b64=None,
        )
        no_date = PhotoScanResult(
            file_path="/c.jpg", filename="c.jpg",
            taken_at=None,
            file_size=100, width=100, height=100,
            thumbnail_b64=None, full_b64=None,
        )
        result = sort_by_timestamp([no_date, newer, older])
        assert result[0].filename == "a.jpg"
        assert result[1].filename == "b.jpg"
        assert result[2].filename == "c.jpg"

    def test_empty_list(self):
        assert sort_by_timestamp([]) == []


class TestSupportedExtensions:
    def test_includes_common_formats(self):
        for ext in [".jpg", ".jpeg", ".png", ".heic"]:
            assert ext in SUPPORTED_EXTENSIONS
