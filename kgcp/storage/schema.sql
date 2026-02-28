-- KGCP SQLite Schema

CREATE TABLE IF NOT EXISTS documents (
    doc_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS triplets (
    triplet_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    chunk_id TEXT REFERENCES chunks(chunk_id),
    doc_id TEXT NOT NULL REFERENCES documents(doc_id) ON DELETE CASCADE,
    inferred BOOLEAN DEFAULT 0,
    metadata TEXT DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS entities (
    name TEXT PRIMARY KEY,
    entity_type TEXT DEFAULT 'unknown',
    first_seen TEXT NOT NULL,
    doc_ids TEXT DEFAULT '[]'
);

-- Indexes for fast retrieval
CREATE INDEX IF NOT EXISTS idx_triplets_subject ON triplets(subject);
CREATE INDEX IF NOT EXISTS idx_triplets_object ON triplets(object);
CREATE INDEX IF NOT EXISTS idx_triplets_predicate ON triplets(predicate);
CREATE INDEX IF NOT EXISTS idx_triplets_doc_id ON triplets(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
