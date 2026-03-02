"""Integration tests for AnomalyDetector orchestration."""

import tempfile
from pathlib import Path

import pytest

from kgcp.anomaly.detector import AnomalyDetector
from kgcp.models import Document, Triplet
from kgcp.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        s = SQLiteStore(db_path)
        yield s
        s.close()


@pytest.fixture
def populated_store(store):
    """Store with a small graph of threat intelligence triplets."""
    doc1 = Document(source_path="/tmp/report1.txt", doc_id="d1", ingested_at="2025-01-15T00:00:00+00:00")
    store.add_document(doc1)
    store.add_triplets([
        Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1", triplet_id="t1"),
        Triplet(subject="apt28", predicate="uses", object="credential harvesting", doc_id="d1", triplet_id="t2"),
        Triplet(subject="apt28", predicate="operates from", object="russia", doc_id="d1", triplet_id="t3"),
        Triplet(subject="energy sector", predicate="includes", object="power grid", doc_id="d1", triplet_id="t4"),
        Triplet(subject="lazarus group", predicate="targets", object="financial sector", doc_id="d1", triplet_id="t5"),
        Triplet(subject="lazarus group", predicate="operates from", object="north korea", doc_id="d1", triplet_id="t6"),
    ])
    return store


def test_create_and_save_baseline(populated_store):
    detector = AnomalyDetector(populated_store)
    bl = detector.create_and_save_baseline(label="v1")

    assert bl.node_count == 8
    assert bl.edge_count == 6
    assert bl.label == "v1"

    # Verify it was persisted
    retrieved = populated_store.get_baseline(bl.baseline_id)
    assert retrieved is not None
    assert retrieved.label == "v1"


def test_list_baselines(populated_store):
    detector = AnomalyDetector(populated_store)
    detector.create_and_save_baseline(label="first")
    detector.create_and_save_baseline(label="second")

    baselines = detector.list_baselines()
    assert len(baselines) == 2


def test_get_latest_baseline(populated_store):
    detector = AnomalyDetector(populated_store)
    detector.create_and_save_baseline(label="first")
    detector.create_and_save_baseline(label="second")

    latest = detector.get_latest_baseline()
    assert latest is not None
    assert latest.label == "second"


def test_score_all_triplets(populated_store):
    detector = AnomalyDetector(populated_store)
    bl = detector.create_and_save_baseline()

    results = detector.score_all_triplets(bl)
    assert len(results) == 6
    # All triplets are "known" — they created the baseline, so scores should be low
    # Community mismatch can still contribute for cross-community edges
    for r in results:
        assert 0.0 <= r.score <= 1.0

    # Verify persisted
    stored = populated_store.get_anomaly_scores(min_score=0.0, baseline_id=bl.baseline_id)
    assert len(stored) == 6


def test_score_all_uses_latest_baseline(populated_store):
    detector = AnomalyDetector(populated_store)
    detector.create_and_save_baseline()

    # Should auto-use latest baseline
    results = detector.score_all_triplets()
    assert len(results) == 6


def test_score_no_baseline(populated_store):
    detector = AnomalyDetector(populated_store)
    results = detector.score_all_triplets()
    assert results == []


def test_score_triplets_since(populated_store):
    detector = AnomalyDetector(populated_store)
    bl = detector.create_and_save_baseline()

    # Add a new document with new triplets after baseline
    doc2 = Document(source_path="/tmp/report2.txt", doc_id="d2", ingested_at="2025-06-01T00:00:00+00:00")
    populated_store.add_document(doc2)
    populated_store.add_triplets([
        Triplet(subject="new_actor", predicate="exploits", object="zero_day", doc_id="d2", triplet_id="t_new1"),
        Triplet(subject="apt28", predicate="collaborates with", object="lazarus group", doc_id="d2", triplet_id="t_new2"),
    ])

    results = detector.score_triplets_since("2025-03-01T00:00:00+00:00", bl)
    assert len(results) == 2

    # new_actor + exploits + zero_day = all novel → high score
    novel_result = next(r for r in results if r.triplet_id == "t_new1")
    assert novel_result.score >= 0.5

    # apt28 collaborates with lazarus group = cross-community, new edge, new predicate
    cross_result = next(r for r in results if r.triplet_id == "t_new2")
    assert cross_result.signals["new_edge"] == 1.0


def test_detect_entity_drift(populated_store):
    detector = AnomalyDetector(populated_store)
    bl = detector.create_and_save_baseline()

    # Add new connections for apt28
    doc2 = Document(source_path="/tmp/update.txt", doc_id="d2", ingested_at="2025-06-01T00:00:00+00:00")
    populated_store.add_document(doc2)
    populated_store.add_triplets([
        Triplet(subject="apt28", predicate="deploys", object="new_malware", doc_id="d2"),
    ])

    drift = detector.detect_entity_drift("apt28", bl)
    assert drift["entity"] == "apt28"
    assert "deploys" in drift["new_predicates"]
    assert "new_malware" in drift["new_neighbors"]
    assert isinstance(drift["centrality_delta"], float)


def test_detect_entity_drift_no_baseline(populated_store):
    detector = AnomalyDetector(populated_store)
    drift = detector.detect_entity_drift("apt28")
    assert "error" in drift


def test_detect_entity_drift_unknown_entity(populated_store):
    detector = AnomalyDetector(populated_store)
    bl = detector.create_and_save_baseline()
    drift = detector.detect_entity_drift("nonexistent", bl)
    assert drift["entity"] == "nonexistent"
    assert drift["new_predicates"] == []
    assert drift["new_neighbors"] == []
