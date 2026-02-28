"""In-memory NetworkX graph cache for fast traversal and analysis."""

from __future__ import annotations

import logging
from typing import Any

import networkx as nx

from ..models import Triplet

logger = logging.getLogger(__name__)


class GraphCache:
    """Maintains an in-memory NetworkX graph alongside SQLite storage.

    Provides fast graph operations: traversal, community detection,
    centrality computation.
    """

    def __init__(self):
        self.graph: nx.DiGraph = nx.DiGraph()

    def build_from_triplets(self, triplets: list[Triplet]) -> None:
        """Build/rebuild the graph from a list of triplets."""
        self.graph.clear()
        for t in triplets:
            self.graph.add_edge(
                t.subject,
                t.object,
                predicate=t.predicate,
                confidence=t.confidence,
                triplet_id=t.triplet_id,
                inferred=t.inferred,
            )
        logger.info(
            "Graph cache: %d nodes, %d edges",
            self.graph.number_of_nodes(),
            self.graph.number_of_edges(),
        )

    def add_triplet(self, triplet: Triplet) -> None:
        """Add a single triplet to the graph."""
        self.graph.add_edge(
            triplet.subject,
            triplet.object,
            predicate=triplet.predicate,
            confidence=triplet.confidence,
            triplet_id=triplet.triplet_id,
            inferred=triplet.inferred,
        )

    def get_neighbors(self, entity: str, hops: int = 1) -> set[str]:
        """Get entities within N hops of a given entity."""
        if entity not in self.graph:
            return set()

        visited: set[str] = {entity}
        frontier: set[str] = {entity}

        for _ in range(hops):
            next_frontier: set[str] = set()
            for node in frontier:
                # Both successors and predecessors (treat as undirected for traversal)
                next_frontier.update(self.graph.successors(node))
                next_frontier.update(self.graph.predecessors(node))
            next_frontier -= visited
            visited.update(next_frontier)
            frontier = next_frontier

        visited.discard(entity)
        return visited

    def get_subgraph_triplet_ids(self, entities: set[str]) -> set[str]:
        """Get triplet IDs for all edges between a set of entities."""
        ids: set[str] = set()
        for u, v, data in self.graph.edges(data=True):
            if u in entities and v in entities:
                if tid := data.get("triplet_id"):
                    ids.add(tid)
        return ids

    def compute_centrality(self) -> dict[str, float]:
        """Compute degree centrality for all nodes."""
        if not self.graph.nodes:
            return {}
        return nx.degree_centrality(self.graph)

    def detect_communities(self) -> dict[str, int]:
        """Detect communities using Louvain method on undirected projection."""
        if not self.graph.nodes:
            return {}

        try:
            import community as community_louvain
            undirected = self.graph.to_undirected()
            return community_louvain.best_partition(undirected)
        except ImportError:
            logger.warning("python-louvain not installed, skipping community detection")
            return {}

    def get_community_entities(self) -> dict[int, list[str]]:
        """Return entities grouped by community."""
        partition = self.detect_communities()
        if not partition:
            return {}

        communities: dict[int, list[str]] = {}
        for entity, comm_id in partition.items():
            communities.setdefault(comm_id, []).append(entity)
        return communities

    def stats(self) -> dict[str, Any]:
        """Return graph statistics."""
        communities = self.detect_communities()
        num_communities = len(set(communities.values())) if communities else 0

        return {
            "nodes": self.graph.number_of_nodes(),
            "edges": self.graph.number_of_edges(),
            "communities": num_communities,
            "density": round(nx.density(self.graph), 4) if self.graph.nodes else 0.0,
        }
