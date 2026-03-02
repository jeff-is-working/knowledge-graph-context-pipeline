"""Tests for anomaly scoring signals."""

from kgcp.anomaly.scorer import (
    _signal_centrality_drift,
    _signal_community_mismatch,
    _signal_new_edge,
    _signal_new_entity,
    _signal_unusual_predicate,
    score_triplet_anomaly,
    score_triplets_anomaly,
)
from kgcp.models import Baseline, Triplet


def _baseline():
    """Baseline with known entities, edges, communities, predicates."""
    return Baseline(
        baseline_id="bl1",
        community_partition={
            "apt28": 0, "energy sector": 0, "credential harvesting": 0,
            "lazarus group": 1, "financial sector": 1,
        },
        centrality_scores={
            "apt28": 0.6, "energy sector": 0.3, "credential harvesting": 0.2,
            "lazarus group": 0.4, "financial sector": 0.3,
        },
        predicate_histogram={"targets": 10, "uses": 5, "operates from": 2, "includes": 1},
        edge_set={
            ("apt28", "energy sector"),
            ("apt28", "credential harvesting"),
            ("lazarus group", "financial sector"),
        },
        entity_predicates={
            "apt28": {"targets", "uses"},
            "energy sector": {"targets", "includes"},
        },
        node_count=5,
        edge_count=3,
        community_count=2,
    )


# -- Individual signal tests --

def test_new_entity_both_known():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    assert _signal_new_entity(t, bl) == 0.0


def test_new_entity_one_new():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="new_target", doc_id="d1")
    assert _signal_new_entity(t, bl) == 0.5


def test_new_entity_both_new():
    bl = _baseline()
    t = Triplet(subject="new_actor", predicate="targets", object="new_target", doc_id="d1")
    assert _signal_new_entity(t, bl) == 1.0


def test_new_edge_existing():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    assert _signal_new_edge(t, bl) == 0.0


def test_new_edge_novel():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="financial sector", doc_id="d1")
    assert _signal_new_edge(t, bl) == 1.0


def test_community_mismatch_same():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    assert _signal_community_mismatch(t, bl) == 0.0


def test_community_mismatch_different():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="collaborates with", object="lazarus group", doc_id="d1")
    assert _signal_community_mismatch(t, bl) == 1.0


def test_community_mismatch_unknown_entity():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="unknown_entity", doc_id="d1")
    assert _signal_community_mismatch(t, bl) == 0.0


def test_unusual_predicate_common():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    # "targets" is the most frequent (10), so score = 0.0
    assert _signal_unusual_predicate(t, bl) == 0.0


def test_unusual_predicate_rare():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="includes", object="energy sector", doc_id="d1")
    # "includes" has count 1, max is 10, score = 1.0 - 1/10 = 0.9
    assert _signal_unusual_predicate(t, bl) == 0.9


def test_unusual_predicate_completely_new():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="never_seen_before", object="energy sector", doc_id="d1")
    assert _signal_unusual_predicate(t, bl) == 1.0


def test_unusual_predicate_empty_histogram():
    bl = Baseline()
    t = Triplet(subject="a", predicate="r", object="b", doc_id="d1")
    assert _signal_unusual_predicate(t, bl) == 1.0


def test_centrality_drift_no_change():
    bl = _baseline()
    current = {"apt28": 0.6, "energy sector": 0.3}
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    assert _signal_centrality_drift(t, bl, current) == 0.0


def test_centrality_drift_significant():
    bl = _baseline()
    current = {"apt28": 0.9, "energy sector": 0.1}
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    # apt28: |0.9-0.6| = 0.3, energy: |0.1-0.3| = 0.2, avg = 0.25
    assert abs(_signal_centrality_drift(t, bl, current) - 0.25) < 0.001


def test_centrality_drift_empty():
    bl = _baseline()
    t = Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1")
    assert _signal_centrality_drift(t, bl, {}) == 0.0


# -- Combined scoring tests --

def test_score_known_triplet_low_anomaly():
    bl = _baseline()
    t = Triplet(
        subject="apt28", predicate="targets", object="energy sector",
        doc_id="d1", triplet_id="t1",
    )
    current = {"apt28": 0.6, "energy sector": 0.3}
    result = score_triplet_anomaly(t, bl, current)
    # All entities known, edge exists, same community, common predicate, no drift
    assert result.score < 0.1
    assert result.baseline_id == "bl1"
    assert result.subject == "apt28"


def test_score_fully_novel_triplet_high_anomaly():
    bl = _baseline()
    t = Triplet(
        subject="new_actor", predicate="brand_new_verb", object="new_target",
        doc_id="d1", triplet_id="t2",
    )
    result = score_triplet_anomaly(t, bl)
    # Both entities new (0.30), new edge (0.25), new predicate (0.15) = at least 0.70
    assert result.score >= 0.65
    assert result.signals["new_entity"] == 1.0
    assert result.signals["new_edge"] == 1.0
    assert result.signals["unusual_predicate"] == 1.0


def test_score_cross_community_triplet():
    bl = _baseline()
    t = Triplet(
        subject="apt28", predicate="targets", object="financial sector",
        doc_id="d1", triplet_id="t3",
    )
    result = score_triplet_anomaly(t, bl)
    assert result.signals["community_mismatch"] == 1.0
    assert result.signals["new_edge"] == 1.0
    assert result.score > 0.3


def test_score_clamped_to_range():
    bl = _baseline()
    t = Triplet(subject="x", predicate="y", object="z", doc_id="d1", triplet_id="t4")
    result = score_triplet_anomaly(t, bl)
    assert 0.0 <= result.score <= 1.0


def test_score_triplets_sorted_descending():
    bl = _baseline()
    triplets = [
        Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1", triplet_id="t1"),
        Triplet(subject="new_actor", predicate="new_verb", object="new_target", doc_id="d1", triplet_id="t2"),
        Triplet(subject="apt28", predicate="targets", object="financial sector", doc_id="d1", triplet_id="t3"),
    ]
    results = score_triplets_anomaly(triplets, bl)
    assert len(results) == 3
    # Should be sorted high to low
    assert results[0].score >= results[1].score >= results[2].score


def test_custom_weights():
    bl = _baseline()
    t = Triplet(subject="new_actor", predicate="targets", object="energy sector", doc_id="d1", triplet_id="t1")
    # Only weight new_entity signal
    weights = {"new_entity": 1.0, "new_edge": 0.0, "community_mismatch": 0.0,
               "unusual_predicate": 0.0, "centrality_drift": 0.0}
    result = score_triplet_anomaly(t, bl, weights=weights)
    # One new entity = 0.5 signal * 1.0 weight = 0.5
    assert result.score == 0.5


def test_score_empty_baseline():
    bl = Baseline()
    t = Triplet(subject="a", predicate="r", object="b", doc_id="d1", triplet_id="t1")
    result = score_triplet_anomaly(t, bl)
    # Everything is "new" against an empty baseline
    assert result.score > 0.5
