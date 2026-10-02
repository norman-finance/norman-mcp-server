"""Real browser-return routes with a local Norman upstream and persisted state."""

import base64
import hashlib
import json
import logging
import time
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from norman_mcp.auth import provider as provider_module
from tests.test_sdk2_oauth import VERIFIER, code_payload, oauth_server, register

# Capture the real class before the shared fixture replaces its public alias.
_HTTP_CLIENT = httpx.AsyncClient
CHATGPT = "https://chatgpt.com/connector/oauth/callback-fixture"
HOST_STATE = "original-chatgpt-state-fixture"
ERROR_DESCRIPTIONS = {
    "access_denied": "Norman authorization was not granted. Please reconnect.",
    "temporarily_unavailable": "Norman authorization is temporarily unavailable. Please retry.",
    "invalid_request": "Norman authorization could not complete. Please reconnect.",
    "server_error": "Norman authorization could not complete. Please reconnect.",
}


def begin(client, registration, state=HOST_STATE, verifier=VERIFIER, redirect=CHATGPT):
    challenge = (
        base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).decode().rstrip("=")
    )
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": redirect,
            "scope": "read",
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    query = parse_qs(urlsplit(response.headers["location"]).query)
    assert query["redirect_uri"] == ["http://localhost:3001/oauth/callback"]
    return query["state"][0]


def returned(response, *, redirect=CHATGPT, state=HOST_STATE, error=None):
    assert response.status_code == 302, response.text
    target = urlsplit(response.headers["location"])
    assert target._replace(query="").geturl() == redirect
    query = parse_qs(target.query)
    assert query["state"] == [state]
    assert response.headers["cache-control"] == "no-store"
    if error:
        assert query["error"] == [error]
        assert "code" not in query
        assert query["error_description"] == [ERROR_DESCRIPTIONS[error]]
    else:
        assert "error" not in query
    return query


def callback(client, state):
    return client.get(
        "/oauth/callback",
        params={"code": "norman-code-fixture", "state": state},
        follow_redirects=False,
    )


@pytest.mark.parametrize(
    "redirect", [CHATGPT, "https://chatgpt.com/connector_platform_oauth_redirect"]
)
def test_saved_chatgpt_client_reconnects_after_invalid_grant_without_reregistering(
    oauth_server, redirect
):
    client, provider, upstream = oauth_server()
    with client:
        metadata = client.get("/.well-known/oauth-authorization-server").json()
        assert not metadata.get("authorization_response_iss_parameter_supported")
        registration = register(client, redirect)
        rejected = client.post(
            "/token",
            data={
                "grant_type": "refresh_token",
                "refresh_token": "missing-old-grant-fixture",
                "client_id": registration["client_id"],
            },
        )
        assert rejected.status_code == 400 and rejected.json()["error"] == "invalid_grant"
        for host_state in ("first-reconnect", "second-reconnect"):
            upstream_state = begin(client, registration, state=host_state, redirect=redirect)
            query = returned(callback(client, upstream_state), redirect=redirect, state=host_state)
            assert "iss" not in query  # Support remains deliberately unadvertised.
            exchanged = client.post("/token", data=code_payload(query["code"][0], redirect))
            assert exchanged.status_code == 200, exchanged.text
        assert len(upstream) == 2
        assert registration["client_id"] in provider.clients


def test_overlapping_reconnects_with_same_host_state_keep_their_own_pkce(oauth_server):
    client, provider, upstream = oauth_server()
    second_verifier = "second-reconnect-verifier-" + "z" * 43
    with client:
        registration = register(client, CHATGPT)
        first = begin(client, registration)
        second = begin(client, registration, verifier=second_verifier)
        assert first != second and HOST_STATE not in (first, second)
        for upstream_state, verifier in ((first, VERIFIER), (second, second_verifier)):
            query = returned(callback(client, upstream_state))
            exchanged = client.post(
                "/token", data=code_payload(query["code"][0], CHATGPT, verifier)
            )
            assert exchanged.status_code == 200, exchanged.text
        assert len(upstream) == 2 and not provider.state_mapping


