# 2026-03-27 -- Prompt Injection Mitigation

## What Was Done

Implemented a 4-layer defense-in-depth prompt injection mitigation for the extraction pipeline, adapted from the proven pattern in `image-to-knowledge`.

### Layer 1: Input Sanitization (`kgcp/extraction/sanitizer.py`)
- Strips control characters (0x00-0x08, 0x0B, 0x0C, 0x0E-0x1F, 0x7F-0x9F) while preserving newlines/tabs
- Strips ANSI escape sequences
- Enforces configurable max length with truncation
- Pre-extraction injection signal detection (instruction override, role manipulation, system prompt probing, exfiltration attempts, encoded payloads, code execution)
- Context-aware false positive reduction for legitimate CTI/security content
- Returns structured `SanitizeResult` with full audit trail

### Layer 2: Prompt Guardrails (`kgcp/extraction/prompts.py`)
- Added explicit untrusted-input preamble to `EXTRACTION_SYSTEM_PROMPT`
- Frames document content as DATA, not INSTRUCTIONS
- Explicit boundary markers (`--- BEGIN DOCUMENT TEXT ---` / `--- END DOCUMENT TEXT ---`) replace bare code fences
- LLM instructed to ignore any embedded instructions and extract knowledge normally

### Layer 3: Post-Extraction Validation (`kgcp/extraction/validator.py`)
- Scans extracted triplets for 7 injection pattern categories across all fields
- Structural checks: empty fields, suspiciously long entities (>10 words)
- Severity scoring (none/low/medium/high) with pipeline blocking on medium+high
- Flagged triplets are dropped by default; `force=True` overrides
- Returns `ValidationResult` with findings, flagged indices, and formatted report

### Layer 4: Context Boundary Markers (`kgcp/integration/claude_api.py`)
- Wrapped packed context in explicit delimiters (`--- BEGIN KNOWLEDGE GRAPH CONTEXT (DATA ONLY) ---`)
- Added instruction header distinguishing data from system instructions
- Prevents indirect prompt injection through triplet content reaching Claude's system prompt

### Pipeline Integration (`kgcp/extraction/extractor.py`)
- Sanitizer runs before prompt interpolation
- Injection signals logged as warnings
- Validator runs after triplet extraction, before storage
- Flagged triplets dropped by default (clean triplets preserved)
- `force` parameter available for override

## Tests Added
- `tests/test_sanitizer.py` -- 20 tests covering sanitization, injection signal detection, false positive reduction
- `tests/test_validator.py` -- 16 tests covering triplet validation, pattern detection, report formatting
- Full suite: 492 passed, 4 skipped, 0 failures

## Decisions Made
- Adapted image-to-knowledge pattern rather than building from scratch -- proven approach with production-quality test coverage
- Chose to DROP flagged triplets by default rather than blocking the entire pipeline -- preserves clean data from mixed documents
- Context-aware false positive reduction for CTI content -- security reports legitimately discuss attack techniques that resemble injection patterns
- Did NOT implement LLM-based secondary validation (cost/latency tradeoff) -- pattern-based detection is fast, auditable, and sufficient for current threat model

## What's Left
- No changes to CTI export path (already has entity sanitization in `export/base.py`)
- Could add LLM-based semantic validation as a future enhancement for high-value ingestions
- Could add configurable severity threshold in `config.toml`
- Graph integrity monitoring (periodic statistical checks) remains a future enhancement

## Issue
Tracked in KGCP-Project/knowledge-graph-context-pipeline#22
