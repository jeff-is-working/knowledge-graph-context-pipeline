"""Tests for SQLite storage."""

import tempfile
from pathlib import Path

import pytest

from kgcp.models import Document, DocumentChunk, Entity, Triplet
from kgcp.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store():
    """Create a temporary SQLite store."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        s = SQLiteStore(db_path)
        yield s
        s.close()


def test_add_and_get_document(store):
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1")
    store.add_document(doc)
    result = store.get_document("doc1")
    assert result is not None
    assert result.source_path == "/tmp/test.txt"


def test_list_documents(store):
    store.add_document(Document(source_path="/tmp/a.txt", doc_id="d1"))
    store.add_document(Document(source_path="/tmp/b.txt", doc_id="d2"))
    docs = store.list_documents()
    assert len(docs) == 2


def test_add_and_search_triplets(store):
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1")
    store.add_document(doc)

    triplets = [
        Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="doc1"),
        Triplet(subject="apt28", predicate="uses", object="credential harvesting", doc_id="doc1"),
        Triplet(subject="fancy bear", predicate="operates", object="russia", doc_id="doc1"),
    ]
    store.add_triplets(triplets)

    results = store.search_triplets("apt28")
    assert len(results) == 2

    results = store.search_triplets("energy")
    assert len(results) == 1

    results = store.search_triplets("credential")
    assert len(results) == 1


def test_get_triplets_by_entity(store):
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1")
    store.add_document(doc)

    store.add_triplets([
        Triplet(subject="apt28", predicate="targets", object="energy", doc_id="doc1"),
        Triplet(subject="energy", predicate="includes", object="power grid", doc_id="doc1"),
    ])

    results = store.get_triplets_by_entity("energy")
    assert len(results) == 2


def test_upsert_entity(store):
    e1 = Entity(name="apt28", entity_type="threat_actor", doc_ids=["d1"])
    store.upsert_entity(e1)

    e2 = Entity(name="apt28", entity_type="threat_actor", doc_ids=["d2"])
    store.upsert_entity(e2)

    entities = store.get_all_entities()
    assert len(entities) == 1
    assert set(entities[0].doc_ids) == {"d1", "d2"}


def test_stats(store):
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1")
    store.add_document(doc)
    store.add_triplets([
        Triplet(subject="a", predicate="b", object="c", doc_id="doc1"),
    ])

    stats = store.get_stats()
    assert stats["documents"] == 1
    assert stats["triplets"] == 1


def test_delete_document_cascades(store):
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1")
    store.add_document(doc)
    store.add_triplets([
        Triplet(subject="a", predicate="b", object="c", doc_id="doc1"),
    ])

    store.delete_document("doc1")
    assert store.get_stats()["triplets"] == 0
    assert store.get_stats()["documents"] == 0
