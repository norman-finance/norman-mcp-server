import asyncio
import inspect
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
import requests
from mcp.server.fastmcp import FastMCP
from pydantic.fields import FieldInfo
from urllib3.exceptions import ReadTimeoutError

from norman_mcp.files import download
from norman_mcp.tools import documents

SIGNED_URL = (
    "https://files.example/receipt.pdf?X-Amz-Signature=DO-NOT-LOG&X-Amz-Security-Token=SECRET"
)


@pytest.fixture
def temp_root(tmp_path, monkeypatch):
    monkeypatch.setattr(download.tempfile, "tempdir", str(tmp_path))
    return tmp_path


@pytest.fixture
def get_response(monkeypatch):
    response = Mock()
    response.headers = {}
    response.status_code = 200
    response.__enter__ = Mock(return_value=response)

    def close_response(*args):
        response.close()
        return False

    response.__exit__ = Mock(side_effect=close_response)
    response.iter_content.return_value = iter([b"%PDF-1.7\n", b"receipt"])
    monkeypatch.setattr(download.requests, "get", Mock(return_value=response))
    return response


def run_tool(name, api, **kwargs):
    server = FastMCP()
    documents.register_document_tools(server)
    fn = server._tool_manager._tools[name].fn
    defaults = {
        name: p.default.default
        for name, p in inspect.signature(fn).parameters.items()
        if isinstance(p.default, FieldInfo)
    }
    ctx = SimpleNamespace(request_context=SimpleNamespace(lifespan_context={"api": api}))
    return fn(ctx, **{**defaults, **kwargs})


class Api:
    company_id = "company-1"

    def __init__(self, fail=False):
        self.files = []
        self.paths = []
        self.fail = fail

    def _make_request(self, method, url, json_data=None, files=None):
        handles = list(files.values()) if isinstance(files, dict) else [h for _, h in files]
        self.files.extend(handles)
        self.paths.extend(h.name for h in handles)
        assert all(h.read().startswith(b"%PDF") for h in handles)
        if self.fail:
            raise RuntimeError("API failure")
        return {"publicId": "attachment-1"}

    async def arequest(self, *args, **kwargs):
        return self._make_request(*args, **kwargs)


@pytest.mark.parametrize(
    "header,expected",
    [
        ('attachment; filename="supplier/receipt.pdf"', "receipt.pdf"),
        ('attachment; filename="../../receipt.pdf"', "receipt.pdf"),
        ('attachment; filename="/outside/receipt.pdf"', "receipt.pdf"),
        ('attachment; filename="C:\\supplier\\receipt.pdf"', "receipt.pdf"),
        ('attachment; filename="receipt; final.pdf"', "receipt; final.pdf"),
        ("attachment; filename*=UTF-8''Rechnung%20M%C3%A4rz.pdf", "Rechnung März.pdf"),
        ('attachment; filename=".."', "downloaded_file"),
    ],
)
def test_untrusted_header_is_only_a_basename(temp_root, get_response, header, expected):
    get_response.headers = {"Content-Disposition": header}
    path = Path(asyncio.run(download.download_file(SIGNED_URL)))
    assert path.name == expected
    assert path.parent.parent == temp_root
    assert path.read_bytes() == b"%PDF-1.7\nreceipt"
    get_response.close.assert_called_once()
    documents._remove_temp_file(str(path))
    assert list(temp_root.iterdir()) == []


def test_long_unicode_filename_keeps_pdf_suffix(temp_root, get_response):
    get_response.headers = {"Content-Disposition": 'attachment; filename="' + "ü" * 300 + '.pdf"'}
    path = Path(asyncio.run(download.download_file(SIGNED_URL)))
    assert len(path.name.encode()) <= 200
    assert path.suffix == ".pdf"


def test_real_http_long_signed_query_and_3_6mb_pdf(temp_root, monkeypatch):
    payload = b"%PDF-1.7\n" + b"x" * (3_600_000 - 9)
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(self.path)
            self.send_response(200)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    target = "/receipt%20final.pdf?X-Amz-Signature=" + "a%2Fb%2Bc%3D" * 400 + "&X-Amz-Expires=1800"
    try:
        path = Path(
            asyncio.run(download.download_file(f"http://127.0.0.1:{server.server_port}{target}"))
        )
        assert seen == [target]
        assert path.name == "receipt final.pdf"
        assert path.read_bytes() == payload
    finally:
        server.shutdown()
        server.server_close()
        thread.join()


@pytest.mark.parametrize("status", [403, 404, 503])
def test_http_errors_keep_status_without_signed_url(temp_root, get_response, caplog, status):
    get_response.status_code = status
    get_response.raise_for_status.side_effect = requests.HTTPError(
        SIGNED_URL, response=get_response
    )
    with pytest.raises(download.FileDownloadError) as raised:
        asyncio.run(download.download_file(SIGNED_URL))
    assert raised.value.as_result() == {
        "error": f"File host returned HTTP {status}.",
        "code": "download_http_error",
        "http_status": status,
    }
    assert "DO-NOT-LOG" not in caplog.text
    assert "SECRET" not in caplog.text
    assert list(temp_root.iterdir()) == []
    get_response.close.assert_called_once()


