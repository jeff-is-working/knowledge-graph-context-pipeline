"""TOML configuration loader for KGCP."""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

try:
    import tomllib  # Python 3.11+
except ModuleNotFoundError:
    import tomli as tomllib  # type: ignore[no-redef]

DEFAULT_CONFIG_PATHS = [
    Path("config.toml"),
    Path("~/.kgcp/config.toml").expanduser(),
]

DEFAULTS: dict[str, Any] = {
    "llm": {
        "model": "gemma3",
        "api_key": "sk-1234",
        "base_url": "http://localhost:11434/v1/chat/completions",
        "max_tokens": 8192,
        "temperature": 0.8,
    },
    "chunking": {
        "chunk_size": 100,
        "overlap": 20,
    },
    "standardization": {
        "enabled": True,
        "use_llm": True,
    },
    "inference": {
        "enabled": True,
        "use_llm": True,
    },
    "storage": {
        "db_path": str(Path("~/.kgcp/knowledge.db").expanduser()),
    },
    "retrieval": {
        "default_hops": 2,
        "default_budget": 2048,
        "default_format": "yaml",
    },
    "packing": {
        "include_provenance": True,
        "include_entity_metadata": True,
    },
    "anomaly": {
        "min_display_score": 0.3,
        "anomaly_boost_weight": 0.1,
        "signal_weights": {
            "new_entity": 0.30,
            "new_edge": 0.25,
            "community_mismatch": 0.20,
            "unusual_predicate": 0.15,
            "centrality_drift": 0.10,
        },
    },
}


def _deep_merge(base: dict, override: dict) -> dict:
    """Merge override into base, preferring override values."""
    result = base.copy()
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def load_config(config_path: str | Path | None = None) -> dict[str, Any]:
    """Load TOML config, falling back to defaults.

    Search order:
    1. Explicit path (if provided)
    2. ./config.toml
    3. ~/.kgcp/config.toml
    4. Built-in defaults
    """
    config = DEFAULTS.copy()

    paths_to_try: list[Path] = []
    if config_path:
        paths_to_try.append(Path(config_path).expanduser())
    paths_to_try.extend(DEFAULT_CONFIG_PATHS)

    for path in paths_to_try:
        resolved = path.expanduser()
        if resolved.exists():
            with open(resolved, "rb") as f:
                file_config = tomllib.load(f)
            config = _deep_merge(config, file_config)
            break

    # Environment variable overrides
    if env_key := os.environ.get("KGCP_API_KEY"):
        config["llm"]["api_key"] = env_key
    if env_url := os.environ.get("KGCP_LLM_URL"):
        config["llm"]["base_url"] = env_url
    if env_model := os.environ.get("KGCP_MODEL"):
        config["llm"]["model"] = env_model
    if env_db := os.environ.get("KGCP_DB_PATH"):
        config["storage"]["db_path"] = env_db

    return config
