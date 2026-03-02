"""SQLite-backed persistent storage for KGCP."""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ..models import AnomalyResult, Baseline, Document, DocumentChunk, Entity, Triplet

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
        self._migrate_schema()

    def _migrate_schema(self) -> None:
        """Add temporal columns to existing databases (idempotent)."""
        migrations = [
            "ALTER TABLE triplets ADD COLUMN first_seen TEXT DEFAULT ''",
            "ALTER TABLE triplets ADD COLUMN last_seen TEXT DEFAULT ''",
            "ALTER TABLE triplets ADD COLUMN observation_count INTEGER DEFAULT 1",
        ]
        for sql in migrations:
            try:
                self.conn.execute(sql)
            except sqlite3.OperationalError:
                pass  # Column already exists
        self.conn.commit()
        self._backfill_temporal()

    def _backfill_temporal(self) -> None:
        """Set first_seen/last_seen on existing triplets from their document's ingested_at."""
        self.conn.execute(
            "UPDATE triplets SET first_seen = ("
            "  SELECT d.ingested_at FROM documents d WHERE d.doc_id = triplets.doc_id"
            "), last_seen = ("
            "  SELECT d.ingested_at FROM documents d WHERE d.doc_id = triplets.doc_id"
            ") WHERE first_seen = '' OR first_seen IS NULL"
        )
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
            "(triplet_id, subject, predicate, object, confidence, chunk_id, doc_id, "
            "inferred, metadata, first_seen, last_seen, observation_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                triplet.first_seen,
                triplet.last_seen,
                triplet.observation_count,
            ),
        )
        self.conn.commit()

    def add_triplets(self, triplets: list[Triplet]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO triplets "
            "(triplet_id, subject, predicate, object, confidence, chunk_id, doc_id, "
            "inferred, metadata, first_seen, last_seen, observation_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    t.first_seen,
                    t.last_seen,
                    t.observation_count,
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

    def upsert_triplet(self, triplet: Triplet) -> None:
        """Insert or update a triplet based on case-insensitive (subject, predicate, object) match.

        If a matching triplet exists: update last_seen, increment observation_count,
        keep the higher confidence, preserve first_seen and triplet_id.
        Otherwise: insert normally.
        """
        row = self.conn.execute(
            "SELECT triplet_id, first_seen, last_seen, observation_count, confidence "
            "FROM triplets WHERE LOWER(subject) = LOWER(?) AND LOWER(predicate) = LOWER(?) "
            "AND LOWER(object) = LOWER(?)",
            (triplet.subject, triplet.predicate, triplet.object),
        ).fetchone()

        if row:
            new_confidence = max(row["confidence"], triplet.confidence)
            new_last_seen = max(row["last_seen"] or "", triplet.last_seen)
            new_count = (row["observation_count"] or 1) + 1
            self.conn.execute(
                "UPDATE triplets SET last_seen = ?, observation_count = ?, confidence = ? "
                "WHERE triplet_id = ?",
                (new_last_seen, new_count, new_confidence, row["triplet_id"]),
            )
        else:
            self.conn.execute(
                "INSERT INTO triplets "
                "(triplet_id, subject, predicate, object, confidence, chunk_id, doc_id, "
                "inferred, metadata, first_seen, last_seen, observation_count) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                    triplet.first_seen,
                    triplet.last_seen,
                    triplet.observation_count,
                ),
            )
        self.conn.commit()

    def upsert_triplets(self, triplets: list[Triplet]) -> None:
        """Batch upsert — calls upsert_triplet for each."""
        for t in triplets:
            self.upsert_triplet(t)

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
            first_seen=row["first_seen"] or "",
            last_seen=row["last_seen"] or "",
            observation_count=row["observation_count"] or 1,
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

    # -- Baselines -------------------------------------------------------------

    def add_baseline(self, baseline: Baseline) -> None:
        edge_set_list = [list(pair) for pair in baseline.edge_set]
        entity_preds = {k: list(v) for k, v in baseline.entity_predicates.items()}
        self.conn.execute(
            "INSERT OR REPLACE INTO baselines "
            "(baseline_id, label, created_at, community_partition, centrality_scores, "
            "predicate_histogram, edge_set, entity_predicates, node_count, edge_count, community_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                baseline.baseline_id,
                baseline.label,
                baseline.created_at,
                json.dumps(baseline.community_partition),
                json.dumps(baseline.centrality_scores),
                json.dumps(baseline.predicate_histogram),
                json.dumps(edge_set_list),
                json.dumps(entity_preds),
                baseline.node_count,
                baseline.edge_count,
                baseline.community_count,
            ),
        )
        self.conn.commit()

    def get_baseline(self, baseline_id: str) -> Baseline | None:
        row = self.conn.execute(
            "SELECT * FROM baselines WHERE baseline_id = ?", (baseline_id,)
        ).fetchone()
        if not row:
            return None
        return self._row_to_baseline(row)

    def get_latest_baseline(self) -> Baseline | None:
        row = self.conn.execute(
            "SELECT * FROM baselines ORDER BY created_at DESC LIMIT 1"
        ).fetchone()
        if not row:
            return None
        return self._row_to_baseline(row)

    def list_baselines(self) -> list[Baseline]:
        rows = self.conn.execute(
            "SELECT * FROM baselines ORDER BY created_at DESC"
        ).fetchall()
        return [self._row_to_baseline(r) for r in rows]

    def delete_baseline(self, baseline_id: str) -> None:
        self.conn.execute("DELETE FROM baselines WHERE baseline_id = ?", (baseline_id,))
        self.conn.commit()

    def _row_to_baseline(self, row: sqlite3.Row) -> Baseline:
        edge_set_list = json.loads(row["edge_set"] or "[]")
        entity_preds_raw = json.loads(row["entity_predicates"] or "{}")
        return Baseline(
            baseline_id=row["baseline_id"],
            label=row["label"] or "",
            created_at=row["created_at"],
            community_partition=json.loads(row["community_partition"] or "{}"),
            centrality_scores=json.loads(row["centrality_scores"] or "{}"),
            predicate_histogram=json.loads(row["predicate_histogram"] or "{}"),
            edge_set={tuple(pair) for pair in edge_set_list},
            entity_predicates={k: set(v) for k, v in entity_preds_raw.items()},
            node_count=row["node_count"],
            edge_count=row["edge_count"],
            community_count=row["community_count"],
        )

    # -- Anomaly Scores --------------------------------------------------------

    def add_anomaly_scores(self, results: list[AnomalyResult]) -> None:
        self.conn.executemany(
            "INSERT OR REPLACE INTO anomaly_scores (triplet_id, baseline_id, score, signals) "
            "VALUES (?, ?, ?, ?)",
            [
                (r.triplet_id, r.baseline_id, r.score, json.dumps(r.signals))
                for r in results
            ],
        )
        self.conn.commit()

    def get_anomaly_scores(
        self,
        min_score: float = 0.0,
        baseline_id: str | None = None,
        limit: int = 100,
    ) -> list[AnomalyResult]:
        if baseline_id:
            rows = self.conn.execute(
                "SELECT a.*, t.subject, t.predicate, t.object "
                "FROM anomaly_scores a JOIN triplets t ON a.triplet_id = t.triplet_id "
                "WHERE a.score >= ? AND a.baseline_id = ? "
                "ORDER BY a.score DESC LIMIT ?",
                (min_score, baseline_id, limit),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT a.*, t.subject, t.predicate, t.object "
                "FROM anomaly_scores a JOIN triplets t ON a.triplet_id = t.triplet_id "
                "WHERE a.score >= ? "
                "ORDER BY a.score DESC LIMIT ?",
                (min_score, limit),
            ).fetchall()
        return [self._row_to_anomaly(r) for r in rows]

    def get_anomaly_score_for_triplet(
        self, triplet_id: str, baseline_id: str | None = None
    ) -> AnomalyResult | None:
        if baseline_id:
            row = self.conn.execute(
                "SELECT a.*, t.subject, t.predicate, t.object "
                "FROM anomaly_scores a JOIN triplets t ON a.triplet_id = t.triplet_id "
                "WHERE a.triplet_id = ? AND a.baseline_id = ?",
                (triplet_id, baseline_id),
            ).fetchone()
        else:
            row = self.conn.execute(
                "SELECT a.*, t.subject, t.predicate, t.object "
                "FROM anomaly_scores a JOIN triplets t ON a.triplet_id = t.triplet_id "
                "WHERE a.triplet_id = ? ORDER BY a.score DESC LIMIT 1",
                (triplet_id,),
            ).fetchone()
        if not row:
            return None
        return self._row_to_anomaly(row)

    def get_triplets_in_range(
        self, since: str | None = None, until: str | None = None
    ) -> list[Triplet]:
        """Get triplets within a time range based on temporal fields.

        Uses last_seen >= since and first_seen <= until. Falls back to
        document.ingested_at for triplets with empty temporal fields.
        """
        conditions = []
        params: list[str] = []

        if since:
            conditions.append(
                "(CASE WHEN t.last_seen != '' THEN t.last_seen "
                "ELSE COALESCE(d.ingested_at, '') END) >= ?"
            )
            params.append(since)

        if until:
            conditions.append(
                "(CASE WHEN t.first_seen != '' THEN t.first_seen "
                "ELSE COALESCE(d.ingested_at, '') END) <= ?"
            )
            params.append(until)

        where_clause = " AND ".join(conditions) if conditions else "1=1"

        rows = self.conn.execute(
            f"SELECT t.* FROM triplets t "
            f"LEFT JOIN documents d ON t.doc_id = d.doc_id "
            f"WHERE {where_clause} "
            f"ORDER BY t.confidence DESC",
            params,
        ).fetchall()
        return [self._row_to_triplet(r) for r in rows]

    def get_triplets_since(self, since: str) -> list[Triplet]:
        """Get triplets from documents ingested after a given ISO date.

        Backward-compatible: filters by document.ingested_at, not triplet temporal fields.
        """
        rows = self.conn.execute(
            "SELECT t.* FROM triplets t "
            "JOIN documents d ON t.doc_id = d.doc_id "
            "WHERE d.ingested_at >= ? "
            "ORDER BY t.confidence DESC",
            (since,),
        ).fetchall()
        return [self._row_to_triplet(r) for r in rows]

    def _row_to_anomaly(self, row: sqlite3.Row) -> AnomalyResult:
        return AnomalyResult(
            triplet_id=row["triplet_id"],
            baseline_id=row["baseline_id"],
            score=row["score"],
            signals=json.loads(row["signals"] or "{}"),
            subject=row["subject"],
            predicate=row["predicate"],
            object=row["object"],
        )
