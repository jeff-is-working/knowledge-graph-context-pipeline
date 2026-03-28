---
title: Developer Guide
scope: Development setup, coding conventions, testing strategy, and module walkthrough for KGCP contributors
last_updated: 2026-03-27
---

# Developer Guide

## Development Setup

For prerequisites, installation, and configuration, see [README Getting Started](../README.md#getting-started). After cloning and installing with `pip install -e ".[dev,all]"`, verify your setup by running the test suite.

The `[dev]` extra installs pytest and pytest-cov. The `[all]` extra installs parsing (PyMuPDF, beautifulsoup4), Claude integration (anthropic), token counting (tiktoken), and CTI (stix2) dependencies. For CTI platform push and TAXII server, install `[cti-platforms]` and `[taxii]` separately — see [SBOM](SBOM.md) for details.

## Project Structure

```
kgcp/
├── models.py                 # All dataclasses (Triplet, Document, Baseline, etc.)
├── config.py                 # TOML config loading with defaults and env overrides
├── cli.py                    # Click CLI entry point — all commands
├── ingestion/                # Document parsing and chunking
│   ├── parser_registry.py    # Extension-to-parser mapping
│   ├── chunker.py            # Paragraph-aware text splitting
│   └── parsers/              # Format-specific parsers
├── extraction/               # LLM-based triplet extraction
│   ├── extractor.py          # Orchestrates chunk→LLM→normalize→score→dedup
│   ├── llm_client.py         # OpenAI-compatible API client
│   ├── prompts.py            # System/user prompt templates
│   ├── normalizer.py         # Entity standardization and deduplication
│   ├── confidence.py         # Heuristic confidence scoring
│   ├── sanitizer.py          # Input text sanitization (control chars, injection signals)
│   └── validator.py          # Post-extraction triplet injection pattern detection
├── storage/                  # Persistence layer
│   ├── sqlite_store.py       # SQLiteStore — all CRUD, baselines, anomaly scores
│   ├── graph_cache.py        # NetworkX in-memory graph (centrality, communities)
│   └── schema.sql            # Table definitions
├── retrieval/                # Query and ranking
│   ├── retriever.py          # Keyword search + N-hop expansion + unified scoring
│   ├── scorer.py             # Centrality and anomaly boosting functions
│   ├── unified_scorer.py     # Cross-algebra fusion scoring engine
│   └── attack_paths.py       # Temporally-ordered attack path reconstruction
├── anomaly/                  # Anomaly detection (Algebra #3)
│   ├── detector.py           # AnomalyDetector orchestrator
│   ├── baseline.py           # Baseline creation from graph snapshot
│   └── scorer.py             # 5-signal anomaly scoring
├── temporal/                 # Temporal analysis (Algebra #4)
│   ├── date_utils.py         # Flexible date parsing (ISO, quarter, relative)
│   └── trends.py             # Frequency trend detection
├── packing/                  # Context serialization
│   ├── packer.py             # Format dispatcher
│   ├── token_counter.py      # Token estimation (tiktoken or fallback)
│   └── formats/
│       ├── yaml_format.py    # YAML output (default)
│       ├── compact_format.py # Arrow notation
│       ├── markdown_format.py # Markdown table
│       └── nl_format.py      # Natural language prose
├── export/                   # CTI export adapters
│   ├── __init__.py           # ExportRegistry — register_exporter/get_exporter
│   ├── base.py               # BaseExporter with sanitization helpers
│   ├── entity_types.py       # KGCP-to-STIX entity type mapping
│   ├── stix_adapter.py       # STIX 2.1 bundle generation
│   ├── attack_mapper.py      # MITRE ATT&CK keyword matching
│   ├── misp_adapter.py       # MISP event/attribute export + PyMISP push
│   ├── opencti_adapter.py    # OpenCTI-enriched STIX + pycti/REST push
│   └── thehive_adapter.py    # TheHive alert/observable export + push
├── server/                   # Network server components
│   └── taxii.py              # TAXII 2.1 FastAPI server (read-only)
└── integration/              # Output delivery
    ├── claude_api.py         # Anthropic SDK integration
    └── output.py             # stdout / clipboard / file writing
```

## Coding Conventions

**Language**: Python 3.10+ with `from __future__ import annotations` in every module for PEP 604 union syntax (`str | None`).

**Data modeling**: All domain objects are `@dataclass` classes in `models.py`. UUIDs are generated via `uuid.uuid4()` default factories. Timestamps are ISO format UTC strings from `datetime.now(timezone.utc).isoformat()`.

**Configuration**: All configurable values have defaults in the `DEFAULTS` dict in `config.py`. TOML config files override defaults via deep merge. Environment variables override four common settings (API key, LLM URL, model, DB path).

**Logging**: Each module creates a logger via `logging.getLogger(__name__)`. CLI stderr output uses `click.echo(..., err=True)` for status messages.

**Scoring**: All confidence and anomaly scores are floats clamped to [0.0, 1.0]. Scoring functions modify triplets in-place and return them for chaining.

**Error handling**: LLM failures are caught and logged, returning empty results rather than crashing. Parser failures raise `ValueError` or `ImportError` with installation guidance.

## Testing

The test suite uses pytest with 492 tests across 29 files. Tests do not require an LLM endpoint — they exercise storage, retrieval, scoring, packing, anomaly detection, temporal analysis, CTI export, TAXII server, and CLI commands using in-memory SQLite databases. CTI platform push tests are skipped when optional SDKs (pymisp, pycti, thehive4py) are not installed.

Run the full suite from the project root:

```bash
.venv/bin/python -m pytest tests/ -v
```

Run a specific test file or test:

```bash
.venv/bin/python -m pytest tests/test_unified_scorer.py -v
.venv/bin/python -m pytest tests/test_attack_paths.py::test_temporal_ordering -v
```

Run with coverage:

```bash
.venv/bin/python -m pytest tests/ --cov=kgcp --cov-report=term-missing
```

### Test Organization

| Test File | Coverage Area | Count |
|-----------|--------------|-------|
| `test_models.py` | Dataclass construction and defaults | 5 |
| `test_storage.py` | SQLiteStore CRUD operations | 7 |
| `test_ingestion.py` | Parser registry, chunking | 6 |
| `test_extraction.py` | Chunking, JSON extraction | 8 |
| `test_confidence.py` | Confidence scoring heuristics | 5 |
| `test_normalizer.py` | Entity normalization, dedup | 5 |
| `test_sanitizer.py` | Input sanitization, injection signal detection | 20 |
| `test_validator.py` | Post-extraction triplet validation | 16 |
| `test_graph_cache.py` | NetworkX graph operations | 5 |
| `test_retrieval.py` | Query, hop expansion, unified scoring | 7 |
| `test_packing.py` | All 4 output formats, budget, unified scores | 12 |
| `test_anomaly_baseline.py` | Baseline creation | 8 |
| `test_anomaly_scorer.py` | 5-signal anomaly scoring | 22 |
| `test_anomaly_detector.py` | Detector orchestration | 10 |
| `test_anomaly_storage.py` | Baseline/score persistence | 14 |
| `test_temporal_storage.py` | Temporal upsert, backfill | 14 |
| `test_temporal_date_utils.py` | Date parsing, time-range queries | 21 |
| `test_temporal_trends.py` | Trend detection | 17 |
| `test_unified_scorer.py` | Cross-algebra scoring | 25 |
| `test_attack_paths.py` | Attack path reconstruction | 12 |
| `test_fusion_cli.py` | CLI unified/paths commands | 9 |
| `test_stix_adapter.py` | STIX 2.1 bundle generation, deterministic IDs | 18 |
| `test_attack_mapper.py` | ATT&CK technique matching | 10 |
| `test_misp_adapter.py` | MISP event/attribute export, push | 42 |
| `test_opencti_adapter.py` | OpenCTI enrichment, push strategies | 24 |
| `test_thehive_adapter.py` | TheHive alert/observable export, push | 38 |
| `test_base_exporter.py` | Input sanitization, error sanitization | 15 |
| `test_export_cli.py` | CLI export-cti commands | 12 |
| `test_taxii_server.py` | TAXII 2.1 endpoints, auth, filtering | 21 |

### Writing New Tests

Follow existing patterns: use `tempfile.TemporaryDirectory` for test databases, create fixtures with `@pytest.fixture` that yield a populated `SQLiteStore`, and assert against model attributes rather than string output. CLI tests use Click's `CliRunner` to invoke commands in-process.

## Common Development Tasks

**Adding a new parser**: Register it in `kgcp/ingestion/parser_registry.py` by calling `register_parser(["ext"], parser_fn)` with a function that takes a `Path` and returns `str`.

**Adding a new packing format**: Create a `pack_<name>()` function in `kgcp/packing/formats/`, add it to `FORMAT_REGISTRY` in `packer.py`, and add the format name to the `--format` Click choice in `cli.py`.

**Adding a new anomaly signal**: Add a `_signal_<name>()` function in `kgcp/anomaly/scorer.py`, include it in the scoring loop, and add a default weight to the `signal_weights` section in `config.py` and `config.toml`.

**Adjusting fusion weights**: Edit the `[fusion.weights]` section in `config.toml` or `DEFAULTS["fusion"]["weights"]` in `config.py`. Weights should sum to 1.0.

**Adding a new CTI exporter**: Create an adapter class inheriting from `BaseExporter` in `kgcp/export/`, implement `export_triplets()` and `export_attack_path()`, register it with `register_exporter("name", MyAdapter)` in `kgcp/export/__init__.py`, and add a CLI subcommand in `cli.py`. See [CTI Integration](CTI_INTEGRATION.md) for the adapter pipeline and data mapping conventions.
