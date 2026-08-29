import asyncio

from norman_mcp.api.client import NormanAPI


def test_arequest_runs_the_existing_secured_request_path(monkeypatch) -> None:
    api = NormanAPI(authenticate_on_init=False)
    calls = []

    def fake_request(method, url, params=None, json_data=None, files=None):
        calls.append((method, url, params, json_data, files))
        return {"ok": True}

    monkeypatch.setattr(api, "_make_request", fake_request)

    result = asyncio.run(
        api.arequest(
            "POST",
            "https://api.norman.finance/api/v1/example/",
            params={"page": 1},
            json_data={"name": "test"},
        ),
    )

    assert result == {"ok": True}
    assert calls == [
        (
            "POST",
            "https://api.norman.finance/api/v1/example/",
            {"page": 1},
            {"name": "test"},
            None,
        ),
    ]
