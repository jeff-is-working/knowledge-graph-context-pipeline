"""Core data models for KGCP."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone


def _uuid() -> str:
    return str(uuid.uuid4())


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class DocumentChunk:
    """A chunk of text extracted from a source document."""

    content: str
    doc_id: str
    source_path: str
    chunk_index: int = 0
    chunk_id: str = field(default_factory=_uuid)
    metadata: dict = field(default_factory=dict)


@dataclass
class Triplet:
    """A Subject-Predicate-Object knowledge triplet."""

    subject: str
    predicate: str
    object: str
    doc_id: str
    confidence: float = 0.5
    source_chunk_id: str = ""
    triplet_id: str = field(default_factory=_uuid)
    inferred: bool = False
    metadata: dict = field(default_factory=dict)


@dataclass
class Document:
    """A tracked source document."""

    source_path: str
    doc_id: str = field(default_factory=_uuid)
    ingested_at: str = field(default_factory=_now)
    metadata: dict = field(default_factory=dict)


@dataclass
class Entity:
    """A named entity appearing in the knowledge graph."""

    name: str
    entity_type: str = "unknown"
    first_seen: str = field(default_factory=_now)
    doc_ids: list[str] = field(default_factory=list)


@dataclass
class PackedContext:
    """Serialized context ready for LLM injection."""

    content: str
    format: str  # yaml, compact, markdown, nl
    token_count: int
    triplet_count: int
    sources: list[str] = field(default_factory=list)
    entities: dict = field(default_factory=dict)
