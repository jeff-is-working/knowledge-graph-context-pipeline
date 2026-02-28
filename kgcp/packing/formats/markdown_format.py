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

    header = "| Subject | Predicate | Object | Confidence |\n|---|---|---|---|\n"
    lines = [header]
    count = 0
    sources: set[str] = set()

    for t in triplets:
        row = f"| {t.subject} | {t.predicate} | {t.object} | {t.confidence:.2f} |"
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