@pytest.mark.parametrize(
    ("upstream_error", "safe_error"),
    [
        ("access_denied", "access_denied"),
        ("temporarily_unavailable", "temporarily_unavailable"),
        ("server_error", "server_error"),
        ("<script>private-upstream-error</script>", "server_error"),
    ],
)
def test_upstream_authorization_error_returns_original_state_once_without_private_details(
    oauth_server, caplog, upstream_error, safe_error
):
    client, provider, upstream = oauth_server()
    with client:
        registration = register(client, CHATGPT)
        upstream_state = begin(client, registration)
        caplog.clear()
        caplog.set_level(logging.INFO, logger="norman_mcp.auth.routes")
        response = client.get(
            "/oauth/callback",
            params={
                "state": upstream_state,
                "error": upstream_error,
                "error_description": "private-description-<script>alert(1)</script>",
                "redirect_uri": "https://attacker.invalid/callback",
            },
            follow_redirects=False,
        )
        returned(response, error=safe_error)
        assert "private" not in response.headers["location"]
        auth_logs = " ".join(
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("norman_mcp.auth")
        )
        assert "private" not in auth_logs and upstream_state not in auth_logs
        assert not upstream and not provider.auth_codes and not provider.tokens
        replay = client.get(
            "/oauth/callback",
            params={"state": upstream_state, "error": "access_denied"},
            follow_redirects=False,
        )
        assert replay.status_code == 400 and "location" not in replay.headers


def test_missing_code_returns_fixed_error_to_known_original_state(oauth_server):
    client, provider, upstream = oauth_server()
    with client:
        registration = register(client, CHATGPT)
        state = begin(client, registration)
        response = client.get("/oauth/callback", params={"state": state}, follow_redirects=False)
        returned(response, error="invalid_request")
        assert not upstream and not provider.state_mapping


@pytest.mark.parametrize("state", [None, "unknown-private-state"])
def test_unknown_callback_stays_local_and_never_renders_or_trusts_supplied_values(
    oauth_server, state, caplog
):
    client, provider, upstream = oauth_server()
    with client:
        caplog.set_level(logging.INFO, logger="norman_mcp.auth.routes")
        params = {
            "code": "private-code-fixture",
            "error": "private-error-<script>alert(1)</script>",
            "error_description": "private-description",
            "redirect_uri": "https://chatgpt.com/connector/oauth/attacker-supplied",
        }
        if state is not None:
            params["state"] = state
        response = client.get("/oauth/callback", params=params, follow_redirects=False)
        assert response.status_code == 400 and "location" not in response.headers
        assert "private" not in response.text and "<script>" not in response.text
        assert "start connecting Norman again" in response.text
        assert response.headers["cache-control"] == "no-store"
        auth_logs = " ".join(
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("norman_mcp.auth")
        )
        assert "private" not in auth_logs
        assert not upstream and not provider.tokens


@pytest.mark.parametrize("failure", ["invalid_grant", "network"])
def test_failed_norman_code_exchange_returns_safe_oauth_error_instead_of_local_500(
    oauth_server, monkeypatch, failure, caplog
):
    client, provider, upstream = oauth_server()
    calls = []

    def fail_exchange(request):
        calls.append(request)
        if failure == "network":
            raise httpx.ConnectError("private-upstream-network-detail", request=request)
        return httpx.Response(
            400, json={"error": "invalid_grant", "error_description": "private-upstream-detail"}
        )

    def failed_http_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(fail_exchange)
        return _HTTP_CLIENT(*args, **kwargs)

    with client:
        registration = register(client, CHATGPT)
        state = begin(client, registration)
        monkeypatch.setattr(provider_module.httpx, "AsyncClient", failed_http_client)
        caplog.clear()
        caplog.set_level(logging.INFO, logger="norman_mcp.auth")
        response = callback(client, state)
        returned(
            response,
            error="temporarily_unavailable" if failure == "network" else "server_error",
        )
        auth_logs = " ".join(
            record.getMessage()
            for record in caplog.records
            if record.name.startswith("norman_mcp.auth")
        )
        assert "private" not in auth_logs and state not in auth_logs
        assert len(calls) == 1 and not upstream and not provider.auth_codes
        replay = callback(client, state)
        assert replay.status_code == 400 and "location" not in replay.headers
        assert len(calls) == 1


