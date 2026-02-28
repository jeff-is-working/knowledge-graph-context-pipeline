# Knowledge Graph Context Pipeline (KGCP)

Ingest documents, extract SPO triplets via LLM, store in a persistent graph, and retrieve token-efficient structured context for Claude.

Extends Robert McDermott's [AI Knowledge Graph Generator (AIKG)](https://github.com/robert-mcdermott/ai-knowledge-graph) — which produces HTML visualizations — by closing the gap between knowledge extraction and LLM context injection. A 10K-token document might yield 2K tokens of structured facts as triplets.

## Quick Start

```bash
# Install
pip install -e .

# Ingest a document (requires Ollama running with gemma3)
kgcp ingest report.txt

# Query the knowledge graph
kgcp query "APT28 targets" --budget 2048

# Get compact output
kgcp query "credential harvesting" --format compact

# Copy to clipboard for Claude
kgcp query "Russian GRU" --to-clipboard

# Check graph stats
kgcp stats --communities
```

## Architecture

```
Documents → [Ingestion] → [Extraction/LLM] → [SQLite Storage]
                                                     ↓
Claude ← [Integration] ← [Context Packing] ← [Retrieval]
```

**6 layers**: Ingestion (multi-format parsing) → Extraction (SPO via LLM) → Storage (SQLite + NetworkX) → Retrieval (keyword + N-hop traversal) → Packing (YAML/compact/markdown/NL) → Integration (Claude API + clipboard)

## Output Formats

**YAML** (default — best accuracy-to-token ratio):
```yaml
# 47 triplets, 1823 tokens, from 3 sources
entities:
  apt28: {type: threat_actor, centrality: 0.82}
facts:
  - [apt28, targets, energy sector]
  - [apt28, uses, credential harvesting]
provenance:
  - source: "Russia-APT28-targeting.txt"
```

**Compact** (maximum density):
```
apt28 -> targets -> energy sector
apt28 -> uses -> credential harvesting
```

## Configuration

Copy `config.toml` to `~/.kgcp/config.toml` or set environment variables:

```bash
export KGCP_LLM_URL="http://localhost:11434/v1/chat/completions"
export KGCP_MODEL="gemma3"
export KGCP_DB_PATH="~/.kgcp/knowledge.db"
```

## Requirements

- Python 3.10+
- An OpenAI-compatible LLM endpoint (Ollama recommended)
- Core: `networkx`, `requests`, `click`, `python-louvain`
- Optional: `PyMuPDF` (PDF), `anthropic` (Claude API), `tiktoken` (precise token counting)

## Full Documentation

See [DESIGN.md](DESIGN.md) for architecture details.
