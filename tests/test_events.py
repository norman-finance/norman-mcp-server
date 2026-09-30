import asyncio
import base64
import hashlib
import hmac
import json
import time
from types import SimpleNamespace
from unittest.mock import patch

import jwt
import pytest
from cryptography.fernet import Fernet
from mcp.server.auth.provider import AccessToken
from mcp.server.mcpserver import MCPServer
from mcp.shared.exceptions import MCPError
from starlette.testclient import TestClient

from norman_mcp.events import webhooks
from norman_mcp.events.service import (
    EventService,
    Subscribe,
    Unsubscribe,
    identity,
    principal,
    register_events,
)
from norman_mcp.events.store import SubscriptionStore

COMPANY = "11111111-1111-4111-8111-111111111111"
RUN = "22222222-2222-4222-8222-222222222222"
SECRET = "whsec_" + base64.b64encode(b"k" * 32).decode()
URL = "https://receiver.example.com/callback"


def subscribe_params(**kwargs):
    return Subscribe(
        name="workflow.attention_required",
        arguments={"company_id": COMPANY, "run_id": RUN},
        delivery={"mode": "webhook", "url": URL, "secret": SECRET},
        **kwargs,
    )


@pytest.fixture
def setup(tmp_path):
    access = AccessToken(
        token="mcp-test", client_id="client-1", scopes=["read"], expires_at=int(time.time()) + 7200
    )
    provider = SimpleNamespace(
        tokens={access.token: access},
        get_norman_token=lambda t: jwt.encode(
            {"user_id": "user-1"}, "fixture-key-with-at-least-32-bytes", algorithm="HS256"
        ),
    )
    store = SubscriptionStore(str(tmp_path / "events.sqlite"), Fernet.generate_key().decode())
    sent = []

    def post(url, secret, sid, eid, payload, **kwargs):
        sent.append((url, secret, sid, eid, payload, kwargs))
        return (
            (200, {"challenge": payload["challenge"]})
            if payload.get("type") == "verification"
            else (200, {})
        )

    service = EventService(store, provider, post=post)

    async def request(method, url, **kwargs):
        return {"publicId": RUN, "state": "active", "blockedReason": None}

    api = SimpleNamespace(company_id=COMPANY, arequest=request)
    ctx = SimpleNamespace(lifespan_context={"api": api})
    return service, access, provider, ctx, sent


def create(setup):
    service, access, _, ctx, _ = setup
    with patch("norman_mcp.events.service.get_access_token", return_value=access):
        return asyncio.run(service.subscribe(ctx, subscribe_params()))


def test_subscribe_verifies_callback_and_is_idempotent_across_token_refresh(setup):
    service, access, provider, ctx, sent = setup
    first = create(setup)
    replacement = access.model_copy(update={"token": "mcp-replacement"})
    provider.tokens[replacement.token] = replacement
    with patch("norman_mcp.events.service.get_access_token", return_value=replacement):
        second = asyncio.run(service.subscribe(ctx, subscribe_params()))
    assert first["id"] == second["id"]
    assert len(service.store.records()) == 1
    assert service.store.get(first["id"])["token"] == replacement.token
    assert len(sent) == 1  # The same owner/callback/key reuses bounded verification.
    assert first["cursor"] is None and first["truncated"] is False


def test_state_is_encrypted_and_survives_restart(setup):
    service, *_ = setup
    result = create(setup)
    with open(service.store.path, "rb") as f:
        raw = f.read()
    assert SECRET.encode() not in raw and b"mcp-test" not in raw and URL.encode() not in raw
    restarted = SubscriptionStore(
        service.store.path,
        base64.urlsafe_b64encode(
            service.store.cipher._signing_key + service.store.cipher._encryption_key
        ).decode(),
    )
    assert restarted.get(result["id"])["secret"] == SECRET


def test_callback_challenge_failure_never_stores_subscription(setup):
    service, access, _, ctx, _ = setup
    service.post = lambda *args: (200, {"challenge": "wrong"})
    with (
        patch("norman_mcp.events.service.get_access_token", return_value=access),
        pytest.raises(MCPError) as exc,
    ):
        asyncio.run(service.subscribe(ctx, subscribe_params()))
    assert exc.value.code == -32015
    assert service.store.records() == []


def test_cross_company_subscription_is_rejected_before_callback(setup):
    service, access, _, ctx, sent = setup
    ctx.lifespan_context["api"].company_id = "other-company"
    with (
        patch("norman_mcp.events.service.get_access_token", return_value=access),
        pytest.raises(MCPError),
    ):
        asyncio.run(service.subscribe(ctx, subscribe_params()))
    assert sent == []


