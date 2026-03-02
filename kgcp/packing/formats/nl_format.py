"""Natural language format — dense prose summaries."""

from __future__ import annotations

from ...models import PackedContext, Triplet
from ..token_counter import estimate_tokens


def pack_natural_language(
    triplets: list[Triplet],
    budget: int = 2048,
) -> PackedContext:
    """Serialize triplets as natural language sentences."""
    if not triplets:
        return PackedContext(
            content="No knowledge available.\n",
            format="nl",
            token_count=4,
            triplet_count=0,
        )

    sentences: list[str] = []
    sources: set[str] = set()

    for t in triplets:
        sentence = f"{t.subject} {t.predicate} {t.object}."
        # Capitalize first letter
        sentence = sentence[0].upper() + sentence[1:]
        # Temporal qualifier
        if t.first_seen and t.observation_count > 1:
            date_part = t.first_seen[:10] if len(t.first_seen) >= 10 else t.first_seen
            sentence = sentence.rstrip(".") + f" (since {date_part}, observed {t.observation_count} times)."
        if t.metadata.get("anomaly_score", 0) > 0:
            sentence = sentence.rstrip(".") + " (anomalous)."
        unified_score = t.metadata.get("unified_score")
        if unified_score is not None:
            sentence = sentence.rstrip(".") + f" (relevance: {unified_score:.2f})."
        candidate = " ".join(sentences + [sentence])
        if estimate_tokens(candidate) > budget:
            break
        sentences.append(sentence)
        if t.metadata.get("source_path"):
            sources.add(t.metadata["source_path"])

    content = " ".join(sentences)
    token_count = estimate_tokens(content)

    return PackedContext(
        content=content,
        format="nl",
        token_count=token_count,
        triplet_count=len(sentences),
        sources=sorted(sources),
    )
