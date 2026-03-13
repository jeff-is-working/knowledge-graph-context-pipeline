---
title: Data Flow
scope: Mermaid sequence diagrams for every major data path through KGCP — ingestion, querying, anomaly detection, attack path reconstruction, CTI export, and TAXII serving
last_updated: 2026-03-12
---

# Data Flow

This document traces how data moves through KGCP's seven layers. Each flow is drawn from the verified execution paths in the codebase: CLI entry point → helper functions → storage/computation → output. For the layer descriptions and design decisions behind these flows, see [Architecture](ARCHITECTURE.md). For CTI-specific data mappings and platform configuration, see [CTI Integration](CTI_INTEGRATION.md).

## Document Ingestion

When a user runs `kgcp ingest`, the pipeline parses files into text chunks, sends each chunk to an LLM for Subject-Predicate-Object extraction, normalizes and scores the resulting triplets, and persists them to SQLite with an in-memory graph mirror.

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli.py (ingest)
    participant Parser as parser_registry
    participant Chunker as chunker
    participant LLM as llm_client
    participant Extractor as extractor
    participant Normalizer as normalizer
    participant Scorer as confidence
    participant Store as SQLiteStore
    participant Graph as GraphCache

    User->>CLI: kgcp ingest report.pdf --recursive
    CLI->>CLI: _get_store() → open SQLite
    CLI->>Parser: get_parser(file_extension)
    Parser-->>CLI: parser function
    CLI->>Parser: parse(file_path) → raw text
    CLI->>Chunker: chunk_text(text, size=100, overlap=20)
    Chunker-->>CLI: DocumentChunk[]

    loop Each chunk
        CLI->>Extractor: extract_triplets_from_text(chunk)
        Extractor->>LLM: call_llm(system_prompt, chunk)
        LLM-->>Extractor: JSON response
        Extractor->>Extractor: extract_json_from_text(response)
        Extractor->>Normalizer: normalize_entity(subject), normalize_entity(object)
        Extractor->>Extractor: limit_predicate_length(predicate)
        Extractor->>Scorer: score_triplet(triplet)
        Scorer-->>Extractor: Triplet (confidence 0.0–1.0)
    end

    CLI->>Store: add_document(doc)
    CLI->>Store: add_triplets(triplets)
    Note over Store: Upsert semantics — re-ingestion updates last_seen, increments observation_count, keeps higher confidence
    CLI->>Graph: build_from_triplets(all_triplets)
    Note over Graph: Rebuilds NetworkX digraph, computes centrality and Louvain communities
    CLI-->>User: Ingested N triplets from M chunks
```

## Query and Context Retrieval

The query flow finds relevant triplets via keyword search, expands the result set through graph traversal, optionally applies cross-algebra scoring, and packs the ranked results into the chosen output format within a token budget.

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli.py (query)
    participant Store as SQLiteStore
    participant Graph as GraphCache
    participant Retriever as retriever
    participant Unified as unified_scorer
    participant Packer as packer
    participant Output as output.py

    User->>CLI: kgcp query "APT28 targets" --unified --budget 2048
    CLI->>CLI: _get_store() → open SQLite
    CLI->>Store: search_triplets(query_text)
    Store-->>CLI: seed Triplet[]

    CLI->>Graph: build_from_triplets(all_triplets)
    CLI->>Retriever: expand_hops(seed_entities, hops=2)
    Note over Graph: N-hop traversal via NetworkX neighbors
    Retriever->>Graph: get_neighbors(entity, depth)
    Graph-->>Retriever: expanded Triplet[]

    alt --unified flag
        CLI->>Store: get_latest_baseline()
        CLI->>Unified: score_triplets(triplets, baseline, graph)
        Note over Unified: Fuses 4 signals: confidence (0.30) + centrality (0.25) + anomaly (0.20) + recency (0.25)
        Unified-->>CLI: ScoredTriplet[]
    else standard scoring
        CLI->>Retriever: boost_query_matches(triplets, query)
        Retriever-->>CLI: ranked Triplet[]
    end

    CLI->>Packer: pack(triplets, format="yaml", budget=2048)
    Note over Packer: Serializes top-ranked triplets until token budget exhausted
    Packer-->>CLI: PackedContext

    alt --to-clipboard
        CLI->>Output: copy_to_clipboard(packed)
    else --to-file
        CLI->>Output: write_to_file(packed, path)
    else default
        CLI->>Output: print to stdout
    end
    Output-->>User: Formatted context (YAML/compact/markdown/NL)
```

