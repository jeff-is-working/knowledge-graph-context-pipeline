"""Tests for KGCP entity type and predicate mapping to STIX 2.1 types."""

import pytest

from kgcp.export.entity_type_map import (
    DEFAULT_RELATIONSHIP,
    ENTITY_TO_STIX_SDO,
    entity_identity_class,
    stix_relationship_for_predicate,
    stix_type_for_entity,
)


class TestEntityToStixSDO:
    @pytest.mark.parametrize(
        "entity_type, expected_sdo",
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
    def test_entity_maps_to_correct_sdo(self, entity_type, expected_sdo):
        assert stix_type_for_entity(entity_type) == expected_sdo

    def test_all_eight_types_present(self):
        assert len(ENTITY_TO_STIX_SDO) == 8

    def test_unknown_entity_falls_back_to_identity(self):
        assert stix_type_for_entity("nonexistent_type") == "identity"
        assert stix_type_for_entity("") == "identity"


class TestPredicateMapping:
    @pytest.mark.parametrize(
        "predicate, expected_rel, expected_reversed",
        [
            ("targets", "targets", False),
            ("exploits", "exploits", False),
            ("uses", "uses", False),
            ("deploys", "uses", False),
            ("delivers", "delivers", False),
            ("compromises", "compromises", False),
            ("breaches", "compromises", False),
            ("connects to", "communicates-with", False),
            ("exfiltrates", "exfiltrates-to", False),
            ("attacks", "targets", False),
            ("employs", "uses", False),
        ],
    )
    def test_non_reversed_predicates(self, predicate, expected_rel, expected_reversed):
        rel_type, is_reversed = stix_relationship_for_predicate(predicate)
        assert rel_type == expected_rel
        assert is_reversed == expected_reversed

    @pytest.mark.parametrize("predicate", ["develops", "creates", "authors", "produces"])
    def test_reversed_predicates(self, predicate):
        rel_type, is_reversed = stix_relationship_for_predicate(predicate)
        assert rel_type == "authored-by"
        assert is_reversed is True

    def test_fallback_for_unknown_predicate(self):
        rel_type, is_reversed = stix_relationship_for_predicate("some_unknown_verb")
        assert (rel_type, is_reversed) == DEFAULT_RELATIONSHIP

    def test_predicate_lookup_is_case_insensitive(self):
        rel_type, _ = stix_relationship_for_predicate("TARGETS")
        assert rel_type == "targets"

    def test_predicate_lookup_strips_whitespace(self):
        rel_type, _ = stix_relationship_for_predicate("  targets  ")
        assert rel_type == "targets"


class TestIdentityClass:
    def test_organization_returns_organization(self):
        assert entity_identity_class("organization") == "organization"

    def test_unknown_returns_unknown(self):
        assert entity_identity_class("unknown") == "unknown"

    @pytest.mark.parametrize(
        "entity_type",
        ["threat_actor", "malware", "location", "technique", "tool", "vulnerability"],
    )
    def test_non_identity_types_return_none(self, entity_type):
        assert entity_identity_class(entity_type) is None

    def test_unrecognized_type_returns_none(self):
        assert entity_identity_class("completely_fake") is None
