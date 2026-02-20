"""Temporary file upload endpoint.

Accepts multipart file uploads via ``POST /files/upload`` and stores them in
a time-limited temporary directory.  Returns a short ``file_ref`` token that
MCP tools (``create_attachment``, ``upload_bulk_attachments``) accept in place
of ``file_content_base64``, avoiding the need to push large binary blobs
through the LLM context window.

Files are cleaned up after ``MAX_AGE_SECONDS`` (default 30 min).
"""

import logging
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Tuple

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)

MAX_AGE_SECONDS = int(os.environ.get("MCP_UPLOAD_MAX_AGE", "1800"))
MAX_FILE_SIZE = int(os.environ.get("MCP_UPLOAD_MAX_SIZE", str(50 * 1024 * 1024)))  # 50 MB

_upload_dir: Path | None = None
_refs: Dict[str, Tuple[str, float]] = {}  # file_ref → (abs_path, created_at)
_lock = threading.Lock()


def _get_upload_dir() -> Path:
    global _upload_dir
    if _upload_dir is None or not _upload_dir.exists():
        _upload_dir = Path(tempfile.mkdtemp(prefix="norman_uploads_"))
        logger.info("Upload temp dir: %s", _upload_dir)
    return _upload_dir


def _cleanup_expired() -> None:
    """Remove uploads older than MAX_AGE_SECONDS."""
    now = time.time()
    expired = [ref for ref, (_, ts) in _refs.items() if now - ts > MAX_AGE_SECONDS]
    for ref in expired:
        path, _ = _refs.pop(ref, (None, 0))
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass


def store_file(data: bytes, filename: str) -> str:
    """Store raw bytes and return a ``file_ref`` token."""
    with _lock:
        _cleanup_expired()
        ref = f"ref_{secrets.token_urlsafe(16)}"
        dest = _get_upload_dir() / f"{ref}_{filename}"
        dest.write_bytes(data)
        _refs[ref] = (str(dest), time.time())
        logger.info("Stored upload %s (%d bytes) → %s", ref, len(data), dest.name)
        return ref


def resolve_ref(file_ref: str) -> str | None:
    """Return the absolute path for *file_ref*, or ``None`` if expired/missing."""
    with _lock:
        _cleanup_expired()
        entry = _refs.get(file_ref)
        if not entry:
            return None
        path, _ = entry
        if not os.path.exists(path):
            _refs.pop(file_ref, None)
            return None
        return path


# ── HTTP handler ────────────────────────────────────────────────────

async def _handle_upload(request: Request) -> JSONResponse:
    """``POST /files/upload`` — multipart form with one ``file`` field."""
    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return JSONResponse(
            {"error": "Content-Type must be multipart/form-data"},
            status_code=400,
        )

    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse(
            {"error": "Missing 'file' field in multipart form"},
            status_code=400,
        )

    data = await upload.read()
    if len(data) > MAX_FILE_SIZE:
        return JSONResponse(
            {"error": f"File exceeds maximum size ({MAX_FILE_SIZE // (1024*1024)} MB)"},
            status_code=413,
        )
    if len(data) == 0:
        return JSONResponse({"error": "Empty file"}, status_code=400)

    filename = getattr(upload, "filename", None) or "upload"
    ref = store_file(data, filename)

    return JSONResponse({
        "file_ref": ref,
        "filename": filename,
        "size": len(data),
        "expires_in_seconds": MAX_AGE_SECONDS,
    })


def create_file_upload_routes() -> List[Route]:
    return [
        Route("/files/upload", _handle_upload, methods=["POST"]),
    ]
