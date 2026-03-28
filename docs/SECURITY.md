---
title: Security
scope: Threat model, data protection, security controls, SBOM requirements, and incident response for KGCP
last_updated: 2026-03-27
---

# Security

KGCP is a local CLI tool that processes documents through an LLM and stores structured knowledge in SQLite. It can also export data to remote CTI platforms (MISP, OpenCTI, TheHive) and serve STIX bundles via a TAXII 2.1 server. This document covers the threat model, security controls, and operational security considerations.

## Threat Model

KGCP's attack surface spans six boundaries: document ingestion, LLM communication, local storage, output delivery, CTI platform push, and TAXII server exposure. The primary risks involve untrusted input processing, credential exposure, and network-facing services.

| Threat | Attack Vector | Impact | Likelihood |
|--------|--------------|--------|------------|
| LLM prompt injection via documents | Malicious text in ingested documents influences extraction prompts | Corrupted triplets, misleading knowledge graph | Medium (mitigated by 4-layer defense) |
| API key exposure | Keys in config.toml committed to version control or logged | Unauthorized LLM/Claude API usage | Medium |
| CTI platform credential exposure | MISP/OpenCTI/TheHive API keys in config or env vars leaked | Unauthorized access to CTI platforms, data injection | Medium |
| Entity injection into CTI platforms | Crafted entity names with control chars or ANSI escapes pushed to remote platforms | XSS or log injection in downstream CTI UIs | Medium (mitigated by sanitization) |
| TAXII server network exposure | TAXII server bound to 0.0.0.0 without API key | Unauthorized access to full knowledge graph via HTTP | Medium (mitigated by auth) |
| SQLite injection | Crafted entity names in extracted triplets | Data corruption or exfiltration | Low (parameterized queries used) |
| Path traversal in parser | Malicious file paths passed to ingestion | File read outside intended scope | Low (Path normalization used) |
| Clipboard exfiltration | Sensitive context copied to clipboard persists | Data leakage via clipboard history | Low |
| Denial of service via large documents | Extremely large files consume memory during chunking | Process crash or system slowdown | Low |
| CTI platform timeout abuse | Slow/unresponsive remote platform holds connection indefinitely | Process hang, resource exhaustion | Low (mitigated by timeouts) |

## Prompt Injection Defense

KGCP processes untrusted documents through an LLM extraction pipeline, making it susceptible to prompt injection attacks where malicious content in ingested documents manipulates the extraction process. A 4-layer defense-in-depth mitigation protects the pipeline at every stage.

| Layer | Module | Defense | Blocks At |
|-------|--------|---------|-----------|
| Input Sanitization | `kgcp/extraction/sanitizer.py` | Strips control characters (0x00-0x08, 0x0B-0x1F, 0x7F-0x9F), ANSI escape sequences, and enforces length limits. Scans for injection signal phrases (instruction override, role manipulation, system prompt probing, exfiltration attempts, encoded payloads) with context-aware false positive reduction for legitimate CTI content. | Before LLM sees the text |
| Prompt Guardrails | `kgcp/extraction/prompts.py` | Explicit untrusted-input preamble in the system prompt instructs the LLM to treat document content as DATA, not INSTRUCTIONS. Boundary delimiters (`--- BEGIN/END DOCUMENT TEXT ---`) clearly separate instructions from content. | During LLM processing |
| Post-Extraction Validation | `kgcp/extraction/validator.py` | Scans extracted triplets across all fields (subject, predicate, object) for 7 injection pattern categories plus structural checks (empty fields, suspiciously long entities). Severity scoring (none/low/medium/high) with automatic dropping of medium+ flagged triplets. | After extraction, before storage |
| Context Boundary Markers | `kgcp/integration/claude_api.py` | Wraps packed triplet context in explicit boundary delimiters with DATA-only instructions when injecting into Claude's system prompt. Prevents indirect prompt injection through stored triplet content. | During context injection |

The pipeline drops flagged triplets by default, preserving clean triplets from the same document. The `force=True` parameter overrides validation blocking when false positives are certain. All security events are logged for audit.

## Security Controls

