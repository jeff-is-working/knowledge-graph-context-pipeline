"""Subgraph retrieval from the knowledge store.

Combines keyword search with graph traversal to find relevant triplets.
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import Triplet
from ..storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


class Retriever:
    """Retrieves relevant subgraphs from the knowledge store."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def query(
        self,
        query_text: str,
        hops: int = 2,
        limit: int = 200,
        include_anomaly_scores: bool = False,
    ) -> list[Triplet]:
        """Retrieve triplets relevant to a query.

        Strategy:
        1. Keyword search for seed triplets matching query terms.
        2. Expand via N-hop traversal from seed entities.
        3. Score and rank by relevance.

        Args:
            query_text: Natural language query or entity name.
            hops: Number of graph hops to expand from seed matches.
            limit: Maximum triplets to return.

        Returns:
            List of Triplets sorted by relevance (confidence * match score).
        """
        # Step 1: keyword search for seeds
        query_terms = query_text.lower().split()
        seed_triplets = self.store.search_triplets(query_text, limit=limit)

        # Also search individual terms if multi-word query
        if len(query_terms) > 1:
            for term in query_terms:
                if len(term) >= 3:  # skip short words
                    seed_triplets.extend(self.store.search_triplets(term, limit=50))

        if not seed_triplets:
            logger.info("No seed triplets found for query: %s", query_text)
            return []

        # Deduplicate seeds
        seen_ids = set()
        unique_seeds = []
        for t in seed_triplets:
            if t.triplet_id not in seen_ids:
                seen_ids.add(t.triplet_id)
                unique_seeds.append(t)
        seed_triplets = unique_seeds

        logger.info("Found %d seed triplets", len(seed_triplets))

        # Step 2: N-hop expansion from seed entities
        all_triplets = list(seed_triplets)
        expanded_entities: set[str] = set()
        frontier_entities: set[str] = set()

        for t in seed_triplets:
            frontier_entities.add(t.subject)
            frontier_entities.add(t.object)

        for hop in range(hops):
            if not frontier_entities:
                break

            next_frontier: set[str] = set()
            for entity in frontier_entities:
                if entity in expanded_entities:
                    continue
                expanded_entities.add(entity)

                neighbors = self.store.get_triplets_by_entity(entity)
                for n in neighbors:
                    if n.triplet_id not in seen_ids:
                        seen_ids.add(n.triplet_id)
                        all_triplets.append(n)
                        next_frontier.add(n.subject)
                        next_frontier.add(n.object)

            frontier_entities = next_frontier - expanded_entities
            logger.info("Hop %d: %d total triplets", hop + 1, len(all_triplets))

        # Step 3: Score by relevance to query
        scored = self._score_relevance(all_triplets, query_terms)

        # Step 4: Attach anomaly scores if requested
        if include_anomaly_scores:
            self._attach_anomaly_scores(scored)

        # Sort by combined score and limit
        scored.sort(key=lambda t: t.confidence, reverse=True)
        return scored[:limit]

    def _score_relevance(
        self,
        triplets: list[Triplet],
        query_terms: list[str],
    ) -> list[Triplet]:
        """Boost confidence of triplets that match query terms."""
        for t in triplets:
            boost = 0.0
            combined = f"{t.subject} {t.predicate} {t.object}".lower()
            for term in query_terms:
                if term in combined:
                    boost += 0.1
            # Cap at 1.0
            t.confidence = min(1.0, t.confidence + boost)
        return triplets

    def _attach_anomaly_scores(self, triplets: list[Triplet]) -> None:
        """Attach anomaly_score and anomaly_signals to triplet metadata."""
        baseline = self.store.get_latest_baseline()
        if not baseline:
            return
        for t in triplets:
            result = self.store.get_anomaly_score_for_triplet(t.triplet_id, baseline.baseline_id)
            if result:
                t.metadata["anomaly_score"] = result.score
                t.metadata["anomaly_signals"] = result.signals
