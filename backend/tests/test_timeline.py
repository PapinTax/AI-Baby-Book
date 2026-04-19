"""Tests for timeline builder and deduplication."""
import datetime
import pytest

from services.timeline import TimelineEntry, deduplicate_timeline


def _entry(
    milestone_type: str,
    taken_at: datetime.datetime,
    confidence: float = 0.8,
    milestone_id: int = 1,
) -> TimelineEntry:
    return TimelineEntry(
        milestone_id=milestone_id,
        photo_id=milestone_id,
        photo_path=f"/photo_{milestone_id}.jpg",
        thumbnail_path=None,
        milestone_type=milestone_type,
        label=milestone_type.replace("_", " ").title(),
        description=None,
        confidence=confidence,
        approximate_age=None,
        taken_at=taken_at,
        child_name=None,
        approved=True,
    )


class TestDeduplicateTimeline:
    def test_keeps_distinct_types(self):
        entries = [
            _entry("first_steps", datetime.datetime(2023, 1, 1), milestone_id=1),
            _entry("first_smile", datetime.datetime(2022, 6, 1), milestone_id=2),
        ]
        result = deduplicate_timeline(entries)
        assert len(result) == 2

    def test_deduplicates_same_type_within_window(self):
        entries = [
            _entry("first_steps", datetime.datetime(2023, 1, 1), confidence=0.7, milestone_id=1),
            _entry("first_steps", datetime.datetime(2023, 1, 2), confidence=0.9, milestone_id=2),
        ]
        result = deduplicate_timeline(entries)
        assert len(result) == 1
        assert result[0].confidence == 0.9  # kept higher confidence

    def test_keeps_same_type_outside_window(self):
        entries = [
            _entry("birthday", datetime.datetime(2022, 6, 1), milestone_id=1),
            _entry("birthday", datetime.datetime(2023, 6, 1), milestone_id=2),
        ]
        result = deduplicate_timeline(entries)
        assert len(result) == 2

    def test_empty_list(self):
        assert deduplicate_timeline([]) == []

    def test_output_is_sorted_by_timestamp(self):
        entries = [
            _entry("first_walk", datetime.datetime(2023, 3, 1), milestone_id=3),
            _entry("first_smile", datetime.datetime(2022, 1, 1), milestone_id=1),
            _entry("first_steps", datetime.datetime(2023, 1, 1), milestone_id=2),
        ]
        result = deduplicate_timeline(entries)
        dates = [e.taken_at for e in result]
        assert dates == sorted(dates)
