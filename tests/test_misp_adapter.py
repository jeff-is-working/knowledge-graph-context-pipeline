"""Tests for the MISP event export adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kgcp.export.misp_adapter import (
    MISPExporter,
    _confidence_tag,
    _misp_attr_for_entity,
    _threat_level_from_anomaly,
)
from kgcp.models import AttackPath, AttackPathStep, Triplet


def _has_pymisp():
    try:
        import pymisp  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture
def exporter():
    return MISPExporter({})


@pytest.fixture
def custom_exporter():
    return MISPExporter({
        "cti": {
            "misp": {
                "url": "https://misp.example.com",
                "api_key": "test-key",
                "default_distribution": 1,
                "default_threat_level": 3,
                "default_analysis": 2,
                "publish_on_push": True,
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
    metadata=None,
):
    return Triplet(
        subject=subject, predicate=predicate, object=obj, doc_id="doc-1",
        confidence=confidence, triplet_id=triplet_id,
        first_seen=first_seen, last_seen=last_seen,
        metadata=metadata or {},
    )


class TestConfidenceTag:
    def test_high_confidence(self):
        assert 'high' in _confidence_tag(0.9)

    def test_moderate_confidence(self):
        assert 'moderate' in _confidence_tag(0.6)

    def test_low_confidence(self):
        assert 'low' in _confidence_tag(0.3)

    def test_boundary_high(self):
        assert 'high' in _confidence_tag(0.8)

    def test_boundary_moderate(self):
        assert 'moderate' in _confidence_tag(0.5)


class TestThreatLevelFromAnomaly:
    def test_high_anomaly(self):
        assert _threat_level_from_anomaly(0.9) == 1

    def test_medium_anomaly(self):
        assert _threat_level_from_anomaly(0.5) == 2

    def test_low_anomaly(self):
        assert _threat_level_from_anomaly(0.2) == 3

    def test_undefined_anomaly(self):
        assert _threat_level_from_anomaly(0.05) == 4

    def test_zero_anomaly(self):
        assert _threat_level_from_anomaly(0.0) == 4


class TestMISPAttrForEntity:
    @pytest.mark.parametrize(
        "entity_type, expected_type, expected_category",
        [
            ("threat_actor", "threat-actor", "Attribution"),
            ("malware", "malware-type", "Payload delivery"),
            ("vulnerability", "vulnerability", "External analysis"),
            ("tool", "text", "Payload delivery"),
            ("organization", "target-org", "Targeting data"),
            ("location", "text", "Targeting data"),
            ("technique", "text", "External analysis"),
            ("unknown", "text", "Other"),
        ],
    )
    def test_mapping(self, entity_type, expected_type, expected_category):
        attr_type, category = _misp_attr_for_entity(entity_type)
        assert attr_type == expected_type
        assert category == expected_category

    def test_unknown_type_fallback(self):
        attr_type, category = _misp_attr_for_entity("nonexistent_type")
        assert attr_type == "text"
        assert category == "Other"


class TestExportTriplets:
    def test_event_structure(self, exporter):
        event = exporter.export_triplets([_make_triplet()])
        assert "Event" in event
        assert "info" in event["Event"]
        assert "Attribute" in event["Event"]
        assert "Tag" in event["Event"]

    def test_default_event_info(self, exporter):
        event = exporter.export_triplets([_make_triplet()])
        assert event["Event"]["info"] == "KGCP exported event"

    def test_custom_event_info(self, exporter):
        event = exporter.export_triplets([_make_triplet()], info="Custom info")
        assert event["Event"]["info"] == "Custom info"

    def test_attributes_created_for_entities(self, exporter):
        event = exporter.export_triplets([_make_triplet()])
        attrs = event["Event"]["Attribute"]
        values = [a["value"] for a in attrs]
        assert "APT28" in values
        assert "ACME Corp" in values

    def test_attributes_deduplicated(self, exporter):
        triplets = [
            _make_triplet(subject="APT28", predicate="targets", obj="Org1", triplet_id="t1"),
            _make_triplet(subject="APT28", predicate="uses", obj="Tool1", triplet_id="t2"),
        ]
        event = exporter.export_triplets(triplets)
        attrs = event["Event"]["Attribute"]
        apt28_attrs = [a for a in attrs if a["value"] == "APT28"]
        assert len(apt28_attrs) == 1

    def test_to_ids_flag_for_threat_actor(self, exporter):
        event = exporter.export_triplets([_make_triplet()])
        attrs = event["Event"]["Attribute"]
        apt28_attr = [a for a in attrs if a["value"] == "APT28"][0]
        assert apt28_attr["to_ids"] is True

    def test_default_distribution(self, exporter):
        event = exporter.export_triplets([_make_triplet()])
        assert event["Event"]["distribution"] == 0

    def test_custom_distribution(self, custom_exporter):
        event = custom_exporter.export_triplets([_make_triplet()])
        assert event["Event"]["distribution"] == 1

    def test_anomaly_affects_threat_level(self, exporter):
        t = _make_triplet(metadata={"anomaly_score": 0.9})
        event = exporter.export_triplets([t])
        assert event["Event"]["threat_level_id"] == 1

    def test_no_anomaly_uses_default_threat_level(self, exporter):
        event = exporter.export_triplets([_make_triplet()])
        assert event["Event"]["threat_level_id"] == 2

    def test_custom_default_threat_level(self, custom_exporter):
        event = custom_exporter.export_triplets([_make_triplet()])
        assert event["Event"]["threat_level_id"] == 3

    def test_confidence_tag_added(self, exporter):
        event = exporter.export_triplets([_make_triplet(confidence=0.9)])
        tag_names = [t["name"] for t in event["Event"]["Tag"]]
        assert any("high" in t for t in tag_names)

    def test_attack_mapper_failure_graceful(self, exporter):
        """ATT&CK mapper failures should not break export."""
        with patch.object(exporter, "_get_attack_mapper", side_effect=Exception("no data")):
            event = exporter.export_triplets([_make_triplet()])
        assert "Event" in event

    def test_empty_triplets(self, exporter):
        event = exporter.export_triplets([])
        assert event["Event"]["Attribute"] == []


class TestExportAttackPath:
    def _make_path(self):
        t1 = _make_triplet(subject="APT28", predicate="targets", obj="Org1", triplet_id="t1")
        t2 = _make_triplet(subject="Org1", predicate="uses", obj="Tool1", triplet_id="t2")
        step1 = AttackPathStep(triplet=t1, timestamp="2025-06-01T00:00:00Z", step_index=0, anomaly_score=0.8)
        step2 = AttackPathStep(triplet=t2, timestamp="2025-06-02T00:00:00Z", step_index=1, anomaly_score=0.3)
        return AttackPath(
            seed_entity="APT28", steps=[step1, step2],
            entities_involved={"APT28", "Org1", "Tool1"},
            time_span=("2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z"),
            total_anomaly=0.65,
        )

    def test_attack_path_event_structure(self, exporter):
        event = exporter.export_attack_path(self._make_path())
        assert "Event" in event

    def test_attack_path_seed_entity(self, exporter):
        event = exporter.export_attack_path(self._make_path())
        assert event["Event"]["x_kgcp_seed_entity"] == "APT28"

    def test_attack_path_total_anomaly(self, exporter):
        event = exporter.export_attack_path(self._make_path())
        assert event["Event"]["x_kgcp_total_anomaly"] == 0.65

    def test_attack_path_time_span(self, exporter):
        event = exporter.export_attack_path(self._make_path())
        assert event["Event"]["x_kgcp_time_start"] == "2025-06-01T00:00:00Z"
        assert event["Event"]["x_kgcp_time_end"] == "2025-06-02T00:00:00Z"

    def test_attack_path_threat_level(self, exporter):
        event = exporter.export_attack_path(self._make_path())
        assert event["Event"]["threat_level_id"] == 1  # max anomaly 0.8 -> high


class TestConfig:
    def test_defaults(self, exporter):
        assert exporter.url == ""
        assert exporter.api_key == ""
        assert exporter.verify_ssl is True
        assert exporter.default_distribution == 0

    def test_custom_config(self, custom_exporter):
        assert custom_exporter.url == "https://misp.example.com"
        assert custom_exporter.api_key == "test-key"
        assert custom_exporter.publish_on_push is True


class TestToFile:
    def test_writes_json(self, exporter):
        event = exporter.export_triplets([_make_triplet()])
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "subdir" / "misp_event.json"
            exporter.to_file(event, out)
            assert out.exists()
            loaded = json.loads(out.read_text())
            assert "Event" in loaded


class TestPush:
    @pytest.mark.skipif(
        not _has_pymisp(), reason="pymisp not installed"
    )
    def test_push_missing_url_raises(self, exporter):
        with pytest.raises(ValueError, match="URL"):
            exporter.push({"Event": {}})

    @pytest.mark.skipif(
        not _has_pymisp(), reason="pymisp not installed"
    )
    def test_push_missing_api_key_raises(self):
        exp = MISPExporter({"cti": {"misp": {"url": "https://misp.example.com"}}})
        with pytest.raises(ValueError, match="API key"):
            exp.push({"Event": {}})

    def test_push_without_pymisp_raises_import_error(self):
        """When pymisp is not installed, push raises ImportError."""
        if _has_pymisp():
            pytest.skip("pymisp is installed")
        exporter = MISPExporter({})
        with pytest.raises(ImportError, match="PyMISP"):
            exporter.push({"Event": {}})


class TestRegistration:
    def test_misp_registered(self):
        from kgcp.export import EXPORTER_REGISTRY
        assert "misp" in EXPORTER_REGISTRY
        assert EXPORTER_REGISTRY["misp"] is MISPExporter
