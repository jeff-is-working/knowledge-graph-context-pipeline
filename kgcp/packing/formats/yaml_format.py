"""YAML output format — the recommended default.

Research shows YAML achieves the best accuracy-to-token ratio for LLM context,
using 34-38% fewer tokens than JSON for equivalent information.
"""

from __future__ import annotations

from ...models import PackedContext, Triplet
from ..token_counter import estimate_tokens


def pack_yaml(
    triplets: list[Triplet],
    budget: int = 2048,
    include_provenance: bool = True,
    include_entity_metadata: bool = True,
) -> PackedContext:
    """Serialize triplets as YAML context within a token budget.

    Format:
        # N triplets, M tokens, from K sources
        entities:
          entity_name: {type: inferred_type, centrality: 0.XX}
        facts:
          - [subject, predicate, object]
        provenance:
          - source: "filename"

    Args:
        triplets: Sorted by confidence (highest first).
        budget: Maximum token count for output.
        include_provenance: Add source document references.
        include_entity_metadata: Add entity type/centrality info.
    """
    if not triplets:
        return PackedContext(
            content="# Empty knowledge graph\nfacts: []\n",
            format="yaml",
            token_count=5,
            triplet_count=0,
        )

    # Collect entity info and sources
    entity_counts: dict[str, int] = {}
    sources: set[str] = set()
    doc_map: dict[str, str] = {}  # doc_id -> source_path (filled from metadata)

    for t in triplets:
        entity_counts[t.subject] = entity_counts.get(t.subject, 0) + 1
        entity_counts[t.object] = entity_counts.get(t.object, 0) + 1
        if t.metadata.get("source_path"):
            sources.add(t.metadata["source_path"])

    # Compute simple centrality (normalized degree)
    max_count = max(entity_counts.values()) if entity_counts else 1
    entity_centrality = {e: round(c / max_count, 2) for e, c in entity_counts.items()}

    # Build YAML incrementally, respecting token budget
    lines: list[str] = []
    included_count = 0

    # Facts section (core — always included first)
    lines.append("facts:")
    for t in triplets:
        fact_line = f"  - [{t.subject}, {t.predicate}, {t.object}]"
        candidate = "\n".join(lines + [fact_line])
        if estimate_tokens(candidate) > budget * 0.85:  # reserve 15% for metadata
            break
        lines.append(fact_line)
        included_count += 1

    # Entity metadata section
    if include_entity_metadata and included_count > 0:
        # Only include entities that appear in included facts
        included_entities: set[str] = set()
        for t in triplets[:included_count]:
            included_entities.add(t.subject)
            included_entities.add(t.object)

        entity_lines = ["entities:"]
        top_entities = sorted(
            included_entities,
            key=lambda e: entity_centrality.get(e, 0),
            reverse=True,
        )[:30]  # Cap entity metadata

        from ...extraction.confidence import infer_entity_type

        for entity in top_entities:
            etype = infer_entity_type(entity)
            cent = entity_centrality.get(entity, 0.0)
            entity_lines.append(f"  {entity}: {{type: {etype}, centrality: {cent}}}")

        candidate = "\n".join(entity_lines + lines)
        if estimate_tokens(candidate) <= budget:
            lines = entity_lines + lines

    # Provenance section
    if include_provenance and sources:
        prov_lines = ["provenance:"]
        for src in sorted(sources):
            prov_lines.append(f'  - source: "{src}"')
        candidate = "\n".join(lines + prov_lines)
        if estimate_tokens(candidate) <= budget:
            lines.extend(prov_lines)

    # Header comment
    content = "\n".join(lines)
    token_count = estimate_tokens(content)
    header = f"# {included_count} triplets, {token_count} tokens, from {len(sources) or '?'} sources"
    content = header + "\n" + content

    token_count = estimate_tokens(content)

    return PackedContext(
        content=content,
        format="yaml",
        token_count=token_count,
        triplet_count=included_count,
        sources=sorted(sources),
        entities={
            e: {"centrality": entity_centrality.get(e, 0.0)}
            for e in entity_centrality
        },
    )
