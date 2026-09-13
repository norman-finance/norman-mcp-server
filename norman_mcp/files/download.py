"""URL downloads with safe filenames, errors and cancellation cleanup."""

import asyncio
import logging
import os
import re
import shutil
import tempfile
from email.message import Message
from urllib.parse import unquote, urlparse

import requests
from urllib3.exceptions import ReadTimeoutError

logger = logging.getLogger(__name__)


class FileDownloadError(Exception):
    def __init__(self, code: str, message: str, http_status: int | None = None):
        super().__init__(message)
        self.code = code
        self.http_status = http_status

    def as_result(self) -> dict:
        result = {"error": str(self), "code": self.code}
        if self.http_status is not None:
            result["http_status"] = self.http_status
        return result


def _safe_filename(url: str, content_disposition: str) -> str:
    header = Message()
    header["Content-Disposition"] = content_disposition
    filename = header.get_filename() or unquote(urlparse(url).path)
    # Header filenames are untrusted paths, including Windows paths on POSIX.
    filename = filename.replace("\\", "/").rsplit("/", 1)[-1]
    filename = re.sub(r"[\x00-\x1f\x7f]", "", filename).strip()
    if filename in {"", ".", ".."}:
        return "downloaded_file"
    # Leave room below common 255-byte filesystem component limits; keep the
    # extension so the API can recognize a PDF/image even with a long name.
    stem, suffix = os.path.splitext(filename)
    if len(suffix.encode("utf-8")) > 20:
        suffix = ""
    budget = 200 - len(suffix.encode("utf-8"))
    return stem.encode("utf-8")[:budget].decode("utf-8", errors="ignore") + suffix


def _download_file(url: str) -> str:
    temp_dir = None
    succeeded = False
    try:
        # Do not rebuild query parameters: presigned URLs need their encoding.
        with requests.get(url, stream=True, timeout=30) as response:
            response.raise_for_status()
            filename = _safe_filename(url, response.headers.get("Content-Disposition", ""))
            temp_dir = tempfile.mkdtemp(prefix="norman_")
            path = os.path.join(temp_dir, filename)
            with open(path, "wb") as output:
                for chunk in response.iter_content(chunk_size=8192):
                    output.write(chunk)
        succeeded = True
        return path
    except requests.HTTPError as exc:
        status = exc.response.status_code if exc.response is not None else None
        raise FileDownloadError(
            "download_http_error", f"File host returned HTTP {status}.", status
        ) from None
    except requests.Timeout:
        raise FileDownloadError(
            "download_timeout", "File download timed out while connecting or reading."
        ) from None
    except requests.ConnectionError as exc:
        # requests wraps urllib3's timeout during iter_content as ConnectionError.
        if any(isinstance(arg, ReadTimeoutError) for arg in exc.args):
            raise FileDownloadError(
                "download_timeout", "File download timed out while reading."
            ) from None
        raise FileDownloadError(
            "download_network_error", "Could not connect to or read from the file host."
        ) from None
    except requests.RequestException:
        raise FileDownloadError(
            "download_network_error", "File download failed during the HTTP request."
        ) from None
    except OSError:
        raise FileDownloadError(
            "download_storage_error", "Could not save the downloaded file."
        ) from None
    except Exception:
        # Neither a provider's exception nor its response body is safe to echo:
        # both can contain the signed URL or other download credentials.
        raise FileDownloadError("download_error", "Could not download the file.") from None
    finally:
        if temp_dir and not succeeded:
            shutil.rmtree(temp_dir, ignore_errors=True)


def _cleanup_abandoned_download(task: asyncio.Task) -> None:
    try:
        path = task.result()
    except BaseException:
        # Failed downloads clean up in the worker; retrieve their exception.
        return
    shutil.rmtree(os.path.dirname(path), ignore_errors=True)


async def download_file(url: str) -> str:
    """Return an owned temporary file; the caller removes it after upload.

    Keep requests off the event loop. Cancelling a tool cannot stop its worker
    thread, so arrange cleanup when that worker eventually finishes.
    """
    task = asyncio.create_task(asyncio.to_thread(_download_file, url))
    try:
        return await asyncio.shield(task)
    except asyncio.CancelledError:
        task.add_done_callback(_cleanup_abandoned_download)
        raise
    except FileDownloadError as exc:
        # No URL, raw exception text, provider response body or traceback.
        logger.warning("File download failed: code=%s http_status=%s", exc.code, exc.http_status)
        raise
