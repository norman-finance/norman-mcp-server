import base64
from pathlib import Path

import pytest

from norman_mcp import document_input
from norman_mcp.document_input import (
    DocumentInputError,
    normalize_document_input,
    resolve_document_input,
    safe_filename,
)
from norman_mcp.files import upload


def test_safe_filename_removes_path_traversal() -> None:
    assert safe_filename("../../invoices/April Rechnung.pdf") == "April Rechnung.pdf"
    assert safe_filename(r"..\..\secret?.pdf") == "secret_.pdf"


def test_normalizes_provider_file_object() -> None:
    payload = normalize_document_input(
        {
            "download_url": "https://files.example.test/receipt.pdf",
            "filename": "receipt.pdf",
            "media_type": "application/pdf",
        }
    )

    assert payload == {
        "url": "https://files.example.test/receipt.pdf",
        "file_ref": None,
        "content": None,
        "file_name": "receipt.pdf",
        "mime_type": "application/pdf",
        "local_path": None,
    }


def test_provider_file_id_alone_returns_actionable_error() -> None:
    with pytest.raises(DocumentInputError, match="file_id cannot be fetched"):
        normalize_document_input({"file_id": "file_123"})


def test_rejects_conflicting_sources() -> None:
    with pytest.raises(DocumentInputError, match="exactly one file source"):
        normalize_document_input(
            {
                "download_url": "https://files.example.test/receipt.pdf",
                "file_ref": "ref_123",
            }
        )


def test_inline_base64_is_written_with_sanitized_name_and_cleaned_up() -> None:
    payload = normalize_document_input(
        {
            "file_data": base64.b64encode(b"pdf bytes").decode(),
            "file_name": "../../receipt.pdf",
        }
    )

    resolved = resolve_document_input(payload)
    path = Path(resolved.path)
    try:
        assert path.name == "receipt.pdf"
        assert path.read_bytes() == b"pdf bytes"
    finally:
        resolved.cleanup()

    assert not path.exists()


def test_inline_base64_enforces_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(document_input, "MAX_INLINE_BYTES", 2)
    payload = normalize_document_input(
        {
            "file_data": base64.b64encode(b"too large").decode(),
            "file_name": "receipt.pdf",
        }
    )

    with pytest.raises(DocumentInputError, match="Inline files are limited"):
        resolve_document_input(payload)


def test_http_document_url_is_rejected_before_download() -> None:
    payload = normalize_document_input(file_url="http://files.example.test/receipt.pdf")

    with pytest.raises(DocumentInputError, match="must use HTTPS"):
        resolve_document_input(payload)


def test_file_ref_uses_server_resolver(tmp_path: Path) -> None:
    source = tmp_path / "receipt.pdf"
    source.write_bytes(b"receipt")
    payload = normalize_document_input(file_ref="ref_123")

    resolved = resolve_document_input(
        payload,
        file_ref_resolver=lambda ref: str(source) if ref == "ref_123" else None,
    )

    assert resolved.path == str(source)
    assert resolved.temporary is False


def test_client_local_path_is_rejected_by_default(tmp_path: Path) -> None:
    source = tmp_path / "receipt.pdf"
    source.write_bytes(b"receipt")
    payload = normalize_document_input(file_path=str(source))

    with pytest.raises(DocumentInputError, match="cannot access client-local paths"):
        resolve_document_input(payload)


def test_store_file_sanitizes_name_and_enforces_size(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setattr(upload, "_upload_dir", tmp_path)
    monkeypatch.setattr(upload, "MAX_FILE_SIZE", 4)
    upload._refs.clear()

    ref = upload.store_file(b"data", "../../receipt.pdf")
    stored_path = Path(upload.resolve_ref(ref) or "")

    assert stored_path.parent == tmp_path
    assert stored_path.name.endswith("_receipt.pdf")
    assert stored_path.read_bytes() == b"data"

    with pytest.raises(ValueError, match="Empty file"):
        upload.store_file(b"", "empty.pdf")
    with pytest.raises(ValueError, match="exceeds maximum size"):
        upload.store_file(b"large", "large.pdf")
