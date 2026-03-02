"""Tests for cross-algebra unified scoring."""

from datetime import datetime, timedelta, timezone

import pytest

from kgcp.models import ScoredTriplet, Triplet
from kgcp.retrieval.unified_scorer import (
    compute_centrality_for_triplets,
    compute_recency,
    compute_unified_scores,
)


def _make_triplet(
    subject="apt28",
    predicate="targets",
    obj="energy sector",
    confidence=0.8,
    first_seen=None,
    last_seen=None,
    metadata=None,
    triplet_id=None,
):
    """Helper to create test triplets with controlled timestamps."""
    now = datetime.now(timezone.utc)
    t = Triplet(
        subject=subject,
        predicate=predicate,
        object=obj,
        doc_id="test-doc",
        confidence=confidence,
        first_seen=first_seen or now.isoformat(),
        last_seen=last_seen or now.isoformat(),
        metadata=metadata or {},
    )
    if triplet_id:
        t.triplet_id = triplet_id
    return t


# --- compute_recency tests ---


class TestComputeRecency:
    def test_just_seen_is_one(self):
        """A triplet last seen right now should have recency 1.0."""
        now = datetime.now(timezone.utc)
        t = _make_triplet(last_seen=now.isoformat())
        score = compute_recency(t, window_days=90, reference_time=now)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_half_window_is_half(self):
        """A triplet last seen 45 days ago in a 90-day window should be ~0.5."""
        now = datetime.now(timezone.utc)
        past = (now - timedelta(days=45)).isoformat()
        t = _make_triplet(last_seen=past)
        score = compute_recency(t, window_days=90, reference_time=now)
        assert score == pytest.approx(0.5, abs=0.01)

    def test_full_window_is_zero(self):
        """A triplet last seen exactly window_days ago should be 0.0."""
        now = datetime.now(timezone.utc)
        past = (now - timedelta(days=90)).isoformat()
        t = _make_triplet(last_seen=past)
        score = compute_recency(t, window_days=90, reference_time=now)
        assert score == pytest.approx(0.0, abs=0.01)

    def test_beyond_window_is_zero(self):
        """A triplet older than the window should clamp to 0.0."""
        now = datetime.now(timezone.utc)
        past = (now - timedelta(days=180)).isoformat()
        t = _make_triplet(last_seen=past)
        score = compute_recency(t, window_days=90, reference_time=now)
        assert score == 0.0

    def test_no_temporal_data(self):
        """A triplet with no timestamps should return 0.0."""
        t = _make_triplet()
        t.last_seen = ""
        t.first_seen = ""
        score = compute_recency(t, window_days=90)
        assert score == 0.0

    def test_fallback_to_first_seen(self):
        """When last_seen is empty, should fall back to first_seen."""
        now = datetime.now(timezone.utc)
        t = _make_triplet(first_seen=now.isoformat())
        t.last_seen = ""
        score = compute_recency(t, window_days=90, reference_time=now)
        assert score == pytest.approx(1.0, abs=0.01)

    def test_future_date_is_one(self):
        """A triplet with a future timestamp should return 1.0."""
        now = datetime.now(timezone.utc)
        future = (now + timedelta(days=10)).isoformat()
        t = _make_triplet(last_seen=future)
        score = compute_recency(t, window_days=90, reference_time=now)
        assert score == 1.0

    def test_quarter_window(self):
        """A triplet 22.5 days into a 90-day window should be ~0.75."""
        now = datetime.now(timezone.utc)
        past = (now - timedelta(days=22.5)).isoformat()
        t = _make_triplet(last_seen=past)
        score = compute_recency(t, window_days=90, reference_time=now)
        assert score == pytest.approx(0.75, abs=0.01)


# --- compute_centrality_for_triplets tests ---


class TestComputeCentralityForTriplets:
    def test_basic_centrality(self):
        """Should compute degree centrality for entities in triplets."""
        triplets = [
            _make_triplet("a", "rel", "b"),
            _make_triplet("a", "rel", "c"),
            _make_triplet("b", "rel", "c"),
        ]
        centrality = compute_centrality_for_triplets(triplets)
        assert "a" in centrality
        assert "b" in centrality
        assert "c" in centrality
        # All nodes connected to 2 others in a 3-node graph
        for v in centrality.values():
            assert 0.0 <= v <= 1.0

    def test_empty_triplets(self):
        """Empty input should return empty dict."""
        assert compute_centrality_for_triplets([]) == {}

    def test_hub_has_highest_centrality(self):
        """A hub entity should have higher centrality than leaves."""
        triplets = [
            _make_triplet("hub", "rel", "leaf1"),
            _make_triplet("hub", "rel", "leaf2"),
            _make_triplet("hub", "rel", "leaf3"),
        ]
        centrality = compute_centrality_for_triplets(triplets)
        assert centrality["hub"] > centrality["leaf1"]


# --- compute_unified_scores tests ---


