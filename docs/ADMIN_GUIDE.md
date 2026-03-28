---
title: Administrative User Guide
scope: Operational procedures, maintenance workflows, and daily administration for KGCP
last_updated: 2026-03-27
---

# Administrative User Guide

This guide covers day-to-day operation of the Knowledge Graph Context Pipeline (KGCP). It assumes the tool is already installed and configured. For installation, LLM setup, and initial configuration, see the [README](../README.md). For system design and data model details, see [Architecture](ARCHITECTURE.md).


## Knowledge Graph Lifecycle

A KGCP deployment moves through four phases: initial population, baseline establishment, production querying, and ongoing maintenance. Understanding this lifecycle prevents common mistakes like querying before enough data exists or creating baselines at the wrong time.

**Phase 1: Initial Population.** Start with your highest-quality, most authoritative documents. Ingest them in small batches (5-10 files) so you can review extraction quality between batches. Check triplet counts with `kgcp stats` after each batch -- a document that yields zero triplets likely has a parsing or formatting issue.

**Phase 2: Baseline Establishment.** Once your core documents are ingested and you have verified extraction quality, create your first baseline. This snapshot captures the "normal" state of the graph and enables anomaly detection on all future ingestions.

```bash
kgcp baseline create --label "initial-corpus"
```

**Phase 3: Production Querying.** With data ingested and a baseline in place, the graph is ready for queries. Use `--unified` scoring for production workflows -- it fuses extraction confidence, graph centrality, anomaly score, and temporal recency into a single relevance score.

**Phase 4: Ongoing Maintenance.** Establish a rhythm: ingest new documents as they arrive, create fresh baselines before and after bulk ingestion events, review anomalies periodically, and back up the database regularly.

| Activity | Frequency | Command |
|----------|-----------|---------|
| Ingest new documents | As received | `kgcp ingest <path>` |
| Review graph health | Weekly | `kgcp stats --communities --anomalies` |
| Create baseline | Before/after bulk ingestions | `kgcp baseline create --label "<reason>"` |
| Review anomalies | After each ingestion batch | `kgcp anomalies --min-score 0.5` |
| Back up database | Daily or before bulk operations | `cp ~/.kgcp/knowledge.db ~/.kgcp/backups/` |
| Prune old baselines | Monthly | `kgcp baseline list` then `kgcp baseline delete <id>` |


## Ingestion Operations

KGCP ingests documents by parsing them into text, chunking the text into overlapping windows, sending each chunk to an LLM for SPO triplet extraction, and upserting the results into SQLite.

**Supported formats.** The parser registry handles plaintext (.txt), Markdown (.md), HTML (.html/.htm), PDF (.pdf, via PyMuPDF), and source code files. Unknown extensions fall back to UTF-8 text parsing.

**Single file ingestion** processes one document end-to-end.

```bash
kgcp ingest report.pdf
```

**Directory ingestion** processes all supported files in a directory. Add `-r` for recursive traversal into subdirectories.

```bash
kgcp ingest ./threat-reports/ -r
```

**Source labeling** tags all triplets from an ingestion with a custom provenance label, useful for tracking which data source contributed which knowledge.

```bash
kgcp ingest ./advisory-feed/ -r --source-label "cisa-advisories-2026q1"
```

**Chunking behavior.** Text is split into 100-word windows with 20-word overlap, respecting paragraph boundaries. These defaults are configurable in `config.toml` under `[chunking]`. Smaller chunks (50-75 words) may improve extraction precision for dense technical documents; larger chunks (150-200 words) work better for narrative text.

**Re-ingestion semantics.** Ingesting the same document again does not create duplicates. The upsert logic updates existing triplets: `last_seen` is set to the current timestamp, `observation_count` is incremented, and if the new extraction yields a higher confidence score, that score is kept. This makes repeated ingestion safe and useful for tracking how knowledge evolves.

**Monitoring extraction quality.** After ingesting, check that the extraction produced reasonable results.

```bash
kgcp stats
```

Look for: triplet count proportional to document size (roughly 5-15 triplets per page of dense text), a healthy entity-to-triplet ratio, and no documents yielding zero triplets. If extraction quality is poor, verify your LLM endpoint is responding correctly and consider adjusting the model. See [Deployment](DEPLOYMENT.md) for LLM configuration.

