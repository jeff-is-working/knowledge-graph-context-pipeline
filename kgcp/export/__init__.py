"""CTI export adapters — STIX 2.1, MISP, OpenCTI, TheHive."""

from __future__ import annotations

from typing import Any

EXPORTER_REGISTRY: dict[str, type] = {}


def register_exporter(name: str, exporter_class: type) -> None:
    """Register a CTI exporter class by name."""
    EXPORTER_REGISTRY[name.lower()] = exporter_class


def get_exporter(name: str, config: dict | None = None) -> Any:
    """Get an initialized exporter instance by name."""
    cls = EXPORTER_REGISTRY.get(name.lower())
    if cls is None:
        available = ", ".join(sorted(EXPORTER_REGISTRY.keys()))
        raise ValueError(f"Unknown exporter '{name}'. Available: {available}")
    return cls(config or {})


def list_exporters() -> list[str]:
    """List registered exporter names."""
    return sorted(EXPORTER_REGISTRY.keys())
