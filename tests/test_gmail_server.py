import asyncio
import time

import jwt
from pytest import MonkeyPatch

from norman_mcp.gmail_server import NormanInternalTokenVerifier, create_gmail_app


def test_internal_token_verifier_requires_expected_audience() -> None:
    verifier = NormanInternalTokenVerifier("internal-secret")
    valid = jwt.encode(
        {
            "sub": "connection-id",
            "aud": "gmail-mcp",
            "exp": int(time.time()) + 60,
        },
        "internal-secret",
        algorithm="HS256",
    )
    wrong_audience = jwt.encode(
        {
            "sub": "connection-id",
            "aud": "another-service",
            "exp": int(time.time()) + 60,
        },
        "internal-secret",
        algorithm="HS256",
    )

    access = asyncio.run(verifier.verify_token(valid))
    assert access is not None
    assert access.client_id == "connection-id"
    assert asyncio.run(verifier.verify_token(wrong_audience)) is None


def test_gmail_adapter_exposes_only_read_tools(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("MCP_INTERNAL_JWT_SECRET", "internal-secret")
    monkeypatch.setenv("NORMAN_API_BASE_URL", "http://backend:8000/")
    monkeypatch.setenv("GMAIL_MCP_RESOURCE_URL", "http://gmail-mcp:8080/mcp")

    app = create_gmail_app()
    tools = asyncio.run(app.list_tools())

    assert {tool.name for tool in tools} == {
        "get_profile",
        "search_receipts",
        "get_receipt_candidate",
        "fetch_receipt_attachment",
    }
