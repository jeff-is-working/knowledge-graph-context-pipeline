"""Tests for context packing."""

from kgcp.models import Triplet
from kgcp.packing.formats.compact_format import pack_compact
from kgcp.packing.formats.markdown_format import pack_markdown
from kgcp.packing.formats.nl_format import pack_natural_language
from kgcp.packing.formats.yaml_format import pack_yaml
from kgcp.packing.packer import pack_context
from kgcp.packing.token_counter import estimate_tokens


def _sample_triplets():
    return [
        Triplet(subject="apt28", predicate="targets", object="energy sector", doc_id="d1", confidence=0.9),
        Triplet(subject="apt28", predicate="uses", object="credential harvesting", doc_id="d1", confidence=0.8),
        Triplet(subject="apt28", predicate="exploits", object="owa portal", doc_id="d1", confidence=0.7),
    ]


def test_yaml_format():
    ctx = pack_yaml(_sample_triplets(), budget=2048)
    assert ctx.format == "yaml"
    assert ctx.triplet_count == 3
    assert "apt28" in ctx.content
    assert "targets" in ctx.content
    assert ctx.token_count > 0


def test_compact_format():
    ctx = pack_compact(_sample_triplets(), budget=2048)
    assert ctx.format == "compact"
    assert "apt28 -> targets -> energy sector" in ctx.content
    assert ctx.triplet_count == 3


def test_markdown_format():
    ctx = pack_markdown(_sample_triplets(), budget=2048)
    assert ctx.format == "markdown"
    assert "| apt28 |" in ctx.content
    assert "| Subject |" in ctx.content


def test_nl_format():
    ctx = pack_natural_language(_sample_triplets(), budget=2048)
    assert ctx.format == "nl"
    assert "Apt28 targets energy sector." in ctx.content


def test_packer_dispatch():
    triplets = _sample_triplets()
    for fmt in ("yaml", "compact", "markdown", "nl"):
        ctx = pack_context(triplets, format=fmt, budget=2048)
        assert ctx.format == fmt
        assert ctx.triplet_count > 0


def test_budget_enforcement():
    # Create many triplets
    triplets = [
        Triplet(
            subject=f"entity_{i}",
            predicate="relates to",
            object=f"entity_{i+100}",
            doc_id="d1",
            confidence=0.5,
        )
        for i in range(200)
    ]
    ctx = pack_yaml(triplets, budget=100)
    assert ctx.token_count <= 120  # some slack for headers


def test_empty_triplets():
    ctx = pack_yaml([], budget=2048)
    assert ctx.triplet_count == 0
    assert "Empty" in ctx.content


def test_estimate_tokens():
    assert estimate_tokens("hello world") > 0
    assert estimate_tokens("a" * 100) > estimate_tokens("a" * 10)


def _sample_triplets_with_unified_scores():
    """Sample triplets with unified_score in metadata."""
    triplets = [
        Triplet(
            subject="apt28", predicate="targets", object="energy sector",
            doc_id="d1", confidence=0.87,
            metadata={"unified_score": 0.87, "score_components": {
                "confidence": 0.9, "centrality": 0.5, "anomaly": 0.6, "recency": 0.8
            }},
        ),
        Triplet(
            subject="apt28", predicate="uses", object="credential harvesting",
            doc_id="d1", confidence=0.72,
            metadata={"unified_score": 0.72, "score_components": {
                "confidence": 0.8, "centrality": 0.3, "anomaly": 0.4, "recency": 0.7
            }},
        ),
    ]
    return triplets


def test_yaml_unified_scores():
    """YAML format should include unified_scores section."""
    ctx = pack_yaml(_sample_triplets_with_unified_scores(), budget=4096)
    assert "unified_scores:" in ctx.content
    assert "components:" in ctx.content


def test_compact_unified_score_suffix():
    """Compact format should append [score:X.XX] when unified_score present."""
    ctx = pack_compact(_sample_triplets_with_unified_scores(), budget=4096)
    assert "[score:0.87]" in ctx.content


def test_markdown_score_column():
    """Markdown format should include Score column when unified scores present."""
    ctx = pack_markdown(_sample_triplets_with_unified_scores(), budget=4096)
    assert "| Score |" in ctx.content
    assert "0.87" in ctx.content


def test_nl_relevance_qualifier():
    """NL format should append (relevance: X.XX) when unified score present."""
    ctx = pack_natural_language(_sample_triplets_with_unified_scores(), budget=4096)
    assert "(relevance: 0.87)" in ctx.content
