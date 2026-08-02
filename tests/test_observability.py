"""Tests for the Sentry event scrubber.

These run without sentry-sdk installed: the scrubbing helpers are deliberately
pure so the security-relevant half of the integration is testable on its own.
"""

import os
from unittest.mock import patch

import pytest

from norman_mcp.observability import (
    FILTERED,
    init_sentry,
    scrub_event,
    scrub_structure,
    scrub_text,
    strip_query,
)


class TestScrubText:
    def test_redacts_bearer_token(self):
        out = scrub_text("Failed with Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9")
        assert "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9" not in out
        assert FILTERED in out

    def test_redacts_basic_auth(self):
        out = scrub_text("Authorization: Basic dXNlcjpwYXNzd29yZA==")
        assert "dXNlcjpwYXNzd29yZA==" not in out

    def test_redacts_oauth_code_in_url(self):
        out = scrub_text("callback failed: https://mcp.norman.finance/cb?code=4/0Ab_c-XYZ&state=zz")
        assert "4/0Ab_c-XYZ" not in out
        assert "state=zz" not in out
        # The useful part of the message survives.
        assert "mcp.norman.finance" in out

    def test_redacts_client_secret_and_tokens(self):
        out = scrub_text("client_secret=abc123&refresh_token=r3fr3sh&access_token=acc3ss")
        for secret in ("abc123", "r3fr3sh", "acc3ss"):
            assert secret not in out

    def test_leaves_ordinary_text_alone(self):
        msg = "Connection closed while listing invoices for company 42"
        assert scrub_text(msg) == msg

    def test_non_string_passes_through(self):
        assert scrub_text(7) == 7
        assert scrub_text(None) is None


class TestStripQuery:
    def test_removes_query_and_fragment(self):
        assert strip_query("https://x.test/cb?code=secret#tok") == "https://x.test/cb"

    def test_keeps_plain_url(self):
        assert strip_query("https://x.test/mcp") == "https://x.test/mcp"

    def test_handles_empty_and_non_string(self):
        assert strip_query("") == ""
        assert strip_query(None) is None


class TestScrubStructure:
    def test_redacts_sensitive_keys_case_insensitively(self):
        out = scrub_structure(
            {
                "Authorization": "Bearer abc",
                "NORMAN_OAUTH_CLIENT_SECRET": "shhh",
                "Mcp-Session-Id": "sess-1",
                "code": "4/0Ab",
                "state": "xyz",
                "content-type": "application/json",
            }
        )
        assert out["Authorization"] == FILTERED
        assert out["NORMAN_OAUTH_CLIENT_SECRET"] == FILTERED
        assert out["Mcp-Session-Id"] == FILTERED
        assert out["code"] == FILTERED
        assert out["state"] == FILTERED
        # Non-sensitive metadata is preserved — the event stays useful.
        assert out["content-type"] == "application/json"

    def test_recurses_into_nested_containers(self):
        out = scrub_structure({"a": [{"password": "p"}, {"ok": "Bearer tokenvalue123"}]})
        assert out["a"][0]["password"] == FILTERED
        assert "tokenvalue123" not in out["a"][1]["ok"]

    def test_bounded_depth_does_not_recurse_forever(self):
        payload = current = {}
        for _ in range(50):
            current["next"] = {}
            current = current["next"]
        # Must terminate rather than blow the stack.
        assert scrub_structure(payload) is not None

    def test_preserves_tuple_type(self):
        assert isinstance(scrub_structure(("a", "b")), tuple)


