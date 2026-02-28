"""Heuristic confidence scoring for triplets.

No extra LLM calls — scores based on predicate specificity,
entity characteristics, and extraction context.
"""

from __future__ import annotations

from ..models import Triplet

# Predicates that indicate strong, specific relationships
STRONG_PREDICATES = frozenset({
    "targets", "exploits", "uses", "deploys", "operates",
    "employs", "develops", "creates", "authors", "leads",
    "manages", "controls", "funds", "owns", "produces",
    "attacks", "compromises", "breaches", "infiltrates",
})

# Generic predicates that are less informative
WEAK_PREDICATES = frozenset({
    "relates to", "associated with", "connected to",
    "linked to", "related to", "involves",
})

# Entity type keywords
ENTITY_TYPE_SIGNALS: dict[str, list[str]] = {
    "threat_actor": ["apt", "group", "actor", "gang", "team"],
    "malware": ["trojan", "ransomware", "backdoor", "exploit", "malware", "rat"],
    "organization": ["inc", "corp", "ltd", "agency", "department", "ministry"],
    "location": ["country", "city", "region", "province", "state"],
    "technique": ["phishing", "harvesting", "injection", "brute force", "scanning"],
    "tool": ["tool", "framework", "kit", "scanner", "proxy"],
    "vulnerability": ["cve", "vulnerability", "flaw", "bug", "weakness"],
}


def infer_entity_type(entity: str) -> str:
    """Infer entity type from name keywords."""
    lower = entity.lower()
    for etype, keywords in ENTITY_TYPE_SIGNALS.items():
        if any(kw in lower for kw in keywords):
            return etype
    return "unknown"


def score_triplet(triplet: Triplet) -> float:
    """Compute heuristic confidence score for a triplet.

    Scoring factors:
    - Predicate specificity (strong > neutral > weak)
    - Entity name quality (multi-word > single word)
    - Inferred penalty (inferred relationships score lower)

    Returns:
        Float between 0.0 and 1.0.
    """
    score = 0.5  # baseline

    # Predicate specificity
    pred_lower = triplet.predicate.lower()
    if pred_lower in STRONG_PREDICATES:
        score += 0.2
    elif pred_lower in WEAK_PREDICATES:
        score -= 0.15

    # Multi-word entities are typically more specific
    subj_words = len(triplet.subject.split())
    obj_words = len(triplet.object.split())
    if subj_words >= 2:
        score += 0.05
    if obj_words >= 2:
        score += 0.05

    # Predicate word count — 1-2 words tend to be cleaner
    pred_words = len(triplet.predicate.split())
    if pred_words <= 2:
        score += 0.05

    # Inferred relationships are less certain
    if triplet.inferred:
        score -= 0.2

    return max(0.0, min(1.0, score))


def score_triplets(triplets: list[Triplet]) -> list[Triplet]:
    """Score all triplets and update their confidence field."""
    for t in triplets:
        t.confidence = score_triplet(t)
    return triplets