def test_unsubscribe_is_idempotent_after_run_disappears_and_cannot_remove_another_owner(setup):
    service, access, _, ctx, _ = setup
    result = create(setup)
    params = Unsubscribe(
        name="workflow.attention_required",
        arguments={"company_id": COMPANY, "run_id": RUN},
        delivery={"mode": "webhook", "url": URL},
    )
    other = access.model_copy(update={"client_id": "different-client"})
    with patch("norman_mcp.events.service.get_access_token", return_value=other):
        asyncio.run(service.unsubscribe(ctx, params))
    assert service.store.get(result["id"])
    ctx.lifespan_context["api"] = None
    with patch("norman_mcp.events.service.get_access_token", return_value=access):
        asyncio.run(service.unsubscribe(ctx, params))
        asyncio.run(service.unsubscribe(ctx, params))
    assert service.store.records() == []


async def blocked(api, path, **kwargs):
    assert api.company_id == COMPANY
    return {
        "publicId": RUN,
        "state": "active",
        "title": "Close September",
        "blockedReason": "user_input",
        "blockedDetail": "Which invoice matches this payment?",
        "updatedAt": "2026-09-30T12:00:00Z",
        "steps": [{"key": "match", "active": True}],
    }


def test_delivers_once_per_blocking_transition_and_pins_company(setup):
    service, _, _, ctx, sent = setup
    create(setup)
    ctx.lifespan_context["api"].company_id = "new-selection"
    with patch("norman_mcp.events.service.read", side_effect=blocked):
        asyncio.run(service.tick())
        asyncio.run(service.tick())
    events = [s for s in sent if s[4].get("name")]
    assert len(events) == 1
    assert events[0][4]["data"]["company_id"] == COMPANY
    assert events[0][4]["data"]["reason"] == "user_input"
    with patch(
        "norman_mcp.events.service.read", return_value={"state": "active", "blockedReason": None}
    ):
        asyncio.run(service.tick())
    with patch("norman_mcp.events.service.read", side_effect=blocked):
        asyncio.run(service.tick())
    assert len([s for s in sent if s[4].get("name")]) == 2


def test_retries_preserve_event_id_and_do_not_send_after_access_loss(setup):
    service, _, provider, _, sent = setup
    sid = create(setup)["id"]
    original = service.post
    service.post = lambda *a, **kw: (sent.append(a), (503, {}))[1]
    with patch("norman_mcp.events.service.read", side_effect=blocked):
        asyncio.run(service.tick())
    pending = service.store.get(sid)["pending"]
    eid = pending["event"]["eventId"]
    pending["nextAttempt"] = 0
    record = service.store.get(sid)
    record["pending"] = pending
    service.store.put(record)
    with patch("norman_mcp.events.service.read", return_value={"error": "403"}):
        asyncio.run(service.tick())
    assert len(sent) == 2
    service.post = original
    with patch("norman_mcp.events.service.read", side_effect=blocked):
        asyncio.run(service.tick())
    assert sent[-1][3] == eid
    provider.tokens.clear()
    with patch("norman_mcp.events.service.read", side_effect=blocked):
        asyncio.run(service.tick())
    assert len(sent) == 3


@pytest.mark.parametrize("code", [410, 413])
def test_permanent_delivery_failures_do_not_retry(setup, code):
    service, _, _, _, sent = setup
    sid = create(setup)["id"]
    service.post = lambda *a, **kw: (sent.append(a), (code, {}))[1]
    with patch("norman_mcp.events.service.read", side_effect=blocked):
        asyncio.run(service.tick())
        asyncio.run(service.tick())
    assert len(sent) == 2
    assert (
        service.store.get(sid) is None
        if code == 410
        else service.store.get(sid)["pending"]["attempts"] == 8
    )


def test_signing_uses_exact_body_and_standard_webhooks_headers():
    body = b'{"data":"receipt"}'
    h = webhooks.headers(SECRET, "evt-1", body, "sub-1", 123)
    expected = base64.b64encode(
        hmac.new(b"k" * 32, b"evt-1.123." + body, hashlib.sha256).digest()
    ).decode()
    assert h["webhook-signature"] == "v1," + expected
    assert h["webhook-id"] == "evt-1" and h["webhook-timestamp"] == "123"


@pytest.mark.parametrize(
    "url",
    ["http://example.com", "https://user:password@example.com", "https://example.com/#fragment"],
)
def test_rejects_invalid_callback_urls(url):
    with pytest.raises(ValueError):
        webhooks.destination(url)


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.1.1.1", "169.254.169.254", "::1", "fc00::1"])
def test_blocks_private_and_local_destinations(ip):
    with (
        patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", (ip, 443))]),
        pytest.raises(ValueError),
    ):
        webhooks.destination(URL)


