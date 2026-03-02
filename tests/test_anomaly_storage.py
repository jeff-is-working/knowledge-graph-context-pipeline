"""Tests for anomaly-related storage (baselines and anomaly scores)."""

import tempfile
from pathlib import Path

import pytest

from kgcp.models import AnomalyResult, Baseline, Document, Triplet
from kgcp.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store():
    """Create a temporary SQLite store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        s = SQLiteStore(db_path)
        yield s
        s.close()


@pytest.fixture
def populated_store(store):
    """Store with documents and triplets for anomaly testing."""
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1", ingested_at="2025-01-15T00:00:00+00:00")
    store.add_document(doc)
    store.add_triplets([
        Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="doc1", triplet_id="t1"),
        Triplet(subject="apt28", predicate="uses", object="credential harvesting", doc_id="doc1", triplet_id="t2"),
        Triplet(subject="fancy bear", predicate="operates", object="russia", doc_id="doc1", triplet_id="t3"),
    ])
    return store


# -- Baseline round-trip tests --

def test_add_and_get_baseline(store):
    bl = Baseline(
        baseline_id="bl1",
        label="test baseline",
        community_partition={"apt28": 0, "energy": 0, "russia": 1},
        centrality_scores={"apt28": 0.8, "energy": 0.4, "russia": 0.2},
        predicate_histogram={"targets": 5, "uses": 3},
        edge_set={("apt28", "energy"), ("apt28", "tools")},
        entity_predicates={"apt28": {"targets", "uses"}, "energy": {"targets"}},
        node_count=5,
        edge_count=4,
        community_count=2,
    )
    store.add_baseline(bl)

    result = store.get_baseline("bl1")
    assert result is not None
    assert result.label == "test baseline"
    assert result.community_partition == {"apt28": 0, "energy": 0, "russia": 1}
    assert result.centrality_scores["apt28"] == 0.8
    assert result.predicate_histogram == {"targets": 5, "uses": 3}
    assert ("apt28", "energy") in result.edge_set
    assert ("apt28", "tools") in result.edge_set
    assert result.entity_predicates["apt28"] == {"targets", "uses"}
    assert result.node_count == 5
    assert result.edge_count == 4
    assert result.community_count == 2


def test_get_latest_baseline(store):
    store.add_baseline(Baseline(baseline_id="old", label="old", created_at="2025-01-01T00:00:00+00:00"))
    store.add_baseline(Baseline(baseline_id="new", label="new", created_at="2025-06-01T00:00:00+00:00"))

    latest = store.get_latest_baseline()
    assert latest is not None
    assert latest.baseline_id == "new"


def test_list_baselines(store):
    store.add_baseline(Baseline(baseline_id="b1", created_at="2025-01-01T00:00:00+00:00"))
    store.add_baseline(Baseline(baseline_id="b2", created_at="2025-06-01T00:00:00+00:00"))
    store.add_baseline(Baseline(baseline_id="b3", created_at="2025-03-01T00:00:00+00:00"))

    baselines = store.list_baselines()
    assert len(baselines) == 3
    assert baselines[0].baseline_id == "b2"  # newest first


def test_delete_baseline(store):
    store.add_baseline(Baseline(baseline_id="bl1"))
    store.delete_baseline("bl1")
    assert store.get_baseline("bl1") is None


def test_get_nonexistent_baseline(store):
    assert store.get_baseline("nonexistent") is None


def test_baseline_empty_fields_roundtrip(store):
    bl = Baseline(baseline_id="empty")
    store.add_baseline(bl)
    result = store.get_baseline("empty")
    assert result is not None
    assert result.edge_set == set()
    assert result.entity_predicates == {}
    assert result.predicate_histogram == {}


# -- Anomaly scores tests --

def test_add_and_get_anomaly_scores(populated_store):
    store = populated_store
    bl = Baseline(baseline_id="bl1")
    store.add_baseline(bl)

    scores = [
        AnomalyResult(triplet_id="t1", score=0.85, signals={"new_edge": 1.0, "new_entity": 0.5}, baseline_id="bl1"),
        AnomalyResult(triplet_id="t2", score=0.3, signals={"new_edge": 0.0}, baseline_id="bl1"),
        AnomalyResult(triplet_id="t3", score=0.6, signals={"community_mismatch": 1.0}, baseline_id="bl1"),
    ]
    store.add_anomaly_scores(scores)

    results = store.get_anomaly_scores(min_score=0.0, baseline_id="bl1")
    assert len(results) == 3
    assert results[0].score == 0.85  # sorted desc
    assert results[0].subject == "apt28"  # joined with triplets


def test_anomaly_scores_min_score_filter(populated_store):
    store = populated_store
    bl = Baseline(baseline_id="bl1")
    store.add_baseline(bl)

    store.add_anomaly_scores([
        AnomalyResult(triplet_id="t1", score=0.85, baseline_id="bl1"),
        AnomalyResult(triplet_id="t2", score=0.3, baseline_id="bl1"),
        AnomalyResult(triplet_id="t3", score=0.6, baseline_id="bl1"),
    ])

    results = store.get_anomaly_scores(min_score=0.5, baseline_id="bl1")
    assert len(results) == 2
    assert all(r.score >= 0.5 for r in results)


def test_anomaly_scores_limit(populated_store):
    store = populated_store
    bl = Baseline(baseline_id="bl1")
    store.add_baseline(bl)

    store.add_anomaly_scores([
        AnomalyResult(triplet_id="t1", score=0.85, baseline_id="bl1"),
        AnomalyResult(triplet_id="t2", score=0.3, baseline_id="bl1"),
        AnomalyResult(triplet_id="t3", score=0.6, baseline_id="bl1"),
    ])

    results = store.get_anomaly_scores(min_score=0.0, baseline_id="bl1", limit=2)
    assert len(results) == 2


def test_get_anomaly_score_for_triplet(populated_store):
    store = populated_store
    bl = Baseline(baseline_id="bl1")
    store.add_baseline(bl)

    store.add_anomaly_scores([
        AnomalyResult(triplet_id="t1", score=0.85, signals={"new_edge": 1.0}, baseline_id="bl1"),
    ])

    result = store.get_anomaly_score_for_triplet("t1", "bl1")
    assert result is not None
    assert result.score == 0.85
    assert result.signals["new_edge"] == 1.0

    result = store.get_anomaly_score_for_triplet("t999")
    assert result is None


def test_cascade_delete_baseline_removes_scores(populated_store):
    store = populated_store
    bl = Baseline(baseline_id="bl1")
    store.add_baseline(bl)

    store.add_anomaly_scores([
        AnomalyResult(triplet_id="t1", score=0.85, baseline_id="bl1"),
    ])

    store.delete_baseline("bl1")
    results = store.get_anomaly_scores(min_score=0.0)
    assert len(results) == 0


def test_cascade_delete_triplet_removes_scores(populated_store):
    store = populated_store
    bl = Baseline(baseline_id="bl1")
    store.add_baseline(bl)

    store.add_anomaly_scores([
        AnomalyResult(triplet_id="t1", score=0.85, baseline_id="bl1"),
        AnomalyResult(triplet_id="t2", score=0.3, baseline_id="bl1"),
    ])

    # Deleting the document cascades to triplets, which cascades to anomaly_scores
    store.delete_document("doc1")
    results = store.get_anomaly_scores(min_score=0.0, baseline_id="bl1")
    assert len(results) == 0


# -- get_triplets_since tests --

def test_get_triplets_since(store):
    doc1 = Document(source_path="/tmp/old.txt", doc_id="d1", ingested_at="2025-01-01T00:00:00+00:00")
    doc2 = Document(source_path="/tmp/new.txt", doc_id="d2", ingested_at="2025-06-15T00:00:00+00:00")
    store.add_document(doc1)
    store.add_document(doc2)

    store.add_triplets([
        Triplet(subject="old_a", predicate="r", object="old_b", doc_id="d1", triplet_id="t_old"),
        Triplet(subject="new_a", predicate="r", object="new_b", doc_id="d2", triplet_id="t_new"),
    ])

    results = store.get_triplets_since("2025-06-01T00:00:00+00:00")
    assert len(results) == 1
    assert results[0].triplet_id == "t_new"


def test_get_triplets_since_returns_empty(store):
    doc = Document(source_path="/tmp/test.txt", doc_id="d1", ingested_at="2025-01-01T00:00:00+00:00")
    store.add_document(doc)
    store.add_triplets([
        Triplet(subject="a", predicate="r", object="b", doc_id="d1"),
    ])

    results = store.get_triplets_since("2026-01-01T00:00:00+00:00")
    assert len(results) == 0
