"""Tests for confidence scoring."""

from kgcp.extraction.confidence import infer_entity_type, score_triplet, score_triplets
from kgcp.models import Triplet


def test_infer_entity_type():
    assert infer_entity_type("apt28") == "threat_actor"
    assert infer_entity_type("ransomware xyz") == "malware"
    assert infer_entity_type("acme inc") == "organization"
    assert infer_entity_type("phishing campaign") == "technique"
    assert infer_entity_type("something unknown") == "unknown"


def test_score_strong_predicate():
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    score = score_triplet(t)
    assert score > 0.5  # Strong predicate boost


def test_score_weak_predicate():
    t = Triplet(subject="a", predicate="relates to", object="b", doc_id="d1")
    score = score_triplet(t)
    assert score < 0.5  # Weak predicate penalty


def test_score_inferred_penalty():
    t1 = Triplet(subject="a", predicate="targets", object="b", doc_id="d1", inferred=False)
    t2 = Triplet(subject="a", predicate="targets", object="b", doc_id="d1", inferred=True)
    assert score_triplet(t1) > score_triplet(t2)


def test_score_triplets_updates_confidence():
    triplets = [
        Triplet(subject="apt28", predicate="targets", object="energy", doc_id="d1"),
        Triplet(subject="a", predicate="relates to", object="b", doc_id="d1"),
    ]
    result = score_triplets(triplets)
    assert result[0].confidence > result[1].confidence
