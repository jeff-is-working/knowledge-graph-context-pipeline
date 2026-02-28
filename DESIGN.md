# Knowledge Graph Context Pipeline (KGCP) — Architecture Document

## Problem Statement

AI-Powered Knowledge Graph (AIKG) extracts SPO triplets from text and renders them as interactive HTML visualizations for human analysis. However, the true power of knowledge graphs lies in using structured triplets as **token-efficient context for LLMs**. A 10K-token document might yield 2K tokens of actual knowledge as triplets — a 3-5x compression ratio that preserves semantic relationships.

KGCP closes this gap: it wraps AIKG's extraction engine, adds persistent storage, retrieval, and context packing to produce dense, structured context suitable for injection into Claude conversations.

## Architecture Overview

```
Documents → [Ingestion] → [Extraction/AIKG] → [SQLite Storage]
                                                      ↓
Claude ← [Claude Integration] ← [Context Packing] ← [Retrieval]
```

### Layer 1: Ingestion
- Multi-format document parsing (Markdown, PDF, HTML, plaintext, source code)
- Parser registry pattern for extensibility
- Paragraph-aware chunking (wraps AIKG's word-level `chunk_text()`)

### Layer 2: Extraction (wraps AIKG)
- SPO triplet extraction via LLM (OpenAI-compatible API)
- Entity standardization (normalization + optional LLM-assisted resolution)
- Confidence scoring via predicate/entity-type heuristics (no extra LLM calls)
- Predicate normalization and deduplication

### Layer 3: Storage
- SQLite for persistent triplet/document/entity storage
- NetworkX in-memory graph cache for fast traversal
- Schema supports provenance tracking (which document/chunk produced each triplet)

### Layer 4: Retrieval
- Keyword matching on entities and predicates
- N-hop graph traversal from seed entities
- Community-based retrieval (Louvain communities)
- Centrality-weighted scoring for relevance ranking

### Layer 5: Context Packing
- YAML (default) — best accuracy-to-token ratio, 34-38% fewer tokens than JSON
- Compact arrows — maximum density (`apt28 -> targets -> energy sector`)
- Markdown tables — human-readable structured format
- Natural language — dense prose summaries
- Token budget enforcement with priority-based truncation

### Layer 6: Claude Integration
- Direct API injection via `anthropic` SDK
- CLI output modes (stdout, clipboard, file)
- Context metadata (triplet count, token count, sources)

## AIKG Reuse Strategy

| AIKG Component | Strategy | Rationale |
|---|---|---|
| `llm.py` (call_llm, extract_json) | **Reuse directly** | Core LLM client, works with any OpenAI-compatible endpoint |
| `prompts/main_prompts.py` | **Reuse directly** | Proven SPO extraction prompts |
| `prompts/entity_prompts.py` | **Reuse directly** | Entity resolution prompts |
| `entity_standardization.py` | **Wrap** | Add confidence scoring, provenance tracking |
| `text_utils.py` (chunk_text) | **Wrap** | Add document metadata, paragraph-aware boundaries |
| `config.py` | **Extend** | Add KGCP-specific sections (storage, retrieval, packing) |
| `visualization.py` | **Skip** | Optional debug tool; our output is structured text, not HTML |

## Key Design Decisions

| Decision | Rationale |
|---|---|
| **YAML as default output** | Research shows best accuracy-to-token ratio across LLMs (34-38% fewer tokens than JSON for equivalent information) |
| **SQLite + NetworkX** (not Neo4j) | Zero external dependencies for prototype; swap via protocol interface later |
| **Wrap AIKG, don't fork** | Inherit upstream improvements; only wrapper functions need updating |
| **Heuristic confidence scoring** | No extra LLM calls — predicate specificity and entity-type heuristics are sufficient for relevance ranking |
| **TOML configuration** | Consistent with AIKG; human-readable, well-supported in Python |
| **Click CLI** | Composable commands, auto-generated help, type validation |

## Data Model

### Core Types

```python
@dataclass
class DocumentChunk:
    chunk_id: str           # UUID
    doc_id: str             # Parent document UUID
    source_path: str        # Original file path
    content: str            # Raw text
    chunk_index: int        # Position in document
    metadata: dict          # Format-specific metadata

@dataclass
class Triplet:
    triplet_id: str         # UUID
    subject: str            # Normalized entity
    predicate: str          # 1-3 word relationship
    object: str             # Normalized entity
    confidence: float       # 0.0-1.0 heuristic score
    source_chunk_id: str    # Provenance link
    doc_id: str             # Document provenance
    inferred: bool          # True if relationship was inferred
    metadata: dict          # Extra attributes

@dataclass
class PackedContext:
    content: str            # Serialized output
    format: str             # yaml|compact|markdown|nl
    token_count: int        # Estimated tokens
    triplet_count: int      # Number of triplets included
    sources: list[str]      # Source document paths
    entities: dict          # Entity metadata (type, centrality)
```

## SQLite Schema

```sql
CREATE TABLE documents (
    doc_id TEXT PRIMARY KEY,
    source_path TEXT NOT NULL,
    ingested_at TEXT NOT NULL,
    metadata TEXT  -- JSON
);

CREATE TABLE chunks (
    chunk_id TEXT PRIMARY KEY,
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    content TEXT NOT NULL,
    chunk_index INTEGER NOT NULL,
    metadata TEXT  -- JSON
);

CREATE TABLE triplets (
    triplet_id TEXT PRIMARY KEY,
    subject TEXT NOT NULL,
    predicate TEXT NOT NULL,
    object TEXT NOT NULL,
    confidence REAL DEFAULT 0.5,
    chunk_id TEXT REFERENCES chunks(chunk_id),
    doc_id TEXT NOT NULL REFERENCES documents(doc_id),
    inferred BOOLEAN DEFAULT FALSE,
    metadata TEXT  -- JSON
);

CREATE TABLE entities (
    name TEXT PRIMARY KEY,
    entity_type TEXT,
    first_seen TEXT,
    doc_ids TEXT  -- JSON array
);

-- Indexes for fast retrieval
CREATE INDEX idx_triplets_subject ON triplets(subject);
CREATE INDEX idx_triplets_object ON triplets(object);
CREATE INDEX idx_triplets_predicate ON triplets(predicate);
CREATE INDEX idx_triplets_doc_id ON triplets(doc_id);
CREATE INDEX idx_chunks_doc_id ON chunks(doc_id);
```

## CLI Interface

```bash
# Ingestion
kgcp ingest report.pdf                          # Single file
kgcp ingest ./threat-intel/ --recursive         # Directory
kgcp ingest report.txt --source-label "APT28 Report"

# Querying
kgcp query "APT28 targets" --budget 2048        # YAML (default)
kgcp query "credential harvesting" --format compact
kgcp query "Russian GRU" --hops 3 --format nl
kgcp query "APT28" --to-clipboard

# Statistics
kgcp stats                                      # Overall graph stats
kgcp stats --communities                        # Community breakdown

# Export
kgcp export --format json                       # Full graph export
kgcp export --format graphml                    # For external tools
```

## Configuration (config.toml)

```toml
[llm]
model = "gemma3"
api_key = "sk-1234"
base_url = "http://localhost:11434/v1/chat/completions"
max_tokens = 8192
temperature = 0.8

[chunking]
chunk_size = 100
overlap = 20

[standardization]
enabled = true
use_llm = true

[inference]
enabled = true
use_llm = true

[storage]
db_path = "~/.kgcp/knowledge.db"

[retrieval]
default_hops = 2
default_budget = 2048
default_format = "yaml"

[packing]
include_provenance = true
include_entity_metadata = true
```

## Implementation Phases

### Phase 1: Minimal Viable Pipeline
- `models.py` — all dataclasses
- `extraction/` — wrap AIKG's SPO extraction
- `storage/sqlite_store.py` — schema + CRUD
- `packing/formats/yaml_format.py` — YAML serializer
- `cli.py` — `ingest` and `query` commands

### Phase 2: Multi-Format Ingestion
- Parser registry + format-specific parsers
- Paragraph-aware chunking

### Phase 3: Advanced Retrieval
- NetworkX graph cache
- N-hop traversal + community-based retrieval
- Weighted relevance scoring

### Phase 4: Format Benchmarking + Claude Integration
- Additional output formats
- `claude_api.py` — direct API injection
- Token efficiency benchmarks

### Phase 5: Polish
- Rich progress bars, error handling
- Tests for each layer
- MCP server (future)

## Verification Criteria

1. Ingest APT28 article → expect ~38 entities, ~105 triplets, 4 communities
2. `kgcp query "APT28 targets" --budget 2048` → relevant YAML with provenance
3. Token count of packed context vs raw document → 3-5x reduction
4. Feed packed context to Claude → accurate answers about APT28 operations