## Anomaly Detection

Anomaly detection compares the current graph state against a saved baseline fingerprint. The scorer evaluates five structural signals per triplet — no LLM calls required. This flow spans two user actions: creating a baseline, then later scoring against it.

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli.py
    participant Store as SQLiteStore
    participant Graph as GraphCache
    participant Baseline as baseline.py
    participant Detector as detector.py
    participant Scorer as anomaly/scorer.py

    Note over User,Scorer: Phase 1 — Create baseline before new ingestion
    User->>CLI: kgcp baseline create --label "pre-intel"
    CLI->>Store: get_all_triplets()
    CLI->>Graph: build_from_triplets(triplets)
    CLI->>Baseline: create_baseline(graph)
    Note over Baseline: Snapshots: community partition, centrality scores, predicate histogram, edge set, entity predicate patterns
    Baseline-->>CLI: Baseline object
    CLI->>Store: add_baseline(baseline)
    CLI-->>User: Baseline saved (ID: abc123)

    Note over User,Scorer: Phase 2 — After ingesting new documents, detect anomalies
    User->>CLI: kgcp anomalies --min-score 0.3
    CLI->>Store: get_latest_baseline()
    Store-->>CLI: Baseline
    CLI->>Store: get_all_triplets()
    CLI->>Graph: build_from_triplets(triplets)
    Graph->>Graph: compute_centrality(), detect_communities()

    CLI->>Detector: detect(triplets, baseline, graph)
    loop Each triplet
        Detector->>Scorer: _signal_new_entity(triplet, baseline)
        Detector->>Scorer: _signal_new_edge(triplet, baseline)
        Detector->>Scorer: _signal_community_mismatch(triplet, baseline, graph)
        Detector->>Scorer: _signal_unusual_predicate(triplet, baseline)
        Detector->>Scorer: _signal_centrality_drift(triplet, baseline, graph)
        Note over Scorer: Weighted sum: new_entity(0.30) + new_edge(0.25) + community(0.20) + predicate(0.15) + centrality(0.10)
        Scorer-->>Detector: AnomalyResult (score 0.0–1.0)
    end

    Detector-->>CLI: AnomalyResult[]
    CLI->>Store: save_anomaly_scores(results)
    CLI-->>User: Table of anomalous relationships (filtered by --min-score)
```

## Attack Path Reconstruction

The `paths` command reconstructs temporally-ordered attack chains from a seed entity. It combines graph traversal with chronological sorting and anomaly annotation to show how an attacker's operations unfolded over time.

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli.py (paths)
    participant Store as SQLiteStore
    participant Graph as GraphCache
    participant Paths as attack_paths.py
    participant Packer as packer

    User->>CLI: kgcp paths apt28 --since 90d --format timeline
    CLI->>CLI: _get_store() → open SQLite
    CLI->>Store: get_all_triplets()
    CLI->>Graph: build_from_triplets(triplets)

    CLI->>Paths: reconstruct(seed="apt28", graph, store)
    Paths->>Graph: get_neighbors("apt28", hops=N)
    Note over Graph: N-hop expansion collects all connected triplets
    Graph-->>Paths: connected Triplet[]

    Paths->>Paths: filter by --since/--until window
    Paths->>Paths: sort by first_seen chronologically
    Paths->>Store: get_anomaly_scores(triplet_ids)
    Note over Paths: Annotate each step with anomaly score if baseline exists
    Paths->>Paths: build AttackPath (steps, entities, time_span, total_anomaly)
    Paths-->>CLI: AttackPath

    CLI->>Packer: pack(attack_path, format="timeline")
    Packer-->>User: Temporally-ordered attack chain with anomaly annotations
```

