"""Trend detection for knowledge graph temporal analysis.

Detects frequency trends in entity-predicate relationships over time windows.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone

from ..models import Triplet


@dataclass
class Trend:
    """A detected trend for an entity-predicate pair."""

    entity: str
    predicate: str
    direction: str  # "increasing", "decreasing", "new", "gone", "stable"
    window_counts: list[int] = field(default_factory=list)
    change_ratio: float = 0.0


def bucket_triplets_by_window(
    triplets: list[Triplet], window_days: int = 90
) -> list[tuple[str, str, list[Triplet]]]:
    """Group triplets into chronological time windows by first_seen.

    Returns:
        List of (window_start_iso, window_end_iso, triplets_in_window).
    """
    if not triplets:
        return []

    # Parse first_seen dates, skip triplets without temporal data
    dated: list[tuple[datetime, Triplet]] = []
    for t in triplets:
        if not t.first_seen:
            continue
        try:
            dt = datetime.fromisoformat(t.first_seen)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            dated.append((dt, t))
        except ValueError:
            continue

    if not dated:
        return []

    dated.sort(key=lambda x: x[0])
    earliest = dated[0][0]
    latest = dated[-1][0]

    delta = timedelta(days=window_days)
    buckets: list[tuple[str, str, list[Triplet]]] = []
    window_start = earliest

    while window_start <= latest:
        window_end = window_start + delta
        bucket_triplets = [
            t for dt, t in dated if window_start <= dt < window_end
        ]
        buckets.append((
            window_start.isoformat(),
            window_end.isoformat(),
            bucket_triplets,
        ))
        window_start = window_end

    return buckets


def detect_trends(
    triplets: list[Triplet],
    entity: str | None = None,
    window_days: int = 90,
    min_observations: int = 2,
) -> list[Trend]:
    """Detect frequency trends for entity-predicate pairs.

    Compares first-half vs second-half frequency across time windows.

    Direction thresholds:
    - >50% increase in second half = "increasing"
    - >50% decrease in second half = "decreasing"
    - Only in last window = "new"
    - Absent from last window = "gone"
    - Otherwise = "stable"

    Args:
        triplets: Triplets to analyze.
        entity: Filter to a specific entity (subject or object).
        window_days: Size of each time window in days.
        min_observations: Minimum total observations to report a trend.

    Returns:
        List of Trend objects sorted by absolute change_ratio (descending).
    """
    if not triplets:
        return []

    # Filter by entity if specified
    if entity:
        entity_lower = entity.lower()
        triplets = [
            t for t in triplets
            if t.subject.lower() == entity_lower or t.object.lower() == entity_lower
        ]

    buckets = bucket_triplets_by_window(triplets, window_days)
    if not buckets:
        return []

    # Count (entity, predicate) occurrences per window
    # Each entity appears as subject or object
    window_counts: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0] * len(buckets))

    for i, (_start, _end, bucket_trips) in enumerate(buckets):
        for t in bucket_trips:
            for ent in (t.subject, t.object):
                if entity and ent.lower() != entity.lower():
                    continue
                key = (ent, t.predicate)
                window_counts[key][i] += 1

    trends: list[Trend] = []

    for (ent, pred), counts in window_counts.items():
        total = sum(counts)
        if total < min_observations:
            continue

        num_windows = len(counts)
        if num_windows < 2:
            # Single window — classify as new or stable
            direction = "new" if counts[0] > 0 else "stable"
            trends.append(Trend(
                entity=ent,
                predicate=pred,
                direction=direction,
                window_counts=counts,
                change_ratio=0.0,
            ))
            continue

        # Split into halves
        mid = num_windows // 2
        first_half = sum(counts[:mid]) or 0
        second_half = sum(counts[mid:]) or 0

        # Determine direction
        last_window = counts[-1]
        first_window = counts[0]

        if first_half == 0 and second_half > 0:
            # Only appeared in second half
            if all(c == 0 for c in counts[:-1]) and last_window > 0:
                direction = "new"
                change_ratio = float(second_half)
            else:
                direction = "increasing"
                change_ratio = float(second_half)
        elif second_half == 0 and first_half > 0:
            # Disappeared in second half
            if last_window == 0:
                direction = "gone"
                change_ratio = -float(first_half)
            else:
                direction = "decreasing"
                change_ratio = -1.0
        elif first_half > 0:
            change_ratio = (second_half - first_half) / first_half
            if change_ratio > 0.5:
                direction = "increasing"
            elif change_ratio < -0.5:
                direction = "decreasing"
            else:
                direction = "stable"
        else:
            direction = "stable"
            change_ratio = 0.0

        trends.append(Trend(
            entity=ent,
            predicate=pred,
            direction=direction,
            window_counts=counts,
            change_ratio=change_ratio,
        ))

    # Sort by absolute change_ratio, descending
    trends.sort(key=lambda t: abs(t.change_ratio), reverse=True)
    return trends
