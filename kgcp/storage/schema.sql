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
    metadata TEXT DEFAULT '{}',
    first_seen TEXT DEFAULT '',
    last_seen TEXT DEFAULT '',
    observation_count INTEGER DEFAULT 1
);

CREATE TABLE IF NOT EXISTS entities (
    name TEXT PRIMARY KEY,
    entity_type TEXT DEFAULT 'unknown',
    first_seen TEXT NOT NULL,
    doc_ids TEXT DEFAULT '[]'
);

CREATE TABLE IF NOT EXISTS baselines (
    baseline_id TEXT PRIMARY KEY,
    label TEXT DEFAULT '',
    created_at TEXT NOT NULL,
    community_partition TEXT DEFAULT '{}',
    centrality_scores TEXT DEFAULT '{}',
    predicate_histogram TEXT DEFAULT '{}',
    edge_set TEXT DEFAULT '[]',
    entity_predicates TEXT DEFAULT '{}',
    node_count INTEGER DEFAULT 0,
    edge_count INTEGER DEFAULT 0,
    community_count INTEGER DEFAULT 0
);

CREATE TABLE IF NOT EXISTS anomaly_scores (
    triplet_id TEXT NOT NULL REFERENCES triplets(triplet_id) ON DELETE CASCADE,
    baseline_id TEXT NOT NULL REFERENCES baselines(baseline_id) ON DELETE CASCADE,
    score REAL NOT NULL,
    signals TEXT DEFAULT '{}',
    PRIMARY KEY (triplet_id, baseline_id)
);

-- Indexes for fast retrieval
CREATE INDEX IF NOT EXISTS idx_triplets_subject ON triplets(subject);
CREATE INDEX IF NOT EXISTS idx_triplets_object ON triplets(object);
CREATE INDEX IF NOT EXISTS idx_triplets_predicate ON triplets(predicate);
CREATE INDEX IF NOT EXISTS idx_triplets_doc_id ON triplets(doc_id);
CREATE INDEX IF NOT EXISTS idx_chunks_doc_id ON chunks(doc_id);
CREATE INDEX IF NOT EXISTS idx_anomaly_scores_score ON anomaly_scores(score DESC);
CREATE INDEX IF NOT EXISTS idx_anomaly_scores_baseline ON anomaly_scores(baseline_id);
CREATE INDEX IF NOT EXISTS idx_baselines_created ON baselines(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_triplets_first_seen ON triplets(first_seen);
CREATE INDEX IF NOT EXISTS idx_triplets_last_seen ON triplets(last_seen);
