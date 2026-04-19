"""Tests for age computation utility."""
import datetime
import pytest

from services.age import compute_age_string, enrich_age

BD = datetime.datetime(2022, 3, 15)  # reference birth date


class TestComputeAgeString:
    def test_newborn_same_day(self):
        assert compute_age_string(BD, BD) == "newborn"

    def test_newborn_day_10(self):
        assert compute_age_string(BD, BD + datetime.timedelta(days=10)) == "newborn"

    def test_2_weeks(self):
        result = compute_age_string(BD, BD + datetime.timedelta(days=14))
        assert "week" in result

    def test_3_months(self):
        result = compute_age_string(BD, datetime.datetime(2022, 6, 15))
        assert "3 month" in result

    def test_1_year(self):
        result = compute_age_string(BD, datetime.datetime(2023, 3, 15))
        assert "1 year" in result
        assert "month" not in result

    def test_1_year_6_months(self):
        result = compute_age_string(BD, datetime.datetime(2023, 9, 15))
        assert "1 year" in result
        assert "6 month" in result

    def test_before_birth(self):
        result = compute_age_string(BD, BD - datetime.timedelta(days=5))
        assert result == "before birth"

    def test_11_months(self):
        result = compute_age_string(BD, datetime.datetime(2023, 2, 15))
        assert "11 month" in result


class TestEnrichAge:
    def test_returns_existing_if_set(self):
        result = enrich_age("~9 months", BD, BD + datetime.timedelta(days=280))
        assert result == "~9 months"

    def test_computes_when_none(self):
        taken = datetime.datetime(2022, 9, 15)
        result = enrich_age(None, BD, taken)
        assert result is not None
        assert "6 month" in result

    def test_returns_none_without_birth_date(self):
        result = enrich_age(None, None, datetime.datetime(2022, 9, 15))
        assert result is None

    def test_returns_none_without_taken_at(self):
        result = enrich_age(None, BD, None)
        assert result is None
