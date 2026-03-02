"""Attack path reconstruction — temporally-ordered paths from a seed entity."""

from __future__ import annotations

import logging

from ..models import AttackPath, AttackPathStep, Triplet
from ..storage.graph_cache import GraphCache
from ..storage.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)


def reconstruct_attack_path(
    seed_entity: str,
    store: SQLiteStore,
    hops: int = 2,
    since: str | None = None,
    until: str | None = None,
    min_anomaly_score: float = 0.0,
    limit: int = 100,
) -> AttackPath:
    """Reconstruct a temporally-ordered attack path from a seed entity.

    Strategy:
    1. Build graph from all triplets, find N-hop neighbors of seed.
    2. Collect subgraph triplets.
    3. Filter by time range.
    4. Attach anomaly scores from latest baseline.
    5. Sort chronologically by first_seen.
    6. Build AttackPathStep list with anomaly annotations.
    7. Filter by min_anomaly_score, apply limit.
    8. Compute time_span and total_anomaly.

    Args:
        seed_entity: Starting entity for path reconstruction.
        store: SQLiteStore instance.
        hops: Number of graph hops to expand from seed.
        since: ISO date — exclude triplets first seen before this.
        until: ISO date — exclude triplets first seen after this.
        min_anomaly_score: Minimum anomaly score to include a step.
        limit: Maximum number of steps in the path.

    Returns:
        AttackPath with temporally-ordered steps.
    """
    all_triplets = store.get_all_triplets()
    if not all_triplets:
        return AttackPath(seed_entity=seed_entity)

    # Step 1: Build graph and find neighbors
    cache = GraphCache()
    cache.build_from_triplets(all_triplets)

    neighbors = cache.get_neighbors(seed_entity, hops=hops)
    relevant_entities = neighbors | {seed_entity}

    # Step 2: Collect subgraph triplets (any triplet involving relevant entities)
    subgraph_triplets: list[Triplet] = []
    for t in all_triplets:
        if t.subject in relevant_entities or t.object in relevant_entities:
            subgraph_triplets.append(t)

    if not subgraph_triplets:
        return AttackPath(seed_entity=seed_entity)

    # Step 3: Filter by time range
    if since or until:
        filtered: list[Triplet] = []
        for t in subgraph_triplets:
            fs = t.first_seen or ""
            if since and fs and fs < since:
                continue
            if until and fs and fs > until:
                continue
            filtered.append(t)
        subgraph_triplets = filtered

    # Step 4: Attach anomaly scores
    baseline = store.get_latest_baseline()
    anomaly_map: dict[str, tuple[float, dict]] = {}
    if baseline:
        for t in subgraph_triplets:
            result = store.get_anomaly_score_for_triplet(t.triplet_id, baseline.baseline_id)
            if result:
                anomaly_map[t.triplet_id] = (result.score, result.signals)

    # Step 5: Sort chronologically by first_seen
    subgraph_triplets.sort(key=lambda t: t.first_seen or "")

    # Step 6: Build AttackPathStep list
    steps: list[AttackPathStep] = []
    entities_involved: set[str] = set()

    for idx, t in enumerate(subgraph_triplets):
        anom_score, anom_signals = anomaly_map.get(t.triplet_id, (0.0, {}))
        step = AttackPathStep(
            triplet=t,
            timestamp=t.first_seen or "",
            anomaly_score=anom_score,
            anomaly_signals=anom_signals,
            step_index=idx,
        )
        steps.append(step)
        entities_involved.add(t.subject)
        entities_involved.add(t.object)

    # Step 7: Filter by min_anomaly_score and apply limit
    if min_anomaly_score > 0.0:
        steps = [s for s in steps if s.anomaly_score >= min_anomaly_score]

    # Re-index after filtering
    for idx, step in enumerate(steps):
        step.step_index = idx

    steps = steps[:limit]

    # Step 8: Compute time_span and total_anomaly
    time_span = ("", "")
    if steps:
        timestamps = [s.timestamp for s in steps if s.timestamp]
        if timestamps:
            time_span = (min(timestamps), max(timestamps))

    total_anomaly = sum(s.anomaly_score for s in steps)

    return AttackPath(
        seed_entity=seed_entity,
        steps=steps,
        entities_involved=entities_involved,
        time_span=time_span,
        total_anomaly=round(total_anomaly, 4),
    )
