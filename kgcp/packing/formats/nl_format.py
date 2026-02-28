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
