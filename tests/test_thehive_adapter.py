"""Tests for TheHive alert export adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from kgcp.export.thehive_adapter import (
    TheHiveExporter,
    _anomaly_to_severity,
    _build_description,
    _compute_time_span,
    _make_source_ref,
)
from kgcp.models import AttackPath, AttackPathStep, Triplet


def _has_thehive4py():
    try:
        import thehive4py  # noqa: F401
        return True
    except ImportError:
        return False


@pytest.fixture
def exporter():
    return TheHiveExporter({})


@pytest.fixture
def custom_exporter():
    return TheHiveExporter({
        "cti": {
            "thehive": {
                "url": "https://thehive.example.com",
                "api_key": "test-key",
                "verify_ssl": False,
                "default_severity": 3,
                "default_tlp": 1,
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


class TestAnomalyToSeverity:
    def test_critical(self):
        assert _anomaly_to_severity(0.9) == 4

    def test_high(self):
        assert _anomaly_to_severity(0.7) == 3

    def test_medium(self):
        assert _anomaly_to_severity(0.4) == 2

    def test_low(self):
        assert _anomaly_to_severity(0.1) == 1

    def test_boundary_critical(self):
        assert _anomaly_to_severity(0.8) == 4

    def test_boundary_high(self):
        assert _anomaly_to_severity(0.6) == 3

    def test_boundary_medium(self):
        assert _anomaly_to_severity(0.3) == 2

    def test_zero(self):
        assert _anomaly_to_severity(0.0) == 1


class TestMakeSourceRef:
    def test_deterministic(self):
        ref1 = _make_source_ref("APT28", "2025-06-01")
        ref2 = _make_source_ref("APT28", "2025-06-01")
        assert ref1 == ref2

    def test_different_inputs(self):
        ref1 = _make_source_ref("APT28", "2025-06-01")
        ref2 = _make_source_ref("APT29", "2025-06-01")
        assert ref1 != ref2

    def test_length(self):
        ref = _make_source_ref("APT28", "2025-06-01")
        assert len(ref) == 16

    def test_hex_string(self):
        ref = _make_source_ref("APT28", "2025-06-01")
        int(ref, 16)  # should not raise


class TestComputeTimeSpan:
    def test_with_times(self):
        triplets = [
            _make_triplet(first_seen="2025-06-01T00:00:00Z", last_seen="2025-06-10T00:00:00Z"),
            _make_triplet(first_seen="2025-05-15T00:00:00Z", last_seen="2025-06-15T00:00:00Z", triplet_id="t2"),
        ]
        start, end = _compute_time_span(triplets)
        assert start == "2025-05-15T00:00:00Z"
        assert end == "2025-06-15T00:00:00Z"

    def test_empty_list(self):
        start, end = _compute_time_span([])
        assert start == ""
        assert end == ""

    def test_no_timestamps(self):
        t = _make_triplet(first_seen="", last_seen="")
        start, end = _compute_time_span([t])
        assert start == ""
        assert end == ""


class TestBuildDescription:
    def test_with_triplets(self):
        triplets = [_make_triplet()]
        entity_types = {"APT28": "threat_actor", "ACME Corp": "organization"}
        desc = _build_description(triplets, entity_types)
        assert "APT28" in desc
        assert "ACME Corp" in desc

    def test_empty_triplets(self):
        desc = _build_description([], {})
        assert "No triplets" in desc

    def test_time_span_single_day(self):
        triplets = [_make_triplet()]
        entity_types = {"APT28": "threat_actor"}
        desc = _build_description(triplets, entity_types, ("2025-06-01T00:00:00Z", "2025-06-01T23:59:59Z"))
        assert "2025-06-01" in desc

    def test_time_span_range(self):
        triplets = [_make_triplet()]
        entity_types = {"APT28": "threat_actor"}
        desc = _build_description(triplets, entity_types, ("2025-06-01T00:00:00Z", "2025-06-15T00:00:00Z"))
        assert "2025-06-01" in desc
        assert "2025-06-15" in desc

    def test_many_triplets_truncated(self):
        triplets = [
            _make_triplet(subject=f"E{i}", obj=f"T{i}", triplet_id=f"t{i}")
            for i in range(15)
        ]
        entity_types = {f"E{i}": "unknown" for i in range(15)}
        desc = _build_description(triplets, entity_types)
        assert "15 total" in desc


class TestExportTriplets:
    def test_alert_structure(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        assert alert["type"] == "kgcp-alert"
        assert alert["source"] == "KGCP"
        assert "title" in alert
        assert "description" in alert
        assert "severity" in alert
        assert "observables" in alert

    def test_title_auto_generated(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        assert "APT28" in alert["title"]

    def test_custom_title(self, exporter):
        alert = exporter.export_triplets([_make_triplet()], title="Custom Alert")
        assert alert["title"] == "Custom Alert"

    def test_observables_created(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        obs_data = [o["data"] for o in alert["observables"]]
        assert "APT28" in obs_data
        assert "ACME Corp" in obs_data

    def test_observable_data_type(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        for obs in alert["observables"]:
            assert obs["dataType"] == "other"

    def test_observable_tags(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        apt_obs = [o for o in alert["observables"] if o["data"] == "APT28"][0]
        assert any("threat-actor" in t for t in apt_obs["tags"])

    def test_severity_from_anomaly(self, exporter):
        t = _make_triplet(metadata={"anomaly_score": 0.9})
        alert = exporter.export_triplets([t])
        assert alert["severity"] == 4  # critical

    def test_default_severity_when_no_anomaly(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        assert alert["severity"] == 2  # default

    def test_custom_severity_override(self, exporter):
        alert = exporter.export_triplets([_make_triplet()], severity=1)
        assert alert["severity"] == 1

    def test_default_tlp(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        assert alert["tlp"] == 2

    def test_custom_tlp(self, custom_exporter):
        alert = custom_exporter.export_triplets([_make_triplet()])
        assert alert["tlp"] == 1

    def test_tags_from_entity_types(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        # Should have entity type tags (threat_actor, organization from defaults)
        assert isinstance(alert["tags"], list)

    def test_empty_triplets(self, exporter):
        alert = exporter.export_triplets([])
        assert alert["title"] == "KGCP Alert (empty)"
        assert alert["observables"] == []

    def test_title_with_time_span(self, exporter):
        t = _make_triplet(first_seen="2025-06-01T00:00:00Z", last_seen="2025-06-15T00:00:00Z")
        alert = exporter.export_triplets([t])
        assert "2025-06-01" in alert["title"]


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

    def test_attack_path_alert_structure(self, exporter):
        alert = exporter.export_attack_path(self._make_path())
        assert alert["type"] == "kgcp-alert"
        assert alert["source"] == "KGCP"

    def test_attack_path_title(self, exporter):
        alert = exporter.export_attack_path(self._make_path())
        assert "Attack Path" in alert["title"]
        assert "APT28" in alert["title"]

    def test_attack_path_severity(self, exporter):
        alert = exporter.export_attack_path(self._make_path())
        assert alert["severity"] == 4  # max anomaly 0.8 -> critical

    def test_attack_path_tags(self, exporter):
        alert = exporter.export_attack_path(self._make_path())
        assert "attack-path" in alert["tags"]

    def test_attack_path_description(self, exporter):
        alert = exporter.export_attack_path(self._make_path())
        assert "seed entity" in alert["description"].lower() or "APT28" in alert["description"]

    def test_attack_path_observables(self, exporter):
        alert = exporter.export_attack_path(self._make_path())
        obs_data = [o["data"] for o in alert["observables"]]
        assert "APT28" in obs_data


class TestConfig:
    def test_defaults(self, exporter):
        assert exporter.url == ""
        assert exporter.api_key == ""
        assert exporter.verify_ssl is True
        assert exporter.default_severity == 2
        assert exporter.default_tlp == 2

    def test_custom_config(self, custom_exporter):
        assert custom_exporter.url == "https://thehive.example.com"
        assert custom_exporter.api_key == "test-key"
        assert custom_exporter.verify_ssl is False
        assert custom_exporter.default_severity == 3
        assert custom_exporter.default_tlp == 1


class TestToFile:
    def test_writes_json(self, exporter):
        alert = exporter.export_triplets([_make_triplet()])
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "subdir" / "thehive_alert.json"
            exporter.to_file(alert, out)
            assert out.exists()
            loaded = json.loads(out.read_text())
            assert loaded["type"] == "kgcp-alert"


class TestPush:
    @pytest.mark.skipif(
        not _has_thehive4py(), reason="thehive4py not installed"
    )
    def test_push_missing_url_raises(self, exporter):
        with pytest.raises(ValueError, match="URL"):
            exporter.push({"title": "test"})

    @pytest.mark.skipif(
        not _has_thehive4py(), reason="thehive4py not installed"
    )
    def test_push_missing_api_key_raises(self):
        exp = TheHiveExporter({"cti": {"thehive": {"url": "https://thehive.example.com"}}})
        with pytest.raises(ValueError, match="API key"):
            exp.push({"title": "test"})

    def test_push_without_thehive4py_raises_import_error(self):
        """When thehive4py is not installed, push raises ImportError."""
        if _has_thehive4py():
            pytest.skip("thehive4py is installed")
        exporter = TheHiveExporter({})
        with pytest.raises(ImportError, match="thehive4py"):
            exporter.push({"title": "test"})


class TestRegistration:
    def test_thehive_registered(self):
        from kgcp.export import EXPORTER_REGISTRY
        assert "thehive" in EXPORTER_REGISTRY
        assert EXPORTER_REGISTRY["thehive"] is TheHiveExporter
