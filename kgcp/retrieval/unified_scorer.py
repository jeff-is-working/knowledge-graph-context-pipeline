"""Cross-algebra unified scoring — fuses confidence, centrality, anomaly, and recency."""

from __future__ import annotations

import logging
from datetime import datetime, timezone

from ..config import DEFAULTS
from ..models import ScoredTriplet, Triplet
from ..storage.graph_cache import GraphCache

logger = logging.getLogger(__name__)

_DEFAULT_WEIGHTS = DEFAULTS["fusion"]["weights"]
_DEFAULT_RECENCY_WINDOW = DEFAULTS["fusion"]["recency_window_days"]


def compute_recency(
    triplet: Triplet,
    window_days: int = _DEFAULT_RECENCY_WINDOW,
    reference_time: datetime | None = None,
) -> float:
    """Compute temporal recency score for a triplet.

    Returns a value from 1.0 (just seen) to 0.0 (window_days ago or older).
    Uses last_seen, falls back to first_seen.

    Args:
        triplet: The triplet to score.
        window_days: How many days back the recency window extends.
        reference_time: The "now" reference point (defaults to UTC now).

    Returns:
        Recency score clamped to [0.0, 1.0].
    """
    if reference_time is None:
        reference_time = datetime.now(timezone.utc)

    timestamp_str = triplet.last_seen or triplet.first_seen
    if not timestamp_str:
        return 0.0

    try:
        dt = datetime.fromisoformat(timestamp_str)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return 0.0

    age_seconds = (reference_time - dt).total_seconds()
    if age_seconds < 0:
        # Future date — treat as maximally recent
        return 1.0

    window_seconds = window_days * 86400
    if window_seconds <= 0:
        return 1.0 if age_seconds == 0 else 0.0

    recency = 1.0 - (age_seconds / window_seconds)
    return max(0.0, min(1.0, recency))


def compute_centrality_for_triplets(triplets: list[Triplet]) -> dict[str, float]:
    """Build a graph from triplets and return entity centrality scores."""
    if not triplets:
        return {}
    cache = GraphCache()
    cache.build_from_triplets(triplets)
    return cache.compute_centrality()


def collect_anomaly_scores(
    triplets: list[Triplet],
    store,
) -> dict[str, float]:
    """Look up anomaly scores for triplets from the store.

    Args:
        triplets: Triplets to look up scores for.
        store: SQLiteStore instance.

    Returns:
        Dict mapping triplet_id to anomaly score.
    """
    baseline = store.get_latest_baseline()
    if not baseline:
        return {}

    scores: dict[str, float] = {}
    for t in triplets:
        # Check metadata first (already attached by retriever)
        if "anomaly_score" in t.metadata:
            scores[t.triplet_id] = t.metadata["anomaly_score"]
        else:
            result = store.get_anomaly_score_for_triplet(
                t.triplet_id, baseline.baseline_id
            )
            if result:
                scores[t.triplet_id] = result.score
    return scores


def compute_unified_scores(
    triplets: list[Triplet],
    entity_centrality: dict[str, float],
    anomaly_scores: dict[str, float],
    weights: dict[str, float] | None = None,
    recency_window_days: int = _DEFAULT_RECENCY_WINDOW,
    apply_to_confidence: bool = True,
    reference_time: datetime | None = None,
) -> list[ScoredTriplet]:
    """Compute cross-algebra unified relevance scores for triplets.

    Combines four signals:
    - confidence: Original extraction confidence
    - centrality: Average degree centrality of subject + object
    - anomaly: Anomaly score from detector
    - recency: Linear temporal decay within window

    Args:
        triplets: Triplets to score.
        entity_centrality: Entity name -> centrality score.
        anomaly_scores: Triplet ID -> anomaly score.
        weights: Signal weights (must sum to ~1.0). Defaults to config.
        recency_window_days: Temporal decay window.
        apply_to_confidence: Whether to write unified_score back to triplet.confidence.
        reference_time: Reference time for recency computation.

    Returns:
        List of ScoredTriplet sorted by unified_score descending.
    """
    if not triplets:
        return []

    w = weights or dict(_DEFAULT_WEIGHTS)

    results: list[ScoredTriplet] = []

    for t in triplets:
        # Component scores
        conf = t.confidence
        subj_c = entity_centrality.get(t.subject, 0.0)
        obj_c = entity_centrality.get(t.object, 0.0)
        cent = (subj_c + obj_c) / 2
        anom = anomaly_scores.get(t.triplet_id, 0.0)
        rec = compute_recency(t, window_days=recency_window_days, reference_time=reference_time)

        # Weighted sum
        unified = (
            w.get("confidence", 0.30) * conf
            + w.get("centrality", 0.25) * cent
            + w.get("anomaly", 0.20) * anom
            + w.get("recency", 0.25) * rec
        )
        unified = max(0.0, min(1.0, unified))

        components = {
            "confidence": round(conf, 4),
            "centrality": round(cent, 4),
            "anomaly": round(anom, 4),
            "recency": round(rec, 4),
        }

        # Attach to triplet metadata
        t.metadata["unified_score"] = round(unified, 4)
        t.metadata["score_components"] = components

        if apply_to_confidence:
            t.confidence = unified

        results.append(
            ScoredTriplet(
                triplet=t,
                unified_score=round(unified, 4),
                components=components,
            )
        )

    results.sort(key=lambda s: s.unified_score, reverse=True)
    return results
