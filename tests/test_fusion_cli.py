"""Tests for Phase 8 CLI enhancements — unified scoring and attack paths."""

import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from click.testing import CliRunner

from kgcp.cli import cli
from kgcp.models import Document, Triplet
from kgcp.storage.sqlite_store import SQLiteStore


def _ts(days_ago: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=days_ago)
    return dt.isoformat()


@pytest.fixture
def cli_store(tmp_path):
    """Create a populated store and config for CLI testing."""
    db_path = tmp_path / "test.db"
    store = SQLiteStore(db_path)

    doc = Document(source_path="/tmp/threat.txt", doc_id="doc1")
    store.add_document(doc)

    triplets = [
        Triplet(
            subject="apt28", predicate="targets", object="energy sector",
            doc_id="doc1", confidence=0.9,
            first_seen=_ts(20), last_seen=_ts(5),
        ),
        Triplet(
            subject="apt28", predicate="uses", object="credential harvesting",
            doc_id="doc1", confidence=0.8,
            first_seen=_ts(15), last_seen=_ts(3),
        ),
        Triplet(
            subject="credential harvesting", predicate="delivers", object="backdoor",
            doc_id="doc1", confidence=0.7,
            first_seen=_ts(10), last_seen=_ts(2),
        ),
    ]
    store.add_triplets(triplets)

    # Write config pointing to this DB
    config_path = tmp_path / "config.toml"
    config_path.write_text(f'[storage]\ndb_path = "{db_path}"\n')

    store.close()
    yield str(config_path), str(db_path)


def test_query_unified_flag(cli_store):
    """--unified flag should produce results with unified_score."""
    config_path, _ = cli_store
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", config_path, "query", "apt28", "--unified"])
    assert result.exit_code == 0


def test_query_min_anomaly(cli_store):
    """--min-anomaly should filter results."""
    config_path, _ = cli_store
    runner = CliRunner()
    # High threshold — likely no results (no baseline)
    result = runner.invoke(cli, [
        "--config", config_path, "query", "apt28", "--min-anomaly", "0.9",
    ])
    # Should succeed (possibly "No matching triplets" but no crash)
    assert result.exit_code == 0


def test_paths_basic(cli_store):
    """paths command should produce output for a known entity."""
    config_path, _ = cli_store
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", config_path, "paths", "apt28"])
    assert result.exit_code == 0
    assert "apt28" in result.output


def test_paths_timeline_format(cli_store):
    """Default timeline format should include table headers."""
    config_path, _ = cli_store
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", config_path, "paths", "apt28", "-f", "timeline"])
    assert result.exit_code == 0
    assert "Attack Path" in result.output


def test_paths_json_format(cli_store):
    """JSON format should produce valid JSON structure."""
    import json

    config_path, _ = cli_store
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", config_path, "paths", "apt28", "-f", "json"])
    assert result.exit_code == 0
    # Extract JSON from output (skip log/status lines)
    json_start = result.output.index("{")
    json_str = result.output[json_start:]
    data = json.loads(json_str)
    assert data["seed_entity"] == "apt28"
    assert "steps" in data


def test_paths_yaml_format(cli_store):
    """YAML format should include path_metadata and timeline sections."""
    config_path, _ = cli_store
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", config_path, "paths", "apt28", "-f", "yaml"])
    assert result.exit_code == 0
    assert "path_metadata:" in result.output
    assert "timeline:" in result.output


def test_paths_compact_format(cli_store):
    """Compact format should use arrow notation with date prefix."""
    config_path, _ = cli_store
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", config_path, "paths", "apt28", "-f", "compact"])
    assert result.exit_code == 0
    assert "->" in result.output


def test_paths_unknown_entity(cli_store):
    """Unknown entity should produce a graceful message."""
    config_path, _ = cli_store
    runner = CliRunner()
    result = runner.invoke(cli, ["--config", config_path, "paths", "totally_unknown_xyz"])
    assert result.exit_code == 0
    assert "No attack path found" in result.output or result.output == ""


def test_paths_to_file(cli_store, tmp_path):
    """--to-file should write output to a file."""
    config_path, _ = cli_store
    out_file = tmp_path / "path_output.txt"
    runner = CliRunner()
    result = runner.invoke(cli, [
        "--config", config_path, "paths", "apt28", "--to-file", str(out_file),
    ])
    assert result.exit_code == 0
    assert out_file.exists()
    content = out_file.read_text()
    assert "apt28" in content