def test_pending_browser_return_survives_provider_restart(oauth_server):
    first, _, upstream = oauth_server()
    with first:
        registration = register(first, CHATGPT)
        state = begin(first, registration)
    restored, provider, _ = oauth_server()
    with restored:
        query = returned(callback(restored, state))
        exchanged = restored.post("/token", data=code_payload(query["code"][0], CHATGPT))
        assert exchanged.status_code == 200, exchanged.text
        assert registration["client_id"] in provider.clients
        assert len(upstream) == 1


def test_authorization_code_survives_restart_between_browser_return_and_token(oauth_server):
    first, _, upstream = oauth_server()
    with first:
        registration = register(first, CHATGPT)
        query = returned(callback(first, begin(first, registration)))
    restored, _, _ = oauth_server()
    with restored:
        payload = code_payload(query["code"][0], CHATGPT)
        payload["client_id"] = registration["client_id"]
        response = restored.post("/token", data=payload)
        assert response.status_code == 200, response.text
        replay = restored.post("/token", data=payload)
        assert replay.status_code == 400 and replay.json()["error"] == "invalid_grant"
        assert len(upstream) == 1


def test_expired_pending_state_is_rejected_without_upstream_exchange_or_redirect(
    oauth_server, monkeypatch
):
    clock = [time.time()]
    monkeypatch.setattr(provider_module, "time", SimpleNamespace(time=lambda: clock[0]))
    client, provider, upstream = oauth_server()
    with client:
        registration = register(client, CHATGPT)
        state = begin(client, registration)
        clock[0] += provider_module.OAUTH_TRANSACTION_TTL + 1
        response = callback(client, state)
        assert response.status_code == 400 and "location" not in response.headers
        assert not upstream and not provider.auth_codes


def test_transaction_ttl_prunes_live_pending_codes_and_unused_credentials_on_next_save(
    oauth_server, monkeypatch
):
    clock = [time.time()]
    monkeypatch.setattr(provider_module, "time", SimpleNamespace(time=lambda: clock[0]))
    client, provider, upstream = oauth_server()
    with client:
        registration = register(client, CHATGPT)
        abandoned_state = begin(client, registration, state="abandoned-browser-attempt")
        completed_state = begin(client, registration)
        query = returned(callback(client, completed_state))
        code = query["code"][0]
        assert code in provider.auth_codes
        assert code in provider.token_mapping and f"refresh_{code}" in provider.token_mapping
        clock[0] += provider_module.OAUTH_TRANSACTION_TTL + 1

        # Starting a later attempt triggers normal persistence, and must not
        # retain expired transactions or their unused Norman credentials.
        fresh_state = begin(client, registration, state="fresh-browser-attempt")
        assert set(provider.state_mapping) == {fresh_state}
        assert abandoned_state not in provider.state_mapping
        assert code not in provider.auth_codes
        assert code not in provider.token_mapping
        assert f"refresh_{code}" not in provider.token_mapping
        stored = json.loads(provider._state_path().read_text())
        assert set(stored["state_mapping"]) == {fresh_state}
        assert code not in stored["auth_codes"]
        assert code not in stored["token_mapping"]
        assert f"refresh_{code}" not in stored["token_mapping"]
        assert len(upstream) == 1


def test_restart_discards_expired_serialized_code_and_its_unused_norman_credentials(
    oauth_server, monkeypatch
):
    clock = [time.time()]
    monkeypatch.setattr(provider_module, "time", SimpleNamespace(time=lambda: clock[0]))
    first, provider, upstream = oauth_server()
    with first:
        registration = register(first, CHATGPT)
        query = returned(callback(first, begin(first, registration)))
        code = query["code"][0]
        stored = json.loads(provider._state_path().read_text())
        assert code in stored["auth_codes"]
        assert code in stored["token_mapping"]
        assert f"refresh_{code}" in stored["token_mapping"]

    # Simulate a deploy after the persisted code expired, without a save in
    # the old process that could have removed the now unusable credentials.
    clock[0] += provider_module.OAUTH_TRANSACTION_TTL + 1
    restored, provider, _ = oauth_server()
    with restored:
        assert registration["client_id"] in provider.clients
        assert code not in provider.auth_codes
        assert code not in provider.token_mapping
        assert f"refresh_{code}" not in provider.token_mapping
        provider._save_state()
        stored = json.loads(provider._state_path().read_text())
        assert code not in stored["auth_codes"]
        assert code not in stored["token_mapping"]
        assert f"refresh_{code}" not in stored["token_mapping"]
        assert len(upstream) == 1
