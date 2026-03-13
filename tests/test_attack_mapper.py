"""Tests for MITRE ATT&CK technique mapper using an embedded mock dataset."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from kgcp.export.attack_mapper import AttackMapper, AttackMatch
from kgcp.models import Triplet

MOCK_ATTACK_BUNDLE = {
    "type": "bundle",
    "id": "bundle--mock",
    "objects": [
        {
            "type": "attack-pattern",
            "id": "attack-pattern--001",
            "name": "Phishing",
            "description": "Adversaries may send phishing messages to gain access to victim systems.",
            "external_references": [
                {"source_name": "mitre-attack", "external_id": "T1566"}
            ],
            "kill_chain_phases": [
                {"kill_chain_name": "mitre-attack", "phase_name": "initial-access"}
            ],
        },
        {
            "type": "attack-pattern",
            "id": "attack-pattern--002",
            "name": "Command and Scripting Interpreter",
            "description": "Adversaries may abuse command and script interpreters to execute commands.",
            "external_references": [
                {"source_name": "mitre-attack", "external_id": "T1059"}
            ],
            "kill_chain_phases": [
                {"kill_chain_name": "mitre-attack", "phase_name": "execution"}
            ],
        },
        {
            "type": "attack-pattern",
            "id": "attack-pattern--003",
            "name": "Data Exfiltration Over Web Service",
            "description": "Adversaries may exfiltrate data over web service channels to avoid detection.",
            "external_references": [
                {"source_name": "mitre-attack", "external_id": "T1567"}
            ],
            "kill_chain_phases": [
                {"kill_chain_name": "mitre-attack", "phase_name": "exfiltration"}
            ],
        },
        {
            "type": "attack-pattern",
            "id": "attack-pattern--004",
            "name": "Credential Dumping",
            "description": "Adversaries may attempt to dump credentials from operating system memory.",
            "external_references": [
                {"source_name": "mitre-attack", "external_id": "T1003"}
            ],
            "kill_chain_phases": [
                {"kill_chain_name": "mitre-attack", "phase_name": "credential-access"}
            ],
        },
        {
            "type": "attack-pattern",
            "id": "attack-pattern--005",
            "name": "Lateral Movement via Remote Services",
            "description": "Adversaries may use remote services to move laterally within a network.",
            "external_references": [
                {"source_name": "mitre-attack", "external_id": "T1021"}
            ],
            "kill_chain_phases": [
                {"kill_chain_name": "mitre-attack", "phase_name": "lateral-movement"}
            ],
        },
        {
            "type": "attack-pattern",
            "id": "attack-pattern--999",
            "name": "Old Revoked Technique",
            "description": "This technique has been revoked.",
            "revoked": True,
            "external_references": [
                {"source_name": "mitre-attack", "external_id": "T9999"}
            ],
        },
        {
            "type": "malware",
            "id": "malware--001",
            "name": "SomeMalware",
        },
    ],
}


@pytest.fixture
def mock_attack_cache():
    with tempfile.TemporaryDirectory() as tmpdir:
        cache_path = Path(tmpdir) / "enterprise-attack.json"
        cache_path.write_text(json.dumps(MOCK_ATTACK_BUNDLE))
        yield cache_path


@pytest.fixture
def mapper(mock_attack_cache):
    m = AttackMapper(cache_path=mock_attack_cache)
    m.ensure_data()
    return m


def _make_triplet(subject="APT28", predicate="targets", obj="ACME Corp", triplet_id="t-001"):
    return Triplet(
        subject=subject, predicate=predicate, object=obj,
        doc_id="doc-1", triplet_id=triplet_id,
    )


class TestDataLoading:
    def test_loads_only_attack_patterns(self, mapper):
        assert len(mapper._techniques) == 5

    def test_revoked_techniques_excluded(self, mapper):
        ids = [t["id"] for t in mapper._techniques]
        assert "T9999" not in ids

    def test_keyword_index_populated(self, mapper):
        assert len(mapper._keyword_index) > 0

    def test_loaded_flag_set(self, mapper):
        assert mapper._loaded is True

    def test_ensure_data_idempotent(self, mapper):
        count_before = len(mapper._techniques)
        mapper.ensure_data()
        assert len(mapper._techniques) == count_before


class TestKeywordExtraction:
    def test_extracts_words_from_name(self):
        keywords = AttackMapper._extract_keywords("Phishing", "")
        assert "phishing" in keywords

    def test_extracts_words_from_description(self):
        keywords = AttackMapper._extract_keywords(
            "Test", "Adversaries may send phishing messages to gain access"
        )
        assert "phishing" in keywords
        assert "messages" in keywords

    def test_stopwords_removed(self):
        keywords = AttackMapper._extract_keywords(
            "Test", "The adversaries have been using this technique with their tools"
        )
        for stopword in ["have", "been", "this", "with", "their"]:
            assert stopword not in keywords

    def test_short_words_excluded_from_description(self):
        keywords = AttackMapper._extract_keywords("XY", "an xy bad run")
        assert "bad" not in keywords
        assert "run" not in keywords

    def test_only_first_sentence_of_description(self):
        keywords = AttackMapper._extract_keywords(
            "Test", "First sentence here. Second sentence with uniqueword content."
        )
        assert "uniqueword" not in keywords


class TestMatchTriplet:
    def test_returns_list_of_attack_match(self, mapper):
        results = mapper.match_triplet("APT28", "sends phishing", "email")
        assert isinstance(results, list)
        for r in results:
            assert isinstance(r, AttackMatch)

    def test_direct_name_match_scores_highest(self, mapper):
        results = mapper.match_triplet("attacker", "uses phishing", "target")
        if results:
            assert results[0].technique_id == "T1566"
            assert results[0].match_confidence >= 0.6

    def test_keyword_overlap_produces_match(self, mapper):
        results = mapper.match_triplet("actor", "exfiltrate", "data over web service")
        matched_ids = [r.technique_id for r in results]
        assert "T1567" in matched_ids

    def test_entity_type_technique_bonus(self, mapper):
        results_no_bonus = mapper.match_triplet(
            "actor", "credential dumping", "target", entity_type="",
        )
        results_with_bonus = mapper.match_triplet(
            "actor", "credential dumping", "target", entity_type="technique",
        )
        if results_no_bonus and results_with_bonus:
            id_to_conf_no = {r.technique_id: r.match_confidence for r in results_no_bonus}
            id_to_conf_yes = {r.technique_id: r.match_confidence for r in results_with_bonus}
            for tid in id_to_conf_no:
                if tid in id_to_conf_yes:
                    assert id_to_conf_yes[tid] >= id_to_conf_no[tid]

    def test_max_results_limits_output(self, mapper):
        results = mapper.match_triplet(
            "phishing credential lateral exfiltrate command",
            "execute script interpreter phishing",
            "remote service credential dump",
            max_results=2,
        )
        assert len(results) <= 2

    def test_results_sorted_by_confidence_descending(self, mapper):
        results = mapper.match_triplet("actor", "phishing exfiltrate credential", "data service")
        confidences = [r.match_confidence for r in results]
        assert confidences == sorted(confidences, reverse=True)

    def test_no_match_for_unrelated_input(self, mapper):
        results = mapper.match_triplet("xyz_entity", "zzzz_verb", "qqqq_object")
        assert len(results) == 0

    def test_match_confidence_capped_at_1(self, mapper):
        results = mapper.match_triplet("phishing", "phishing", "phishing", entity_type="technique")
        for r in results:
            assert r.match_confidence <= 1.0

    def test_tactic_field_populated(self, mapper):
        results = mapper.match_triplet("attacker", "uses phishing", "target")
        phishing_matches = [r for r in results if r.technique_id == "T1566"]
        if phishing_matches:
            assert phishing_matches[0].tactic == "initial-access"


class TestMatchTriplets:
    def test_processes_multiple_triplets(self, mapper):
        triplets = [
            _make_triplet(subject="APT28", predicate="sends phishing", obj="target", triplet_id="t1"),
            _make_triplet(subject="actor", predicate="exfiltrate data", obj="web service", triplet_id="t2"),
        ]
        with patch("kgcp.extraction.confidence.infer_entity_type", return_value="unknown"):
            results = mapper.match_triplets(triplets, max_results_per=3)
        assert isinstance(results, dict)
        for tid, matches in results.items():
            assert len(matches) <= 3

    def test_returns_dict_keyed_by_triplet_id(self, mapper):
        triplets = [
            _make_triplet(subject="actor", predicate="sends phishing", obj="victim", triplet_id="custom-id-1"),
        ]
        with patch("kgcp.extraction.confidence.infer_entity_type", return_value="unknown"):
            results = mapper.match_triplets(triplets)
        if results:
            assert "custom-id-1" in results

    def test_empty_triplets_returns_empty_dict(self, mapper):
        with patch("kgcp.extraction.confidence.infer_entity_type", return_value="unknown"):
            results = mapper.match_triplets([])
        assert results == {}


class TestAttackMatchDataclass:
    def test_construction(self):
        m = AttackMatch(
            technique_id="T1566", technique_name="Phishing",
            match_confidence=0.85, matched_on="name:Phishing", tactic="initial-access",
        )
        assert m.technique_id == "T1566"
        assert m.match_confidence == 0.85

    def test_default_tactic_empty(self):
        m = AttackMatch(
            technique_id="T1234", technique_name="Test",
            match_confidence=0.5, matched_on="test",
        )
        assert m.tactic == ""