def test_pins_public_destination_without_second_dns_lookup():
    with patch("socket.getaddrinfo", return_value=[(2, 1, 6, "", ("8.8.8.8", 443))]):
        assert webhooks.destination(URL) == ("receiver.example.com", 443, "/callback", "8.8.8.8")
    connection = webhooks.PinnedHTTPSConnection("receiver.example.com", 443, "8.8.8.8")
    with (
        patch("socket.create_connection") as create,
        patch.object(connection._context, "wrap_socket") as wrap,
    ):
        connection.connect()
        create.assert_called_once_with(("8.8.8.8", 443), 10)
        wrap.assert_called_once_with(create.return_value, server_hostname="receiver.example.com")


@pytest.mark.parametrize("version", ["2024-11-05", "2025-03-26", "2025-06-18", "2025-11-25"])
def test_enabled_events_preserve_legacy_initialization_and_tool_calls(setup, version):
    service, *_ = setup
    server = MCPServer("events")
    register_events(server, service)

    @server.tool()
    def compatibility_probe() -> dict[str, bool]:
        return {"ok": True}

    with TestClient(
        server.streamable_http_app(stateless_http=True, json_response=True),
        base_url="http://localhost:8000",
    ) as client:
        headers = {"Accept": "application/json, text/event-stream"}
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": version,
                    "capabilities": {},
                    "clientInfo": {"name": "legacy-fixture", "version": "1"},
                },
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert result["protocolVersion"] == version
        assert "events" not in result["capabilities"]
        headers["MCP-Protocol-Version"] = version
        response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "method": "notifications/initialized"},
        )
        assert response.status_code == 202, response.text
        response = client.post(
            "/mcp",
            headers=headers,
            json={"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["tools"][0]["name"] == "compatibility_probe"
        response = client.post(
            "/mcp",
            headers=headers,
            json={
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "compatibility_probe", "arguments": {}},
            },
        )
        assert response.status_code == 200, response.text
        result = response.json()["result"]
        assert not result.get("isError")
        assert json.loads(result["content"][0]["text"]) == {"ok": True}


def test_modern_http_discovery_advertises_events_and_methods(setup):
    service, *_ = setup
    server = MCPServer("events")
    register_events(server, service)
    with TestClient(
        server.streamable_http_app(stateless_http=True, json_response=True),
        base_url="http://localhost:8000",
    ) as client:
        headers = {
            "Accept": "application/json, text/event-stream",
            "MCP-Protocol-Version": "2026-07-28",
        }
        response = client.post(
            "/mcp",
            headers={**headers, "MCP-Method": "server/discover"},
            json={
                "jsonrpc": "2.0",
                "id": 1,
                "method": "server/discover",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["capabilities"]["events"] == {}
        response = client.post(
            "/mcp",
            headers={**headers, "MCP-Method": "events/list"},
            json={
                "jsonrpc": "2.0",
                "id": 2,
                "method": "events/list",
                "params": {
                    "_meta": {
                        "io.modelcontextprotocol/protocolVersion": "2026-07-28",
                        "io.modelcontextprotocol/clientCapabilities": {},
                    }
                },
            },
        )
        assert response.status_code == 200, response.text
        assert response.json()["result"]["events"][0]["name"] == "workflow.attention_required"


def test_encryption_key_mismatch_fails_startup(setup):
    from cryptography.fernet import InvalidToken

    service, *_ = setup
    create(setup)
    with pytest.raises(InvalidToken):
        SubscriptionStore(service.store.path, Fernet.generate_key().decode())


def test_expiry_and_signing_key_rotation_are_bounded(setup):
    service, access, _, ctx, sent = setup
    first = create(setup)
    first_record = service.store.get(first["id"])
    assert first_record["expires"] <= time.time() + 3600
    new_secret = "whsec_" + base64.b64encode(b"n" * 32).decode()
    params = subscribe_params()
    params.delivery.secret = new_secret
    with patch("norman_mcp.events.service.get_access_token", return_value=access):
        result = asyncio.run(service.subscribe(ctx, params))
    record = service.store.get(result["id"])
    assert result["id"] == first["id"]
    assert record["oldSecret"] == SECRET
    assert time.time() < record["rotateUntil"] <= time.time() + 300
    assert len(sent) == 2  # Rotating the key requires fresh signed verification.
    with patch("norman_mcp.events.service.read", side_effect=blocked):
        asyncio.run(service.tick())
    assert sent[-1][5]["old_secret"] == SECRET
    record = service.store.get(first["id"])
    record["expires"] = 0
    service.store.put(record)
    asyncio.run(service.tick())
    assert service.store.get(first["id"]) is None
