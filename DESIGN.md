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

## Future Expansion: The Four Algebras of Defense

Informed by John Lambert's (Microsoft) framework — "Building Attack Graphs and the Algebra of Defense." Lambert argues that defenders need four complementary data representations to flip the physics of cyber defense. KGCP currently implements two; phases 6-8 extend it to all four.

> "Defenders think in lists. Attackers think in graphs. As long as this is true, attackers win." — John Lambert

### Current Coverage

| Algebra | Status | KGCP Implementation |
|---|---|---|
| **1. Relational Tables** | Implemented | SQLite storage with indexed triplets, entities, documents, and chunks |
| **2. Graphs** | Implemented | SPO triplet extraction, NetworkX graph cache, N-hop traversal, community detection |
| **3. Anomalies** | Implemented | Baseline fingerprinting, 5-signal anomaly scoring, entity drift detection, CLI commands |
| **4. Vectors Over Time** | Not yet | — |

### Phase 6: Anomaly Detection (Algebra #3) — Complete

Detect unusual entity relationships or new connections that deviate from established graph patterns. Purely computational (no LLM calls).

- **Baseline graph fingerprinting** — `kgcp baseline create` snapshots community partition, centrality scores, predicate histogram, edge set, and entity predicate patterns
- **5-signal anomaly scoring** — Each triplet scored against baseline using weighted signals: new entity (0.30), new edge (0.25), community mismatch (0.20), unusual predicate (0.15), centrality drift (0.10)
- **Entity drift detection** — `kgcp anomalies --entity <name>` reports community change, centrality delta, new/lost predicates, new neighbors
- **Context packing integration** — All 4 output formats include anomaly data when present (YAML `anomalies:` section, compact `[!anomaly:0.85]` suffix, markdown Anomaly column, NL `(anomalous)` suffix)
- **CLI**: `kgcp baseline create/list/show/delete`, `kgcp anomalies [--since DATE] [--min-score FLOAT] [--entity TEXT] [--format table|json|yaml]`, `kgcp stats --anomalies`, `kgcp query --anomalies`
- **Storage**: `baselines` and `anomaly_scores` tables with cascade deletes, `get_triplets_since()` for incremental scoring
- **Config**: Tunable signal weights and display thresholds in `[anomaly]` config section
- **Tests**: 54 new tests (107 total) across 4 test files

### Phase 7: Temporal Analysis (Algebra #4)

Add time-series awareness to track how threat actor TTPs, infrastructure, and targeting evolve.

- **Temporal metadata on triplets** — Store `first_seen`, `last_seen`, and `observation_count` on each triplet
- **Temporal queries** — "What changed in APT28's targeting in Q4?", "When did this entity first appear?"
- **Trend detection** — Identify increasing/decreasing relationship frequencies over time (e.g., a threat actor shifting from one sector to another)
- **Temporal context packing** — Include time-range context in packed output so Claude can reason about evolution
- **CLI**: `kgcp query "APT28 targets" --since 2025-Q3 --until 2025-Q4` — scoped temporal retrieval

### Phase 8: Cross-Algebra Fusion

Lambert's key insight: AI can leverage all four algebras simultaneously, operating in a "much more highly dimensional space" than human analysts.

- **Unified scoring** — Combine graph centrality (Algebra #2), anomaly score (Algebra #3), and temporal recency (Algebra #4) into a single relevance score for context packing
- **Multi-algebra queries** — "Show me anomalous relationships involving APT28 that emerged in the last 90 days" — fuses graph traversal, anomaly detection, and temporal filtering
- **Attack path reconstruction** — Use graph + temporal data to reconstruct the "red thread" of activity from siloed intelligence reports

### References

- John Lambert, "Changing the Physics of Cyber Defense" (Dec 2025): https://www.microsoft.com/en-us/security/blog/2025/12/09/changing-the-physics-of-cyber-defense/
- GitHub: https://github.com/JohnLaTwC/Shared
- Medium: https://medium.com/@johnlatwc/defenders-mindset-319854d10aaa

## Verification Criteria

1. Ingest APT28 article → expect ~38 entities, ~105 triplets, 4 communities
2. `kgcp query "APT28 targets" --budget 2048` → relevant YAML with provenance
3. Token count of packed context vs raw document → 3-5x reduction
4. Feed packed context to Claude → accurate answers about APT28 operations
