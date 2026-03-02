"""Baseline fingerprinting — snapshot the graph's structural signature."""

from __future__ import annotations

import logging
from collections import Counter

from ..models import Baseline, Triplet
from ..storage.graph_cache import GraphCache

logger = logging.getLogger(__name__)


def create_baseline(triplets: list[Triplet], label: str = "") -> Baseline:
    """Create a baseline fingerprint from a set of triplets.

    Captures:
    - Community partition (Louvain)
    - Degree centrality scores
    - Predicate frequency histogram
    - Edge set (subject, object pairs)
    - Entity predicate patterns (which predicates each entity uses)
    - Graph size stats
    """
    if not triplets:
        return Baseline(label=label, node_count=0, edge_count=0, community_count=0)

    # Build graph and compute structural features
    cache = GraphCache()
    cache.build_from_triplets(triplets)

    community_partition = cache.detect_communities()
    centrality_scores = cache.compute_centrality()
    graph_stats = cache.stats()

    # Compute predicate histogram
    predicate_histogram = dict(Counter(t.predicate for t in triplets))

    # Compute edge set (unique subject-object pairs)
    edge_set = {(t.subject, t.object) for t in triplets}

    # Compute entity predicate patterns
    entity_predicates: dict[str, set[str]] = {}
    for t in triplets:
        entity_predicates.setdefault(t.subject, set()).add(t.predicate)
        entity_predicates.setdefault(t.object, set()).add(t.predicate)

    logger.info(
        "Baseline created: %d nodes, %d edges, %d communities, %d predicates",
        graph_stats["nodes"],
        graph_stats["edges"],
        graph_stats["communities"],
        len(predicate_histogram),
    )

    return Baseline(
        label=label,
        community_partition=community_partition,
        centrality_scores=centrality_scores,
        predicate_histogram=predicate_histogram,
        edge_set=edge_set,
        entity_predicates=entity_predicates,
        node_count=graph_stats["nodes"],
        edge_count=graph_stats["edges"],
        community_count=graph_stats["communities"],
    )
