"""Portable and safe file inputs for MCP document tools.

MCP clients do not share one attachment transport. ChatGPT can inject a
structured file object, while Claude and generic clients normally provide a
signed URL, a Norman upload reference, or (for tiny files) inline base64.
This module normalizes those transports before the existing Norman attachment
API stores and processes the document.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import re
import shutil
import socket
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Callable, Mapping
from urllib.parse import unquote, urljoin, urlparse

import requests

MAX_INLINE_BYTES = int(os.environ.get("MCP_INLINE_FILE_MAX_SIZE", str(50 * 1024)))
MAX_REMOTE_BYTES = int(os.environ.get("MCP_ATTACHMENT_MAX_SIZE", str(10 * 1024 * 1024)))
MAX_REDIRECTS = 3


class DocumentInputError(ValueError):
    """Raised when a client-provided file cannot be accepted safely."""


@dataclass(frozen=True)
class ResolvedDocument:
    path: str
    temporary: bool = False

    @property
    def filename(self) -> str:
        return os.path.basename(self.path)

    def cleanup(self) -> None:
        if self.temporary:
            shutil.rmtree(os.path.dirname(self.path), ignore_errors=True)


def safe_filename(value: str | None, default: str = "upload") -> str:
    """Return a basename that cannot escape the temporary upload directory."""
    raw = unquote(value or "").replace("\\", "/")
    name = raw.rsplit("/", 1)[-1].strip().strip(".")
    name = re.sub(r"[^A-Za-z0-9._ -]+", "_", name)
    name = re.sub(r"\s+", " ", name).strip()
    return name[:180] or default


def normalize_document_input(
    file: Mapping[str, Any] | None = None,
    *,
    file_url: str | None = None,
    file_ref: str | None = None,
    file_content_base64: str | None = None,
    file_name: str | None = None,
    file_path: str | None = None,
) -> dict[str, Any]:
    """Normalize provider-native and portable MCP file arguments."""
    if file is not None and not isinstance(file, Mapping):
        raise DocumentInputError(
            "file must be an object containing download_url, file_ref, or file_data."
        )
    payload = dict(file or {})
    url = payload.get("download_url") or payload.get("file_url") or payload.get("url") or file_url
    ref = payload.get("file_ref") or file_ref
    content = (
        payload.get("file_data")
        or payload.get("file_content_base64")
        or payload.get("content")
        or file_content_base64
    )
    name = payload.get("file_name") or payload.get("filename") or payload.get("name") or file_name
    provider_id = payload.get("file_id") or payload.get("id")

    if file_path:
        parsed = urlparse(file_path)
        if parsed.scheme in {"http", "https"}:
            url = url or file_path
        else:
            payload["local_path"] = file_path

    sources = [bool(url), bool(ref), bool(content), bool(payload.get("local_path"))]
    if sum(sources) > 1:
        raise DocumentInputError(
            "Provide exactly one file source: download_url/file_url, file_ref, "
            "file_data (base64), or a supported local path."
        )
    if not any(sources):
        if provider_id:
            raise DocumentInputError(
                "The provider file_id cannot be fetched by Norman. Pass the client-provided "
                "download_url as file.download_url, or upload the file with request_file_upload "
                "and pass the resulting file_ref."
            )
        raise DocumentInputError(
            "Provide a file object, file_url, file_ref, or small base64 file content."
        )

    return {
        "url": url,
        "file_ref": ref,
        "content": content,
        "file_name": name,
        "mime_type": payload.get("mime_type") or payload.get("media_type"),
        "local_path": payload.get("local_path"),
    }


def _validate_remote_url(url: str) -> None:
    parsed = urlparse(url)
    allowed_schemes = {"https"}
    if os.environ.get("MCP_ALLOW_INSECURE_FILE_URLS", "").lower() in {"1", "true", "yes"}:
        allowed_schemes.add("http")
    if parsed.scheme.lower() not in allowed_schemes:
        raise DocumentInputError("Document URLs must use HTTPS.")
    if not parsed.hostname or parsed.username or parsed.password:
        raise DocumentInputError(
            "Document URL must have a valid public host and no embedded credentials."
        )

    try:
        addresses = socket.getaddrinfo(parsed.hostname, parsed.port or 443, type=socket.SOCK_STREAM)
    except socket.gaierror as exc:
        raise DocumentInputError("Document URL host could not be resolved.") from exc

    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if any(
            (
                ip.is_private,
                ip.is_loopback,
                ip.is_link_local,
                ip.is_multicast,
                ip.is_reserved,
                ip.is_unspecified,
            )
        ):
            raise DocumentInputError("Document URL must resolve only to public internet addresses.")


def _content_disposition_filename(value: str | None) -> str | None:
    if not value:
        return None
    match = re.search(r"filename\*?=(?:UTF-8''|\")?([^\";]+)", value, re.IGNORECASE)
    return unquote(match.group(1).strip()) if match else None


def _download_remote(url: str, requested_name: str | None) -> ResolvedDocument:
    session = requests.Session()
    session.trust_env = False
    current_url = url

    try:
        for redirect_count in range(MAX_REDIRECTS + 1):
            _validate_remote_url(current_url)
            response = session.get(current_url, stream=True, timeout=(5, 30), allow_redirects=False)
            if response.is_redirect or response.is_permanent_redirect:
                if redirect_count >= MAX_REDIRECTS:
                    response.close()
                    raise DocumentInputError("Document URL redirected too many times.")
                location = response.headers.get("location")
                response.close()
                if not location:
                    raise DocumentInputError("Document URL returned an invalid redirect.")
                current_url = urljoin(current_url, location)
                continue

            try:
                response.raise_for_status()
                declared_size = response.headers.get("content-length")
                if declared_size:
                    try:
                        exceeds_limit = int(declared_size) > MAX_REMOTE_BYTES
                    except (TypeError, ValueError):
                        exceeds_limit = False
                    if exceeds_limit:
                        raise DocumentInputError(
                            f"Document exceeds the {MAX_REMOTE_BYTES // (1024 * 1024)} MB upload limit."
                        )

                fallback_name = os.path.basename(urlparse(current_url).path) or "download"
                filename = safe_filename(
                    requested_name
                    or _content_disposition_filename(response.headers.get("content-disposition"))
                    or fallback_name
                )
                temp_dir = tempfile.mkdtemp(prefix="norman_document_")
                temp_path = os.path.join(temp_dir, filename)
                size = 0
                try:
                    with open(temp_path, "wb") as output:
                        for chunk in response.iter_content(chunk_size=64 * 1024):
                            if not chunk:
                                continue
                            size += len(chunk)
                            if size > MAX_REMOTE_BYTES:
                                raise DocumentInputError(
                                    f"Document exceeds the {MAX_REMOTE_BYTES // (1024 * 1024)} MB upload limit."
                                )
                            output.write(chunk)
                except Exception:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise
                if size == 0:
                    shutil.rmtree(temp_dir, ignore_errors=True)
                    raise DocumentInputError("Downloaded document is empty.")
                return ResolvedDocument(path=temp_path, temporary=True)
            finally:
                response.close()
    except requests.RequestException as exc:
        raise DocumentInputError(f"Could not download the document: {exc}") from exc
    finally:
        session.close()

    raise DocumentInputError("Could not download the document.")


def _decode_inline(content: str, requested_name: str | None) -> ResolvedDocument:
    raw = content.split(",", 1)[1] if content.startswith("data:") and "," in content else content
    raw = re.sub(r"\s+", "", raw)
    if len(raw) > ((MAX_INLINE_BYTES + 2) // 3) * 4 + 8:
        raise DocumentInputError(f"Inline files are limited to {MAX_INLINE_BYTES // 1024} KB.")
    try:
        decoded = base64.b64decode(raw, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise DocumentInputError("Inline file content is not valid base64.") from exc
    if not decoded:
        raise DocumentInputError("Inline file content is empty.")
    if len(decoded) > MAX_INLINE_BYTES:
        raise DocumentInputError(f"Inline files are limited to {MAX_INLINE_BYTES // 1024} KB.")

    temp_dir = tempfile.mkdtemp(prefix="norman_document_")
    temp_path = os.path.join(temp_dir, safe_filename(requested_name))
    Path(temp_path).write_bytes(decoded)
    return ResolvedDocument(path=temp_path, temporary=True)


def resolve_document_input(
    payload: Mapping[str, Any],
    *,
    file_ref_resolver: Callable[[str], str | None] | None = None,
    allow_local_paths: bool = False,
) -> ResolvedDocument:
    """Resolve one normalized input to a readable file path."""
    if payload.get("url"):
        return _download_remote(str(payload["url"]), payload.get("file_name"))
    if payload.get("content"):
        return _decode_inline(str(payload["content"]), payload.get("file_name"))
    if payload.get("file_ref"):
        if not file_ref_resolver:
            raise DocumentInputError(
                "file_ref is not supported by this server. Pass a signed HTTPS download_url instead."
            )
        path = file_ref_resolver(str(payload["file_ref"]))
        if not path or not os.path.isfile(path):
            raise DocumentInputError(
                "file_ref was not found or has expired. Upload the file again."
            )
        return ResolvedDocument(path=path)
    if payload.get("local_path"):
        if not allow_local_paths:
            raise DocumentInputError(
                "The remote MCP server cannot access client-local paths. Pass a signed HTTPS URL or file_ref."
            )
        path = os.path.abspath(str(payload["local_path"]))
        if not os.path.isfile(path):
            raise DocumentInputError("Local document path does not exist.")
        if os.path.getsize(path) > MAX_REMOTE_BYTES:
            raise DocumentInputError(
                f"Document exceeds the {MAX_REMOTE_BYTES // (1024 * 1024)} MB upload limit."
            )
        return ResolvedDocument(path=path)
    raise DocumentInputError("No document source was provided.")