class TestComputeUnifiedScores:
    def test_basic_scoring(self):
        """Should produce ScoredTriplet objects with valid scores."""
        triplets = [_make_triplet(confidence=0.8)]
        centrality = {"apt28": 0.5, "energy sector": 0.3}
        anomaly = {triplets[0].triplet_id: 0.6}

        results = compute_unified_scores(triplets, centrality, anomaly)
        assert len(results) == 1
        assert isinstance(results[0], ScoredTriplet)
        assert 0.0 <= results[0].unified_score <= 1.0

    def test_score_components_present(self):
        """Each result should have all four component scores."""
        triplets = [_make_triplet()]
        results = compute_unified_scores(triplets, {}, {})
        assert "confidence" in results[0].components
        assert "centrality" in results[0].components
        assert "anomaly" in results[0].components
        assert "recency" in results[0].components

    def test_metadata_attachment(self):
        """unified_score and score_components should be attached to triplet metadata."""
        triplets = [_make_triplet()]
        results = compute_unified_scores(triplets, {}, {})
        t = results[0].triplet
        assert "unified_score" in t.metadata
        assert "score_components" in t.metadata

    def test_sorted_descending(self):
        """Results should be sorted by unified_score descending."""
        triplets = [
            _make_triplet(confidence=0.3, subject="low"),
            _make_triplet(confidence=0.9, subject="high"),
        ]
        centrality = {"high": 0.8, "low": 0.1, "energy sector": 0.2}
        results = compute_unified_scores(triplets, centrality, {})
        assert results[0].unified_score >= results[1].unified_score

    def test_custom_weights(self):
        """Custom weights should change the scoring."""
        triplets = [_make_triplet(confidence=0.5)]
        tid = triplets[0].triplet_id
        centrality = {"apt28": 0.0, "energy sector": 0.0}
        anomaly = {tid: 1.0}

        # All weight on anomaly
        w_anomaly = {"confidence": 0.0, "centrality": 0.0, "anomaly": 1.0, "recency": 0.0}
        results = compute_unified_scores(triplets, centrality, anomaly, weights=w_anomaly)
        assert results[0].unified_score == pytest.approx(1.0, abs=0.01)

        # Reset metadata for next run
        triplets[0].metadata = {}
        triplets[0].confidence = 0.5

        # All weight on confidence
        w_conf = {"confidence": 1.0, "centrality": 0.0, "anomaly": 0.0, "recency": 0.0}
        results = compute_unified_scores(triplets, centrality, anomaly, weights=w_conf)
        assert results[0].unified_score == pytest.approx(0.5, abs=0.01)

    def test_single_signal_dominance(self):
        """When one weight is 1.0, score should equal that component."""
        now = datetime.now(timezone.utc)
        t = _make_triplet(confidence=0.0, last_seen=now.isoformat())
        centrality = {"apt28": 1.0, "energy sector": 1.0}

        w = {"confidence": 0.0, "centrality": 1.0, "anomaly": 0.0, "recency": 0.0}
        results = compute_unified_scores(
            [t], centrality, {}, weights=w, reference_time=now
        )
        assert results[0].unified_score == pytest.approx(1.0, abs=0.01)

    def test_clamping_to_unit_range(self):
        """Score should be clamped to [0.0, 1.0] even with extreme inputs."""
        t = _make_triplet(confidence=1.0)
        centrality = {"apt28": 1.0, "energy sector": 1.0}
        anomaly = {t.triplet_id: 1.0}

        results = compute_unified_scores([t], centrality, anomaly)
        assert results[0].unified_score <= 1.0
        assert results[0].unified_score >= 0.0

    def test_empty_input(self):
        """Empty triplet list should return empty results."""
        results = compute_unified_scores([], {}, {})
        assert results == []

    def test_default_weights_sum_to_one(self):
        """Default weights should sum to 1.0."""
        from kgcp.config import DEFAULTS
        weights = DEFAULTS["fusion"]["weights"]
        total = sum(weights.values())
        assert total == pytest.approx(1.0, abs=0.01)

    def test_apply_to_confidence_true(self):
        """When apply_to_confidence=True, triplet.confidence should be overwritten."""
        t = _make_triplet(confidence=0.8)
        original_conf = t.confidence
        compute_unified_scores([t], {}, {}, apply_to_confidence=True)
        # Confidence should now be the unified score, which differs from original
        # (because centrality/anomaly are 0)
        assert t.confidence != original_conf or t.confidence == t.metadata["unified_score"]

    def test_apply_to_confidence_false(self):
        """When apply_to_confidence=False, triplet.confidence should be preserved."""
        t = _make_triplet(confidence=0.8)
        compute_unified_scores([t], {}, {}, apply_to_confidence=False)
        assert t.confidence == 0.8

    def test_missing_entities_default_to_zero(self):
        """Entities not in centrality dict should get centrality 0.0."""
        t = _make_triplet(subject="unknown_entity", obj="another_unknown")
        results = compute_unified_scores([t], {}, {})
        assert results[0].components["centrality"] == 0.0

    def test_missing_anomaly_defaults_to_zero(self):
        """Triplets not in anomaly dict should get anomaly 0.0."""
        t = _make_triplet()
        results = compute_unified_scores([t], {}, {})
        assert results[0].components["anomaly"] == 0.0

    def test_multiple_triplets_ranked(self):
        """Multiple triplets should be ranked by unified score."""
        now = datetime.now(timezone.utc)
        t1 = _make_triplet(confidence=0.9, subject="high", last_seen=now.isoformat())
        t2 = _make_triplet(confidence=0.1, subject="low", last_seen=(now - timedelta(days=89)).isoformat())

        centrality = {"high": 0.8, "low": 0.1, "energy sector": 0.2}
        results = compute_unified_scores([t1, t2], centrality, {}, reference_time=now)
        assert len(results) == 2
        assert results[0].unified_score > results[1].unified_score
