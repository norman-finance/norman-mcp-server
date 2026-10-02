"""Reconnect a saved MCP client after losing one upstream authorization.

These tests exercise the real OAuth and MCP HTTP routes, including the Inbox
read. All Norman authorization and API traffic is intercepted locally.
"""

import asyncio
import base64
import hashlib
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from types import SimpleNamespace
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest
import requests
from starlette.testclient import TestClient

from norman_mcp import context
from norman_mcp.server import create_app, create_cors_app

BASE = "http://localhost:3001"
REDIRECT = "https://chatgpt.com/cb"
COMPANY_A = "11111111-1111-4111-8111-111111111111"
COMPANY_B = "22222222-2222-4222-8222-222222222222"
VERIFIER = "reconnect-fixture-verifier-" + "x" * 43
CHALLENGE = (
    base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest()).decode().rstrip("=")
)


def upstream_response(status, body):
    response = requests.Response()
    response.status_code = status
    response.url = "https://api.norman.finance/api/v1/oauth/token/"
    response._content = json.dumps(body).encode()
    response.headers["Content-Type"] = "application/json"
    return response


class Upstream:
    """A fake Norman server with independent single-use refresh grants."""

    def __init__(self):
        self.versions = {}
        self.revoked = set()
        self.refresh_failure = None
        self.api_reads = []
        self.company_responses = {}
        self.refresh_calls = []
        self.lock = threading.Lock()
        self.block_entered = None
        self.block_release = None

    def exchange(self, request):
        assert request.url.path.endswith("/oauth/token/")
        data = {key: values[0] for key, values in parse_qs(request.content.decode()).items()}
        assert data["grant_type"] == "authorization_code"
        assert data["client_id"] == "norman-reconnect-fixture"
        assert data["redirect_uri"] == BASE + "/oauth/callback"
        grant = data["code"].removeprefix("norman-code-")
        with self.lock:
            assert grant not in self.versions
            self.versions[grant] = 0
        return httpx.Response(
            200,
            json={"access_token": f"access_{grant}_0", "refresh_token": f"refresh_{grant}_0"},
        )

    def refresh(self, url, *, data, timeout):
        assert url.endswith("/oauth/token/")
        assert data["grant_type"] == "refresh_token"
        assert data["client_id"] == "norman-reconnect-fixture"
        assert timeout > 0
        if self.block_entered is not None:
            self.block_entered.set()
            assert self.block_release.wait(5), "test did not release the upstream refresh"
        with self.lock:
            self.refresh_calls.append(data["refresh_token"])
            if isinstance(self.refresh_failure, Exception):
                raise self.refresh_failure
            if self.refresh_failure is not None:
                return upstream_response(*self.refresh_failure)
            for grant, version in self.versions.items():
                if data["refresh_token"] != f"refresh_{grant}_{version}":
                    continue
                if grant in self.revoked:
                    return upstream_response(400, {"error": "invalid_grant"})
                self.versions[grant] += 1
                return upstream_response(
                    200,
                    {
                        "access_token": f"access_{grant}_{version + 1}",
                        "refresh_token": f"refresh_{grant}_{version + 1}",
                    },
                )
            return upstream_response(400, {"error": "invalid_grant"})

    def api(self, method, url, *, headers, params=None, **kwargs):
        assert method == "GET", "reconnect must only read Norman business data"
        token = headers["Authorization"].removeprefix("Bearer ")
        with self.lock:
            self.api_reads.append((url, token, dict(headers), params))
            grant = next((g for g, v in self.versions.items() if token == f"access_{g}_{v}"), None)
            if grant is None or grant in self.revoked:
                return upstream_response(401, {"error": "invalid_token"})
        company = COMPANY_B if grant == "b" else COMPANY_A
        if url.endswith("/companies/"):
            if grant in self.company_responses:
                return upstream_response(*self.company_responses[grant])
            return upstream_response(200, {"results": [{"publicId": company}]})
        assert headers["X-Company-Id"] == company
        if url.endswith("/assistant/workflow-runs/"):
            body = {"runs": []}
        elif url.endswith("/accounting/rule-executions/"):
            body = {"count": 0, "results": [], "next": None}
        elif url.endswith(f"/companies/{company}/autofiling/runs/"):
            body = []
        elif url.endswith(f"/companies/{company}/balance/"):
            body = {
                "bankAccounts": ["fixture-account"],
                "sumsByCurrency": [{"currency": "EUR", "sumAmount": "123.45"}],
            }
        elif url.endswith("/accounting/transactions/"):
            body = {"count": 4 if params.get("status") else 37, "results": []}
        elif url.endswith(f"/companies/{company}/invoices/"):
            body = {"count": 2, "results": []}
        elif url.endswith("/attachments/"):
            body = {"count": 1, "results": []}
        else:
            raise AssertionError(f"Unexpected Norman fixture endpoint: {url}")
        return upstream_response(200, body)