@pytest.mark.parametrize(
    "error,code",
    [
        (requests.Timeout(SIGNED_URL), "download_timeout"),
        (
            requests.ConnectionError(ReadTimeoutError(None, SIGNED_URL, "timeout")),
            "download_timeout",
        ),
        (requests.ConnectionError(SIGNED_URL), "download_network_error"),
        (requests.exceptions.ChunkedEncodingError(SIGNED_URL), "download_network_error"),
        (OSError(SIGNED_URL), "download_storage_error"),
    ],
)
def test_partial_download_is_cleaned_and_error_is_safe(
    temp_root, get_response, caplog, error, code
):
    def chunks(**kwargs):
        yield b"partial PDF"
        raise error

    get_response.iter_content.side_effect = chunks
    with pytest.raises(download.FileDownloadError) as raised:
        asyncio.run(download.download_file(SIGNED_URL))
    assert raised.value.code == code
    assert "DO-NOT-LOG" not in str(raised.value) + caplog.text
    assert "SECRET" not in str(raised.value) + caplog.text
    assert list(temp_root.iterdir()) == []
    get_response.close.assert_called_once()


def test_cannot_create_temp_directory_is_storage_error(temp_root, get_response, monkeypatch):
    monkeypatch.setattr(download.tempfile, "mkdtemp", Mock(side_effect=PermissionError("denied")))
    with pytest.raises(download.FileDownloadError, match="Could not save") as raised:
        asyncio.run(download.download_file(SIGNED_URL))
    assert raised.value.code == "download_storage_error"
    get_response.close.assert_called_once()


def test_download_yields_event_loop_and_cancellation_removes_eventual_file(temp_root, get_response):
    release = threading.Event()
    started = threading.Event()

    def chunks(**kwargs):
        started.set()
        assert release.wait(3), "download blocked the event loop"
        yield b"%PDF delayed"

    get_response.iter_content.side_effect = chunks

    async def scenario():
        task = asyncio.create_task(download.download_file(SIGNED_URL))
        assert await asyncio.to_thread(started.wait, 2)
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        release.set()
        # Wait for the worker and its cleanup callback without blocking the loop.
        for _ in range(200):
            if get_response.close.called and not list(temp_root.iterdir()):
                return
            await asyncio.sleep(0.01)
        pytest.fail("abandoned download leaked a temporary file")

    try:
        asyncio.run(scenario())
    finally:
        release.set()


@pytest.mark.parametrize(
    "name,args",
    [
        ("create_attachment", {"file_url": SIGNED_URL}),
        ("upload_bulk_attachments", {"file_urls": [SIGNED_URL]}),
        ("upload_structured_attachments", {"documents": [{"file_url": SIGNED_URL}]}),
    ],
)
@pytest.mark.parametrize("fail", [False, True])
def test_tools_close_files_and_cleanup_after_upload(temp_root, get_response, name, args, fail):
    api = Api(fail=fail)
    asyncio.run(run_tool(name, api, **args))
    assert api.files
    assert all(f.closed for f in api.files)
    assert not any(Path(p).exists() for p in api.paths)
    assert list(temp_root.iterdir()) == []


@pytest.mark.parametrize(
    "name,args",
    [
        ("create_attachment", {"file_url": SIGNED_URL}),
        ("upload_bulk_attachments", {"file_urls": [SIGNED_URL]}),
        ("upload_structured_attachments", {"documents": [{"file_url": SIGNED_URL}]}),
    ],
)
def test_tools_return_download_diagnostics_without_calling_api(
    temp_root, get_response, caplog, name, args
):
    get_response.status_code = 403
    get_response.raise_for_status.side_effect = requests.HTTPError(
        SIGNED_URL, response=get_response
    )
    api = Api()
    result = asyncio.run(run_tool(name, api, **args))
    encoded = json.dumps(result)
    assert "download_http_error" in encoded
    assert '"http_status": 403' in encoded
    assert "DO-NOT-LOG" not in encoded + caplog.text
    assert "SECRET" not in encoded + caplog.text
    assert api.files == []


def test_bulk_partial_success_reports_failed_url_index(temp_root, get_response, monkeypatch):
    original = documents.download_file

    async def download_or_fail(url):
        if url == SIGNED_URL:
            raise download.FileDownloadError("download_timeout", "Download timed out.")
        return await original(url)

    monkeypatch.setattr(documents, "download_file", download_or_fail)
    api = Api()
    result = asyncio.run(
        run_tool(
            "upload_bulk_attachments", api, file_urls=[SIGNED_URL, "https://files.example/good.pdf"]
        )
    )
    assert result["publicId"] == "attachment-1"
    assert result["download_errors"] == [
        {"index": 0, "code": "download_timeout", "error": "Download timed out."}
    ]
    assert len(api.files) == 1
    assert list(temp_root.iterdir()) == []