## CTI Export

The `export-cti` commands select triplets from the store (by entity, query, or full graph), convert them to a platform-native format via the appropriate adapter, and either write to a file or push to a remote CTI platform. This flow covers MISP, OpenCTI, and TheHive — the STIX adapter is the base that all others compose or build upon.

```mermaid
sequenceDiagram
    participant User
    participant CLI as cli.py (export-cti)
    participant Store as SQLiteStore
    participant Graph as GraphCache
    participant Paths as attack_paths.py
    participant Exporter as Platform Adapter
    participant Remote as CTI Platform

    User->>CLI: kgcp export-cti misp --entity APT28 --push
    CLI->>CLI: _select_triplets(entity="APT28")
    CLI->>Store: get_all_triplets()
    CLI->>Graph: build_from_triplets(triplets)
    CLI->>Paths: reconstruct(seed="APT28", graph, store)
    Paths-->>CLI: AttackPath

    CLI->>Exporter: export_attack_path(path)
    Note over Exporter: Maps entities to platform types,<br/>maps anomaly to severity/threat level,<br/>adds ATT&CK tags if matches found
    Exporter-->>CLI: platform-native dict

    alt --push flag
        CLI->>Exporter: push(data)
        Note over Exporter: Lazy-imports platform SDK<br/>(PyMISP / pycti / thehive4py)
        Exporter->>Remote: API call (HTTPS)
        Remote-->>Exporter: response
        Note over Exporter: Sanitize error responses<br/>before returning to user
        Exporter-->>CLI: {status, id}
    else -o file.json
        CLI->>Exporter: to_file(data, path)
    else default
        CLI-->>User: JSON to stdout
    end
```

## TAXII 2.1 Server

The `serve-taxii` command starts a FastAPI server that serves STIX bundles from the live KGCP graph. External consumers poll the TAXII endpoints to pull STIX objects. Each request builds a fresh bundle from the current triplet store.

```mermaid
sequenceDiagram
    participant Client as TAXII Consumer
    participant Server as FastAPI (taxii.py)
    participant Auth as verify_api_key
    participant Store as SQLiteStore
    participant STIX as STIXExporter

    Client->>Server: GET /taxii2/ (Authorization: Bearer key)
    Server->>Auth: validate API key
    Auth-->>Server: OK
    Server-->>Client: Discovery (API roots, title)

    Client->>Server: GET /api/collections/kgcp-all-triplets/objects/?added_after=2025-06-01
    Server->>Auth: validate API key
    Server->>Store: get_all_triplets()
    Store-->>Server: Triplet[]
    Server->>Server: filter by added_after
    Server->>STIX: export_triplets(filtered)
    Note over STIX: Generates deterministic STIX 2.1<br/>bundle with SDOs + SROs
    STIX-->>Server: STIX bundle dict
    Server-->>Client: application/stix+json;version=2.1
```

## Data Lifecycle

All persistent state lives in a single SQLite file. This table summarizes what is stored and how it changes over time.

| Data | Created By | Updated By | Deleted By |
|------|-----------|-----------|-----------|
| Documents | `kgcp ingest` | Re-ingestion (updates ingested_at) | Not exposed via CLI |
| Chunks | `kgcp ingest` | Re-ingestion (replaced) | Not exposed via CLI |
| Triplets | `kgcp ingest` | Re-ingestion (upsert: last_seen, observation_count, max confidence) | Not exposed via CLI |
| Entities | `kgcp ingest` | Re-ingestion (adds doc_ids) | Not exposed via CLI |
| Baselines | `kgcp baseline create` | Immutable after creation | `kgcp baseline delete <ID>` |
| Anomaly scores | `kgcp anomalies` | Re-scored on each `kgcp anomalies` run | Cascade-deleted with baseline |
