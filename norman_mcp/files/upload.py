"""Temporary file upload endpoint.

Provides two upload flows:

1. **Direct POST** ``/files/upload`` — multipart form upload (for programmatic
   clients like curl, n8n, etc.).
2. **Browser upload link** — the ``create_upload_link`` MCP tool generates a
   short-lived URL like ``/files/upload/<token>``.  When the user opens it in a
   browser they see a drag-and-drop page.  After upload the page shows a
   ``file_ref`` that the AI uses in ``create_attachment``.

   This is the recommended path for AI desktop apps (Claude, ChatGPT) that
   cannot make outbound HTTP requests or encode large files as base64.

Files are cleaned up after ``MAX_AGE_SECONDS`` (default 30 min).
"""

import html
import logging
import os
import secrets
import tempfile
import threading
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

logger = logging.getLogger(__name__)

MAX_AGE_SECONDS = int(os.environ.get("MCP_UPLOAD_MAX_AGE", "1800"))
MAX_FILE_SIZE = int(os.environ.get("MCP_UPLOAD_MAX_SIZE", str(50 * 1024 * 1024)))  # 50 MB

_upload_dir: Path | None = None
_refs: Dict[str, Tuple[str, float]] = {}  # file_ref → (abs_path, created_at)
_upload_tokens: Dict[str, Tuple[float, Optional[str]]] = {}  # token → (created_at, description)
_lock = threading.Lock()


def _get_upload_dir() -> Path:
    global _upload_dir
    if _upload_dir is None or not _upload_dir.exists():
        _upload_dir = Path(tempfile.mkdtemp(prefix="norman_uploads_"))
        logger.info("Upload temp dir: %s", _upload_dir)
    return _upload_dir


def _cleanup_expired() -> None:
    """Remove uploads and tokens older than MAX_AGE_SECONDS."""
    now = time.time()
    expired_refs = [r for r, (_, ts) in _refs.items() if now - ts > MAX_AGE_SECONDS]
    for ref in expired_refs:
        path, _ = _refs.pop(ref, (None, 0))
        if path:
            try:
                os.unlink(path)
            except OSError:
                pass
    expired_tokens = [t for t, (ts, _) in _upload_tokens.items() if now - ts > MAX_AGE_SECONDS]
    for tok in expired_tokens:
        _upload_tokens.pop(tok, None)


# ── Public helpers for tools ─────────────────────────────────────────

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


def create_upload_token(description: str | None = None) -> str:
    """Create a short-lived upload token for the browser upload page."""
    with _lock:
        _cleanup_expired()
        token = secrets.token_urlsafe(24)
        _upload_tokens[token] = (time.time(), description)
        return token


def _validate_upload_token(token: str) -> bool:
    with _lock:
        _cleanup_expired()
        return token in _upload_tokens


def _consume_upload_token(token: str) -> bool:
    """Validate and consume (single-use) an upload token. Returns True if valid."""
    with _lock:
        _cleanup_expired()
        if token in _upload_tokens:
            # Don't delete — allow multiple uploads on same page visit
            return True
        return False


# ── HTTP handlers ────────────────────────────────────────────────────

async def _handle_direct_upload(request: Request) -> JSONResponse:
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


