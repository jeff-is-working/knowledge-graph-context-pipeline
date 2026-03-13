"""Tests for the TAXII 2.1 read-only server."""

from __future__ import annotations

import json
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from kgcp.server.taxii import (
    DEFAULT_COLLECTION_ID,
    DEFAULT_COLLECTION_TITLE,
    STIX_CONTENT_TYPE,
    TAXII_CONTENT_TYPE,
    create_app,
)


def _has_fastapi():
    try:
        import fastapi
        return True
    except ImportError:
        return False


pytestmark = pytest.mark.skipif(not _has_fastapi(), reason="fastapi not installed")


@pytest.fixture
def db_path(tmp_path):
    """Create a test SQLite database with sample triplets using the real schema."""
    db = tmp_path / "test.db"
    schema_path = Path(__file__).parent.parent / "kgcp" / "storage" / "schema.sql"
    conn = sqlite3.connect(str(db))
    conn.executescript(schema_path.read_text())
    conn.execute("""
        INSERT INTO triplets (triplet_id, subject, predicate, object, doc_id,
                              confidence, observation_count, first_seen, last_seen, metadata)
        VALUES ('t-001', 'APT28', 'targets', 'ACME Corp', 'doc-1',
                0.85, 1, '2025-06-01T00:00:00Z', '2025-06-15T00:00:00Z', '{}')
    """)
    conn.execute("""
        INSERT INTO triplets (triplet_id, subject, predicate, object, doc_id,
                              confidence, observation_count, first_seen, last_seen, metadata)
        VALUES ('t-002', 'APT28', 'uses', 'DarkComet', 'doc-1',
                0.75, 2, '2025-06-10T00:00:00Z', '2025-06-20T00:00:00Z', '{}')
    """)
    conn.commit()
    conn.close()
    return db


@pytest.fixture
def config(db_path):
    return {
        "storage": {"db_path": str(db_path)},
        "cti": {
            "taxii": {
                "api_key": "test-secret-key",
                "title": "Test TAXII Server",
                "max_content_length": 5_000_000,
            },
            "stix": {
                "default_confidence": 50,
                "identity_name": "KGCP-Test",
            },
        },
    }


@pytest.fixture
def open_config(db_path):
    """Config with no API key (open server)."""
    return {
        "storage": {"db_path": str(db_path)},
        "cti": {
            "taxii": {"api_key": "", "title": "Open TAXII"},
            "stix": {"default_confidence": 50, "identity_name": "KGCP-Test"},
        },
    }


@pytest.fixture
def client(config):
    from fastapi.testclient import TestClient
    app = create_app(config)
    return TestClient(app)


@pytest.fixture
def open_client(open_config):
    from fastapi.testclient import TestClient
    app = create_app(open_config)
    return TestClient(app)


AUTH_HEADER = {"Authorization": "Bearer test-secret-key"}


