---
title: Documentation Index
scope: Navigation hub for all KGCP project documentation
last_updated: 2026-03-27
---

# KGCP Documentation

## Documents

| Document | Purpose |
|----------|---------|
| [README](../README.md) | Project overview, features, getting started, CLI reference |
| [Architecture](ARCHITECTURE.md) | System design, data model, data flow, design decisions |
| [Developer Guide](DEVELOPER_GUIDE.md) | Development setup, coding conventions, testing, module walkthrough |
| [Deployment](DEPLOYMENT.md) | Installation, LLM configuration, operations, troubleshooting |
| [Security](SECURITY.md) | Threat model, prompt injection defense, data protection, security controls |
| [Admin Guide](ADMIN_GUIDE.md) | Operational procedures, maintenance workflows, daily administration |
| [Infrastructure](INFRASTRUCTURE.md) | Network architecture, LLM deployment, backup/recovery, capacity planning |
| [SBOM](SBOM.md) | Dependency inventory, license compliance, vulnerability scanning |
| [Data Flow](DATA_FLOW.md) | Mermaid sequence diagrams for ingestion, querying, anomaly detection, and attack paths |
| [CTI Integration](CTI_INTEGRATION.md) | STIX 2.1, MISP, OpenCTI, TheHive, TAXII 2.1 — architecture, data mapping, configuration, CLI usage |
| [Design Journal](../DESIGN.md) | Phase-by-phase implementation history and Lambert's Four Algebras framework |

## Documentation Methodology

These documents follow the Enterprise Documentation v1.3 methodology:

- **YAML metadata** on every file with title, scope, and last-updated date
- **Cross-reference, never duplicate** — each piece of information lives in exactly one place, with links between docs
- **Tables over prose** for structured information like troubleshooting, security controls, and configuration
- **Context before code** — every snippet has a preceding sentence explaining what it is
- **Setup/deploy steps live in README only** — other docs link there instead of duplicating

## Contributing to Docs

When updating documentation, follow these conventions:

1. Keep each file under 10 top-level (`##`) headings
2. Add context sentences before code blocks
3. Update the `last_updated` field in the YAML header
4. Link to existing docs rather than duplicating content
5. Use tables for structured reference information