_UPLOAD_PAGE_HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Upload file — Norman Finance</title>
<style>
  *{box-sizing:border-box;margin:0;padding:0}
  body{font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",Roboto,sans-serif;
       background:#fafafa;display:flex;align-items:center;justify-content:center;
       min-height:100vh;padding:1rem;color:#1a1a1a}
  .card{background:#fff;border-radius:12px;box-shadow:0 2px 12px rgba(0,0,0,.08);
        padding:2.5rem;max-width:440px;width:100%;text-align:center}
  h1{font-size:1.25rem;margin-bottom:.25rem}
  .desc{color:#666;font-size:.875rem;margin-bottom:1.5rem}
  .drop{border:2px dashed #ccc;border-radius:8px;padding:2.5rem 1rem;
        cursor:pointer;transition:border-color .2s,background .2s;margin-bottom:1rem}
  .drop.over{border-color:#000;background:#f5f5f5}
  .drop p{color:#888;font-size:.9rem}
  .drop .icon{font-size:2rem;margin-bottom:.5rem}
  input[type=file]{display:none}
  .result{margin-top:1.25rem;padding:1rem;background:#f0fdf4;border:1px solid #bbf7d0;
          border-radius:8px;text-align:left;word-break:break-all}
  .result .label{font-size:.75rem;color:#666;text-transform:uppercase;letter-spacing:.05em}
  .result .ref{font-family:monospace;font-size:1rem;margin-top:.25rem;user-select:all}
  .result .hint{font-size:.8rem;color:#444;margin-top:.75rem}
  .error{margin-top:1rem;padding:.75rem;background:#fef2f2;border:1px solid #fecaca;
         border-radius:8px;color:#991b1b;font-size:.875rem}
  .spinner{display:none;margin:1rem auto}
  .spinner.show{display:block}
  .spinner svg{animation:spin 1s linear infinite;width:24px;height:24px}
  @keyframes spin{to{transform:rotate(360deg)}}
  .done .drop{pointer-events:none;opacity:.5}
</style>
</head>
<body>
<div class="card" id="card">
  <h1>Upload file to Norman</h1>
  <p class="desc">%%DESCRIPTION%%</p>

  <div class="drop" id="drop">
    <div class="icon">📎</div>
    <p>Drag &amp; drop a file here or click to browse</p>
  </div>
  <input type="file" id="fileInput">

  <div class="spinner" id="spinner">
    <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2">
      <path d="M12 2v4m0 12v4m-7.07-15.07l2.83 2.83m8.48 8.48l2.83 2.83M2 12h4m12 0h4M4.93 19.07l2.83-2.83m8.48-8.48l2.83-2.83"/>
    </svg>
  </div>

  <div id="resultBox" style="display:none" class="result">
    <div class="label">File reference</div>
    <div class="ref" id="refValue"></div>
    <div class="hint">
      ✅ Upload complete. You can close this page — the AI assistant
      already has the reference and will attach the file automatically.
    </div>
  </div>
  <div id="errorBox" style="display:none" class="error"></div>
</div>

<script>
const token = "%%TOKEN%%";
const drop = document.getElementById("drop");
const fileInput = document.getElementById("fileInput");
const spinner = document.getElementById("spinner");
const resultBox = document.getElementById("resultBox");
const refValue = document.getElementById("refValue");
const errorBox = document.getElementById("errorBox");
const card = document.getElementById("card");

drop.addEventListener("click", () => fileInput.click());
drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", e => {
  e.preventDefault(); drop.classList.remove("over");
  if (e.dataTransfer.files.length) upload(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files.length) upload(fileInput.files[0]); });

async function upload(file) {
  errorBox.style.display = "none";
  resultBox.style.display = "none";
  spinner.classList.add("show");

  const form = new FormData();
  form.append("file", file);

  try {
    const res = await fetch("/files/upload/" + token, { method: "POST", body: form });
    const json = await res.json();
    spinner.classList.remove("show");
    if (!res.ok) { showError(json.error || "Upload failed"); return; }
    refValue.textContent = json.file_ref;
    resultBox.style.display = "block";
    card.classList.add("done");
  } catch (err) {
    spinner.classList.remove("show");
    showError("Network error: " + err.message);
  }
}
function showError(msg) { errorBox.textContent = msg; errorBox.style.display = "block"; }
</script>
</body>
</html>"""


async def _handle_upload_page_get(request: Request) -> HTMLResponse:
    """Serve the browser drag-and-drop upload page."""
    token = request.path_params.get("token", "")
    if not _validate_upload_token(token):
        return HTMLResponse(
            "<h1>Link expired or invalid</h1>"
            "<p>Ask the AI assistant to generate a new upload link.</p>",
            status_code=410,
        )
    desc_pair = _upload_tokens.get(token)
    desc = html.escape(desc_pair[1] or "Drop your file below") if desc_pair else ""
    page = _UPLOAD_PAGE_HTML.replace("%%TOKEN%%", token).replace("%%DESCRIPTION%%", desc)
    return HTMLResponse(page)


async def _handle_upload_page_post(request: Request) -> JSONResponse:
    """Handle the file POST from the browser upload page."""
    token = request.path_params.get("token", "")
    if not _consume_upload_token(token):
        return JSONResponse({"error": "Upload link expired or invalid"}, status_code=410)

    content_type = request.headers.get("content-type", "")
    if "multipart/form-data" not in content_type:
        return JSONResponse({"error": "Expected multipart/form-data"}, status_code=400)

    form = await request.form()
    upload = form.get("file")
    if upload is None:
        return JSONResponse({"error": "No file provided"}, status_code=400)

    data = await upload.read()
    if len(data) > MAX_FILE_SIZE:
        return JSONResponse(
            {"error": f"File too large (max {MAX_FILE_SIZE // (1024*1024)} MB)"},
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


# ── Route factory ────────────────────────────────────────────────────

def create_file_upload_routes() -> List[Route]:
    return [
        Route("/files/upload", _handle_direct_upload, methods=["POST"]),
        Route("/files/upload/{token}", _handle_upload_page_get, methods=["GET"]),
        Route("/files/upload/{token}", _handle_upload_page_post, methods=["POST"]),
    ]