@pytest.fixture
def reconnect_server(monkeypatch, tmp_path):
    monkeypatch.setattr("norman_mcp.auth.provider._STATE_FILE", str(tmp_path / "oauth.json"))
    monkeypatch.setenv("NORMAN_OAUTH_CLIENT_ID", "norman-reconnect-fixture")
    monkeypatch.delenv("NORMAN_OAUTH_CLIENT_SECRET", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_DB", raising=False)
    monkeypatch.delenv("NORMAN_MCP_EVENTS_KEY", raising=False)
    monkeypatch.delenv("NORMAN_MCP_INBOX_LIVE", raising=False)
    upstream = Upstream()
    previous = (
        context.get_oauth_provider(),
        context.get_api_client(),
        context.get_api_token(),
        context.get_api_company_id(),
    )
    original_async_client = httpx.AsyncClient

    def async_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(upstream.exchange)
        return original_async_client(*args, **kwargs)

    monkeypatch.setattr("norman_mcp.auth.provider.httpx.AsyncClient", async_client)
    monkeypatch.setattr(requests, "post", upstream.refresh)
    monkeypatch.setattr(requests, "request", upstream.api)
    monkeypatch.setattr(requests, "get", lambda url, **kwargs: upstream.api("GET", url, **kwargs))

    def make():
        context.set_api_token(None)
        context.set_api_company_id(None)
        server = create_app(
            public_url=BASE,
            transport="streamable-http",
            streamable_http_options={"stateless": True},
        )
        return SimpleNamespace(
            client=TestClient(create_cors_app(server), base_url=BASE),
            provider=context.get_oauth_provider(),
            upstream=upstream,
        )

    try:
        yield make
    finally:
        context.set_oauth_provider(previous[0])
        context.set_api_client(previous[1])
        context.set_api_token(previous[2])
        context.set_api_company_id(previous[3])


def register(client, name="Saved ChatGPT fixture"):
    response = client.post(
        "/register",
        json={
            "client_name": name,
            "redirect_uris": [REDIRECT],
            "token_endpoint_auth_method": "none",
            "grant_types": ["authorization_code", "refresh_token"],
            "response_types": ["code"],
            "scope": "read",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def authorize(client, registration, grant):
    state = f"chatgpt-reconnect-state-{grant}"
    response = client.get(
        "/authorize",
        params={
            "response_type": "code",
            "client_id": registration["client_id"],
            "redirect_uri": REDIRECT,
            "scope": "read",
            "state": state,
            "code_challenge": CHALLENGE,
            "code_challenge_method": "S256",
        },
        follow_redirects=False,
    )
    assert response.status_code in (302, 303), response.text
    upstream_query = parse_qs(urlsplit(response.headers["location"]).query)
    response = client.get(
        "/oauth/callback",
        params={"code": f"norman-code-{grant}", "state": upstream_query["state"][0]},
        follow_redirects=False,
    )
    assert response.status_code == 302, response.text
    destination = urlsplit(response.headers["location"])
    assert destination._replace(query="").geturl() == REDIRECT
    query = parse_qs(destination.query)
    assert query["state"] == [state]
    # Retain the ChatGPT workaround for token calls that omit client_id. A new
    # registration or connector reinstall is not required for this flow.
    response = client.post(
        "/token",
        data={
            "grant_type": "authorization_code",
            "code": query["code"][0],
            "redirect_uri": REDIRECT,
            "code_verifier": VERIFIER,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def refresh(client, registration, tokens):
    return client.post(
        "/token",
        data={
            "grant_type": "refresh_token",
            "client_id": registration["client_id"],
            "refresh_token": tokens["refresh_token"],
        },
    )


def inbox(client, access):
    return client.post(
        "/mcp",
        headers={
            "Authorization": f"Bearer {access}",
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2025-11-25",
        },
        json={
            "jsonrpc": "2.0",
            "id": 1,
            "method": "tools/call",
            "params": {"name": "open_norman_inbox", "arguments": {}},
        },
    )


def assert_inbox(response, company):
    assert response.status_code == 200, response.text
    data = response.json()["result"]["structuredContent"]
    assert not data.get("error"), data
    assert data["companyId"] == company
    assert data["summary"] == {"questions": 0, "approvals": 0, "taxReviewsShown": 0}
    assert data["overview"]["transactionsCount"] == 37
    assert data["overview"]["bankBalances"]["values"] == [{"currency": "EUR", "amount": "123.45"}]
    return data


def credentials(provider):
    return {
        "tokens": {key: value.model_dump() for key, value in provider.tokens.items()},
        "refresh_tokens": {
            key: value.model_dump() for key, value in provider.refresh_tokens.items()
        },
        "token_mapping": dict(provider.token_mapping),
        "token_to_company_id": dict(provider.token_to_company_id),
        "token_grants": dict(provider.token_grants),
    }


def assert_removed(provider, refresh_token, accesses):
    assert refresh_token not in provider.refresh_tokens
    assert refresh_token not in provider.token_mapping
    assert refresh_token not in provider.token_grants
    for access in accesses:
        assert access not in provider.tokens
        assert access not in provider.token_mapping
        assert f"refresh_for_{access}" not in provider.token_mapping
        assert access not in provider.token_to_company_id
        assert access not in provider.token_grants


@pytest.mark.parametrize("failure", ["revoked_refresh", "terminal_refresh", "terminal_transparent"])
def test_saved_client_reconnects_to_inbox_without_reinstall(reconnect_server, failure):
    first = reconnect_server()
    with first.client as client:
        registration = register(client)
        other_registration = register(client, "Unrelated saved client")
        a = authorize(client, registration, "a")
        b = authorize(client, registration, "b")  # Same DCR client, independent grant.
        first.provider.set_company_for_token(a["access_token"], COMPANY_A)
        first.provider.set_company_for_token(b["access_token"], COMPANY_B)
        assert_inbox(inbox(client, a["access_token"]), COMPANY_A)
        rotated = refresh(client, registration, a)
        assert rotated.status_code == 200, rotated.text
        a2 = rotated.json()
        first.provider.set_company_for_token(a2["access_token"], COMPANY_A)
        clients_before = {key: value.model_dump() for key, value in first.provider.clients.items()}
        b_before = {
            "access": first.provider.tokens[b["access_token"]].model_dump(),
            "refresh": first.provider.refresh_tokens[b["refresh_token"]].model_dump(),
            "norman_access": first.provider.get_norman_token(b["access_token"]),
            "norman_refresh": first.provider.token_mapping[b["refresh_token"]],
            "grant": first.provider.grant_for_token(b["access_token"]),
        }

        if failure == "revoked_refresh":
            asyncio.run(first.provider.revoke_token(a["refresh_token"], "refresh_token"))
        elif failure == "terminal_refresh":
            first.upstream.revoked.add("a")
            rejected = refresh(client, registration, a)
            assert rejected.status_code == 400, rejected.text
            assert rejected.json()["error"] == "invalid_grant"
        else:
            first.upstream.revoked.add("a")
            rejected = inbox(client, a["access_token"])
            assert rejected.status_code == 200, rejected.text
            assert rejected.json()["result"]["structuredContent"]["reconnect"] is True

        old_accesses = [a["access_token"], a2["access_token"]]
        assert_removed(first.provider, a["refresh_token"], old_accesses)
        for access in old_accesses:
            rejected = inbox(client, access)
            assert rejected.status_code == 401
            assert 'error="invalid_token"' in rejected.headers["www-authenticate"]
        assert first.provider.get_norman_token(b["access_token"]) == b_before["norman_access"]
        assert_inbox(inbox(client, b["access_token"]), COMPANY_B)
        assert {
            key: value.model_dump() for key, value in first.provider.clients.items()
        } == clients_before

    # The invalidation and unrelated credentials must survive a deploy. Keep
    # the registration returned by the first server, rather than calling DCR again.
    restored = reconnect_server()
    with restored.client as client:
        assert {
            key: value.model_dump() for key, value in restored.provider.clients.items()
        } == clients_before
        assert registration["client_id"] in restored.provider.clients
        assert other_registration["client_id"] in restored.provider.clients
        assert_removed(restored.provider, a["refresh_token"], old_accesses)
        assert restored.provider.tokens[b["access_token"]].model_dump() == b_before["access"]
        assert (
            restored.provider.refresh_tokens[b["refresh_token"]].model_dump() == b_before["refresh"]
        )
        assert restored.provider.token_mapping[b["refresh_token"]] == b_before["norman_refresh"]
        assert restored.provider.grant_for_token(b["access_token"]) == b_before["grant"]
        assert_inbox(inbox(client, b["access_token"]), COMPANY_B)
        rejected = refresh(client, registration, a)
        assert rejected.status_code == 400
        assert rejected.json()["error"] == "invalid_grant"

        reconnected = authorize(client, registration, "reconnected")
        assert reconnected["access_token"] not in old_accesses
        assert reconnected["refresh_token"] != a["refresh_token"]
        data = assert_inbox(inbox(client, reconnected["access_token"]), COMPANY_A)
        assert data["overview"]["actions"]["unreviewedTransactions"] == 4
        assert restored.provider.grant_for_token(reconnected["access_token"]) != b_before["grant"]
        assert {
            key: value.model_dump() for key, value in restored.provider.clients.items()
        } == clients_before


@pytest.mark.parametrize(
    ("failure", "expected_status"),
    [
        (requests.ConnectionError("fixture network unavailable"), 503),
        ((429, {"error": "temporarily_unavailable"}), 503),
        ((503, {"error": "temporarily_unavailable"}), 503),
        ((400, {"error": "invalid_client"}), 502),
    ],
    ids=["network", "rate-limit", "server-error", "upstream-invalid-client"],
)
def test_nonterminal_refresh_error_retains_saved_authorization(
    reconnect_server, failure, expected_status
):
    fixture = reconnect_server()
    with fixture.client as client:
        registration = register(client)
        tokens = authorize(client, registration, "a")
        fixture.provider.set_company_for_token(tokens["access_token"], COMPANY_A)
        before = credentials(fixture.provider)
        fixture.upstream.refresh_failure = failure
        rejected = refresh(client, registration, tokens)
        assert rejected.status_code == expected_status, rejected.text
        assert credentials(fixture.provider) == before
        assert_inbox(inbox(client, tokens["access_token"]), COMPANY_A)


def test_revocation_during_inflight_refresh_does_not_resurrect_grant(reconnect_server):
    fixture = reconnect_server()
    with fixture.client as client:
        registration = register(client)
        a = authorize(client, registration, "a")
        b = authorize(client, registration, "b")
        fixture.provider.set_company_for_token(a["access_token"], COMPANY_A)
        fixture.provider.set_company_for_token(b["access_token"], COMPANY_B)
        fixture.upstream.block_entered = threading.Event()
        fixture.upstream.block_release = threading.Event()
        revoke_started = threading.Event()
        revoke_finished = threading.Event()

        def revoke():
            revoke_started.set()
            try:
                asyncio.run(fixture.provider.revoke_token(a["refresh_token"], "refresh_token"))
            finally:
                revoke_finished.set()

        with ThreadPoolExecutor(max_workers=2) as pool:
            refreshing = pool.submit(refresh, client, registration, a)
            assert fixture.upstream.block_entered.wait(2)
            revoking = pool.submit(revoke)
            assert revoke_started.wait(2)
            # Allow either locking strategy: immediate invalidation while the
            # request is in flight, or serialized revocation after it finishes.
            revoke_finished.wait(0.1)
            fixture.upstream.block_release.set()
            result = refreshing.result(timeout=5)
            revoking.result(timeout=5)

        accesses = [a["access_token"]]
        if result.status_code == 200:
            accesses.append(result.json()["access_token"])
        else:
            assert result.status_code == 400, result.text
            assert result.json()["error"] == "invalid_grant"
        assert_removed(fixture.provider, a["refresh_token"], accesses)
        for access in accesses:
            assert inbox(client, access).status_code == 401
        assert_inbox(inbox(client, b["access_token"]), COMPANY_B)


def test_terminal_refresh_during_company_lookup_returns_reconnect_and_preserves_other_grant(
    reconnect_server,
):
    fixture = reconnect_server()
    with fixture.client as client:
        registration = register(client)
        a = authorize(client, registration, "a")
        b = authorize(client, registration, "b")
        assert fixture.provider.get_company_for_token(a["access_token"]) is None
        assert fixture.provider.get_company_for_token(b["access_token"]) is None
        b_before = {
            "access": fixture.provider.tokens[b["access_token"]].model_dump(),
            "refresh": fixture.provider.refresh_tokens[b["refresh_token"]].model_dump(),
            "norman_access": fixture.provider.get_norman_token(b["access_token"]),
            "norman_refresh": fixture.provider.token_mapping[b["refresh_token"]],
            "grant": fixture.provider.grant_for_token(b["access_token"]),
        }
        fixture.upstream.revoked.add("a")

        # No seeded company: the actual NormanAPI.company_id lookup must see
        # the upstream 401 and its terminal refresh failure before Inbox loads.
        rejected = inbox(client, a["access_token"])
        assert rejected.status_code == 200, rejected.text
        result = rejected.json()["result"]
        assert result["structuredContent"] == {
            "error": "Your Norman session expired. Please reconnect Norman.",
            "reconnect": True,
        }
        assert result["content"][0]["text"] == result["structuredContent"]["error"]
        assert fixture.upstream.refresh_calls == ["refresh_a_0"]
        assert [
            (url.endswith("/companies/"), token) for url, token, _, _ in fixture.upstream.api_reads
        ] == [(True, "access_a_0")]
        assert_removed(fixture.provider, a["refresh_token"], [a["access_token"]])
        assert inbox(client, a["access_token"]).status_code == 401

        assert fixture.provider.tokens[b["access_token"]].model_dump() == b_before["access"]
        assert (
            fixture.provider.refresh_tokens[b["refresh_token"]].model_dump() == b_before["refresh"]
        )
        assert fixture.provider.get_norman_token(b["access_token"]) == b_before["norman_access"]
        assert fixture.provider.token_mapping[b["refresh_token"]] == b_before["norman_refresh"]
        assert fixture.provider.grant_for_token(b["access_token"]) == b_before["grant"]
        assert registration["client_id"] in fixture.provider.clients
        assert_inbox(inbox(client, b["access_token"]), COMPANY_B)
        assert any(
            url.endswith("/companies/") and token == "access_b_0"
            for url, token, _, _ in fixture.upstream.api_reads
        )


@pytest.mark.parametrize("failure", ["empty", "company-unavailable", "refresh-unavailable"])
def test_company_lookup_without_terminal_auth_failure_does_not_request_reconnect(
    reconnect_server, failure
):
    fixture = reconnect_server()
    with fixture.client as client:
        registration = register(client)
        tokens = authorize(client, registration, "a")
        before = credentials(fixture.provider)
        assert fixture.provider.get_company_for_token(tokens["access_token"]) is None
        if failure == "empty":
            fixture.upstream.company_responses["a"] = (200, {"results": []})
        elif failure == "company-unavailable":
            fixture.upstream.company_responses["a"] = (503, {"error": "private-upstream-detail"})
        else:
            fixture.upstream.company_responses["a"] = (401, {"error": "invalid_token"})
            fixture.upstream.refresh_failure = (503, {"error": "private-upstream-detail"})

        response = inbox(client, tokens["access_token"])
        assert response.status_code == 200, response.text
        data = response.json()["result"]["structuredContent"]
        assert data == {"error": "Please connect Norman and select a company."}
        assert "private" not in str(data)
        assert credentials(fixture.provider) == before
        assert len(fixture.upstream.refresh_calls) == (1 if failure == "refresh-unavailable" else 0)
        assert all(url.endswith("/companies/") for url, _, _, _ in fixture.upstream.api_reads)

        fixture.upstream.company_responses.clear()
        fixture.upstream.refresh_failure = None
        assert_inbox(inbox(client, tokens["access_token"]), COMPANY_A)
