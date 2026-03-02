---
title: Security
scope: Threat model, data protection, security controls, SBOM requirements, and incident response for KGCP
last_updated: 2026-03-01
---

# Security

KGCP is a local CLI tool that processes documents through an LLM and stores structured knowledge in SQLite. This document covers the threat model, security controls, and operational security considerations.

## Threat Model

KGCP's attack surface spans four boundaries: document ingestion, LLM communication, local storage, and output delivery. The primary risks involve untrusted input processing and credential exposure.

| Threat | Attack Vector | Impact | Likelihood |
|--------|--------------|--------|------------|
| LLM prompt injection via documents | Malicious text in ingested documents influences extraction prompts | Corrupted triplets, misleading knowledge graph | Medium |
| API key exposure | Keys in config.toml committed to version control or logged | Unauthorized LLM/Claude API usage | Medium |
| SQLite injection | Crafted entity names in extracted triplets | Data corruption or exfiltration | Low (parameterized queries used) |
| Path traversal in parser | Malicious file paths passed to ingestion | File read outside intended scope | Low (Path normalization used) |
| Clipboard exfiltration | Sensitive context copied to clipboard persists | Data leakage via clipboard history | Low |
| Denial of service via large documents | Extremely large files consume memory during chunking | Process crash or system slowdown | Low |

## Security Controls

| Control | Implementation | Location |
|---------|---------------|----------|
| Parameterized SQL queries | All database operations use `?` placeholders, never string interpolation | `kgcp/storage/sqlite_store.py` |
| Input validation on extraction | LLM responses are parsed through fault-tolerant JSON extraction that rejects non-dict objects | `kgcp/extraction/llm_client.py` |
| Entity normalization | All extracted entities are lowercased and stripped, reducing injection surface | `kgcp/extraction/extractor.py` |
| API key via environment variable | `KGCP_API_KEY` and `ANTHROPIC_API_KEY` env vars avoid hardcoding secrets | `kgcp/config.py`, `kgcp/integration/claude_api.py` |
| WAL journal mode | SQLite WAL mode prevents corruption from concurrent access | `kgcp/storage/sqlite_store.py` |
| Foreign key enforcement | `PRAGMA foreign_keys=ON` ensures referential integrity | `kgcp/storage/sqlite_store.py` |
| File type validation | Parser registry only processes known extensions; unknown types fall back to UTF-8 text or raise `ValueError` | `kgcp/ingestion/parser_registry.py` |
| LLM timeout | HTTP requests to the LLM endpoint timeout after 120 seconds | `kgcp/extraction/llm_client.py` |

## Data Protection

**Data at rest**: All knowledge graph data lives in a local SQLite file (`~/.kgcp/knowledge.db`). The database is not encrypted. File system permissions are the primary access control. Users processing sensitive documents should ensure appropriate directory permissions and consider full-disk encryption.

**Data in transit**: Communication with the LLM endpoint uses HTTP by default (Ollama on localhost). When using remote LLM endpoints or the Claude API, connections use HTTPS. The Anthropic SDK enforces TLS for all API calls.

**Credential handling**: The default `config.toml` ships with a placeholder API key (`sk-1234`). Production API keys should be set via environment variables (`KGCP_API_KEY`, `ANTHROPIC_API_KEY`) rather than stored in config files. The `.gitignore` excludes `.db` files but does not exclude `config.toml` — users should avoid committing files with real credentials.

**Output handling**: Packed context sent to clipboard or files may contain sensitive extracted knowledge. The `--to-file` option writes plaintext. Users should be aware that clipboard contents may be logged by clipboard managers.

## Software Bill of Materials (SBOM)

KGCP maintains a full dependency inventory with license compliance analysis and SBOM generation instructions. See [docs/SBOM.md](SBOM.md) for the complete SBOM including dependency tables, license compliance, vulnerability scanning, and generation instructions.

## Incident Response

| Severity | Description | Response |
|----------|-------------|----------|
| Critical | API key compromised, database contains sensitive data exposed | Rotate keys immediately, assess data exposure, delete and recreate the database if needed |
| High | LLM prompt injection producing systematically corrupted triplets | Identify affected documents, delete them with `kgcp baseline delete` + re-ingest, review extraction prompts |
| Medium | Unauthorized access to knowledge.db file | Restrict file permissions, assess what data was stored, consider encrypting the database |
| Low | Stale or inaccurate triplets from poor extraction quality | Re-ingest with a better model, create a new baseline, review anomaly scores |

## Recommendations

1. **Never commit real API keys** to version control. Use environment variables for all credentials.
2. **Restrict file permissions** on `~/.kgcp/knowledge.db` if it contains sensitive extracted knowledge.
3. **Use HTTPS** when pointing `KGCP_LLM_URL` at a remote endpoint rather than localhost.
4. **Review extracted triplets** before feeding them to Claude for high-stakes decisions — LLM extraction is imperfect and may hallucinate relationships.
5. **Generate and review SBOMs** before deploying to shared or regulated environments.
6. **Run `pip-audit`** regularly to check for known vulnerabilities in dependencies.
