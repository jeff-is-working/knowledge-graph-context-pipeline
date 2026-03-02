"""Tests for temporal storage features: field roundtrip, migration, backfill, upsert."""

import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kgcp.models import Document, Triplet
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
def store_with_doc(store):
    """Store with a pre-created document."""
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1",
                   ingested_at="2025-01-15T10:00:00+00:00")
    store.add_document(doc)
    return store


# -- Temporal field roundtrip --

def test_temporal_fields_roundtrip(store_with_doc):
    """Temporal fields survive storage and retrieval."""
    t = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", triplet_id="t1",
        first_seen="2025-01-15T10:00:00+00:00",
        last_seen="2025-03-01T12:00:00+00:00",
        observation_count=3,
    )
    store_with_doc.add_triplet(t)

    results = store_with_doc.search_triplets("apt28")
    assert len(results) == 1
    assert results[0].first_seen == "2025-01-15T10:00:00+00:00"
    assert results[0].last_seen == "2025-03-01T12:00:00+00:00"
    assert results[0].observation_count == 3


def test_temporal_defaults_on_new_triplet(store_with_doc):
    """New triplets get auto-populated first_seen and last_seen."""
    t = Triplet(subject="apt28", predicate="targets", object="energy", doc_id="doc1")
    store_with_doc.add_triplet(t)

    results = store_with_doc.search_triplets("apt28")
    assert len(results) == 1
    assert results[0].first_seen != ""
    assert results[0].last_seen != ""
    assert results[0].observation_count == 1


def test_temporal_fields_in_batch_add(store_with_doc):
    """Batch add preserves temporal fields."""
    triplets = [
        Triplet(
            subject="apt28", predicate="targets", object="energy",
            doc_id="doc1", triplet_id="t1",
            first_seen="2025-01-01", last_seen="2025-06-01",
            observation_count=5,
        ),
        Triplet(
            subject="apt28", predicate="uses", object="phishing",
            doc_id="doc1", triplet_id="t2",
            first_seen="2025-02-01", last_seen="2025-05-01",
            observation_count=2,
        ),
    ]
    store_with_doc.add_triplets(triplets)

    results = store_with_doc.get_all_triplets()
    assert len(results) == 2

    by_id = {r.triplet_id: r for r in results}
    assert by_id["t1"].observation_count == 5
    assert by_id["t1"].first_seen == "2025-01-01"
    assert by_id["t2"].observation_count == 2


def test_temporal_fields_preserved_on_search(store_with_doc):
    """search_triplets, get_triplets_by_entity, get_triplets_by_doc all return temporal fields."""
    t = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", triplet_id="t1",
        first_seen="2025-01-15", last_seen="2025-03-01",
        observation_count=7,
    )
    store_with_doc.add_triplet(t)

    for results in [
        store_with_doc.search_triplets("apt28"),
        store_with_doc.get_triplets_by_entity("apt28"),
        store_with_doc.get_triplets_by_doc("doc1"),
        store_with_doc.get_all_triplets(),
    ]:
        assert len(results) >= 1
        found = results[0]
        assert found.observation_count == 7
        assert found.first_seen == "2025-01-15"


# -- Migration / backfill --

def test_migration_is_idempotent(store):
    """Running migration multiple times doesn't error."""
    store._migrate_schema()
    store._migrate_schema()


def test_backfill_from_document_ingested_at(store):
    """Backfill populates first_seen/last_seen from document.ingested_at for empty fields."""
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1",
                   ingested_at="2025-06-15T10:00:00+00:00")
    store.add_document(doc)

    # Insert a triplet with empty temporal fields directly
    store.conn.execute(
        "INSERT INTO triplets (triplet_id, subject, predicate, object, doc_id, "
        "first_seen, last_seen, observation_count) VALUES (?, ?, ?, ?, ?, '', '', 1)",
        ("t-backfill", "a", "b", "c", "doc1"),
    )
    store.conn.commit()

    store._backfill_temporal()

    row = store.conn.execute(
        "SELECT first_seen, last_seen FROM triplets WHERE triplet_id = ?",
        ("t-backfill",),
    ).fetchone()
    assert row["first_seen"] == "2025-06-15T10:00:00+00:00"
    assert row["last_seen"] == "2025-06-15T10:00:00+00:00"


