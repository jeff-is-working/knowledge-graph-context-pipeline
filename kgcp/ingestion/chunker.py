"""Paragraph-aware text chunking.

Wraps AIKG's word-level chunking with paragraph boundary awareness
so chunks don't split mid-sentence when possible.
"""

from __future__ import annotations

import re

from ..models import DocumentChunk


def chunk_text_paragraphs(
    text: str,
    doc_id: str,
    source_path: str,
    chunk_size: int = 100,
    overlap: int = 20,
) -> list[DocumentChunk]:
    """Split text into chunks, preferring paragraph boundaries.

    1. Split text into paragraphs.
    2. Greedily combine paragraphs until hitting chunk_size words.
    3. Fall back to word-level splitting for oversized paragraphs.

    Returns list of DocumentChunks.
    """
    # Split into paragraphs (double newline or more)
    paragraphs = re.split(r"\n\s*\n", text.strip())
    paragraphs = [p.strip() for p in paragraphs if p.strip()]

    if not paragraphs:
        return []

    chunks: list[DocumentChunk] = []
    current_words: list[str] = []
    chunk_index = 0

    for para in paragraphs:
        para_words = para.split()

        # If this paragraph alone exceeds chunk_size, split it
        if len(para_words) > chunk_size:
            # Flush current buffer first
            if current_words:
                chunks.append(
                    DocumentChunk(
                        content=" ".join(current_words),
                        doc_id=doc_id,
                        source_path=source_path,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1
                # Keep overlap words
                current_words = current_words[-overlap:] if overlap > 0 else []

            # Word-level split of the large paragraph
            start = 0
            while start < len(para_words):
                end = start + chunk_size
                chunk_words = para_words[start:end]
                chunks.append(
                    DocumentChunk(
                        content=" ".join(chunk_words),
                        doc_id=doc_id,
                        source_path=source_path,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1
                start = end - overlap if overlap > 0 else end
                if start >= len(para_words):
                    break
            current_words = para_words[-overlap:] if overlap > 0 else []
            continue

        # Would adding this paragraph exceed the chunk size?
        if len(current_words) + len(para_words) > chunk_size:
            # Flush current chunk
            if current_words:
                chunks.append(
                    DocumentChunk(
                        content=" ".join(current_words),
                        doc_id=doc_id,
                        source_path=source_path,
                        chunk_index=chunk_index,
                    )
                )
                chunk_index += 1
                current_words = current_words[-overlap:] if overlap > 0 else []

        current_words.extend(para_words)

    # Flush remaining
    if current_words:
        chunks.append(
            DocumentChunk(
                content=" ".join(current_words),
                doc_id=doc_id,
                source_path=source_path,
                chunk_index=chunk_index,
            )
        )

    return chunks
