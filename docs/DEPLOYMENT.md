---
title: Deployment
scope: Installation, LLM configuration, operations, and troubleshooting for KGCP
last_updated: 2026-03-12
---

# Deployment

KGCP is a local CLI tool installed via pip. It requires an OpenAI-compatible LLM endpoint for triplet extraction. For setup steps, see [README Getting Started](../README.md#getting-started).

## Environment Overview

KGCP runs locally — there are no staging or production server environments. All state lives in a SQLite database at `~/.kgcp/knowledge.db` (configurable).

| Component | Default Location | Override |
|-----------|-----------------|----------|
| Database | `~/.kgcp/knowledge.db` | `KGCP_DB_PATH` env var or `[storage] db_path` in config.toml |
| Config | `./config.toml` then `~/.kgcp/config.toml` | `--config` CLI flag |
| LLM endpoint | `http://localhost:11434/v1/chat/completions` | `KGCP_LLM_URL` env var |
| LLM model | `gemma3` | `KGCP_MODEL` env var |
| ATT&CK cache | `~/.kgcp/enterprise-attack.json` | `[cti] attack_data_path` in config.toml |
| TAXII server | `127.0.0.1:9500` | `--host`/`--port` flags or `[cti.taxii]` in config.toml |

## LLM Endpoint Configuration

KGCP's extraction layer calls any OpenAI-compatible chat completions endpoint. Ollama is the recommended local option because it runs open-weight models without GPU cloud costs.

To set up Ollama, install it from [ollama.com](https://ollama.com), pull a model, and start the server. KGCP's `config.toml` points to Ollama's default endpoint by default, so no additional configuration is needed after pulling the model.

Other compatible endpoints include vLLM, LM Studio, and the OpenAI API itself. Point `KGCP_LLM_URL` at the endpoint's chat completions URL and set `KGCP_MODEL` to the model name.

## Configuration

KGCP searches for configuration in this order: explicit `--config` path, then `./config.toml`, then `~/.kgcp/config.toml`, then built-in defaults. Environment variables override file values for the four most common settings.

| Env Variable | Overrides | Example |
|-------------|-----------|---------|
| `KGCP_API_KEY` | `[llm] api_key` | `sk-...` |
| `KGCP_LLM_URL` | `[llm] base_url` | `http://localhost:11434/v1/chat/completions` |
| `KGCP_MODEL` | `[llm] model` | `gemma3:12b` |
| `KGCP_DB_PATH` | `[storage] db_path` | `~/my-project/knowledge.db` |
| `KGCP_MISP_URL` | `[cti.misp] url` | `https://misp.example.com` |
| `KGCP_MISP_API_KEY` | `[cti.misp] api_key` | API key string |
| `KGCP_OPENCTI_URL` | `[cti.opencti] url` | `https://opencti.example.com` |
| `KGCP_OPENCTI_API_KEY` | `[cti.opencti] api_key` | API key string |
| `KGCP_THEHIVE_URL` | `[cti.thehive] url` | `https://thehive.example.com` |
| `KGCP_THEHIVE_API_KEY` | `[cti.thehive] api_key` | API key string |
| `KGCP_TAXII_API_KEY` | `[cti.taxii] api_key` | TAXII server auth key |

For the full configuration reference, see `config.toml` in the project root. For CTI platform configuration details, see [CTI Integration](CTI_INTEGRATION.md).

## Operations

**Database management**: The SQLite database is a single file. Back it up by copying `~/.kgcp/knowledge.db`. KGCP uses WAL journaling mode for safe concurrent reads.

**Baseline lifecycle**: Create baselines before and after ingesting new documents to detect structural anomalies. Old baselines can be deleted with `kgcp baseline delete <ID>` to reclaim space.

**Re-ingestion**: KGCP uses upsert semantics — re-ingesting a document updates `last_seen`, increments `observation_count`, and preserves the higher confidence score. It will not create duplicate triplets for the same (subject, predicate, object) tuple.

## Troubleshooting

| Symptom | Cause | Resolution |
|---------|-------|------------|
| `ConnectionError: Cannot reach LLM endpoint` | Ollama not running or wrong URL | Start Ollama with `ollama serve` and verify `KGCP_LLM_URL` |
| `No triplets extracted` | Model returned unparseable output | Try a larger model (`gemma3:12b`), check chunking config, or increase `max_tokens` |
| `ModuleNotFoundError: PyMuPDF` | PDF parsing dependency not installed | Install with `pip install kgcp[parsing]` |
| `ModuleNotFoundError: anthropic` | Claude integration dependency not installed | Install with `pip install kgcp[claude]` |
| Token counts seem inaccurate | tiktoken not installed, using fallback estimator | Install with `pip install kgcp[tokens]` |
| `No baseline found` | Anomaly commands require a baseline | Run `kgcp baseline create` first |
| Database locked errors | Another process has the DB open | Close other kgcp processes; WAL mode handles most concurrency |
| Empty query results | No matching entities in the graph | Check entity names with `kgcp stats --communities`, try broader query terms |
| `ImportError: PyMISP is required` | CTI platform SDK not installed | Install with `pip install kgcp[cti-platforms]` |
| `ImportError: FastAPI...required` | TAXII server deps not installed | Install with `pip install kgcp[taxii]` |
| `ValueError: URL not configured` | CTI push without platform URL set | Set `KGCP_MISP_URL` / `KGCP_OPENCTI_URL` / `KGCP_THEHIVE_URL` env var or config.toml |
| `ValueError: API key not configured` | CTI push without API key set | Set the corresponding `_API_KEY` env var |
| TAXII server returns 401 | Wrong or missing API key in request | Include `Authorization: Bearer <key>` header; check `[cti.taxii] api_key` in config |
| CTI push hangs | Remote platform unresponsive | All push calls have 120s timeout (configurable via `[cti.{platform}] timeout`); Ctrl-C to cancel |
