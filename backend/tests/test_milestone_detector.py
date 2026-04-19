"""Tests for milestone detector — mocks Claude API calls."""
import json
import pytest
from unittest.mock import MagicMock, patch

from services.photo_scanner import PhotoScanResult
from services.milestone_detector import (
    detect_milestone,
    _parse_response,
    MilestoneDetection,
    DEFAULT_MODEL,
)


def _make_photo(b64="fakeb64") -> PhotoScanResult:
    return PhotoScanResult(
        file_path="/test/baby.jpg",
        filename="baby.jpg",
        taken_at=None,
        file_size=1000,
        width=400,
        height=400,
        thumbnail_b64=b64,
        full_b64=b64,
    )


GOOD_RESPONSE = json.dumps({
    "has_milestone": True,
    "milestone_type": "first_steps",
    "label": "First Steps",
    "description": "Little one takes their very first steps!",
    "confidence": 0.88,
    "approximate_age": "~11 months",
    "evidence": ["upright posture", "arms extended for balance", "forward motion"],
})

NO_MILESTONE_RESPONSE = json.dumps({
    "has_milestone": False,
    "milestone_type": None,
    "label": "No milestone",
    "description": None,
    "confidence": 0.1,
    "approximate_age": None,
    "evidence": [],
})


class TestParseResponse:
    def test_parses_valid_json(self):
        result = _parse_response(GOOD_RESPONSE, "/test.jpg")
        assert result.has_milestone is True
        assert result.milestone_type == "first_steps"
        assert result.confidence == 0.88
        assert len(result.evidence) == 3

    def test_parses_no_milestone(self):
        result = _parse_response(NO_MILESTONE_RESPONSE, "/test.jpg")
        assert result.has_milestone is False
        assert result.confidence == 0.1

    def test_handles_markdown_fences(self):
        wrapped = f"```json\n{GOOD_RESPONSE}\n```"
        result = _parse_response(wrapped, "/test.jpg")
        assert result.has_milestone is True

    def test_handles_invalid_json(self):
        result = _parse_response("not json at all", "/test.jpg")
        assert result.error is not None
        assert result.has_milestone is False

    def test_handles_empty_string(self):
        result = _parse_response("", "/test.jpg")
        assert result.error is not None


class TestDetectMilestone:
    def test_returns_error_for_missing_image_data(self):
        photo = _make_photo(b64=None)
        result = detect_milestone(photo)
        assert result.error is not None
        assert result.has_milestone is False

    @patch("services.milestone_detector.client")
    def test_successful_detection(self, mock_client):
        mock_response = MagicMock()
        mock_response.content = [MagicMock(text=GOOD_RESPONSE)]
        mock_client.messages.create.return_value = mock_response

        photo = _make_photo()
        result = detect_milestone(photo)

        assert result.has_milestone is True
        assert result.milestone_type == "first_steps"
        assert result.confidence == 0.88
        mock_client.messages.create.assert_called_once()

    @patch("services.milestone_detector.client")
    def test_api_error_returns_graceful_result(self, mock_client):
        import anthropic
        mock_client.messages.create.side_effect = anthropic.APIError(
            message="Rate limit", request=MagicMock(), body={}
        )
        photo = _make_photo()
        result = detect_milestone(photo)
        assert result.has_milestone is False
        assert result.error is not None
