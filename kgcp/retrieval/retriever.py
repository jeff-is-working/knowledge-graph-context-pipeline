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
        since: str | None = None,
        until: str | None = None,
        unified_scoring: bool = False,
        fusion_weights: dict[str, float] | None = None,
        min_anomaly_score: float | None = None,
    ) -> list[Triplet]:
        """Retrieve triplets relevant to a query.

        Strategy:
        1. Keyword search for seed triplets matching query terms.
        2. Expand via N-hop traversal from seed entities.
        3. Score and rank by relevance.
        4. Filter by time range if since/until provided.
        5. (Optional) Cross-algebra unified scoring.

        Args:
            query_text: Natural language query or entity name.
            hops: Number of graph hops to expand from seed matches.
            limit: Maximum triplets to return.
            since: ISO date string — exclude triplets last seen before this.
            until: ISO date string — exclude triplets first seen after this.
            unified_scoring: Enable cross-algebra unified scoring.
            fusion_weights: Override config fusion weights.
            min_anomaly_score: Filter out triplets below this anomaly score.

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

        # Step 4: Attach anomaly scores if requested (or if unified scoring needs them)
        if include_anomaly_scores or unified_scoring:
            self._attach_anomaly_scores(scored)

        # Step 5: Filter by time range if provided
        if since or until:
            scored = [t for t in scored if self._passes_temporal_filter(t, since, until)]

        # Step 6: Cross-algebra unified scoring
        if unified_scoring:
            from .unified_scorer import (
                compute_centrality_for_triplets,
                compute_unified_scores,
            )

            entity_centrality = compute_centrality_for_triplets(scored)
            anomaly_map = {
                t.triplet_id: t.metadata.get("anomaly_score", 0.0) for t in scored
            }
            compute_unified_scores(
                scored,
                entity_centrality,
                anomaly_map,
                weights=fusion_weights,
                apply_to_confidence=True,
            )

        # Step 7: Filter by minimum anomaly score if set
        if min_anomaly_score is not None:
            scored = [
                t for t in scored
                if t.metadata.get("anomaly_score", 0.0) >= min_anomaly_score
            ]

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

    @staticmethod
    def _passes_temporal_filter(
        triplet: Triplet, since: str | None, until: str | None
    ) -> bool:
        """Check if a triplet falls within the given time range."""
        if since:
            last_seen = triplet.last_seen or triplet.first_seen or ""
            if last_seen and last_seen < since:
                return False
        if until:
            first_seen = triplet.first_seen or triplet.last_seen or ""
            if first_seen and first_seen > until:
                return False
        return True

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
