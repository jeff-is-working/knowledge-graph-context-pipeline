"""Tests for temporal trend detection."""

import pytest

from kgcp.models import Triplet
from kgcp.temporal.trends import Trend, bucket_triplets_by_window, detect_trends


def _make_triplet(subject, predicate, obj, first_seen, doc_id="doc1"):
    return Triplet(
        subject=subject, predicate=predicate, object=obj,
        doc_id=doc_id, first_seen=first_seen, last_seen=first_seen,
    )


# -- bucket_triplets_by_window --

def test_bucket_empty():
    assert bucket_triplets_by_window([], 90) == []


def test_bucket_single_window():
    triplets = [
        _make_triplet("a", "b", "c", "2025-01-15"),
        _make_triplet("d", "e", "f", "2025-02-01"),
    ]
    buckets = bucket_triplets_by_window(triplets, 90)
    assert len(buckets) == 1
    assert len(buckets[0][2]) == 2


def test_bucket_multiple_windows():
    triplets = [
        _make_triplet("a", "b", "c", "2025-01-15"),
        _make_triplet("d", "e", "f", "2025-05-01"),
        _make_triplet("g", "h", "i", "2025-08-01"),
    ]
    buckets = bucket_triplets_by_window(triplets, 90)
    assert len(buckets) >= 2


def test_bucket_skips_no_date():
    t = Triplet(subject="a", predicate="b", object="c", doc_id="d", first_seen="")
    buckets = bucket_triplets_by_window([t], 90)
    assert buckets == []


# -- detect_trends: increasing --

def test_detect_increasing_trend():
    """Entity appearing more frequently over time."""
    triplets = [
        _make_triplet("apt28", "targets", "energy", "2025-01-15"),
        _make_triplet("apt28", "targets", "gov", "2025-05-01"),
        _make_triplet("apt28", "targets", "health", "2025-05-15"),
        _make_triplet("apt28", "targets", "finance", "2025-06-01"),
    ]
    trends = detect_trends(triplets, entity="apt28", window_days=90)
    target_trends = [t for t in trends if t.predicate == "targets"]
    assert len(target_trends) > 0
    assert any(t.direction == "increasing" for t in target_trends)


# -- detect_trends: decreasing --

def test_detect_decreasing_trend():
    """Entity appearing less frequently over time."""
    triplets = [
        # First window (Jan): 3 appearances
        _make_triplet("apt28", "targets", "energy", "2025-01-01"),
        _make_triplet("apt28", "targets", "gov", "2025-01-15"),
        _make_triplet("apt28", "targets", "health", "2025-02-01"),
        # Second window (Apr-Jun): 0 appearances for apt28
        # Need a triplet in this window to extend the range
        _make_triplet("apt28", "uses", "phishing", "2025-05-01"),
    ]
    trends = detect_trends(triplets, entity="apt28", window_days=90, min_observations=2)
    target_trends = [t for t in trends if t.predicate == "targets"]
    assert any(t.direction in ("decreasing", "gone") for t in target_trends)


# -- detect_trends: stable --

def test_detect_stable_trend():
    """Even distribution across windows."""
    triplets = [
        _make_triplet("apt28", "targets", "energy", "2025-01-15"),
        _make_triplet("apt28", "targets", "gov", "2025-04-15"),
    ]
    trends = detect_trends(triplets, entity="apt28", window_days=90)
    target_trends = [t for t in trends if t.predicate == "targets"]
    assert any(t.direction == "stable" for t in target_trends)


# -- detect_trends: new --

def test_detect_new_trend():
    """Entity-predicate pair only in the last window."""
    triplets = [
        # Need multiple windows for the filtered entity
        # First window: entity appears with a different predicate
        _make_triplet("newactor", "operates from", "unknown", "2025-01-01"),
        _make_triplet("newactor", "operates from", "unknown2", "2025-01-15"),
        # Last window: entity appears with "targets" (new predicate for this entity)
        _make_triplet("newactor", "targets", "gov", "2025-07-01"),
        _make_triplet("newactor", "targets", "finance", "2025-07-15"),
    ]
    trends = detect_trends(triplets, entity="newactor", window_days=90, min_observations=2)
    targets_trends = [t for t in trends if t.predicate == "targets"]
    assert any(t.direction == "new" for t in targets_trends)


