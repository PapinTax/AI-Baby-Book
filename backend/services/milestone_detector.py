"""
Milestone detector using Claude Vision API.
Analyzes photos and returns structured milestone detections with confidence scores.

Design decisions:
- Uses claude-haiku for speed/cost on bulk scans; caller can override with sonnet for accuracy pass
- Batches photos but keeps prompts short to stay within token budget
- Returns structured JSON so parsing is deterministic
"""
import json
import os
from dataclasses import dataclass
from typing import Optional

import anthropic

from services.photo_scanner import PhotoScanResult

client = anthropic.Anthropic(api_key=os.getenv("ANTHROPIC_API_KEY"))

DEFAULT_MODEL = "claude-haiku-4-5-20251001"
ACCURACY_MODEL = "claude-sonnet-4-6"

MILESTONE_TAXONOMY = {
    "first_smile": "Baby smiling — earliest captured smile",
    "first_laugh": "Baby laughing or giggling",
    "tummy_time": "Baby on stomach lifting head",
    "first_roll": "Baby rolling over",
    "sitting_up": "Baby sitting unassisted",
    "first_crawl": "Baby crawling on hands and knees",
    "first_pull_to_stand": "Baby pulling themselves to standing position",
    "first_stand": "Baby standing (may be holding something)",
    "first_steps": "Baby taking first steps — wobbly, arms out",
    "first_walk": "Baby walking with confidence",
    "first_solid_food": "Baby eating solid food, in high chair or at table",
    "first_birthday": "First birthday — cake with 1 candle, decorations",
    "birthday": "Birthday celebration — cake, candles, gathering",
    "first_bath": "Baby in bath or bathtub",
    "first_tooth": "Visible new tooth in baby's mouth",
    "vacation": "Family at travel destination, beach, landmark",
    "holiday": "Holiday scene — Christmas, Halloween, Thanksgiving etc.",
    "memorable_moment": "Clearly special family moment not covered above",
}

SYSTEM_PROMPT = """You are an expert at identifying childhood developmental milestones and memorable family moments in photos.

Analyze the photo and determine if it captures a milestone moment for a baby or young child (typically 0-3 years old).

Return ONLY valid JSON in this exact format:
{
  "has_milestone": true or false,
  "milestone_type": "<type from taxonomy or null>",
  "label": "<short human-readable label>",
  "description": "<1-2 warm, parent-friendly sentences describing the moment>",
  "confidence": <0.0 to 1.0>,
  "approximate_age": "<e.g. '~6 months', '~1 year', 'newborn', or null if unknown>",
  "evidence": ["<visual cue 1>", "<visual cue 2>"]
}

Milestone taxonomy:
""" + "\n".join(f"- {k}: {v}" for k, v in MILESTONE_TAXONOMY.items()) + """

Rules:
- Set has_milestone=false if no child/baby is the focus, or no milestone is present
- Confidence: 0.9+ only if very clear visual evidence. 0.7-0.89 = likely. 0.5-0.69 = possible.
- Keep description warm and parent-friendly, like a caption in a baby book
- If multiple milestones apply, pick the most significant one
- Never guess — if unclear, lower the confidence score
"""


@dataclass
class MilestoneDetection:
    has_milestone: bool
    milestone_type: Optional[str]
    label: str
    description: Optional[str]
    confidence: float
    approximate_age: Optional[str]
    evidence: list[str]
    photo_path: str
    raw_response: Optional[str] = None
    error: Optional[str] = None


def _build_message(photo: PhotoScanResult, model: str) -> dict:
    """Build a Claude API message for a single photo."""
    return {
        "role": "user",
        "content": [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": photo.media_type,
                    "data": photo.full_b64,
                },
            },
            {
                "type": "text",
                "text": "Analyze this photo for childhood milestone moments. Return only the JSON response.",
            },
        ],
    }


def _parse_response(raw: str, photo_path: str) -> MilestoneDetection:
    """Parse Claude's JSON response into a MilestoneDetection."""
    try:
        # Strip markdown code fences if present
        text = raw.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        data = json.loads(text.strip())
        return MilestoneDetection(
            has_milestone=bool(data.get("has_milestone", False)),
            milestone_type=data.get("milestone_type"),
            label=data.get("label", "Milestone"),
            description=data.get("description"),
            confidence=float(data.get("confidence", 0.0)),
            approximate_age=data.get("approximate_age"),
            evidence=data.get("evidence", []),
            photo_path=photo_path,
            raw_response=raw,
        )
    except (json.JSONDecodeError, KeyError, TypeError) as e:
        return MilestoneDetection(
            has_milestone=False,
            milestone_type=None,
            label="Parse error",
            description=None,
            confidence=0.0,
            approximate_age=None,
            evidence=[],
            photo_path=photo_path,
            raw_response=raw,
            error=str(e),
        )


def detect_milestone(photo: PhotoScanResult, model: str = DEFAULT_MODEL) -> MilestoneDetection:
    """
    Synchronous milestone detection for a single photo.
    Use via asyncio.to_thread for async contexts.
    """
    if not photo.full_b64:
        return MilestoneDetection(
            has_milestone=False,
            milestone_type=None,
            label="No image data",
            description=None,
            confidence=0.0,
            approximate_age=None,
            evidence=[],
            photo_path=photo.file_path,
            error="Photo could not be loaded",
        )

    try:
        response = client.messages.create(
            model=model,
            max_tokens=512,
            system=SYSTEM_PROMPT,
            messages=[_build_message(photo, model)],
        )
        raw = response.content[0].text
        return _parse_response(raw, photo.file_path)
    except anthropic.APIError as e:
        return MilestoneDetection(
            has_milestone=False,
            milestone_type=None,
            label="API error",
            description=None,
            confidence=0.0,
            approximate_age=None,
            evidence=[],
            photo_path=photo.file_path,
            error=str(e),
        )


async def detect_milestones_batch(
    photos: list[PhotoScanResult],
    model: str = DEFAULT_MODEL,
    min_confidence: float = 0.5,
    progress_callback=None,
) -> list[MilestoneDetection]:
    """
    Detect milestones across a list of photos.
    Only returns detections above min_confidence threshold.
    progress_callback(current, total, filename) called per photo.
    """
    import asyncio
    results = []
    for i, photo in enumerate(photos):
        if progress_callback:
            progress_callback(i + 1, len(photos), photo.filename)
        detection = await asyncio.to_thread(detect_milestone, photo, model)
        if detection.has_milestone and detection.confidence >= min_confidence:
            results.append(detection)
    return results
