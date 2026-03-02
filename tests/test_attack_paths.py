"""Tests for attack path reconstruction."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from kgcp.models import AttackPath, AttackPathStep, Document, Triplet
from kgcp.retrieval.attack_paths import reconstruct_attack_path
from kgcp.storage.sqlite_store import SQLiteStore


def _ts(days_ago: int) -> str:
    """Helper: ISO timestamp for N days ago."""
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


@pytest.fixture
def attack_store():
    """Create a store with a temporal attack chain."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = SQLiteStore(db_path)

        doc = Document(source_path="/tmp/threat.txt", doc_id="doc1")
        store.add_document(doc)

        triplets = [
            Triplet(
                subject="apt28", predicate="sends", object="phishing email",
                doc_id="doc1", confidence=0.9,
                first_seen=_ts(30), last_seen=_ts(30),
            ),
            Triplet(
                subject="phishing email", predicate="delivers", object="malware dropper",
                doc_id="doc1", confidence=0.8,
                first_seen=_ts(25), last_seen=_ts(25),
            ),
            Triplet(
                subject="malware dropper", predicate="installs", object="backdoor",
                doc_id="doc1", confidence=0.85,
                first_seen=_ts(20), last_seen=_ts(20),
            ),
            Triplet(
                subject="backdoor", predicate="connects to", object="c2 server",
                doc_id="doc1", confidence=0.7,
                first_seen=_ts(15), last_seen=_ts(15),
            ),
            Triplet(
                subject="c2 server", predicate="exfiltrates", object="sensitive data",
                doc_id="doc1", confidence=0.75,
                first_seen=_ts(10), last_seen=_ts(10),
            ),
            # Unrelated triplet
            Triplet(
                subject="acme corp", predicate="headquartered in", object="new york",
                doc_id="doc1", confidence=0.6,
                first_seen=_ts(50), last_seen=_ts(50),
            ),
        ]
        store.add_triplets(triplets)

        yield store
        store.close()


def test_basic_reconstruction(attack_store):
    """Should reconstruct a path from the seed entity."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5)
    assert isinstance(path, AttackPath)
    assert path.seed_entity == "apt28"
    assert len(path.steps) > 0


def test_seed_entity_in_results(attack_store):
    """The seed entity should appear in entities_involved."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5)
    assert "apt28" in path.entities_involved


def test_temporal_ordering(attack_store):
    """Steps should be ordered chronologically."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5)
    timestamps = [s.timestamp for s in path.steps if s.timestamp]
    assert timestamps == sorted(timestamps)


def test_hop_depth(attack_store):
    """More hops should reach more entities."""
    path_1 = reconstruct_attack_path("apt28", attack_store, hops=1)
    path_3 = reconstruct_attack_path("apt28", attack_store, hops=3)
    assert len(path_3.entities_involved) >= len(path_1.entities_involved)


def test_unknown_entity(attack_store):
    """An unknown seed entity should return an empty path."""
    path = reconstruct_attack_path("completely_unknown_entity", attack_store, hops=2)
    assert len(path.steps) == 0
    assert path.seed_entity == "completely_unknown_entity"


def test_time_span(attack_store):
    """time_span should reflect the earliest and latest timestamps."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5)
    if path.steps:
        start, end = path.time_span
        assert start <= end
        assert start != ""
        assert end != ""


def test_min_anomaly_filter(attack_store):
    """With a high min_anomaly_score, should filter out steps (no baseline = all 0)."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5, min_anomaly_score=0.5)
    # No baseline exists, so all anomaly scores are 0 — all filtered out
    assert len(path.steps) == 0


def test_limit(attack_store):
    """limit should cap the number of steps."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5, limit=2)
    assert len(path.steps) <= 2


def test_step_indices(attack_store):
    """Steps should have sequential indices starting from 0."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5)
    for idx, step in enumerate(path.steps):
        assert step.step_index == idx


def test_no_baseline_works(attack_store):
    """Reconstruction should work even without a baseline (anomaly scores = 0)."""
    path = reconstruct_attack_path("apt28", attack_store, hops=5)
    assert path.total_anomaly == 0.0
    for step in path.steps:
        assert step.anomaly_score == 0.0


def test_dataclass_construction():
    """AttackPath and AttackPathStep should construct properly."""
    t = Triplet(subject="a", predicate="rel", object="b", doc_id="d1")
    step = AttackPathStep(triplet=t, timestamp="2025-01-01T00:00:00+00:00", anomaly_score=0.5)
    path = AttackPath(
        seed_entity="a",
        steps=[step],
        entities_involved={"a", "b"},
        time_span=("2025-01-01T00:00:00+00:00", "2025-01-01T00:00:00+00:00"),
        total_anomaly=0.5,
    )
    assert path.seed_entity == "a"
    assert len(path.steps) == 1
    assert path.total_anomaly == 0.5


def test_temporal_filter_since(attack_store):
    """--since should exclude steps before the cutoff."""
    # Only include steps from the last 18 days
    since = _ts(18)
    path = reconstruct_attack_path("apt28", attack_store, hops=5, since=since)
    for step in path.steps:
        if step.timestamp:
            assert step.timestamp >= since
