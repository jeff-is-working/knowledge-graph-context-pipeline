"""Compact arrow format — maximum token density.

Format:
    apt28 -> targets -> energy sector
    apt28 -> uses -> credential harvesting
"""

from __future__ import annotations

from ...models import PackedContext, Triplet
from ..token_counter import estimate_tokens


def pack_compact(
    triplets: list[Triplet],
    budget: int = 2048,
) -> PackedContext:
    """Serialize triplets as compact arrow notation."""
    if not triplets:
        return PackedContext(
            content="# Empty graph\n",
            format="compact",
            token_count=3,
            triplet_count=0,
        )

    lines: list[str] = []
    sources: set[str] = set()

    for t in triplets:
        line = f"{t.subject} -> {t.predicate} -> {t.object}"
        # Temporal suffix when observation_count > 1
        if t.first_seen and t.observation_count > 1:
            date_part = t.first_seen[:10] if len(t.first_seen) >= 10 else t.first_seen
            line += f" [since:{date_part}, x{t.observation_count}]"
        anomaly_score = t.metadata.get("anomaly_score", 0)
        if anomaly_score > 0:
            line += f" [!anomaly:{anomaly_score:.2f}]"
        unified_score = t.metadata.get("unified_score")
        if unified_score is not None:
            line += f" [score:{unified_score:.2f}]"
        candidate = "\n".join(lines + [line])
        if estimate_tokens(candidate) > budget:
            break
        lines.append(line)
        if t.metadata.get("source_path"):
            sources.add(t.metadata["source_path"])

    content = "\n".join(lines)
    token_count = estimate_tokens(content)

    return PackedContext(
        content=content,
        format="compact",
        token_count=token_count,
        triplet_count=len(lines),
        sources=sorted(sources),
    )
