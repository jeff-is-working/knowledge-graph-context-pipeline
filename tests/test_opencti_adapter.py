"""Tests for the OpenCTI export adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from kgcp.export.opencti_adapter import OpenCTIExporter, _add_opencti_extensions
from kgcp.models import AttackPath, AttackPathStep, Triplet


@pytest.fixture
def exporter():
    return OpenCTIExporter({})


@pytest.fixture
def custom_exporter():
    return OpenCTIExporter({
        "cti": {
            "opencti": {
                "url": "https://opencti.example.com",
                "api_key": "test-key",
                "verify_ssl": False,
            }
        }
    })


def _make_triplet(
    subject="APT28",
    predicate="targets",
    obj="ACME Corp",
    confidence=0.85,
    triplet_id="t-001",
    first_seen="2025-06-01T00:00:00Z",
    last_seen="2025-06-15T00:00:00Z",
):
    return Triplet(
        subject=subject, predicate=predicate, object=obj, doc_id="doc-1",
        confidence=confidence, triplet_id=triplet_id,
        first_seen=first_seen, last_seen=last_seen,
    )


class TestOpenCTIExtensions:
    def test_adds_score_to_sdos(self):
        bundle = {
            "type": "bundle",
            "objects": [
                {"type": "threat-actor", "name": "APT28"},
                {"type": "malware", "name": "DarkComet", "confidence": 80},
            ],
        }
        result = _add_opencti_extensions(bundle)
        ta = [o for o in result["objects"] if o["type"] == "threat-actor"][0]
        assert ta["x_opencti_score"] == 50  # default

        mw = [o for o in result["objects"] if o["type"] == "malware"][0]
        assert mw["x_opencti_score"] == 80  # from confidence

    def test_skips_relationships(self):
        bundle = {
            "type": "bundle",
            "objects": [
                {"type": "relationship", "relationship_type": "targets"},
            ],
        }
        result = _add_opencti_extensions(bundle)
        rel = result["objects"][0]
        assert "x_opencti_score" not in rel

    def test_skips_bundle_type(self):
        bundle = {
            "type": "bundle",
            "objects": [
                {"type": "bundle", "id": "bundle--nested"},
            ],
        }
        result = _add_opencti_extensions(bundle)
        nested = result["objects"][0]
        assert "x_opencti_score" not in nested

    def test_preserves_existing_score(self):
        bundle = {
            "type": "bundle",
            "objects": [
                {"type": "threat-actor", "name": "APT28", "x_opencti_score": 90},
            ],
        }
        result = _add_opencti_extensions(bundle)
        assert result["objects"][0]["x_opencti_score"] == 90

    def test_empty_objects(self):
        bundle = {"type": "bundle", "objects": []}
        result = _add_opencti_extensions(bundle)
        assert result["objects"] == []


class TestExportTriplets:
    def test_returns_stix_bundle(self, exporter):
        bundle = exporter.export_triplets([_make_triplet()])
        assert bundle["type"] == "bundle"
        assert "objects" in bundle

    def test_bundle_has_opencti_scores(self, exporter):
        bundle = exporter.export_triplets([_make_triplet()])
        sdos = [o for o in bundle["objects"] if o["type"] not in ("relationship", "bundle")]
        for sdo in sdos:
            assert "x_opencti_score" in sdo

    def test_confidence_maps_to_score(self, exporter):
        bundle = exporter.export_triplets([_make_triplet(confidence=0.75)])
        # SROs should have confidence but SDOs get x_opencti_score
        sros = [o for o in bundle["objects"] if o["type"] == "relationship"]
        if sros:
            assert sros[0]["confidence"] == 75


class TestExportAttackPath:
    def _make_path(self):
        t1 = _make_triplet(subject="APT28", predicate="targets", obj="Org1", triplet_id="t1")
        t2 = _make_triplet(subject="Org1", predicate="uses", obj="Tool1", triplet_id="t2")
        step1 = AttackPathStep(triplet=t1, timestamp="2025-06-01T00:00:00Z", step_index=0)
        step2 = AttackPathStep(triplet=t2, timestamp="2025-06-02T00:00:00Z", step_index=1)
        return AttackPath(
            seed_entity="APT28", steps=[step1, step2],
            entities_involved={"APT28", "Org1", "Tool1"},
            time_span=("2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z"),
            total_anomaly=0.7,
        )

    def test_attack_path_returns_bundle(self, exporter):
        bundle = exporter.export_attack_path(self._make_path())
        assert bundle["type"] == "bundle"

    def test_attack_path_has_opencti_scores(self, exporter):
        bundle = exporter.export_attack_path(self._make_path())
        sdos = [o for o in bundle["objects"] if o["type"] not in ("relationship", "bundle")]
        for sdo in sdos:
            assert "x_opencti_score" in sdo


class TestConfig:
    def test_defaults(self, exporter):
        assert exporter.url == ""
        assert exporter.api_key == ""
        assert exporter.verify_ssl is True

    def test_custom_config(self, custom_exporter):
        assert custom_exporter.url == "https://opencti.example.com"
        assert custom_exporter.api_key == "test-key"
        assert custom_exporter.verify_ssl is False


class TestToFile:
    def test_writes_json(self, exporter):
        bundle = exporter.export_triplets([_make_triplet()])
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "subdir" / "opencti_bundle.json"
            exporter.to_file(bundle, out)
            assert out.exists()
            loaded = json.loads(out.read_text())
            assert loaded["type"] == "bundle"


class TestPush:
    def test_push_missing_url_raises(self, exporter):
        """URL validation happens before any imports."""
        with pytest.raises(ValueError, match="URL"):
            exporter.push({"type": "bundle", "objects": []})

    def test_push_missing_api_key_raises(self):
        exp = OpenCTIExporter({"cti": {"opencti": {"url": "https://opencti.example.com"}}})
        with pytest.raises(ValueError, match="API key"):
            exp.push({"type": "bundle", "objects": []})


class TestRegistration:
    def test_opencti_registered(self):
        from kgcp.export import EXPORTER_REGISTRY
        assert "opencti" in EXPORTER_REGISTRY
        assert EXPORTER_REGISTRY["opencti"] is OpenCTIExporter
