"""Tests for baseline fingerprinting."""

from kgcp.anomaly.baseline import create_baseline
from kgcp.models import Triplet


def _make_triplets():
    """Sample triplets forming a small graph with 2 communities."""
    return [
        Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1", triplet_id="t1"),
        Triplet(subject="apt28", predicate="uses", object="credential harvesting", doc_id="d1", triplet_id="t2"),
        Triplet(subject="apt28", predicate="operates from", object="russia", doc_id="d1", triplet_id="t3"),
        Triplet(subject="energy sector", predicate="includes", object="power grid", doc_id="d1", triplet_id="t4"),
        Triplet(subject="lazarus group", predicate="targets", object="financial sector", doc_id="d1", triplet_id="t5"),
        Triplet(subject="lazarus group", predicate="operates from", object="north korea", doc_id="d1", triplet_id="t6"),
    ]


def test_baseline_captures_communities():
    bl = create_baseline(_make_triplets(), label="test")
    assert bl.label == "test"
    assert bl.community_count >= 1
    assert len(bl.community_partition) > 0


def test_baseline_captures_centrality():
    bl = create_baseline(_make_triplets())
    assert "apt28" in bl.centrality_scores
    assert "energy sector" in bl.centrality_scores
    # apt28 has 3 edges, should be among the most central
    assert bl.centrality_scores["apt28"] > 0


def test_baseline_captures_predicate_histogram():
    bl = create_baseline(_make_triplets())
    assert bl.predicate_histogram["targets"] == 2
    assert bl.predicate_histogram["uses"] == 1
    assert bl.predicate_histogram["operates from"] == 2
    assert bl.predicate_histogram["includes"] == 1


def test_baseline_captures_edge_set():
    bl = create_baseline(_make_triplets())
    assert ("apt28", "energy sector") in bl.edge_set
    assert ("apt28", "credential harvesting") in bl.edge_set
    assert ("lazarus group", "financial sector") in bl.edge_set
    assert len(bl.edge_set) == 6


def test_baseline_captures_entity_predicates():
    bl = create_baseline(_make_triplets())
    assert "targets" in bl.entity_predicates["apt28"]
    assert "uses" in bl.entity_predicates["apt28"]
    assert "operates from" in bl.entity_predicates["apt28"]
    # energy sector appears as object of targets and subject of includes
    assert "targets" in bl.entity_predicates["energy sector"]
    assert "includes" in bl.entity_predicates["energy sector"]


def test_baseline_graph_stats():
    bl = create_baseline(_make_triplets())
    assert bl.node_count == 8  # 8 unique entities
    assert bl.edge_count == 6  # 6 triplets = 6 edges


def test_baseline_empty_graph():
    bl = create_baseline([], label="empty")
    assert bl.label == "empty"
    assert bl.node_count == 0
    assert bl.edge_count == 0
    assert bl.community_count == 0
    assert bl.edge_set == set()
    assert bl.entity_predicates == {}
    assert bl.predicate_histogram == {}


def test_baseline_single_triplet():
    triplets = [
        Triplet(subject="a", predicate="relates to", object="b", doc_id="d1"),
    ]
    bl = create_baseline(triplets)
    assert bl.node_count == 2
    assert bl.edge_count == 1
    assert ("a", "b") in bl.edge_set
    assert bl.predicate_histogram == {"relates to": 1}
