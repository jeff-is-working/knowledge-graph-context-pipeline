"""Relevance scoring for retrieved triplets."""

from __future__ import annotations

from ..models import Triplet


def score_by_centrality(
    triplets: list[Triplet],
    entity_centrality: dict[str, float],
) -> list[Triplet]:
    """Boost triplet scores based on entity centrality in the graph.

    Entities that appear in many relationships are more central
    and their triplets should rank higher.
    """
    for t in triplets:
        subj_c = entity_centrality.get(t.subject, 0.0)
        obj_c = entity_centrality.get(t.object, 0.0)
        centrality_boost = (subj_c + obj_c) / 2 * 0.2
        t.confidence = min(1.0, t.confidence + centrality_boost)
    return triplets


def boost_by_anomaly(
    triplets: list[Triplet],
    weight: float = 0.1,
) -> list[Triplet]:
    """Boost triplet confidence based on anomaly score in metadata.

    Anomalous triplets are interesting and worth surfacing. This function
    boosts their confidence score proportionally to their anomaly score.
    """
    for t in triplets:
        anomaly_score = t.metadata.get("anomaly_score", 0.0)
        if anomaly_score > 0:
            t.confidence = min(1.0, t.confidence + anomaly_score * weight)
    return triplets
