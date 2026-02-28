"""Context packer — dispatches to format implementations."""

from __future__ import annotations

from ..models import PackedContext, Triplet
from .formats.compact_format import pack_compact
from .formats.markdown_format import pack_markdown
from .formats.nl_format import pack_natural_language
from .formats.yaml_format import pack_yaml

FORMAT_REGISTRY: dict[str, callable] = {
    "yaml": pack_yaml,
    "compact": pack_compact,
    "markdown": pack_markdown,
    "md": pack_markdown,
    "nl": pack_natural_language,
    "natural_language": pack_natural_language,
}


def pack_context(
    triplets: list[Triplet],
    format: str = "yaml",
    budget: int = 2048,
    **kwargs,
) -> PackedContext:
    """Pack triplets into the specified format within a token budget.

    Args:
        triplets: Sorted by relevance/confidence (highest first).
        format: Output format name (yaml, compact, markdown, nl).
        budget: Maximum token count.
        **kwargs: Passed through to format-specific packer.

    Returns:
        PackedContext with serialized content.

    Raises:
        ValueError: If format is not recognized.
    """
    packer_fn = FORMAT_REGISTRY.get(format.lower())
    if packer_fn is None:
        available = ", ".join(sorted(FORMAT_REGISTRY.keys()))
        raise ValueError(f"Unknown format '{format}'. Available: {available}")

    return packer_fn(triplets, budget=budget, **kwargs)
