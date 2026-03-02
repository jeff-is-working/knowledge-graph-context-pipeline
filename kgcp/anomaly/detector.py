"""AnomalyDetector — high-level orchestration for anomaly detection."""

from __future__ import annotations

import logging

from ..models import AnomalyResult, Baseline
from ..storage.graph_cache import GraphCache
from ..storage.sqlite_store import SQLiteStore
from .baseline import create_baseline
from .scorer import score_triplets_anomaly

logger = logging.getLogger(__name__)


class AnomalyDetector:
    """Orchestrates baseline creation and anomaly scoring."""

    def __init__(self, store: SQLiteStore):
        self.store = store

    def create_and_save_baseline(self, label: str = "") -> Baseline:
        """Create a baseline from all current triplets and persist it."""
        triplets = self.store.get_all_triplets()
        baseline = create_baseline(triplets, label=label)
        self.store.add_baseline(baseline)
        logger.info(
            "Saved baseline %s: %d nodes, %d edges",
            baseline.baseline_id[:8],
            baseline.node_count,
            baseline.edge_count,
        )
        return baseline

    def get_latest_baseline(self) -> Baseline | None:
        return self.store.get_latest_baseline()

    def list_baselines(self) -> list[Baseline]:
        return self.store.list_baselines()

    def score_all_triplets(
        self,
        baseline: Baseline | None = None,
        weights: dict[str, float] | None = None,
    ) -> list[AnomalyResult]:
        """Score every triplet against a baseline and persist results."""
        if baseline is None:
            baseline = self.store.get_latest_baseline()
        if baseline is None:
            logger.warning("No baseline available for scoring")
            return []

        triplets = self.store.get_all_triplets()
        if not triplets:
            return []

        current_centrality = self._compute_current_centrality(triplets)
        results = score_triplets_anomaly(triplets, baseline, current_centrality, weights)
        self.store.add_anomaly_scores(results)
        logger.info("Scored %d triplets, max anomaly: %.2f", len(results), results[0].score if results else 0)
        return results

    def score_triplets_since(
        self,
        since: str,
        baseline: Baseline | None = None,
        weights: dict[str, float] | None = None,
    ) -> list[AnomalyResult]:
        """Score only triplets from documents ingested after a date."""
        if baseline is None:
            baseline = self.store.get_latest_baseline()
        if baseline is None:
            logger.warning("No baseline available for scoring")
            return []

        triplets = self.store.get_triplets_since(since)
        if not triplets:
            return []

        # Current centrality includes all triplets (the full graph)
        all_triplets = self.store.get_all_triplets()
        current_centrality = self._compute_current_centrality(all_triplets)

        results = score_triplets_anomaly(triplets, baseline, current_centrality, weights)
        self.store.add_anomaly_scores(results)
        logger.info("Scored %d new triplets since %s", len(results), since)
        return results

    def detect_entity_drift(
        self,
        entity: str,
        baseline: Baseline | None = None,
    ) -> dict:
        """Report how an entity has changed relative to baseline.

        Returns dict with:
        - community_change: old -> new community ID (or None)
        - centrality_delta: change in centrality score
        - new_predicates: predicates not in baseline
        - lost_predicates: baseline predicates no longer used
        - new_neighbors: entities not connected in baseline
        """
        if baseline is None:
            baseline = self.store.get_latest_baseline()
        if baseline is None:
            return {"error": "No baseline available"}

        # Current state
        all_triplets = self.store.get_all_triplets()
        cache = GraphCache()
        cache.build_from_triplets(all_triplets)
        current_centrality = cache.compute_centrality()
        current_communities = cache.detect_communities()

        # Current predicates and neighbors for entity
        current_predicates: set[str] = set()
        current_neighbors: set[str] = set()
        for t in all_triplets:
            if t.subject == entity:
                current_predicates.add(t.predicate)
                current_neighbors.add(t.object)
            if t.object == entity:
                current_predicates.add(t.predicate)
                current_neighbors.add(t.subject)

        # Baseline state
        baseline_predicates = baseline.entity_predicates.get(entity, set())
        baseline_neighbors = set()
        for subj, obj in baseline.edge_set:
            if subj == entity:
                baseline_neighbors.add(obj)
            if obj == entity:
                baseline_neighbors.add(subj)

        old_comm = baseline.community_partition.get(entity)
        new_comm = current_communities.get(entity)
        old_cent = baseline.centrality_scores.get(entity, 0.0)
        new_cent = current_centrality.get(entity, 0.0)

        return {
            "entity": entity,
            "community_change": {"old": old_comm, "new": new_comm}
            if old_comm != new_comm
            else None,
            "centrality_delta": round(new_cent - old_cent, 4),
            "new_predicates": sorted(current_predicates - baseline_predicates),
            "lost_predicates": sorted(baseline_predicates - current_predicates),
            "new_neighbors": sorted(current_neighbors - baseline_neighbors),
        }

    def _compute_current_centrality(self, triplets) -> dict[str, float]:
        cache = GraphCache()
        cache.build_from_triplets(triplets)
        return cache.compute_centrality()