**Prompt injection mitigation.** When ingesting untrusted documents, the pipeline applies a layered defense: input text is sanitized (control characters, ANSI escapes, and null bytes stripped), the extraction prompt frames the text as untrusted input with boundary delimiters, extracted triplets are validated for injection patterns (flagged triplets are dropped), and all security events are logged. For the full threat model and security control inventory, see [Security](SECURITY.md).


## Query and Context Retrieval

Querying is how you get structured context out of the knowledge graph. Every query follows the same pipeline: keyword matching finds seed triplets, N-hop graph expansion pulls in connected knowledge, scoring ranks relevance, and context packing serializes the result within a token budget.

**Basic query** returns triplets matching the query text, expanded by 2 hops (default) through the graph.

```bash
kgcp query "lateral movement techniques"
```

**Unified scoring** activates the cross-algebra scorer, which fuses four signals (extraction confidence, graph centrality, anomaly score, temporal recency) into a single weighted relevance score. Use this for production queries where ranking quality matters.

```bash
kgcp query "credential theft" --unified
```

**Token budget** controls how much context is packed. The default is 2048 tokens. Increase it when feeding context to Claude with a large context window; decrease it for constrained prompts.

```bash
kgcp query "network indicators" --budget 4096
```

**Output format** determines serialization. YAML is the default because it uses 34-38% fewer tokens than JSON for equivalent information.

| Format | Flag | Best for |
|--------|------|----------|
| YAML | `--format yaml` | Claude context injection (default, most token-efficient) |
| Compact | `--format compact` | Minimal token usage, machine parsing |
| Markdown | `--format markdown` | Human-readable reports |
| Natural Language | `--format nl` | Narrative summaries |

**N-hop expansion** controls how far the graph traversal reaches from seed entities. More hops means broader context but more tokens consumed.

```bash
kgcp query "apt29" --hops 3
```

**Time-scoped queries** filter triplets by their temporal metadata. The `--since` and `--until` flags accept ISO dates, quarter notation, and relative shorthand.

```bash
kgcp query "phishing campaigns" --since 2026-01-01
kgcp query "infrastructure changes" --since 2026Q1 --until 2026Q2
kgcp query "recent activity" --since 90d
```

**Anomaly filtering** restricts results to triplets with anomaly scores above a threshold, useful for surfacing only unusual or unexpected relationships.

```bash
kgcp query "network traffic" --unified --min-anomaly 0.5
```

**Output destinations.** By default, context goes to stdout. Other options deliver it directly where it is needed.

```bash
kgcp query "indicators of compromise" --to-clipboard
kgcp query "threat actors" --to-file context.yaml
```


## Anomaly Detection and Baselines

Anomaly detection compares the current state of the knowledge graph against a saved baseline to identify new, unexpected, or structurally unusual relationships. This is the core mechanism for detecting changes worth investigating.

**Creating a baseline** snapshots the graph's current nodes, edges, community structure, and predicate distribution.

```bash
kgcp baseline create --label "pre-advisory-ingest"
```

**When to create baselines:**
- Before ingesting a new data source for the first time
- After completing a bulk ingestion (to establish a new "normal")
- Before and after any manual database modifications
- At regular intervals during ongoing operations (weekly or monthly)

**Viewing anomalies** scores all triplets added since the latest baseline and surfaces those exceeding the threshold.

```bash
kgcp anomalies --min-score 0.3
kgcp anomalies --min-score 0.5 --entity "apt29" --format json
```

**The five anomaly signals.** Each triplet is scored against five independent detectors, and the weighted sum produces the final anomaly score.

| Signal | Default Weight | What It Detects |
|--------|---------------|-----------------|
| `new_entity` | 0.30 | Subject or object not present in the baseline graph |
| `new_edge` | 0.25 | Relationship (subject-object pair) not previously observed |
| `community_mismatch` | 0.20 | Subject and object belong to different graph communities than expected |
| `unusual_predicate` | 0.15 | Predicate that is rare or absent in the baseline's predicate histogram |
| `centrality_drift` | 0.10 | Entity's centrality score has shifted significantly from baseline |

**Tuning weights.** The default weights emphasize novelty (new entities and edges account for 55% of the score). For environments where structural changes matter more than new arrivals, increase `community_mismatch` and `centrality_drift`. Weights are configurable in `config.toml` under `[anomaly.weights]`.

**Baseline lifecycle management.** Over time, baselines accumulate. List them to review, inspect one for details, or delete stale ones.

```bash
kgcp baseline list
kgcp baseline show abc12345
kgcp baseline delete abc12345
```

