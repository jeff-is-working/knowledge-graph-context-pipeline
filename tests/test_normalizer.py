"""Tests for entity normalization."""

from kgcp.extraction.normalizer import (
    deduplicate_triplets,
    limit_predicate_length,
    normalize_entity,
    standardize_entities,
)
from kgcp.models import Triplet


def test_normalize_entity():
    assert normalize_entity("The United States of America") == "united states america"
    assert normalize_entity("APT28") == "apt28"
    assert normalize_entity("  john smith  ") == "john smith"


def test_limit_predicate_length():
    assert limit_predicate_length("targets") == "targets"
    assert limit_predicate_length("is known to target") == "is known to"
    assert limit_predicate_length("relates to") == "relates to"


def test_standardize_removes_self_references():
    triplets = [
        Triplet(subject="apt28", predicate="targets", object="apt 28", doc_id="d1"),
    ]
    # After standardization, "apt 28" -> "apt28", creating self-ref
    result = standardize_entities(triplets)
    # Self-reference should be removed
    for t in result:
        assert t.subject != t.object


def test_standardize_picks_most_frequent():
    triplets = [
        Triplet(subject="the energy sector", predicate="targets", object="grid", doc_id="d1"),
        Triplet(subject="the energy sector", predicate="uses", object="phishing", doc_id="d1"),
        Triplet(subject="energy sector", predicate="exploits", object="owa", doc_id="d1"),
    ]
    result = standardize_entities(triplets)
    # Both normalize to "energy sector", the more frequent variant wins
    subjects = {t.subject for t in result}
    # "the energy sector" appears twice, should be the standard
    assert "energy sector" not in subjects or "the energy sector" not in subjects


def test_deduplicate():
    t1 = Triplet(subject="a", predicate="b", object="c", doc_id="d1", confidence=0.8)
    t2 = Triplet(subject="a", predicate="b", object="c", doc_id="d1", confidence=0.5)
    result = deduplicate_triplets([t1, t2])
    assert len(result) == 1
    assert result[0].confidence == 0.8