# -- detect_trends: gone --

def test_detect_gone_trend():
    """Entity-predicate pair absent from the last window."""
    triplets = [
        # First window: apt28 targets things
        _make_triplet("apt28", "targets", "energy", "2025-01-01"),
        _make_triplet("apt28", "targets", "gov", "2025-01-15"),
        # Last window: apt28 still active but with different predicate
        _make_triplet("apt28", "uses", "new_tool", "2025-10-01"),
        _make_triplet("apt28", "uses", "another_tool", "2025-10-15"),
    ]
    trends = detect_trends(triplets, entity="apt28", window_days=90, min_observations=2)
    target_trends = [t for t in trends if t.predicate == "targets"]
    assert any(t.direction == "gone" for t in target_trends)


# -- entity filter --

def test_entity_filter():
    """Only returns trends for specified entity."""
    triplets = [
        _make_triplet("apt28", "targets", "energy", "2025-01-01"),
        _make_triplet("apt29", "targets", "gov", "2025-01-01"),
        _make_triplet("apt28", "targets", "health", "2025-06-01"),
        _make_triplet("apt29", "targets", "finance", "2025-06-01"),
    ]
    trends = detect_trends(triplets, entity="apt28", window_days=90)
    for t in trends:
        assert t.entity.lower() == "apt28"


def test_no_entity_filter_returns_all():
    """Without entity filter, returns trends for all entities."""
    triplets = [
        _make_triplet("apt28", "targets", "energy", "2025-01-01"),
        _make_triplet("apt29", "targets", "gov", "2025-01-01"),
        _make_triplet("apt28", "targets", "health", "2025-06-01"),
        _make_triplet("apt29", "targets", "finance", "2025-06-01"),
    ]
    trends = detect_trends(triplets, window_days=90)
    entities = {t.entity.lower() for t in trends}
    assert len(entities) > 1


# -- min_observations --

def test_min_observations_filters():
    """Trends below min_observations are excluded."""
    triplets = [
        _make_triplet("apt28", "targets", "energy", "2025-01-01"),
    ]
    trends = detect_trends(triplets, entity="apt28", window_days=90, min_observations=3)
    assert len(trends) == 0


def test_min_observations_includes():
    """Trends at or above min_observations are included."""
    triplets = [
        _make_triplet("apt28", "targets", "energy", "2025-01-01"),
        _make_triplet("apt28", "targets", "gov", "2025-01-15"),
    ]
    trends = detect_trends(triplets, entity="apt28", window_days=90, min_observations=2)
    assert len(trends) > 0


# -- empty input --

def test_detect_trends_empty():
    assert detect_trends([]) == []


def test_detect_trends_no_temporal_data():
    """Triplets without first_seen are ignored."""
    triplets = [
        Triplet(subject="a", predicate="b", object="c", doc_id="d", first_seen=""),
    ]
    assert detect_trends(triplets) == []


# -- sorting --

def test_trends_sorted_by_change_ratio():
    """Trends are sorted by absolute change_ratio descending."""
    triplets = [
        # Stable pair
        _make_triplet("stable", "does", "thing1", "2025-01-01"),
        _make_triplet("stable", "does", "thing2", "2025-06-01"),
        # Increasing pair
        _make_triplet("growing", "targets", "a", "2025-06-01"),
        _make_triplet("growing", "targets", "b", "2025-06-15"),
        _make_triplet("growing", "targets", "c", "2025-07-01"),
    ]
    trends = detect_trends(triplets, window_days=90)
    if len(trends) >= 2:
        assert abs(trends[0].change_ratio) >= abs(trends[-1].change_ratio)


# -- Trend dataclass --

def test_trend_dataclass():
    t = Trend(entity="apt28", predicate="targets", direction="increasing",
              window_counts=[1, 3], change_ratio=2.0)
    assert t.entity == "apt28"
    assert t.direction == "increasing"
    assert t.change_ratio == 2.0