| Control | Implementation | Location |
|---------|---------------|----------|
| Parameterized SQL queries | All database operations use `?` placeholders, never string interpolation | `kgcp/storage/sqlite_store.py` |
| Input text sanitization | Control characters, ANSI escapes stripped from document text before prompt interpolation; injection signals logged | `kgcp/extraction/sanitizer.py` |
| Prompt injection guardrails | Untrusted-input framing in system prompt; boundary delimiters separate instructions from content | `kgcp/extraction/prompts.py` |
| Post-extraction triplet validation | Extracted triplets scanned for injection patterns; flagged triplets dropped by default | `kgcp/extraction/validator.py` |
| Context boundary markers | Packed context wrapped in DATA-only delimiters in Claude system prompts | `kgcp/integration/claude_api.py` |
| Input validation on extraction | LLM responses are parsed through fault-tolerant JSON extraction that rejects non-dict objects | `kgcp/extraction/llm_client.py` |
| Entity normalization | All extracted entities are lowercased and stripped, reducing injection surface | `kgcp/extraction/extractor.py` |
| API key via environment variable | `KGCP_API_KEY` and `ANTHROPIC_API_KEY` env vars avoid hardcoding secrets | `kgcp/config.py`, `kgcp/integration/claude_api.py` |
| WAL journal mode | SQLite WAL mode prevents corruption from concurrent access | `kgcp/storage/sqlite_store.py` |
| Foreign key enforcement | `PRAGMA foreign_keys=ON` ensures referential integrity | `kgcp/storage/sqlite_store.py` |
| File type validation | Parser registry only processes known extensions; unknown types fall back to UTF-8 text or raise `ValueError` | `kgcp/ingestion/parser_registry.py` |
| LLM timeout | HTTP requests to the LLM endpoint timeout after 120 seconds | `kgcp/extraction/llm_client.py` |
| Entity name sanitization | Control characters, ANSI escapes, and null bytes stripped; names truncated to 512 chars before export | `kgcp/export/base.py` |
| Error message sanitization | Remote platform error responses stripped of escape sequences and truncated to 1000 chars before display | `kgcp/export/base.py` |
| CTI push timeouts | All remote platform push operations timeout after 120 seconds (configurable per platform) | `kgcp/export/misp_adapter.py`, `thehive_adapter.py` |
| TAXII API key authentication | Bearer token auth on all TAXII endpoints; server runs open only if no key is configured | `kgcp/server/taxii.py` |
| TAXII content limits | Maximum 10,000 objects per response; `max_content_length` configurable | `kgcp/server/taxii.py` |
| CTI credential isolation | Platform API keys loaded via dedicated env vars (`KGCP_MISP_API_KEY`, etc.) separate from LLM keys | `kgcp/config.py` |

## Data Protection

**Data at rest**: All knowledge graph data lives in a local SQLite file (`~/.kgcp/knowledge.db`). The database is not encrypted. File system permissions are the primary access control. Users processing sensitive documents should ensure appropriate directory permissions and consider full-disk encryption.

**Data in transit**: Communication with the LLM endpoint uses HTTP by default (Ollama on localhost). When using remote LLM endpoints or the Claude API, connections use HTTPS. The Anthropic SDK enforces TLS for all API calls.

**Credential handling**: The default `config.toml` ships with a placeholder API key (`sk-1234`). Production API keys should be set via environment variables (`KGCP_API_KEY`, `ANTHROPIC_API_KEY`, `KGCP_MISP_API_KEY`, `KGCP_OPENCTI_API_KEY`, `KGCP_THEHIVE_API_KEY`, `KGCP_TAXII_API_KEY`) rather than stored in config files. The `.gitignore` excludes `.db` files but does not exclude `config.toml` — users should avoid committing files with real credentials.

**Output handling**: Packed context sent to clipboard or files may contain sensitive extracted knowledge. The `--to-file` option writes plaintext. Users should be aware that clipboard contents may be logged by clipboard managers.

**CTI export**: Data pushed to remote CTI platforms (MISP, OpenCTI, TheHive) travels over HTTPS. All entity names are sanitized before export to prevent injection into downstream platform UIs. STIX bundles written to files or served via TAXII contain the full subgraph for the queried entity — review before sharing.

## Software Bill of Materials (SBOM)

KGCP maintains a full dependency inventory with license compliance analysis and SBOM generation instructions. See [docs/SBOM.md](SBOM.md) for the complete SBOM including dependency tables, license compliance, vulnerability scanning, and generation instructions.

## Incident Response

| Severity | Description | Response |
|----------|-------------|----------|
| Critical | API key compromised, database contains sensitive data exposed | Rotate keys immediately, assess data exposure, delete and recreate the database if needed |
| High | LLM prompt injection bypassing the 4-layer defense | Review validator patterns in `sanitizer.py` and `validator.py`, add new detection patterns, re-ingest affected documents, create new baseline |
| Medium | Unauthorized access to knowledge.db file | Restrict file permissions, assess what data was stored, consider encrypting the database |
| High | CTI platform API key compromised | Rotate key on the affected platform immediately, audit push history for unauthorized data, update env vars |
| Medium | TAXII server exposed to untrusted network | Stop the server, review access logs, restrict bind address to localhost or add API key auth |
| Medium | Malicious entity names pushed to CTI platform | Sanitization should prevent this; if bypassed, review affected events/alerts on the platform, re-export with updated KGCP |
| Low | Stale or inaccurate triplets from poor extraction quality | Re-ingest with a better model, create a new baseline, review anomaly scores |

## Recommendations

1. **Never commit real API keys** to version control. Use environment variables for all credentials.
2. **Restrict file permissions** on `~/.kgcp/knowledge.db` if it contains sensitive extracted knowledge.
3. **Use HTTPS** when pointing `KGCP_LLM_URL` at a remote endpoint rather than localhost.
4. **Review extracted triplets** before feeding them to Claude for high-stakes decisions — LLM extraction is imperfect and may hallucinate relationships.
5. **Generate and review SBOMs** before deploying to shared or regulated environments.
6. **Run `pip-audit`** regularly to check for known vulnerabilities in dependencies.
7. **Configure TAXII API key** before binding the server to a non-localhost address. Running open on `0.0.0.0` exposes the full knowledge graph to the network.
8. **Use separate API keys** for each CTI platform rather than sharing a single credential across MISP, OpenCTI, and TheHive.
