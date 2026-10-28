"""Bounded, grant/company-scoped document uploads for the MCP App.

Only metadata is persisted. Bytes are spooled for the current request and sent
once to Norman's existing attachment API. An ambiguous upstream outcome is
never automatically retried. SQLite must live on the same persistent volume
as the OAuth registry (all workers must share it; separate hosts need shared
storage/routing). No OAuth credentials are stored in this database or UI.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import re
import secrets
import sqlite3
import time
from contextlib import contextmanager
from pathlib import Path
from typing import Any
from urllib.parse import urljoin

import httpx
from starlette.datastructures import UploadFile
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import HTMLResponse, JSONResponse
from starlette.routing import Route

from norman_mcp import config
from norman_mcp.context import get_oauth_provider

TTL = 1800
MAX_FILE_SIZE = 10_000_000  # Norman's MAX_ATTACHMENT_FILE_SIZE
MAX_TOTAL_SIZE = 100_000_000
MAX_FILES = 20
EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".webp", ".xml"}
DENIED = "Upload session expired or unavailable. Open a new upload panel."
UNKNOWN = (
    "The upload outcome is unconfirmed. Check your documents in Norman before uploading again."
)


def digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def grant_key(provider: Any, access: Any) -> str:
    return digest(access.client_id + ":" + provider.grant_for_token(access.token))


def public_url() -> str:
    return os.environ.get("NORMAN_MCP_PUBLIC_URL", "https://mcp.norman.finance").rstrip("/")


def database_path() -> Path:
    state = Path(
        os.environ.get("MCP_OAUTH_STATE_FILE", str(Path.home() / ".norman-mcp/oauth_state.json"))
    )
    return Path(
        os.environ.get("MCP_UPLOAD_STATE_FILE", str(state.with_name("document_uploads.sqlite3")))
    )


class UploadError(Exception):
    def __init__(self, message: str, status: int = 400):
        self.message, self.status = message, status
        super().__init__(message)


class UploadStore:
    def __init__(self, path: Path | None = None):
        self.path = path or database_path()
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        # Restrict permissions before sqlite opens the database.
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS sessions (
                    id TEXT PRIMARY KEY, ticket_hash TEXT UNIQUE, grant_key TEXT,
                    company TEXT, selection TEXT, name TEXT, country TEXT, expires REAL
                );
                CREATE TABLE IF NOT EXISTS files (
                    session TEXT REFERENCES sessions(id) ON DELETE CASCADE,
                    id TEXT, name TEXT, size INTEGER, sha256 TEXT, cashflow TEXT,
                    state TEXT, result TEXT, PRIMARY KEY(session, id)
                );
            """)

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        db.execute("PRAGMA foreign_keys=ON")
        try:
            with db:
                yield db
        finally:
            db.close()

    def create(self, grant: str, company: str, selection: str | None, name: str, country: str):
        session_id, ticket = secrets.token_urlsafe(24), secrets.token_urlsafe(32)
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            db.execute("DELETE FROM sessions WHERE expires < ?", (time.time(),))
            if (
                db.execute("SELECT COUNT(*) FROM sessions WHERE grant_key=?", (grant,)).fetchone()[
                    0
                ]
                >= 8
            ):
                raise UploadError(
                    "Too many active upload panels. Retry after an existing panel expires.", 429
                )
            if db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] >= 512:
                raise UploadError("Upload service is busy. Try again later.", 429)
            db.execute(
                "INSERT INTO sessions VALUES (?,?,?,?,?,?,?,?)",
                (
                    session_id,
                    digest(ticket),
                    grant,
                    company,
                    selection,
                    name,
                    country,
                    time.time() + TTL,
                ),
            )
        return session_id, ticket

    def session(self, *, ticket: str | None = None, session_id: str | None = None):
        with self.connect() as db:
            row = db.execute(
                "SELECT * FROM sessions WHERE " + ("ticket_hash=?" if ticket else "id=?"),
                (digest(ticket) if ticket else session_id,),
            ).fetchone()
        if not row or row["expires"] <= time.time():
            raise UploadError(DENIED, 410)
        return dict(row)

    def summary(self, session: dict) -> dict:
        with self.connect() as db:
            rows = db.execute(
                "SELECT id,name,cashflow,state,result FROM files WHERE session=? ORDER BY rowid",
                (session["id"],),
            ).fetchall()
        files = []
        for row in rows:
            result = json.loads(row["result"]) if row["result"] else {"error": UNKNOWN}
            files.append(
                {
                    "id": row["id"],
                    "file_name": row["name"],
                    "cashflow_type": row["cashflow"],
                    "status": row["state"],
                    **result,
                }
            )
        return {
            "session_id": session["id"],
            "company_id": session["company"],
            "company_name": session["name"],
            "country": session["country"],
            "files": files,
            "uploaded_count": sum(f["status"] == "uploaded" for f in files),
            "expires_at": session["expires"],
            "instructions": "Uploaded documents already exist in Norman. Do not create them again. OCR may still be pending; bookkeeping is not finalized.",
        }

    def reserve(self, session: dict, file_id: str, name: str, size: int, sha: str, cashflow: str):
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute(
                "SELECT * FROM files WHERE session=? AND id=?", (session["id"], file_id)
            ).fetchone()
            if row:
                if (row["sha256"], row["cashflow"], row["name"]) != (sha, cashflow, name):
                    raise UploadError(
                        "This file changed after an upload attempt. Check the existing result first.",
                        409,
                    )
                # This includes in-flight/uncertain requests: never replay a POST.
                return (
                    json.loads(row["result"])
                    if row["result"]
                    else {"status": "unknown", "error": UNKNOWN}
                )
            count, total = db.execute(
                "SELECT COUNT(*), COALESCE(SUM(size),0) FROM files WHERE session=?",
                (session["id"],),
            ).fetchone()
            if count >= MAX_FILES or total + size > MAX_TOTAL_SIZE:
                raise UploadError("Upload panel limit reached (20 files, 100 MB total).", 413)
            # Duplicate bytes in the same panel are not uploaded a second time,
            # even if a file is reselected and receives a fresh UI id.
            duplicate = db.execute(
                "SELECT * FROM files WHERE session=? AND sha256=?", (session["id"], sha)
            ).fetchone()
            if duplicate:
                raise UploadError(
                    "This document has already been attempted in this panel. Check its result before retrying.",
                    409,
                )
            db.execute(
                "INSERT INTO files VALUES (?,?,?,?,?,?,?,NULL)",
                (session["id"], file_id, name, size, sha, cashflow, "unknown"),
            )
        return None

    def finish(self, session_id: str, file_id: str, result: dict):
        with self.connect() as db:
            db.execute(
                "UPDATE files SET state=?,result=? WHERE session=? AND id=?",
                (result["status"], json.dumps(result), session_id, file_id),
            )


