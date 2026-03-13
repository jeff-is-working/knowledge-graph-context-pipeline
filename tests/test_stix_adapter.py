"""Tests for the STIX 2.1 bundle export adapter."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

import pytest

from kgcp.export.stix_adapter import STIXExporter, _deterministic_id, _parse_timestamp
from kgcp.models import AttackPath, AttackPathStep, Triplet


@pytest.fixture
def exporter():
    return STIXExporter({})


@pytest.fixture
def custom_exporter():
    return STIXExporter({
        "cti": {"stix": {"identity_name": "TestProducer", "default_confidence": 75}}
    })


def _make_triplet(
    subject="APT28",
    predicate="targets",
    obj="ACME Corp",
    confidence=0.85,
    triplet_id="t-001",
    observation_count=1,
    first_seen="2025-06-01T00:00:00Z",
    last_seen="2025-06-15T00:00:00Z",
):
    return Triplet(
        subject=subject, predicate=predicate, object=obj, doc_id="doc-1",
        confidence=confidence, triplet_id=triplet_id,
        observation_count=observation_count,
        first_seen=first_seen, last_seen=last_seen,
    )


class TestBundleStructure:
    def test_bundle_has_type_bundle(self, exporter):
        bundle = exporter.export_triplets([_make_triplet()])
        assert bundle["type"] == "bundle"

    def test_bundle_id_starts_with_bundle(self, exporter):
        bundle = exporter.export_triplets([_make_triplet()])
        assert bundle["id"].startswith("bundle--")

    def test_bundle_has_objects_list(self, exporter):
        bundle = exporter.export_triplets([_make_triplet()])
        assert isinstance(bundle["objects"], list)
        assert len(bundle["objects"]) > 0


class TestProducerIdentity:
    def test_producer_identity_present(self, exporter):
        bundle = exporter.export_triplets([_make_triplet()])
        identities = [
            o for o in bundle["objects"]
            if o["type"] == "identity" and o.get("identity_class") == "system"
        ]
        assert len(identities) == 1
        assert identities[0]["name"] == "KGCP"

    def test_custom_producer_name(self, custom_exporter):
        bundle = custom_exporter.export_triplets([_make_triplet()])
        system_ids = [
            o for o in bundle["objects"]
            if o["type"] == "identity" and o.get("identity_class") == "system"
        ]
        assert system_ids[0]["name"] == "TestProducer"


class TestSDOGeneration:
    @pytest.mark.parametrize(
        "entity_type, expected_sdo_type",
        [
            ("threat_actor", "threat-actor"),
            ("malware", "malware"),
            ("organization", "identity"),
            ("location", "location"),
            ("technique", "attack-pattern"),
            ("tool", "tool"),
            ("vulnerability", "vulnerability"),
            ("unknown", "identity"),
        ],
    )
    def test_sdo_type_for_entity(self, exporter, entity_type, expected_sdo_type):
        sdo = exporter._make_sdo("TestEntity", entity_type)
        assert sdo["type"] == expected_sdo_type
        assert sdo["name"] == "TestEntity"
        assert sdo["spec_version"] == "2.1"
        assert sdo["id"].startswith(f"{expected_sdo_type}--")

    def test_identity_class_set_for_organization(self, exporter):
        sdo = exporter._make_sdo("ACME Corp", "organization")
        assert sdo["identity_class"] == "organization"

    def test_no_identity_class_for_malware(self, exporter):
        sdo = exporter._make_sdo("DarkComet", "malware")
        assert "identity_class" not in sdo

    def test_malware_has_is_family(self, exporter):
        sdo = exporter._make_sdo("DarkComet", "malware")
        assert sdo["is_family"] is True

    def test_created_by_ref_set(self, exporter):
        sdo = exporter._make_sdo("TestEntity", "threat_actor")
        assert sdo["created_by_ref"] == exporter._producer_id


class TestSROGeneration:
    def _build_entity_sdos(self, exporter):
        return {
            "APT28": exporter._make_sdo("APT28", "threat_actor"),
            "ACME Corp": exporter._make_sdo("ACME Corp", "organization"),
        }

    def test_sro_source_and_target(self, exporter):
        triplet = _make_triplet(predicate="targets")
        sdos = self._build_entity_sdos(exporter)
        sro = exporter._make_sro(triplet, sdos)
        assert sro["source_ref"] == sdos["APT28"]["id"]
        assert sro["target_ref"] == sdos["ACME Corp"]["id"]
        assert sro["relationship_type"] == "targets"

    def test_reversed_predicate_swaps_source_target(self, exporter):
        triplet = _make_triplet(subject="APT28", predicate="develops", obj="ACME Corp")
        sdos = self._build_entity_sdos(exporter)
        sro = exporter._make_sro(triplet, sdos)
        assert sro["relationship_type"] == "authored-by"
        assert sro["source_ref"] == sdos["ACME Corp"]["id"]
        assert sro["target_ref"] == sdos["APT28"]["id"]

    def test_confidence_maps_to_integer_0_100(self, exporter):
        triplet = _make_triplet(confidence=0.85)
        sdos = self._build_entity_sdos(exporter)
        sro = exporter._make_sro(triplet, sdos)
        assert sro["confidence"] == 85
        assert isinstance(sro["confidence"], int)

    def test_confidence_boundaries(self, exporter):
        sdos = self._build_entity_sdos(exporter)
        sro_zero = exporter._make_sro(_make_triplet(confidence=0.0), sdos)
        sro_one = exporter._make_sro(_make_triplet(confidence=1.0), sdos)
        assert sro_zero["confidence"] == 0
        assert sro_one["confidence"] == 100

    def test_custom_properties_preserved(self, exporter):
        triplet = _make_triplet(triplet_id="my-custom-id", predicate="uses")
        sdos = self._build_entity_sdos(exporter)
        sro = exporter._make_sro(triplet, sdos)
        assert sro["x_kgcp_triplet_id"] == "my-custom-id"
        assert sro["x_kgcp_predicate"] == "uses"

    def test_observation_count_included_when_gt_1(self, exporter):
        triplet = _make_triplet(observation_count=5)
        sdos = self._build_entity_sdos(exporter)
        sro = exporter._make_sro(triplet, sdos)
        assert sro["x_kgcp_observation_count"] == 5

    def test_observation_count_excluded_when_1(self, exporter):
        triplet = _make_triplet(observation_count=1)
        sdos = self._build_entity_sdos(exporter)
        sro = exporter._make_sro(triplet, sdos)
        assert "x_kgcp_observation_count" not in sro

    def test_sro_returns_none_for_missing_entity(self, exporter):
        triplet = _make_triplet(subject="NoSuchEntity")
        sdos = self._build_entity_sdos(exporter)
        assert exporter._make_sro(triplet, sdos) is None


class TestDeterministicIDs:
    def test_same_input_same_id(self):
        id1 = _deterministic_id("threat-actor", "APT28", "threat_actor")
        id2 = _deterministic_id("threat-actor", "APT28", "threat_actor")
        assert id1 == id2

    def test_different_input_different_id(self):
        id1 = _deterministic_id("threat-actor", "APT28", "threat_actor")
        id2 = _deterministic_id("threat-actor", "APT29", "threat_actor")
        assert id1 != id2

    def test_id_has_correct_prefix(self):
        assert _deterministic_id("malware", "DarkComet").startswith("malware--")

    def test_sdo_ids_stable_across_exports(self, exporter):
        sdo1 = exporter._make_sdo("APT28", "threat_actor")
        sdo2 = exporter._make_sdo("APT28", "threat_actor")
        assert sdo1["id"] == sdo2["id"]


class TestTimestampParsing:
    def test_valid_iso_timestamp(self):
        assert _parse_timestamp("2025-06-01T12:00:00+00:00") == "2025-06-01T12:00:00.000Z"

    def test_z_suffix_timestamp(self):
        assert _parse_timestamp("2025-06-01T12:00:00Z") == "2025-06-01T12:00:00.000Z"

    def test_empty_string_returns_now(self):
        result = _parse_timestamp("")
        assert result.endswith(".000Z")

    def test_invalid_string_returns_now(self):
        result = _parse_timestamp("not-a-date")
        assert result.endswith(".000Z")


class TestExportAttackPath:
    def test_grouping_object_present(self, exporter):
        t1 = _make_triplet(subject="APT28", predicate="targets", obj="ACME Corp", triplet_id="t1")
        t2 = _make_triplet(subject="ACME Corp", predicate="uses", obj="Firewall", triplet_id="t2")
        step1 = AttackPathStep(triplet=t1, timestamp="2025-06-01T00:00:00Z", step_index=0)
        step2 = AttackPathStep(triplet=t2, timestamp="2025-06-02T00:00:00Z", step_index=1)
        path = AttackPath(
            seed_entity="APT28", steps=[step1, step2],
            entities_involved={"APT28", "ACME Corp", "Firewall"},
            time_span=("2025-06-01T00:00:00Z", "2025-06-02T00:00:00Z"),
            total_anomaly=0.7,
        )
        bundle = exporter.export_attack_path(path)
        groupings = [o for o in bundle["objects"] if o["type"] == "grouping"]
        assert len(groupings) == 1
        g = groupings[0]
        assert g["context"] == "suspicious-activity"
        assert g["x_kgcp_seed_entity"] == "APT28"
        assert g["x_kgcp_total_anomaly"] == 0.7
        assert g["id"].startswith("grouping--")

    def test_empty_path_no_grouping(self, exporter):
        path = AttackPath(seed_entity="APT28", steps=[], entities_involved=set(),
                          time_span=("", ""), total_anomaly=0.0)
        bundle = exporter.export_attack_path(path)
        groupings = [o for o in bundle["objects"] if o["type"] == "grouping"]
        assert len(groupings) == 0


class TestFileOutput:
    def test_to_file_creates_json(self, exporter):
        data = {"type": "bundle", "id": "bundle--test", "objects": []}
        with tempfile.TemporaryDirectory() as tmpdir:
            out = Path(tmpdir) / "subdir" / "output.json"
            exporter.to_file(data, out)
            assert out.exists()
            loaded = json.loads(out.read_text())
            assert loaded["type"] == "bundle"


class TestExporterRegistration:
    def test_stix_registered(self):
        from kgcp.export import EXPORTER_REGISTRY
        assert "stix" in EXPORTER_REGISTRY
        assert EXPORTER_REGISTRY["stix"] is STIXExporter
