"""Tests for retrieval."""

import tempfile
from pathlib import Path

import pytest

from kgcp.models import Document, Triplet
from kgcp.retrieval.retriever import Retriever
from kgcp.storage.sqlite_store import SQLiteStore


@pytest.fixture
def populated_store():
    """Create a store with sample data."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        store = SQLiteStore(db_path)

        doc = Document(source_path="/tmp/test.txt", doc_id="doc1")
        store.add_document(doc)

        triplets = [
            Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="doc1", confidence=0.9),
            Triplet(subject="apt28", predicate="uses", object="credential harvesting", doc_id="doc1", confidence=0.8),
            Triplet(subject="apt28", predicate="exploits", object="owa portal", doc_id="doc1", confidence=0.7),
            Triplet(subject="energy sector", predicate="includes", object="power grid", doc_id="doc1", confidence=0.6),
            Triplet(subject="credential harvesting", predicate="involves", object="turkish language", doc_id="doc1", confidence=0.5),
            Triplet(subject="fancy bear", predicate="alias for", object="apt28", doc_id="doc1", confidence=0.8),
            Triplet(subject="russian gru", predicate="operates", object="apt28", doc_id="doc1", confidence=0.9),
        ]
        store.add_triplets(triplets)

        yield store
        store.close()


def test_keyword_retrieval(populated_store):
    retriever = Retriever(populated_store)
    results = retriever.query("apt28", hops=0)
    assert len(results) > 0
    subjects = [t.subject for t in results]
    assert "apt28" in subjects


def test_hop_expansion(populated_store):
    retriever = Retriever(populated_store)
    # With 0 hops, only direct matches
    results_0 = retriever.query("apt28", hops=0)
    # With 2 hops, should also find power grid (via energy sector)
    results_2 = retriever.query("apt28", hops=2)
    assert len(results_2) >= len(results_0)


def test_multi_word_query(populated_store):
    retriever = Retriever(populated_store)
    results = retriever.query("APT28 targets energy", hops=1)
    assert len(results) > 0


def test_no_results(populated_store):
    retriever = Retriever(populated_store)
    results = retriever.query("completely unrelated query xyz123", hops=0)
    assert len(results) == 0


def test_default_behavior_unchanged(populated_store):
    """New params should not alter default behavior."""
    retriever = Retriever(populated_store)
    results = retriever.query("apt28", hops=1)
    assert len(results) > 0
    # No unified_score in metadata by default
    for t in results:
        assert "unified_score" not in t.metadata


def test_unified_scoring_attaches_metadata(populated_store):
    """With unified_scoring=True, triplets should have unified_score in metadata."""
    retriever = Retriever(populated_store)
    results = retriever.query("apt28", hops=1, unified_scoring=True)
    assert len(results) > 0
    for t in results:
        assert "unified_score" in t.metadata
        assert "score_components" in t.metadata
        assert 0.0 <= t.metadata["unified_score"] <= 1.0


def test_min_anomaly_score_filters(populated_store):
    """min_anomaly_score should filter out triplets below the threshold."""
    retriever = Retriever(populated_store)
    # With a very high threshold, should get few or no results
    # (no anomaly scores have been computed, all default to 0.0)
    results = retriever.query("apt28", hops=1, min_anomaly_score=0.5)
    # All results should have anomaly_score >= 0.5 (likely none without a baseline)
    for t in results:
        assert t.metadata.get("anomaly_score", 0.0) >= 0.5