def current_access(session: dict, provider: Any):
    if not provider:
        raise UploadError(DENIED, 401)
    # A refreshed MCP token may replace the original token; the grant is stable.
    accesses = [
        a
        for a in list(provider.tokens.values())
        if grant_key(provider, a) == session["grant_key"]
        and (a.expires_at is None or a.expires_at > time.time())
    ]
    accesses.sort(key=lambda a: a.expires_at or float("inf"), reverse=True)
    if not accesses:
        raise UploadError(DENIED, 401)
    access = accesses[0]
    selection = provider.get_company_for_token(access.token)
    if selection != session["selection"] or not provider.get_norman_token(access.token):
        raise UploadError("The active company or connection changed. Open a new upload panel.", 409)
    return access


async def post_attachment(
    provider: Any, access: Any, company: str, upload: UploadFile, name: str, cashflow: str
) -> dict:
    """One write, with only a definitive 401 eligible for credential refresh."""
    url = urljoin(config.api_base_url, f"api/v1/companies/{company}/attachments/")
    data = {
        "company": company,
        "cashflow_type": cashflow,
        "attachment_type": "invoice" if cashflow == "INCOME" else "receipt",
    }
    try:
        async with httpx.AsyncClient(
            timeout=120, follow_redirects=False, trust_env=False
        ) as client:
            for attempt in range(2):
                token = provider.get_norman_token(access.token)
                if not token:
                    return {
                        "status": "rejected",
                        "error": "Reconnect Norman and open a new upload panel.",
                    }
                await upload.seek(0)
                response = await client.post(
                    url,
                    data=data,
                    files={
                        "file": (
                            name,
                            upload.file,
                            upload.content_type or "application/octet-stream",
                        )
                    },
                    headers={"Authorization": "Bearer " + token, "X-Company-Id": company},
                )
                if response.status_code != 401 or attempt:
                    break
                if not await asyncio.to_thread(provider.refresh_norman_token_sync, access.token):
                    break
    except httpx.RequestError:
        return {"status": "unknown", "error": UNKNOWN}
    if response.status_code == 201:
        try:
            payload = response.json()
            attachment_id = payload.get("publicId") or payload.get("public_id") or payload.get("pk")
        except (ValueError, AttributeError):
            attachment_id = None
        if attachment_id:
            return {
                "status": "uploaded",
                "attachment_id": str(attachment_id),
                "processing_status": "pending",
            }
    if response.status_code in (400, 401, 403, 404, 413, 415, 429):
        return {
            "status": "rejected",
            "error": "Norman did not accept this file. Check its format, size and your access before trying again.",
            "status_code": response.status_code,
        }
    return {"status": "unknown", "error": UNKNOWN}


