from tests.mcp_harness import FakeApi, call_tool


def test_private_client_type_reaches_the_api_as_person() -> None:
    api = FakeApi(respond={"publicId": "client-1"})

    call_tool("create_client", {"name": "Alex Müller", "client_type": "private"}, api)
    call_tool("update_client", {"client_id": "client-1", "client_type": "private"}, api)

    sent = [kwargs["json_data"]["clientType"] for method, _, kwargs in api.requests if method in ("POST", "PATCH")]
    assert sent == ["person", "person"]
