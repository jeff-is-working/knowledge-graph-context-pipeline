"""Tests for document ingestion."""

import tempfile
from pathlib import Path

from kgcp.ingestion.chunker import chunk_text_paragraphs
from kgcp.ingestion.parser_registry import parse_file, supported_extensions


def test_supported_extensions():
    exts = supported_extensions()
    assert "txt" in exts
    assert "md" in exts
    assert "html" in exts
    assert "py" in exts


def test_parse_plaintext():
    with tempfile.NamedTemporaryFile(suffix=".txt", mode="w", delete=False) as f:
        f.write("Hello, this is test content.")
        f.flush()
        result = parse_file(f.name)
    assert "test content" in result


def test_parse_markdown():
    with tempfile.NamedTemporaryFile(suffix=".md", mode="w", delete=False) as f:
        f.write("# Header\n\n**Bold text** and [a link](http://example.com).\n")
        f.flush()
        result = parse_file(f.name)
    assert "Header" in result
    assert "Bold text" in result
    assert "a link" in result
    assert "**" not in result  # Markdown markers stripped


def test_chunk_text_paragraphs():
    text = "First paragraph with some words.\n\nSecond paragraph with more words.\n\nThird paragraph here."
    chunks = chunk_text_paragraphs(text, doc_id="d1", source_path="test.txt", chunk_size=20, overlap=3)
    assert len(chunks) >= 1
    # All content should be covered
    all_content = " ".join(c.content for c in chunks)
    assert "First paragraph" in all_content
    assert "Third paragraph" in all_content


def test_chunk_large_paragraph():
    # Single paragraph bigger than chunk_size
    words = " ".join(f"word{i}" for i in range(50))
    chunks = chunk_text_paragraphs(words, doc_id="d1", source_path="test.txt", chunk_size=20, overlap=5)
    assert len(chunks) >= 2


def test_parse_nonexistent_file():
    import pytest
    with pytest.raises(FileNotFoundError):
        parse_file("/nonexistent/file.txt")
