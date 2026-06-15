"""Regression tests for norman_mcp.security.utils.validate_input.

The old implementation stripped SQL-keyword substrings (and '@'), silently
corrupting legitimate input such as status="PENDING" -> "PING" or "OpenAI" -> "AI".
These tests pin the corrected behaviour: normal text passes through unchanged,
only HTML/JS injection patterns are stripped.
"""
import pytest

from norman_mcp.security.utils import validate_input


@pytest.mark.parametrize("value", [
    "PENDING",            # contains "end" — must NOT become "PING"
    "PAID",
    "OpenAI",             # contains "open" — must NOT become "AI"
    "foo@example.com",    # the "@" must survive
    "end", "open", "create", "update", "delete", "select", "table",
    "Invoice for September 2025",
    "Acme GmbH & Co. KG",
])
def test_preserves_normal_text(value):
    assert validate_input(value) == value


def test_none_passthrough():
    assert validate_input(None) is None


def test_empty_string():
    assert validate_input("") == ""


def test_strips_script_injection():
    assert "<script" not in validate_input("<script>alert(1)</script>").lower()
    assert "javascript:" not in validate_input("javascript:alert(1)").lower()
    assert "alert(" not in validate_input("x = alert(1)")
