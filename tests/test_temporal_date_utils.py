"""Tests for temporal date parsing utilities."""

import re
from datetime import datetime, timezone

import pytest

from kgcp.temporal.date_utils import parse_date, quarter_end


# -- ISO date parsing --

def test_parse_iso_date():
    result = parse_date("2025-01-15")
    assert result == "2025-01-15T00:00:00+00:00"


def test_parse_iso_datetime():
    result = parse_date("2025-01-15T10:30:00+00:00")
    assert "2025-01-15" in result
    assert "10:30:00" in result


def test_parse_iso_datetime_no_tz():
    result = parse_date("2025-01-15T10:30:00")
    assert "2025-01-15" in result
    assert "+00:00" in result


# -- Quarter parsing --

def test_parse_quarter_q1():
    result = parse_date("2025-Q1")
    assert result == "2025-01-01T00:00:00+00:00"


def test_parse_quarter_q2():
    result = parse_date("2025-Q2")
    assert result == "2025-04-01T00:00:00+00:00"


def test_parse_quarter_q3():
    result = parse_date("2025-Q3")
    assert result == "2025-07-01T00:00:00+00:00"


def test_parse_quarter_q4():
    result = parse_date("2025-Q4")
    assert result == "2025-10-01T00:00:00+00:00"


def test_parse_quarter_lowercase():
    result = parse_date("2025-q2")
    assert result == "2025-04-01T00:00:00+00:00"


# -- Relative dates --

def test_parse_relative_days():
    result = parse_date("90d")
    dt = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = now - dt
    assert 89 <= delta.days <= 91


def test_parse_relative_months():
    result = parse_date("6m")
    dt = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = now - dt
    assert 175 <= delta.days <= 185


def test_parse_relative_years():
    result = parse_date("1y")
    dt = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = now - dt
    assert 360 <= delta.days <= 370


def test_parse_relative_uppercase():
    result = parse_date("30D")
    dt = datetime.fromisoformat(result)
    now = datetime.now(timezone.utc)
    delta = now - dt
    assert 29 <= delta.days <= 31


# -- Invalid input --

def test_parse_empty_string():
    with pytest.raises(ValueError, match="Empty date"):
        parse_date("")


def test_parse_garbage():
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_date("not-a-date")


def test_parse_invalid_quarter():
    with pytest.raises(ValueError, match="Cannot parse"):
        parse_date("2025-Q5")


# -- quarter_end --

def test_quarter_end_q1():
    result = quarter_end("2025-Q1")
    assert result == "2025-04-01T00:00:00+00:00"


def test_quarter_end_q2():
    result = quarter_end("2025-Q2")
    assert result == "2025-07-01T00:00:00+00:00"


def test_quarter_end_q3():
    result = quarter_end("2025-Q3")
    assert result == "2025-10-01T00:00:00+00:00"


def test_quarter_end_q4():
    """Q4 end wraps to next year."""
    result = quarter_end("2025-Q4")
    assert result == "2026-01-01T00:00:00+00:00"


def test_quarter_end_invalid():
    with pytest.raises(ValueError, match="Not a quarter"):
        quarter_end("2025-01-15")


# -- Whitespace handling --

def test_parse_whitespace_stripped():
    result = parse_date("  2025-01-15  ")
    assert result == "2025-01-15T00:00:00+00:00"


# -- Time-range storage tests --

import tempfile
from pathlib import Path
from kgcp.models import Document, Triplet
from kgcp.storage.sqlite_store import SQLiteStore


@pytest.fixture
def store():
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        s = SQLiteStore(db_path)
        yield s
        s.close()


@pytest.fixture
def store_with_data(store):
    """Store with document and triplets spanning Jan-Jun 2025."""
    doc = Document(source_path="/tmp/test.txt", doc_id="doc1",
                   ingested_at="2025-01-01T00:00:00+00:00")
    store.add_document(doc)

    triplets = [
        Triplet(
            subject="apt28", predicate="targets", object="energy",
            doc_id="doc1", triplet_id="t1",
            first_seen="2025-01-15", last_seen="2025-03-01",
        ),
        Triplet(
            subject="apt29", predicate="targets", object="gov",
            doc_id="doc1", triplet_id="t2",
            first_seen="2025-04-01", last_seen="2025-06-01",
        ),
        Triplet(
            subject="lazarus", predicate="targets", object="finance",
            doc_id="doc1", triplet_id="t3",
            first_seen="2025-02-01", last_seen="2025-05-01",
        ),
    ]
    store.add_triplets(triplets)
    return store


def test_get_triplets_in_range_since(store_with_data):
    """Since filter: triplets with last_seen >= since."""
    results = store_with_data.get_triplets_in_range(since="2025-04-01")
    ids = {r.triplet_id for r in results}
    assert "t2" in ids  # last_seen 2025-06-01
    assert "t3" in ids  # last_seen 2025-05-01
    assert "t1" not in ids  # last_seen 2025-03-01


def test_get_triplets_in_range_until(store_with_data):
    """Until filter: triplets with first_seen <= until."""
    results = store_with_data.get_triplets_in_range(until="2025-02-01")
    ids = {r.triplet_id for r in results}
    assert "t1" in ids  # first_seen 2025-01-15
    assert "t3" in ids  # first_seen 2025-02-01
    assert "t2" not in ids  # first_seen 2025-04-01


def test_get_triplets_in_range_both(store_with_data):
    """Combined range query."""
    results = store_with_data.get_triplets_in_range(
        since="2025-03-01", until="2025-03-01"
    )
    ids = {r.triplet_id for r in results}
    assert "t1" in ids  # last_seen 2025-03-01, first_seen 2025-01-15
    assert "t3" in ids  # last_seen 2025-05-01, first_seen 2025-02-01
    assert "t2" not in ids  # first_seen 2025-04-01 > until


def test_get_triplets_in_range_no_filter(store_with_data):
    """No filter returns all triplets."""
    results = store_with_data.get_triplets_in_range()
    assert len(results) == 3


def test_get_triplets_since_backward_compat(store):
    """get_triplets_since uses document.ingested_at for backward compatibility."""
    doc1 = Document(source_path="/tmp/old.txt", doc_id="d1",
                    ingested_at="2025-01-01T00:00:00+00:00")
    doc2 = Document(source_path="/tmp/new.txt", doc_id="d2",
                    ingested_at="2025-06-01T00:00:00+00:00")
    store.add_document(doc1)
    store.add_document(doc2)

    store.add_triplets([
        Triplet(subject="old", predicate="r", object="b", doc_id="d1", triplet_id="t_old",
                first_seen="2025-01-01", last_seen="2025-01-01"),
        Triplet(subject="new", predicate="r", object="b", doc_id="d2", triplet_id="t_new",
                first_seen="2025-06-01", last_seen="2025-06-01"),
    ])

    results = store.get_triplets_since("2025-04-01")
    ids = {r.triplet_id for r in results}
    assert "t_new" in ids
    assert "t_old" not in ids
