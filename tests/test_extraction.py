"""Tests for extraction — LLM-independent tests."""

from kgcp.extraction.extractor import chunk_text
from kgcp.extraction.llm_client import extract_json_from_text


def test_chunk_text_small():
    text = "hello world this is a test"
    chunks = chunk_text(text, chunk_size=100)
    assert len(chunks) == 1
    assert chunks[0] == text


def test_chunk_text_splits():
    words = " ".join(f"word{i}" for i in range(200))
    chunks = chunk_text(words, chunk_size=50, overlap=10)
    assert len(chunks) > 1
    # Non-final chunks should be roughly chunk_size words
    for chunk in chunks[:-1]:
        assert len(chunk.split()) <= 55  # some tolerance
    # Last chunk may be larger (absorbs remainder)
    assert len(chunks[-1].split()) <= 100


def test_chunk_text_overlap():
    words = " ".join(f"w{i}" for i in range(100))
    chunks = chunk_text(words, chunk_size=30, overlap=5)
    assert len(chunks) >= 3
    # Check overlap: last 5 words of chunk 0 should appear in chunk 1
    c0_words = chunks[0].split()
    c1_words = chunks[1].split()
    assert c0_words[-5:] == c1_words[:5]


def test_extract_json_clean():
    text = '[{"subject": "a", "predicate": "b", "object": "c"}]'
    result = extract_json_from_text(text)
    assert result is not None
    assert len(result) == 1
    assert result[0]["subject"] == "a"


def test_extract_json_code_block():
    text = '''Here are the triples:
```json
[{"subject": "apt28", "predicate": "targets", "object": "energy"}]
```
'''
    result = extract_json_from_text(text)
    assert result is not None
    assert result[0]["subject"] == "apt28"


def test_extract_json_trailing_comma():
    text = '[{"subject": "a", "predicate": "b", "object": "c"},]'
    result = extract_json_from_text(text)
    assert result is not None
    assert len(result) == 1


def test_extract_json_garbage():
    text = "This is not JSON at all."
    result = extract_json_from_text(text)
    assert result is None


def test_extract_json_partial():
    text = '{"subject": "a", "predicate": "b", "object": "c"} some garbage {"subject": "d", "predicate": "e", "object": "f"}'
    result = extract_json_from_text(text)
    assert result is not None
    assert len(result) == 2