class TestScrubEvent:
    def test_scrubs_request_block(self):
        event = {
            "request": {
                "url": "https://mcp.norman.finance/oauth/callback?code=4/0Ab&state=xy",
                "query_string": "code=4/0Ab&state=xy",
                "data": {"client_secret": "shhh"},
                "cookies": {"session": "abc"},
                "headers": {"Authorization": "Bearer abc", "Accept": "application/json"},
            }
        }
        out = scrub_event(event)
        req = out["request"]
        assert req["url"] == "https://mcp.norman.finance/oauth/callback"
        assert req["query_string"] == FILTERED
        assert req["data"] == FILTERED
        assert req["cookies"] == FILTERED
        assert req["headers"]["Authorization"] == FILTERED
        assert req["headers"]["Accept"] == "application/json"

    def test_scrubs_exception_value(self):
        event = {
            "exception": {
                "values": [
                    {"type": "HTTPError", "value": "401 for Bearer eyJsecrettokenvalue"}
                ]
            }
        }
        out = scrub_event(event)
        assert "eyJsecrettokenvalue" not in out["exception"]["values"][0]["value"]

    def test_scrubs_logentry_extra_and_breadcrumbs(self):
        event = {
            "logentry": {"message": "token=abcdef123", "params": {"password": "p"}},
            "extra": {"access_token": "tok", "company": "acme"},
            "breadcrumbs": {"values": [{"message": "client_secret=zzz"}]},
        }
        out = scrub_event(event)
        assert "abcdef123" not in out["logentry"]["message"]
        assert out["logentry"]["params"]["password"] == FILTERED
        assert out["extra"]["access_token"] == FILTERED
        assert out["extra"]["company"] == "acme"
        assert "zzz" not in out["breadcrumbs"]["values"][0]["message"]

    def test_handles_breadcrumbs_as_list(self):
        event = {"breadcrumbs": [{"message": "Bearer abcdefgh12345"}]}
        out = scrub_event(event)
        assert "abcdefgh12345" not in out["breadcrumbs"][0]["message"]

    def test_tolerates_missing_and_odd_shapes(self):
        assert scrub_event({}) == {}
        assert scrub_event({"exception": {"values": []}}) is not None
        assert scrub_event({"request": {}}) is not None


class TestInitSentry:
    def test_no_dsn_is_a_noop(self):
        with patch.dict(os.environ, {}, clear=True):
            assert init_sentry() is False

    def test_blank_dsn_is_a_noop(self):
        with patch.dict(os.environ, {"SENTRY_DSN": "   "}, clear=True):
            assert init_sentry() is False

    def test_missing_sdk_degrades_gracefully(self):
        real_import = __builtins__["__import__"] if isinstance(__builtins__, dict) else __import__

        def fake_import(name, *args, **kwargs):
            if name == "sentry_sdk":
                raise ImportError("no sentry_sdk")
            return real_import(name, *args, **kwargs)

        with patch.dict(os.environ, {"SENTRY_DSN": "https://k@o1.ingest.sentry.io/1"}, clear=True):
            with patch("builtins.__import__", side_effect=fake_import):
                # Must not raise: a missing optional dep cannot break startup.
                assert init_sentry() is False

    def test_initialises_with_safe_defaults(self):
        sentry_sdk = pytest.importorskip("sentry_sdk")
        env = {
            "SENTRY_DSN": "https://k@o1.ingest.sentry.io/1",
            "NORMAN_ENVIRONMENT": "production",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sentry_sdk, "init") as mock_init:
                assert init_sentry() is True
        kwargs = mock_init.call_args.kwargs
        assert kwargs["environment"] == "production"
        assert kwargs["send_default_pii"] is False
        assert kwargs["include_local_variables"] is False
        assert kwargs["max_request_body_size"] == "never"
        # Tracing off unless explicitly turned on.
        assert kwargs["traces_sample_rate"] == 0.0
        assert kwargs["profiles_sample_rate"] == 0.0
        assert kwargs["before_send"] is not None

    def test_sample_rates_and_environment_from_env(self):
        sentry_sdk = pytest.importorskip("sentry_sdk")
        env = {
            "SENTRY_DSN": "https://k@o1.ingest.sentry.io/1",
            "SENTRY_ENVIRONMENT": "stage",
            "NORMAN_ENVIRONMENT": "production",
            "SENTRY_TRACES_SAMPLE_RATE": "0.25",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sentry_sdk, "init") as mock_init:
                init_sentry()
        kwargs = mock_init.call_args.kwargs
        # SENTRY_ENVIRONMENT wins over NORMAN_ENVIRONMENT.
        assert kwargs["environment"] == "stage"
        assert kwargs["traces_sample_rate"] == 0.25

    def test_non_numeric_sample_rate_falls_back(self):
        sentry_sdk = pytest.importorskip("sentry_sdk")
        env = {
            "SENTRY_DSN": "https://k@o1.ingest.sentry.io/1",
            "SENTRY_TRACES_SAMPLE_RATE": "high",
        }
        with patch.dict(os.environ, env, clear=True):
            with patch.object(sentry_sdk, "init") as mock_init:
                init_sentry()
        assert mock_init.call_args.kwargs["traces_sample_rate"] == 0.0
