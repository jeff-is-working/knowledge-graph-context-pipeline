"""Tests for BaseExporter sanitization helpers."""

from __future__ import annotations

import pytest

from kgcp.export.base import BaseExporter, MAX_ENTITY_NAME_LEN, MAX_ERROR_MSG_LEN


class TestSanitizeEntityName:
    def test_normal_name_unchanged(self):
        assert BaseExporter._sanitize_entity_name("APT28") == "APT28"

    def test_strips_control_characters(self):
        assert BaseExporter._sanitize_entity_name("APT\x0028") == "APT28"

    def test_strips_null_bytes(self):
        assert BaseExporter._sanitize_entity_name("APT\x0028\x00") == "APT28"

    def test_strips_ansi_escape(self):
        assert BaseExporter._sanitize_entity_name("\x1b[31mAPT28\x1b[0m") == "APT28"

    def test_strips_whitespace(self):
        assert BaseExporter._sanitize_entity_name("  APT28  ") == "APT28"

    def test_truncates_long_name(self):
        long_name = "A" * 1000
        result = BaseExporter._sanitize_entity_name(long_name)
        assert len(result) == MAX_ENTITY_NAME_LEN

    def test_combined_sanitization(self):
        dirty = "  \x1b[31m\x00Evil\x07Name\x1b[0m  "
        result = BaseExporter._sanitize_entity_name(dirty)
        assert result == "EvilName"

    def test_empty_string(self):
        assert BaseExporter._sanitize_entity_name("") == ""

    def test_unicode_preserved(self):
        assert BaseExporter._sanitize_entity_name("Fancy Bär") == "Fancy Bär"


class TestSanitizeError:
    def test_normal_message_unchanged(self):
        assert BaseExporter._sanitize_error("Something failed") == "Something failed"

    def test_strips_ansi_escape(self):
        assert BaseExporter._sanitize_error("\x1b[31mError\x1b[0m") == "Error"

    def test_strips_control_characters(self):
        assert BaseExporter._sanitize_error("Error\x07\x08msg") == "Errormsg"

    def test_truncates_long_message(self):
        long_msg = "E" * 2000
        result = BaseExporter._sanitize_error(long_msg)
        assert len(result) <= MAX_ERROR_MSG_LEN + len("... (truncated)")
        assert result.endswith("... (truncated)")

    def test_short_message_no_truncation(self):
        msg = "Short error"
        result = BaseExporter._sanitize_error(msg)
        assert result == msg
        assert "truncated" not in result

    def test_empty_string(self):
        assert BaseExporter._sanitize_error("") == ""
