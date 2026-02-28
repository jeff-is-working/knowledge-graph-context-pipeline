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
) -> list[dict]:
    """Extract raw SPO triplets from a text chunk via LLM.

    Returns:
        List of dicts with 'subject', 'predicate', 'object' keys.
    """
    prompt = EXTRACTION_USER_PROMPT.format(text=text)

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
