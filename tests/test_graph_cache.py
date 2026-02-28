"""Tests for graph cache."""

from kgcp.models import Triplet
from kgcp.storage.graph_cache import GraphCache


def _sample_triplets():
    return [
        Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1", triplet_id="t1"),
        Triplet(subject="apt28", predicate="uses", object="credential harvesting", doc_id="d1", triplet_id="t2"),
        Triplet(subject="energy sector", predicate="includes", object="power grid", doc_id="d1", triplet_id="t3"),
        Triplet(subject="fancy bear", predicate="alias for", object="apt28", doc_id="d1", triplet_id="t4"),
    ]


def test_build_from_triplets():
    cache = GraphCache()
    cache.build_from_triplets(_sample_triplets())
    assert cache.graph.number_of_nodes() == 5
    assert cache.graph.number_of_edges() == 4


def test_get_neighbors():
    cache = GraphCache()
    cache.build_from_triplets(_sample_triplets())

    # 1-hop neighbors of apt28
    neighbors = cache.get_neighbors("apt28", hops=1)
    assert "energy sector" in neighbors
    assert "credential harvesting" in neighbors
    assert "fancy bear" in neighbors

    # 2-hop should include power grid
    neighbors_2 = cache.get_neighbors("apt28", hops=2)
    assert "power grid" in neighbors_2


def test_compute_centrality():
    cache = GraphCache()
    cache.build_from_triplets(_sample_triplets())
    centrality = cache.compute_centrality()
    # apt28 should have highest centrality (most connections)
    assert max(centrality, key=centrality.get) == "apt28"


def test_stats():
    cache = GraphCache()
    cache.build_from_triplets(_sample_triplets())
    s = cache.stats()
    assert s["nodes"] == 5
    assert s["edges"] == 4


def test_empty_graph():
    cache = GraphCache()
    assert cache.get_neighbors("nonexistent") == set()
    assert cache.compute_centrality() == {}
    assert cache.stats()["nodes"] == 0
