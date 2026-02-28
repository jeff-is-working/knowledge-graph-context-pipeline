"""Tests for core data models."""

from kgcp.models import Document, DocumentChunk, Entity, PackedContext, Triplet


def test_triplet_defaults():
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    assert t.subject == "apt28"
    assert t.predicate == "targets"
    assert t.object == "energy sector"
    assert t.confidence == 0.5
    assert t.inferred is False
    assert t.triplet_id  # UUID generated


def test_document_chunk():
    c = DocumentChunk(content="test text", doc_id="d1", source_path="test.txt")
    assert c.chunk_index == 0
    assert c.chunk_id  # UUID generated


def test_document():
    d = Document(source_path="/tmp/test.txt")
    assert d.doc_id
    assert d.ingested_at


def test_entity():
    e = Entity(name="apt28", entity_type="threat_actor", doc_ids=["d1"])
    assert e.name == "apt28"
    assert e.doc_ids == ["d1"]


def test_packed_context():
    p = PackedContext(
        content="facts:\n  - [a, b, c]",
        format="yaml",
        token_count=10,
        triplet_count=1,
    )
    assert p.format == "yaml"
    assert p.triplet_count == 1
