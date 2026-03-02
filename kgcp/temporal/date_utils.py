"""Flexible date parsing for temporal queries.

Supports:
- ISO dates: 2025-01-15, 2025-01-15T10:30:00+00:00
- Quarter notation: 2025-Q3 -> start of quarter
- Relative dates: 90d, 6m, 1y (days/months/years ago from now)
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

# Quarter start months: Q1=Jan, Q2=Apr, Q3=Jul, Q4=Oct
_QUARTER_START_MONTH = {1: 1, 2: 4, 3: 7, 4: 10}
_QUARTER_END_MONTH = {1: 4, 2: 7, 3: 10, 4: 1}

_RELATIVE_PATTERN = re.compile(r"^(\d+)([dmy])$", re.IGNORECASE)
_QUARTER_PATTERN = re.compile(r"^(\d{4})-Q([1-4])$", re.IGNORECASE)


def parse_date(value: str) -> str:
    """Parse a flexible date string into an ISO date string.

    Args:
        value: One of:
            - ISO date: "2025-01-15" or "2025-01-15T10:30:00+00:00"
            - Quarter: "2025-Q3" -> "2025-07-01T00:00:00+00:00"
            - Relative: "90d" (90 days ago), "6m" (6 months ago), "1y" (1 year ago)

    Returns:
        ISO format date string.

    Raises:
        ValueError: If the value cannot be parsed.
    """
    value = value.strip()
    if not value:
        raise ValueError("Empty date string")

    # Try relative date first (90d, 6m, 1y)
    match = _RELATIVE_PATTERN.match(value)
    if match:
        amount = int(match.group(1))
        unit = match.group(2).lower()
        now = datetime.now(timezone.utc)
        if unit == "d":
            dt = now - timedelta(days=amount)
        elif unit == "m":
            # Approximate months as 30 days
            dt = now - timedelta(days=amount * 30)
        elif unit == "y":
            dt = now - timedelta(days=amount * 365)
        else:
            raise ValueError(f"Unknown relative unit: {unit}")
        return dt.isoformat()

    # Try quarter notation (2025-Q3)
    match = _QUARTER_PATTERN.match(value)
    if match:
        year = int(match.group(1))
        quarter = int(match.group(2))
        month = _QUARTER_START_MONTH[quarter]
        dt = datetime(year, month, 1, tzinfo=timezone.utc)
        return dt.isoformat()

    # Try ISO date parsing
    # Handle date-only format
    if re.match(r"^\d{4}-\d{2}-\d{2}$", value):
        dt = datetime.strptime(value, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return dt.isoformat()

    # Handle full ISO datetime
    try:
        dt = datetime.fromisoformat(value)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.isoformat()
    except ValueError:
        pass

    raise ValueError(f"Cannot parse date: {value!r}")


def quarter_end(value: str) -> str:
    """Return the start of the next quarter for a quarter notation string.

    Args:
        value: Quarter notation like "2025-Q3".

    Returns:
        ISO format date for the start of the next quarter.

    Raises:
        ValueError: If the value is not a valid quarter string.
    """
    value = value.strip()
    match = _QUARTER_PATTERN.match(value)
    if not match:
        raise ValueError(f"Not a quarter string: {value!r}")

    year = int(match.group(1))
    quarter = int(match.group(2))
    end_month = _QUARTER_END_MONTH[quarter]

    if quarter == 4:
        year += 1
    dt = datetime(year, end_month, 1, tzinfo=timezone.utc)
    return dt.isoformat()
