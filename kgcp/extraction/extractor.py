"""Main extraction pipeline — orchestrates chunking, LLM extraction, and normalization.

This is the KGCP equivalent of AIKG's main.py process_text_in_chunks().
"""

from __future__ import annotations

import logging
from typing import Any

from ..models import DocumentChunk, Triplet
from .confidence import score_triplets
from .llm_client import call_llm, extract_json_from_text
from .normalizer import deduplicate_triplets, standardize_entities
from .prompts import EXTRACTION_SYSTEM_PROMPT, EXTRACTION_USER_PROMPT
from .sanitizer import sanitize_for_prompt, detect_injection_signals
from .validator import validate_triplets, format_validation_report

logger = logging.getLogger(__name__)


def chunk_text(text: str, chunk_size: int = 100, overlap: int = 20) -> list[str]:
    """Split text into overlapping word-level chunks.

    Adapted from AIKG's text_utils.chunk_text().
    """
    words = text.split()
    if len(words) <= chunk_size:
        return [text]

    chunks = []
    start = 0
    while start < len(words):
        end = start + chunk_size
        chunk = " ".join(words[start:end])
        chunks.append(chunk)

        next_start = start + chunk_size - overlap
        # If remaining is too small, absorb it into the last chunk
        if next_start + chunk_size - overlap >= len(words):
            if end < len(words):
                chunks[-1] = " ".join(words[start:])
            break
        start = next_start

    return chunks


def extract_triplets_from_text(
    text: str,
    config: dict[str, Any],
    force: bool = False,
) -> list[dict]:
    """Extract raw SPO triplets from a text chunk via LLM.

    Applies input sanitization before prompt interpolation and validates
    extracted triplets for prompt injection indicators.

    Args:
        text: Raw text chunk (untrusted).
        config: Pipeline configuration.
        force: If True, include flagged triplets with a warning instead
               of dropping them.

    Returns:
        List of dicts with 'subject', 'predicate', 'object' keys.
    """
    # Layer 1: Sanitize input text
    sanitized = sanitize_for_prompt(text)
    if not sanitized.clean:
        logger.info("Input sanitized: %s", ", ".join(sanitized.stripped))

    # Layer 1b: Check for injection signals in source text
    signals = detect_injection_signals(sanitized.text)
    high_signals = [s for s in signals if s["severity"] == "high"]
    if high_signals:
        logger.warning(
            "High-severity injection signals detected in source text (%d signals)",
            len(high_signals),
        )

    # Layer 2: Prompt with untrusted-input guardrails (in prompts.py)
    prompt = EXTRACTION_USER_PROMPT.format(text=sanitized.text)

    try:
        response = call_llm(prompt, config, system_prompt=EXTRACTION_SYSTEM_PROMPT)
    except (ConnectionError, Exception) as e:
        logger.error("LLM call failed: %s", e)
        return []

    triplets = extract_json_from_text(response)
    if triplets is None:
        logger.warning("Failed to extract JSON from LLM response")
        return []

    # Validate structure
    valid = []
    for t in triplets:
        if isinstance(t, dict) and all(k in t for k in ("subject", "predicate", "object")):
            valid.append({
                "subject": str(t["subject"]).lower().strip(),
                "predicate": str(t["predicate"]).lower().strip(),
                "object": str(t["object"]).lower().strip(),
            })

    # Layer 3: Post-extraction validation
    validation = validate_triplets(valid)
    if not validation.clean:
        report = format_validation_report(validation)
        logger.warning("Post-extraction validation:\n%s", report)

        if validation.flagged and not force:
            # Drop flagged triplets, keep clean ones
            flagged_set = set(validation.flagged_indices)
            clean_triplets = [t for i, t in enumerate(valid) if i not in flagged_set]
            logger.warning(
                "Dropped %d flagged triplets (use force=True to override)",
                len(flagged_set),
            )
            return clean_triplets

    return valid


def extract_from_chunks(
    chunks: list[DocumentChunk],
    config: dict[str, Any],
) -> list[Triplet]:
    """Run extraction pipeline on a list of document chunks.

    Pipeline: chunk text → LLM extraction → normalize → score → deduplicate.
    """
    all_triplets: list[Triplet] = []

    for chunk in chunks:
        logger.info(
            "Extracting from chunk %d of doc %s",
            chunk.chunk_index,
            chunk.doc_id,
        )
        raw = extract_triplets_from_text(chunk.content, config)

        for raw_t in raw:
            triplet = Triplet(
                subject=raw_t["subject"],
                predicate=raw_t["predicate"],
                object=raw_t["object"],
                doc_id=chunk.doc_id,
                source_chunk_id=chunk.chunk_id,
            )
            all_triplets.append(triplet)

    logger.info("Extracted %d raw triplets from %d chunks", len(all_triplets), len(chunks))

    # Standardize entities
    if config.get("standardization", {}).get("enabled", True):
        all_triplets = standardize_entities(all_triplets)
        logger.info("After standardization: %d triplets", len(all_triplets))

    # Score confidence
    all_triplets = score_triplets(all_triplets)

    # Deduplicate
    all_triplets = deduplicate_triplets(all_triplets)
    logger.info("After deduplication: %d triplets", len(all_triplets))

    return all_triplets


def ingest_text(
    text: str,
    doc_id: str,
    source_path: str,
    config: dict[str, Any],
) -> list[Triplet]:
    """Full ingestion pipeline: text → chunks → triplets.

    This is the main entry point for document ingestion.
    """
    chunk_size = config.get("chunking", {}).get("chunk_size", 100)
    overlap = config.get("chunking", {}).get("overlap", 20)

    text_chunks = chunk_text(text, chunk_size, overlap)
    logger.info("Split into %d chunks (size=%d, overlap=%d)", len(text_chunks), chunk_size, overlap)

    chunks = [
        DocumentChunk(
            content=tc,
            doc_id=doc_id,
            source_path=source_path,
            chunk_index=i,
        )
        for i, tc in enumerate(text_chunks)
    ]

    return extract_from_chunks(chunks, config)
