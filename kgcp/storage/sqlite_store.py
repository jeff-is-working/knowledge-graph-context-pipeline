"""SQLite-backed persistent storage for KGCP."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import Document, DocumentChunk, Entity, Triplet

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).parent / "schema.sql"


class SQLiteStore:
    """Persistent storage for documents, chunks, triplets, and entities."""

    def __init__(self, db_path: str | Path):
        self.db_path = Path(db_path).expanduser()
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(self.db_path))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA foreign_keys=ON")
        self._init_schema()

    def _init_schema(self) -> None:
        """Create tables if they don't exist."""
        schema_sql = SCHEMA_PATH.read_text()
        self.conn.executescript(schema_sql)
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    # -- Documents -------------------------------------------------------------

    def add_document(self, doc: Document) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO documents (doc_id, source_path, ingested_at, metadata) "
            "VALUES (?, ?, ?, ?)",
            (doc.doc_id, doc.source_path, doc.ingested_at, json.dumps(doc.metadata)),
        )
        self.conn.commit()

    def get_document(self, doc_id: str) -> Document | None:
        row = self.conn.execute(
            "SELECT * FROM documents WHERE doc_id = ?", (doc_id,)
        ).fetchone()
        if not row:
            return None
        return Document(
            doc_id=row["doc_id"],
            source_path=row["source_path"],
            ingested_at=row["ingested_at"],
            metadata=json.loads(row["metadata"] or "{}"),
        )

    def list_documents(self) -> list[Document]:
        rows = self.conn.execute(
            "SELECT * FROM documents ORDER BY ingested_at DESC"
        ).fetchall()
        return [
            Document(
                doc_id=r["doc_id"],
                source_path=r["source_path"],
                ingested_at=r["ingested_at"],
                metadata=json.loads(r["metadata"] or "{}"),
            )
            for r in rows
        ]

    def delete_document(self, doc_id: str) -> None:
        """Delete a document and all its chunks/triplets (cascading)."""
        self.conn.execute("DELETE FROM documents WHERE doc_id = ?", (doc_id,))
        self.conn.commit()

    # -- Chunks ----------------------------------------------------------------

    def add_chunk(self, chunk: DocumentChunk) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO chunks (chunk_id, doc_id, content, chunk_index, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                chunk.chunk_id,
                chunk.doc_id,
                chunk.content,
                chunk.chunk_index,
                json.dumps(chunk.metadata),
            ),
        )
        self.conn.commit()

    def add_chunks(self, chunks: list[DocumentChunk]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO chunks (chunk_id, doc_id, content, chunk_index, metadata) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (c.chunk_id, c.doc_id, c.content, c.chunk_index, json.dumps(c.metadata))
                for c in chunks
            ],
        )
        self.conn.commit()

    # -- Triplets --------------------------------------------------------------

    def add_triplet(self, triplet: Triplet) -> None:
        self.conn.execute(
            "INSERT OR REPLACE INTO triplets "
            "(triplet_id, subject, predicate, object, confidence, chunk_id, doc_id, inferred, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                triplet.triplet_id,
                triplet.subject,
                triplet.predicate,
                triplet.object,
                triplet.confidence,
                triplet.source_chunk_id or None,
                triplet.doc_id,
                triplet.inferred,
                json.dumps(triplet.metadata),
            ),
        )
        self.conn.commit()

    def add_triplets(self, triplets: list[Triplet]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO triplets "
            "(triplet_id, subject, predicate, object, confidence, chunk_id, doc_id, inferred, metadata) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [
                (
                    t.triplet_id,
                    t.subject,
                    t.predicate,
                    t.object,
                    t.confidence,
                    t.source_chunk_id or None,
                    t.doc_id,
                    t.inferred,
                    json.dumps(t.metadata),
                )
                for t in triplets
            ],
        )
        self.conn.commit()

    def search_triplets(
        self,
        query: str,
        limit: int = 100,
    ) -> list[Triplet]:
        """Search triplets by keyword match on subject, predicate, or object."""
        pattern = f"%{query.lower()}%"
        rows = self.conn.execute(
            "SELECT * FROM triplets "
            "WHERE subject LIKE ? OR predicate LIKE ? OR object LIKE ? "
            "ORDER BY confidence DESC "
            "LIMIT ?",
            (pattern, pattern, pattern, limit),
        ).fetchall()
        return [self._row_to_triplet(r) for r in rows]

    def get_triplets_by_entity(self, entity: str) -> list[Triplet]:
        """Get all triplets involving an entity (as subject or object)."""
        pattern = f"%{entity.lower()}%"
        rows = self.conn.execute(
            "SELECT * FROM triplets WHERE subject LIKE ? OR object LIKE ? "
            "ORDER BY confidence DESC",
            (pattern, pattern),
        ).fetchall()
        return [self._row_to_triplet(r) for r in rows]

    def get_all_triplets(self) -> list[Triplet]:
        rows = self.conn.execute(
            "SELECT * FROM triplets ORDER BY confidence DESC"
        ).fetchall()
        return [self._row_to_triplet(r) for r in rows]

    def get_triplets_by_doc(self, doc_id: str) -> list[Triplet]:
        rows = self.conn.execute(
            "SELECT * FROM triplets WHERE doc_id = ? ORDER BY confidence DESC",
            (doc_id,),
        ).fetchall()
        return [self._row_to_triplet(r) for r in rows]

    def _row_to_triplet(self, row: sqlite3.Row) -> Triplet:
        return Triplet(
            triplet_id=row["triplet_id"],
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
            confidence=row["confidence"],
            source_chunk_id=row["chunk_id"] or "",
            doc_id=row["doc_id"],
            inferred=bool(row["inferred"]),
            metadata=json.loads(row["metadata"] or "{}"),
        )

    # -- Entities --------------------------------------------------------------

    def upsert_entity(self, entity: Entity) -> None:
        """Insert or update an entity, merging doc_ids."""
        existing = self.conn.execute(
            "SELECT doc_ids FROM entities WHERE name = ?", (entity.name,)
        ).fetchone()

        if existing:
            existing_ids = set(json.loads(existing["doc_ids"] or "[]"))
            merged = sorted(existing_ids | set(entity.doc_ids))
            self.conn.execute(
                "UPDATE entities SET doc_ids = ?, entity_type = ? WHERE name = ?",
                (json.dumps(merged), entity.entity_type, entity.name),
            )
        else:
            self.conn.execute(
                "INSERT INTO entities (name, entity_type, first_seen, doc_ids) "
                "VALUES (?, ?, ?, ?)",
                (
                    entity.name,
                    entity.entity_type,
                    entity.first_seen,
                    json.dumps(entity.doc_ids),
                ),
            )
        self.conn.commit()

    def get_all_entities(self) -> list[Entity]:
        rows = self.conn.execute("SELECT * FROM entities ORDER BY name").fetchall()
        return [
            Entity(
                name=r["name"],
                entity_type=r["entity_type"],
                first_seen=r["first_seen"],
                doc_ids=json.loads(r["doc_ids"] or "[]"),
            )
            for r in rows
        ]

    # -- Stats -----------------------------------------------------------------

    def get_stats(self) -> dict[str, Any]:
        """Return summary statistics about the knowledge graph."""
        doc_count = self.conn.execute("SELECT COUNT(*) FROM documents").fetchone()[0]
        chunk_count = self.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        triplet_count = self.conn.execute("SELECT COUNT(*) FROM triplets").fetchone()[0]
        entity_count = self.conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
        inferred_count = self.conn.execute(
            "SELECT COUNT(*) FROM triplets WHERE inferred = 1"
        ).fetchone()[0]

        avg_confidence = self.conn.execute(
            "SELECT AVG(confidence) FROM triplets"
        ).fetchone()[0]

        return {
            "documents": doc_count,
            "chunks": chunk_count,
            "triplets": triplet_count,
            "entities": entity_count,
            "inferred_triplets": inferred_count,
            "extracted_triplets": triplet_count - inferred_count,
            "avg_confidence": round(avg_confidence, 3) if avg_confidence else 0.0,
        }
