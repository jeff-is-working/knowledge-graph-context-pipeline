---
title: Software Bill of Materials
scope: Dependency inventory, SBOM generation, license compliance, and supply chain security for KGCP
last_updated: 2026-03-11
---

# Software Bill of Materials (SBOM)

An SBOM provides a complete inventory of KGCP's software components, enabling vulnerability tracking, license compliance, and supply chain risk management.

## Generating an SBOM

Generate a CycloneDX SBOM from the installed environment using `cyclonedx-py`. This should be run from within the project's virtual environment so it captures the exact installed dependency tree.

```bash
pip install cyclonedx-bom
cyclonedx-py environment -o sbom.cdx.json --output-format json
```

For SPDX format, use `syft` or `spdx-tools`:

```bash
# Using syft (install from https://github.com/anchore/syft)
syft dir:. -o spdx-json > sbom.spdx.json
```

## Direct Dependencies

These are the packages declared in `pyproject.toml` that KGCP directly imports and uses.

### Core (always installed)

| Package | Version Constraint | Purpose | License |
|---------|--------------------|---------|---------|
| networkx | >=3.4.2 | In-memory graph operations, centrality, traversal | BSD-3-Clause |
| requests | >=2.32.3 | HTTP client for OpenAI-compatible LLM endpoints | Apache-2.0 |
| click | >=8.1.0 | CLI framework with command groups and option parsing | BSD-3-Clause |
| rich | >=13.0.0 | Terminal formatting and progress display | MIT |
| python-louvain | >=0.16 | Louvain community detection algorithm | BSD-3-Clause |

### Optional — Parsing (`pip install kgcp[parsing]`)

| Package | Version Constraint | Purpose | License |
|---------|--------------------|---------|---------|
| PyMuPDF | >=1.24.0 | PDF document text extraction | AGPL-3.0 |
| beautifulsoup4 | >=4.12.0 | HTML document parsing | MIT |
| html2text | >=2024.2.26 | HTML-to-plaintext conversion | GPL-3.0 |

### Optional — Claude Integration (`pip install kgcp[claude]`)

| Package | Version Constraint | Purpose | License |
|---------|--------------------|---------|---------|
| anthropic | >=0.40.0 | Anthropic Claude API SDK | MIT |

### Optional — Token Counting (`pip install kgcp[tokens]`)

| Package | Version Constraint | Purpose | License |
|---------|--------------------|---------|---------|
| tiktoken | >=0.7.0 | Precise BPE token estimation (cl100k_base) | MIT |

### Development (`pip install kgcp[dev]`)

| Package | Version Constraint | Purpose | License |
|---------|--------------------|---------|---------|
| pytest | >=8.0.0 | Test framework | MIT |
| pytest-cov | >=5.0.0 | Coverage reporting | MIT |

## License Compliance

KGCP is licensed under MIT. Most core dependencies use permissive licenses (MIT, BSD-3-Clause, Apache-2.0) that are compatible without restriction.

Two optional parsing dependencies use copyleft licenses that may affect distribution:

| Package | License | Impact |
|---------|---------|--------|
| PyMuPDF | AGPL-3.0 | Requires source disclosure if KGCP is distributed as a network service with PDF parsing enabled. No impact for local CLI use. |
| html2text | GPL-3.0 | Requires source disclosure if distributed in a combined work. No impact for local CLI use or when installed separately as an optional dependency. |

These packages are optional extras, not core dependencies. Users who need to avoid copyleft obligations can install KGCP without the `[parsing]` extra and use only plaintext, Markdown, and code file ingestion.

## Vulnerability Scanning

Run `pip-audit` to check installed packages against the Python Packaging Advisory Database:

```bash
pip install pip-audit
pip-audit
```

For continuous monitoring, integrate `pip-audit` or `osv-scanner` into CI when a pipeline is added.

## SBOM Practices

- **When to regenerate**: After any dependency change — additions, version bumps, or removals in `pyproject.toml`
- **Where to store**: Include `sbom.cdx.json` in release artifacts alongside the source distribution. Do not commit generated SBOMs to the repo (they are environment-specific)
- **Version pinning**: For reproducible builds, generate a lockfile with `pip freeze > requirements.lock` and reference it in the SBOM
- **Transitive dependencies**: The CycloneDX generator captures the full transitive tree. Review transitive dependencies periodically, especially after major version upgrades
- **Attestation**: Consider signing SBOMs with `cosign` or `sigstore` for tamper-evident distribution when publishing releases