def _ticket(request: Request) -> str:
    header = request.headers.get("authorization", "")
    if not header.startswith("Bearer ") or len(header) > 200:
        raise UploadError(DENIED, 401)
    return header[7:]


def _response(payload: dict, status: int = 200):
    return JSONResponse(
        payload,
        status_code=status,
        headers={"Cache-Control": "no-store", "Referrer-Policy": "no-referrer"},
    )


async def handle_session(request: Request):
    try:
        store = UploadStore()
        session = store.session(ticket=_ticket(request))
        current_access(session, get_oauth_provider())
        return _response(store.summary(session))
    except UploadError as exc:
        return _response({"error": exc.message}, exc.status)


async def handle_file(request: Request):
    try:
        store = UploadStore()
        session = store.session(ticket=_ticket(request))
        provider = get_oauth_provider()
        current_access(session, provider)
        # Enforce a streaming request bound before multipart parsing can spool
        # an unbounded file. Multipart overhead has a small explicit allowance.
        original_receive, received = request._receive, 0

        async def bounded_receive():
            nonlocal received
            message = await original_receive()
            received += len(message.get("body", b""))
            if received > MAX_FILE_SIZE + 65536:
                raise HTTPException(413, "File exceeds the 10 MB limit.")
            return message

        request._receive = bounded_receive
        async with request.form(max_files=1, max_fields=2) as form:
            upload, file_id, cashflow = (
                form.get("file"),
                form.get("file_id"),
                form.get("cashflow_type"),
            )
            if (
                not isinstance(upload, UploadFile)
                or not isinstance(file_id, str)
                or not re.fullmatch(r"[A-Za-z0-9_-]{16,80}", file_id)
            ):
                raise UploadError("Choose a file to upload.")
            if cashflow not in ("INCOME", "EXPENSE"):
                raise UploadError("Choose Revenue or Expense for this document.")
            name = re.sub(
                r"[\x00-\x1f\x7f]",
                "",
                (upload.filename or "").replace("\\", "/").rsplit("/", 1)[-1],
            ).strip()
            if not name or len(name) > 200 or Path(name).suffix.lower() not in EXTENSIONS:
                raise UploadError("Supported files: PDF, PNG, JPG, WEBP and XML.")
            sha, size = hashlib.sha256(), 0
            while chunk := await upload.read(65536):
                size += len(chunk)
                if size > MAX_FILE_SIZE:
                    raise UploadError("File exceeds the 10 MB limit.", 413)
                sha.update(chunk)
            if not size:
                raise UploadError("This file is empty.")
            # Recheck the grant after receiving the bytes and before writing.
            access = current_access(session, provider)
            if session["expires"] <= time.time():
                raise UploadError(DENIED, 410)
            prior = store.reserve(session, file_id, name, size, sha.hexdigest(), cashflow)
            if prior is not None:
                return _response(prior)
            result = await post_attachment(
                provider, access, session["company"], upload, name, cashflow
            )
            store.finish(session["id"], file_id, result)
            return _response(result)
    except UploadError as exc:
        return _response({"error": exc.message}, exc.status)
    except HTTPException as exc:
        return _response({"error": str(exc.detail)}, exc.status_code)


def upload_html() -> str:
    return (Path(__file__).parent.parent / "apps/document_upload.html").read_text()


async def handle_page(request: Request):
    return HTMLResponse(
        upload_html(),
        headers={
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
            "X-Content-Type-Options": "nosniff",
            "Content-Security-Policy": "default-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'none'",
        },
    )


def create_inline_upload_routes():
    return [
        Route("/files/upload-app", handle_page, methods=["GET"]),
        Route("/files/upload-app/session", handle_session, methods=["GET"]),
        Route("/files/upload-app/file", handle_file, methods=["POST"]),
    ]