The `show` command displays the full predicate histogram, node/edge counts, and community count. If called without an ID, it shows the latest baseline.


## Attack Path Analysis

Attack path reconstruction traces temporally ordered chains of relationships from a seed entity outward through the graph. Where standard queries return a ranked set of triplets, paths return a sequenced timeline showing how entities are connected over time.

**Basic path reconstruction** traces outward from a seed entity.

```bash
kgcp paths "compromised-host-01"
```

The default output format is `timeline`, which displays steps in chronological order with timestamps. Each step shows the triplet, its observation window, and its anomaly score if a baseline exists.

**Time-windowed paths** restrict reconstruction to a specific period, useful for isolating activity during an incident.

```bash
kgcp paths "attacker-ip" --since 2026-03-01 --until 2026-03-15
```

**Output formats** control how the path is serialized.

```bash
kgcp paths "malware-sample" --format json --to-file path-analysis.json
kgcp paths "malware-sample" --format compact --budget 4096
```

| Format | Use Case |
|--------|----------|
| `timeline` | Human review during investigation (default) |
| `json` | Machine consumption, downstream tooling |
| `yaml` | Claude context injection |
| `compact` | Minimal token usage |

**Anomaly annotations.** When a baseline exists, each step in the path includes its anomaly score. Steps with high anomaly scores (above 0.5) represent unexpected transitions -- these are often the most investigatively relevant points in the chain.

**When to use paths vs. queries.** Use `kgcp query` when you need broad context about a topic. Use `kgcp paths` when you need to understand how a specific entity connects to others over time -- incident timelines, lateral movement chains, or infrastructure pivot analysis.

```bash
kgcp paths "threat-actor" --hops 4 --min-anomaly 0.3 --format timeline
```


## CTI Export Operations

KGCP exports knowledge graph data to four CTI platforms. Each serves a different operational purpose. The decision table below guides platform selection.

| Scenario | Platform | Command |
|----------|----------|---------|
| Archive STIX bundles for offline analysis or sharing | STIX file export | `kgcp export-cti stix` |
| Share indicators with partner organizations | MISP | `kgcp export-cti misp` |
| Enrich indicators with external intelligence feeds | OpenCTI | `kgcp export-cti opencti` |
| Create alerts and cases for incident response | TheHive | `kgcp export-cti thehive` |
| Serve STIX bundles to pull-based consumers | TAXII 2.1 server | `kgcp serve-taxii` |

**End-to-end workflow.** A typical CTI export follows this sequence: ingest source documents, establish a baseline, review anomalies to identify findings worth sharing, reconstruct attack paths for context, then export to the appropriate platform.

```bash
kgcp ingest ./incident-data/ -r --source-label "incident-2026-042"
kgcp baseline create --label "pre-incident-042"
kgcp anomalies --min-score 0.5
kgcp paths "compromised-host" --format timeline
kgcp export-cti stix --entity "compromised-host" --output incident-042.json
kgcp export-cti thehive --entity "compromised-host" --push
```

**ATT&CK mapping** maps extracted triplets to MITRE ATT&CK techniques. This enriches exports with technique IDs and tactic context.

```bash
kgcp export-cti attack-map --entity "threat-actor" --format table
kgcp export-cti attack-map --update    # download fresh ATT&CK data
```

**TAXII server operations.** The built-in TAXII 2.1 server provides read-only access to STIX bundles over HTTP. Configure an API key before exposing it on a network.

```bash
export KGCP_TAXII_API_KEY="your-api-key"
kgcp serve-taxii --host 127.0.0.1 --port 9500
```

The server binds to localhost by default. Binding to `0.0.0.0` exposes the graph to the network -- only do this with an API key configured. The server enforces a maximum of 10,000 objects per response (configurable via `[cti.taxii] max_content_length` in config.toml).

For platform-specific configuration (API keys, URLs, push options, data mapping details), see [CTI Integration](CTI_INTEGRATION.md). For the security implications of network-facing services, see [Security](SECURITY.md).


## Database Administration

All KGCP state lives in a single SQLite database. Understanding its location, backup requirements, and health checks is essential for reliable operations.

**Database location.** The default path is `~/.kgcp/knowledge.db`. Override it with the `KGCP_DB_PATH` environment variable or the `[storage] db_path` setting in config.toml. See [Deployment](DEPLOYMENT.md) for the full configuration reference.

**Backup strategy.** SQLite with WAL mode allows safe file copies while the database is open for reads. For a consistent backup, simply copy the database file and its WAL/SHM companions.

