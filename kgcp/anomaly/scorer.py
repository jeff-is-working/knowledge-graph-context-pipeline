"""Anomaly scoring — five structural signals combined into a single score."""

from __future__ import annotations

import logging

from ..models import AnomalyResult, Baseline, Triplet

logger = logging.getLogger(__name__)

# Default signal weights
DEFAULT_WEIGHTS = {
    "new_entity": 0.30,
    "new_edge": 0.25,
    "community_mismatch": 0.20,
    "unusual_predicate": 0.15,
    "centrality_drift": 0.10,
}


def _signal_new_entity(triplet: Triplet, baseline: Baseline) -> float:
    """Score based on whether entities are new (not in baseline).

    Returns:
        1.0 if both entities are new, 0.5 if one is new, 0.0 if both known.
    """
    known = set(baseline.centrality_scores.keys())
    subj_new = triplet.subject not in known
    obj_new = triplet.object not in known
    if subj_new and obj_new:
        return 1.0
    elif subj_new or obj_new:
        return 0.5
    return 0.0


def _signal_new_edge(triplet: Triplet, baseline: Baseline) -> float:
    """Score based on whether the (subject, object) pair existed in baseline.

    Returns:
        1.0 if the edge pair is new, 0.0 if it existed.
    """
    if (triplet.subject, triplet.object) in baseline.edge_set:
        return 0.0
    return 1.0


def _signal_community_mismatch(triplet: Triplet, baseline: Baseline) -> float:
    """Score based on whether subject and object are in different communities.

    Returns:
        1.0 if in different communities, 0.0 if same or unknown.
    """
    partition = baseline.community_partition
    subj_comm = partition.get(triplet.subject)
    obj_comm = partition.get(triplet.object)
    if subj_comm is not None and obj_comm is not None and subj_comm != obj_comm:
        return 1.0
    return 0.0


def _signal_unusual_predicate(triplet: Triplet, baseline: Baseline) -> float:
    """Score based on predicate rarity (inverse frequency).

    Returns:
        Score from 0.0 (most common) to 1.0 (new predicate).
    """
    histogram = baseline.predicate_histogram
    if not histogram:
        return 1.0

    count = histogram.get(triplet.predicate, 0)
    if count == 0:
        return 1.0  # Completely new predicate

    max_count = max(histogram.values())
    # Inverse frequency: rare predicates score higher
    return 1.0 - (count / max_count)


def _signal_centrality_drift(
    triplet: Triplet,
    baseline: Baseline,
    current_centrality: dict[str, float],
) -> float:
    """Score based on centrality change from baseline.

    Returns:
        Average absolute centrality change for both entities, clamped to [0, 1].
    """
    if not current_centrality or not baseline.centrality_scores:
        return 0.0

    subj_old = baseline.centrality_scores.get(triplet.subject, 0.0)
    subj_new = current_centrality.get(triplet.subject, 0.0)
    obj_old = baseline.centrality_scores.get(triplet.object, 0.0)
    obj_new = current_centrality.get(triplet.object, 0.0)

    drift = (abs(subj_new - subj_old) + abs(obj_new - obj_old)) / 2
    return min(1.0, drift)


def score_triplet_anomaly(
    triplet: Triplet,
    baseline: Baseline,
    current_centrality: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> AnomalyResult:
    """Score a single triplet's anomaly level against a baseline.

    Args:
        triplet: The triplet to score.
        baseline: The baseline fingerprint to compare against.
        current_centrality: Current graph centrality scores (optional).
        weights: Signal weights (defaults to DEFAULT_WEIGHTS).

    Returns:
        AnomalyResult with score 0.0 (normal) to 1.0 (highly anomalous).
    """
    w = weights or DEFAULT_WEIGHTS
    current = current_centrality or {}

    signals = {
        "new_entity": _signal_new_entity(triplet, baseline),
        "new_edge": _signal_new_edge(triplet, baseline),
        "community_mismatch": _signal_community_mismatch(triplet, baseline),
        "unusual_predicate": _signal_unusual_predicate(triplet, baseline),
        "centrality_drift": _signal_centrality_drift(triplet, baseline, current),
    }

    score = sum(signals[s] * w.get(s, 0.0) for s in signals)
    score = max(0.0, min(1.0, score))

    return AnomalyResult(
        triplet_id=triplet.triplet_id,
        score=round(score, 4),
        signals={k: round(v, 4) for k, v in signals.items()},
        baseline_id=baseline.baseline_id,
        subject=triplet.subject,
        predicate=triplet.predicate,
        object=triplet.object,
    )


def score_triplets_anomaly(
    triplets: list[Triplet],
    baseline: Baseline,
    current_centrality: dict[str, float] | None = None,
    weights: dict[str, float] | None = None,
) -> list[AnomalyResult]:
    """Score multiple triplets and return sorted by anomaly score (highest first)."""
    results = [
        score_triplet_anomaly(t, baseline, current_centrality, weights)
        for t in triplets
    ]
    results.sort(key=lambda r: r.score, reverse=True)
    return results
