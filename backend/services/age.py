"""
Compute human-readable age strings from birth date and photo date.
Used to enrich milestone approximate_age when a child profile has a birth_date.
"""
import datetime
from typing import Optional


def compute_age_string(birth_date: datetime.datetime, taken_at: datetime.datetime) -> str:
    """
    Return a warm, readable age string like "3 months", "1 year 2 months", "newborn".
    Always from the child's perspective (birth_date → taken_at).
    """
    if taken_at < birth_date:
        return "before birth"

    delta_days = (taken_at - birth_date).days

    if delta_days <= 13:
        return "newborn"
    if delta_days < 30:
        weeks = delta_days // 7
        return f"{weeks} week{'s' if weeks != 1 else ''} old"

    total_months = (
        (taken_at.year - birth_date.year) * 12
        + (taken_at.month - birth_date.month)
    )
    if taken_at.day < birth_date.day:
        total_months -= 1
    total_months = max(0, total_months)

    if total_months < 12:
        return f"{total_months} month{'s' if total_months != 1 else ''} old"

    years = total_months // 12
    remaining_months = total_months % 12
    if remaining_months == 0:
        return f"{years} year{'s' if years != 1 else ''} old"
    return f"{years} year{'s' if years != 1 else ''} {remaining_months} month{'s' if remaining_months != 1 else ''} old"


def enrich_age(
    approximate_age: Optional[str],
    birth_date: Optional[datetime.datetime],
    taken_at: Optional[datetime.datetime],
) -> Optional[str]:
    """
    Return computed age string if approximate_age is None and we have enough data.
    Leaves existing approximate_age values untouched.
    """
    if approximate_age:
        return approximate_age
    if birth_date and taken_at:
        return compute_age_string(birth_date, taken_at)
    return None
