"""Entity and predicate normalization.

Adapted from AIKG's entity_standardization.py — implements multi-pass
normalization without requiring LLM calls for the basic passes.
"""

from __future__ import annotations

import logging
import re
from collections import Counter

from ..models import Triplet

logger = logging.getLogger(__name__)

STOPWORDS = frozenset(
    "the a an of and or in on at to for with by as is are was were".split()
)


def normalize_entity(name: str) -> str:
    """Normalize an entity name: lowercase, strip stopwords, collapse whitespace."""
    name = name.lower().strip()
    words = [w for w in name.split() if w not in STOPWORDS]
    return " ".join(words) if words else name.lower().strip()


def limit_predicate_length(predicate: str, max_words: int = 3) -> str:
    """Enforce the 1-3 word limit on predicates."""
    words = predicate.strip().split()
    return " ".join(words[:max_words])


def standardize_entities(triplets: list[Triplet]) -> list[Triplet]:
    """Multi-pass entity standardization (no LLM required).

    Pass 1: Group entities by normalized form, pick most frequent variant.
    Pass 2: Merge entities where one is a word-subset of another.

    Returns new Triplet list with standardized subject/object names.
    """
    if not triplets:
        return triplets

    # Collect all entity mentions
    entity_counts: Counter[str] = Counter()
    for t in triplets:
        entity_counts[t.subject] += 1
        entity_counts[t.object] += 1

    # Pass 1: normalization-based grouping
    norm_groups: dict[str, list[str]] = {}
    for entity in entity_counts:
        norm = normalize_entity(entity)
        norm_groups.setdefault(norm, []).append(entity)

    # For each group, pick the most frequent variant (tiebreak: shorter)
    mapping: dict[str, str] = {}
    for norm, variants in norm_groups.items():
        if len(variants) <= 1:
            continue
        best = max(variants, key=lambda v: (entity_counts[v], -len(v)))
        for v in variants:
            if v != best:
                mapping[v] = best

    # Pass 2: subset matching
    standards = sorted(set(entity_counts.keys()) - set(mapping.keys()))
    for i, a in enumerate(standards):
        a_words = set(normalize_entity(a).split())
        for b in standards[i + 1 :]:
            b_words = set(normalize_entity(b).split())
            if a_words and b_words and (a_words <= b_words or b_words <= a_words):
                # Shorter entity becomes the standard
                if len(a) <= len(b):
                    mapping[b] = mapping.get(a, a)
                else:
                    mapping[a] = mapping.get(b, b)

    if mapping:
        logger.info("Standardized %d entity variants", len(mapping))

    # Apply mapping
    result = []
    for t in triplets:
        subject = mapping.get(t.subject, t.subject)
        obj = mapping.get(t.object, t.object)
        predicate = limit_predicate_length(t.predicate)

        # Skip self-references created by standardization
        if subject == obj:
            continue

        result.append(
            Triplet(
                subject=subject,
                predicate=predicate,
                object=obj,
                doc_id=t.doc_id,
                confidence=t.confidence,
                source_chunk_id=t.source_chunk_id,
                triplet_id=t.triplet_id,
                inferred=t.inferred,
                metadata=t.metadata,
            )
        )

    return result


def deduplicate_triplets(triplets: list[Triplet]) -> list[Triplet]:
    """Remove duplicate triplets, keeping the one with highest confidence."""
    seen: dict[tuple[str, str, str], Triplet] = {}
    for t in triplets:
        key = (t.subject, t.predicate, t.object)
        if key not in seen or t.confidence > seen[key].confidence:
            seen[key] = t
    return list(seen.values())
