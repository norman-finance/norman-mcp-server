import asyncio
import base64
import json
import time
from types import SimpleNamespace

import httpx

from norman_mcp import context
from norman_mcp.auth import provider as provider_module
from norman_mcp.auth.provider import NormanOAuthProvider


def _token(**claims):
    def encode(value):
        return base64.urlsafe_b64encode(json.dumps(value).encode()).rstrip(b"=").decode()

    return f"{encode({'alg': 'none'})}.{encode(claims)}.signature"


def _provider():
    provider = NormanOAuthProvider.__new__(NormanOAuthProvider)
    provider.tokens = {}
    provider._first_party_tokens = {}
    return provider


def test_first_party_norman_token_is_validated_and_cached(monkeypatch):
    token = _token(
        norman_mcp_first_party=True,
        company_id="company-1",
        exp=time.time() + 300,
    )
    requests = []

    def handler(request):
        requests.append(request)
        assert request.url.path == "/api/v1/companies/company-1/"
        assert request.headers["Authorization"] == f"Bearer {token}"
        return httpx.Response(200, json={"publicId": "company-1"})

    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(handler)
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        provider_module,
        "config",
        SimpleNamespace(internal_api_base_url="https://api.example.test/"),
    )

    provider = _provider()

    async def exercise():
        first = await provider.load_access_token(token)
        second = await provider.load_access_token(token)
        assert context.get_api_token() == token
        assert context.get_api_company_id() == "company-1"
        return first, second

    first, second = asyncio.run(exercise())

    assert first is not None
    assert second is first
    assert len(requests) == 1


def test_first_party_token_rejects_failed_norman_api_validation(monkeypatch):
    token = _token(
        norman_mcp_first_party=True,
        company_id="company-foreign",
        exp=time.time() + 300,
    )
    real_client = httpx.AsyncClient
    transport = httpx.MockTransport(lambda _request: httpx.Response(404))
    monkeypatch.setattr(
        provider_module.httpx,
        "AsyncClient",
        lambda **kwargs: real_client(transport=transport, **kwargs),
    )
    monkeypatch.setattr(
        provider_module,
        "config",
        SimpleNamespace(internal_api_base_url="https://api.example.test/"),
    )

    assert asyncio.run(_provider().load_access_token(token)) is None


def test_unmarked_bearer_is_not_sent_to_norman_api(monkeypatch):
    def fail_client(**_kwargs):
        raise AssertionError("unmarked bearer must not trigger API validation")

    monkeypatch.setattr(provider_module.httpx, "AsyncClient", fail_client)

    assert asyncio.run(_provider().load_access_token("not-a-first-party-token")) is None
