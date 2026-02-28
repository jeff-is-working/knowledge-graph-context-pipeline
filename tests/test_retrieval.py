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