class TestDiscovery:
    def test_discovery_response(self, client):
        resp = client.get("/taxii2/", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test TAXII Server"
        assert "/api/" in data["api_roots"]
        assert data["default"] == "/api/"

    def test_discovery_requires_auth(self, client):
        resp = client.get("/taxii2/")
        assert resp.status_code == 401

    def test_discovery_wrong_key(self, client):
        resp = client.get("/taxii2/", headers={"Authorization": "Bearer wrong"})
        assert resp.status_code == 401

    def test_discovery_open_server(self, open_client):
        resp = open_client.get("/taxii2/")
        assert resp.status_code == 200


class TestAPIRoot:
    def test_api_root_response(self, client):
        resp = client.get("/api/", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert data["title"] == "Test TAXII Server"
        assert "2.1" in data["versions"][0]
        assert data["max_content_length"] == 5_000_000


class TestCollections:
    def test_list_collections(self, client):
        resp = client.get("/api/collections/", headers=AUTH_HEADER)
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["collections"]) == 1
        coll = data["collections"][0]
        assert coll["id"] == DEFAULT_COLLECTION_ID
        assert coll["can_read"] is True
        assert coll["can_write"] is False

    def test_get_collection(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["id"] == DEFAULT_COLLECTION_ID
        assert data["title"] == DEFAULT_COLLECTION_TITLE

    def test_get_collection_not_found(self, client):
        resp = client.get(
            "/api/collections/nonexistent/",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 404


class TestGetObjects:
    def test_returns_stix_bundle(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/objects/",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["type"] == "bundle"
        assert len(data["objects"]) > 0

    def test_bundle_has_relationships(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/objects/",
            headers=AUTH_HEADER,
        )
        data = resp.json()
        sros = [o for o in data["objects"] if o["type"] == "relationship"]
        assert len(sros) >= 1

    def test_added_after_filter(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/objects/",
            params={"added_after": "2025-06-05T00:00:00Z"},
            headers=AUTH_HEADER,
        )
        data = resp.json()
        assert data["type"] == "bundle"
        # Only t-002 (first_seen=2025-06-10) should match
        sros = [o for o in data["objects"] if o["type"] == "relationship"]
        assert len(sros) >= 1

    def test_limit_parameter(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/objects/",
            params={"limit": 1},
            headers=AUTH_HEADER,
        )
        data = resp.json()
        assert data["type"] == "bundle"
        # With limit=1, should have fewer objects than full export
        sros = [o for o in data["objects"] if o["type"] == "relationship"]
        assert len(sros) <= 1

    def test_collection_not_found(self, client):
        resp = client.get(
            "/api/collections/nonexistent/objects/",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 404


class TestManifest:
    def test_manifest_returns_entries(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/manifest/",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 200
        data = resp.json()
        assert "objects" in data
        assert len(data["objects"]) >= 2

    def test_manifest_entry_structure(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/manifest/",
            headers=AUTH_HEADER,
        )
        data = resp.json()
        entry = data["objects"][0]
        assert "id" in entry
        assert "date_added" in entry
        assert "version" in entry
        assert entry["media_type"] == STIX_CONTENT_TYPE

    def test_manifest_added_after(self, client):
        resp = client.get(
            f"/api/collections/{DEFAULT_COLLECTION_ID}/manifest/",
            params={"added_after": "2025-06-05T00:00:00Z"},
            headers=AUTH_HEADER,
        )
        data = resp.json()
        assert len(data["objects"]) >= 1

    def test_manifest_collection_not_found(self, client):
        resp = client.get(
            "/api/collections/nonexistent/manifest/",
            headers=AUTH_HEADER,
        )
        assert resp.status_code == 404


class TestEmptyDatabase:
    def test_empty_db_returns_empty_bundle(self, tmp_path):
        from fastapi.testclient import TestClient

        db = tmp_path / "empty.db"
        schema_path = Path(__file__).parent.parent / "kgcp" / "storage" / "schema.sql"
        conn = sqlite3.connect(str(db))
        conn.executescript(schema_path.read_text())
        conn.commit()
        conn.close()

        config = {
            "storage": {"db_path": str(db)},
            "cti": {
                "taxii": {"api_key": ""},
                "stix": {"default_confidence": 50, "identity_name": "KGCP"},
            },
        }
        app = create_app(config)
        client = TestClient(app)
        resp = client.get(f"/api/collections/{DEFAULT_COLLECTION_ID}/objects/")
        data = resp.json()
        assert data["type"] == "bundle"
        assert data["objects"] == []


class TestAuthModes:
    def test_bearer_prefix(self, client):
        resp = client.get("/taxii2/", headers={"Authorization": "Bearer test-secret-key"})
        assert resp.status_code == 200

    def test_raw_key(self, client):
        resp = client.get("/taxii2/", headers={"Authorization": "test-secret-key"})
        assert resp.status_code == 200

    def test_no_auth_when_required(self, client):
        resp = client.get("/taxii2/")
        assert resp.status_code == 401