def test_backfill_does_not_overwrite_existing(store):
    """Backfill skips triplets that already have first_seen set."""
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1",
                   ingested_at="2025-06-15T10:00:00+00:00")
    store.add_document(doc)

    t = Triplet(
        subject="a", predicate="b", object="c", doc_id="doc1",
        triplet_id="t-existing",
        first_seen="2025-01-01", last_seen="2025-03-01",
    )
    store.add_triplet(t)

    store._backfill_temporal()

    result = store.search_triplets("a")
    assert result[0].first_seen == "2025-01-01"


# -- Upsert tests --

def test_upsert_new_triplet(store_with_doc):
    """Upsert inserts when no matching SPO exists."""
    t = Triplet(subject="apt28", predicate="targets", object="energy", doc_id="doc1")
    store_with_doc.upsert_triplet(t)

    results = store_with_doc.get_all_triplets()
    assert len(results) == 1
    assert results[0].observation_count == 1


def test_upsert_increments_count(store_with_doc):
    """Re-upserting same SPO increments observation_count."""
    t1 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", first_seen="2025-01-01", last_seen="2025-01-01",
    )
    store_with_doc.upsert_triplet(t1)

    t2 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", last_seen="2025-06-01",
    )
    store_with_doc.upsert_triplet(t2)

    results = store_with_doc.get_all_triplets()
    assert len(results) == 1
    assert results[0].observation_count == 2
    assert results[0].last_seen == "2025-06-01"


def test_upsert_preserves_first_seen(store_with_doc):
    """Upsert keeps the earliest first_seen."""
    t1 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", first_seen="2025-01-01", last_seen="2025-01-01",
    )
    store_with_doc.upsert_triplet(t1)

    t2 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", first_seen="2025-06-01", last_seen="2025-06-01",
    )
    store_with_doc.upsert_triplet(t2)

    results = store_with_doc.get_all_triplets()
    assert results[0].first_seen == "2025-01-01"


def test_upsert_preserves_triplet_id(store_with_doc):
    """Upsert keeps the original triplet_id."""
    t1 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", triplet_id="original-id",
    )
    store_with_doc.upsert_triplet(t1)

    t2 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", triplet_id="new-id",
    )
    store_with_doc.upsert_triplet(t2)

    results = store_with_doc.get_all_triplets()
    assert results[0].triplet_id == "original-id"


def test_upsert_case_insensitive(store_with_doc):
    """Upsert matches SPO case-insensitively."""
    t1 = Triplet(subject="APT28", predicate="Targets", object="Energy", doc_id="doc1")
    store_with_doc.upsert_triplet(t1)

    t2 = Triplet(subject="apt28", predicate="targets", object="energy", doc_id="doc1")
    store_with_doc.upsert_triplet(t2)

    results = store_with_doc.get_all_triplets()
    assert len(results) == 1
    assert results[0].observation_count == 2


def test_upsert_takes_higher_confidence(store_with_doc):
    """Upsert keeps the higher confidence value."""
    t1 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", confidence=0.6,
    )
    store_with_doc.upsert_triplet(t1)

    t2 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", confidence=0.9,
    )
    store_with_doc.upsert_triplet(t2)

    results = store_with_doc.get_all_triplets()
    assert results[0].confidence == 0.9


def test_upsert_does_not_downgrade_confidence(store_with_doc):
    """Upsert doesn't lower confidence when new value is lower."""
    t1 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", confidence=0.9,
    )
    store_with_doc.upsert_triplet(t1)

    t2 = Triplet(
        subject="apt28", predicate="targets", object="energy",
        doc_id="doc1", confidence=0.3,
    )
    store_with_doc.upsert_triplet(t2)

    results = store_with_doc.get_all_triplets()
    assert results[0].confidence == 0.9


def test_upsert_triplets_batch(store_with_doc):
    """Batch upsert works correctly."""
    triplets1 = [
        Triplet(subject="apt28", predicate="targets", object="energy", doc_id="doc1"),
        Triplet(subject="apt28", predicate="uses", object="phishing", doc_id="doc1"),
    ]
    store_with_doc.upsert_triplets(triplets1)

    triplets2 = [
        Triplet(subject="apt28", predicate="targets", object="energy", doc_id="doc1"),
        Triplet(subject="apt28", predicate="uses", object="spearphishing", doc_id="doc1"),
    ]
    store_with_doc.upsert_triplets(triplets2)

    results = store_with_doc.get_all_triplets()
    assert len(results) == 3  # 2 original + 1 new (spearphishing)

    by_obj = {r.object: r for r in results}
    assert by_obj["energy"].observation_count == 2
    assert by_obj["phishing"].observation_count == 1
    assert by_obj["spearphishing"].observation_count == 1
