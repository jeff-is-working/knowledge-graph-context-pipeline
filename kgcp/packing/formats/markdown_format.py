"""Markdown table format — human-readable structured output."""

from __future__ import annotations

from ...models import PackedContext, Triplet
from ..token_counter import estimate_tokens


def pack_markdown(
    triplets: list[Triplet],
    budget: int = 2048,
) -> PackedContext:
    """Serialize triplets as a Markdown table."""
    if not triplets:
        return PackedContext(
            content="*No triplets found.*\n",
            format="markdown",
            token_count=5,
            triplet_count=0,
        )

    has_anomalies = any(t.metadata.get("anomaly_score", 0) > 0 for t in triplets)
    has_temporal = any(t.first_seen and t.observation_count > 0 for t in triplets)
    has_unified = any("unified_score" in t.metadata for t in triplets)

    # Build header based on available columns
    cols = ["Subject", "Predicate", "Object", "Confidence"]
    if has_temporal:
        cols.extend(["First Seen", "Obs"])
    if has_anomalies:
        cols.append("Anomaly")
    if has_unified:
        cols.append("Score")
    header = "| " + " | ".join(cols) + " |\n|" + "|".join(["---"] * len(cols)) + "|\n"

    lines = [header]
    count = 0
    sources: set[str] = set()

    for t in triplets:
        parts = [t.subject, t.predicate, t.object, f"{t.confidence:.2f}"]
        if has_temporal:
            fs = t.first_seen[:10] if t.first_seen and len(t.first_seen) >= 10 else (t.first_seen or "")
            parts.append(fs)
            parts.append(str(t.observation_count) if t.observation_count > 1 else "")
        if has_anomalies:
            anom = t.metadata.get("anomaly_score", 0)
            parts.append(f"{anom:.2f}" if anom > 0 else "")
        if has_unified:
            us = t.metadata.get("unified_score")
            parts.append(f"{us:.2f}" if us is not None else "")
        row = "| " + " | ".join(parts) + " |"
        candidate = "".join(lines) + row + "\n"
        if estimate_tokens(candidate) > budget:
            break
        lines.append(row + "\n")
        count += 1
        if t.metadata.get("source_path"):
            sources.add(t.metadata["source_path"])

    content = "".join(lines)
    token_count = estimate_tokens(content)

    return PackedContext(
        content=content,
        format="markdown",
        token_count=token_count,
        triplet_count=count,
        sources=sorted(sources),
    )