```bash
cp ~/.kgcp/knowledge.db ~/.kgcp/backups/knowledge-$(date +%Y%m%d).db
cp ~/.kgcp/knowledge.db-wal ~/.kgcp/backups/knowledge-$(date +%Y%m%d).db-wal 2>/dev/null
cp ~/.kgcp/knowledge.db-shm ~/.kgcp/backups/knowledge-$(date +%Y%m%d).db-shm 2>/dev/null
```

Do not copy the database while an active write operation (ingestion or anomaly scoring) is in progress. Schedule backups during idle periods or before bulk operations. For automated backup scheduling, see [Infrastructure](INFRASTRUCTURE.md).

**Graph health checks.** The `stats` command provides a comprehensive view of the database state, including triplet counts, entity counts, community structure, and top anomalies.

```bash
kgcp stats
kgcp stats --communities --anomalies
```

Key indicators to monitor:

| Metric | Healthy Range | Action if Outside |
|--------|--------------|-------------------|
| Triplets per document | 5-15 per page | Check LLM endpoint and model configuration |
| Entity-to-triplet ratio | 0.3-0.7 | Low ratio means redundant entities; high means sparse connections |
| Community count | Grows with data diversity | Sudden drops may indicate entity merge issues |
| Zero-triplet documents | 0% | Re-ingest with verbose logging to diagnose |

**Data deletion.** KGCP does not currently provide CLI commands for deleting individual triplets, entities, or documents. If you need to remove data, operate directly on the SQLite database.

```bash
sqlite3 ~/.kgcp/knowledge.db "DELETE FROM triplets WHERE subject = 'stale-entity';"
```

Exercise caution with manual SQL operations. Back up the database first, and rebuild the graph cache afterward by running any query (the cache rebuilds lazily on first access).


## Troubleshooting and Best Practices

### Common Operational Issues

| Symptom | Cause | Resolution |
|---------|-------|------------|
| Ingestion yields 0 triplets | LLM endpoint unreachable or model not loaded | Verify Ollama is running: `curl http://localhost:11434/v1/models` |
| Ingestion yields 0 triplets | File format not recognized | Check `supported_extensions()` or convert to plaintext |
| Anomaly scores all zero | No baseline exists | Create a baseline: `kgcp baseline create --label "initial"` |
| Anomaly scores all 1.0 | Baseline created from empty graph | Delete the empty baseline, ingest data, create a new one |
| Query returns empty results | No triplets match the query text | Try broader terms, reduce `--hops`, check `kgcp stats` for data |
| Query returns too many low-relevance results | Default scoring without unified mode | Add `--unified` for cross-algebra scoring |
| TAXII server returns 401 | API key mismatch | Verify `KGCP_TAXII_API_KEY` matches client configuration |
| TAXII server returns empty collection | No STIX-exportable triplets | Ingest documents and verify with `kgcp stats` |
| CTI push fails with timeout | Remote platform unresponsive | Check platform URL and network connectivity; increase timeout in config.toml |
| Database locked errors | Concurrent write operations | Ensure only one ingestion process runs at a time |
| High memory usage during ingestion | Large documents with many chunks | Ingest large files individually rather than in bulk directory scans |

For installation, dependency, and configuration troubleshooting, see the troubleshooting section in [Deployment](DEPLOYMENT.md).

### Best Practices

- **Baseline before bulk ingest.** Always create a labeled baseline before ingesting a large batch of new documents. This gives you a clean comparison point for anomaly detection.
- **Review extraction quality early.** After the first few ingestions, review triplets with `kgcp stats` and sample queries. Catching extraction issues early prevents garbage accumulation.
- **Use unified scoring for production queries.** The `--unified` flag provides meaningfully better ranking than keyword-only retrieval. The overhead is negligible.
- **Label your ingestions.** Use `--source-label` consistently so you can trace any triplet back to its source data.
- **Configure TAXII API key before network exposure.** The TAXII server runs without authentication if no API key is set. Always set `KGCP_TAXII_API_KEY` before binding to a non-loopback address.
- **Keep baselines lean.** Delete baselines you no longer need. Each baseline stores a full snapshot of the graph's structural metadata.
- **Back up before manual SQL.** Any direct SQLite operations should be preceded by a database backup. There is no undo.
- **One writer at a time.** SQLite supports concurrent reads but only one writer. Do not run parallel ingestion processes against the same database.
