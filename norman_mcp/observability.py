"""Optional Sentry wiring for the Norman MCP server.

The server brokers OAuth credentials for third-party providers (Gmail,
Microsoft 365, PayPal, Stripe, Qonto) and mints its own MCP tokens, so error
reporting is deliberately conservative:

* Opt-in. Without ``SENTRY_DSN`` nothing is imported and nothing is sent, which
  keeps the local/stdio use of this package (and the published PyPI wheel)
  unchanged.
* Everything that leaves the process passes through :func:`scrub_event` first.
  ``send_default_pii=False`` only stops the SDK from *adding* identifying data;
  it does not redact secrets the application itself put into a URL, a header or
  an exception message. The scrubber below is what actually does that.

Tracing defaults to off: this service is diagnosed from errors, and performance
transactions would be the expensive half of the quota.
"""

import logging
import os
import re
from typing import Any, Dict, Optional
from urllib.parse import urlsplit, urlunsplit

logger = logging.getLogger(__name__)

FILTERED = "[Filtered]"

# Matched case-insensitively against mapping keys (headers, cookies, query
# params, form fields, breadcrumb data). Substring match, so "client_secret"
# also covers "NORMAN_OAUTH_CLIENT_SECRET" and "x-client-secret".
_SENSITIVE_KEY_PARTS = (
    "authorization",
    "cookie",
    "password",
    "secret",
    "token",
    "api-key",
    "api_key",
    "apikey",
    "session-id",
    "session_id",
    # OAuth authorization-code flow: both halves are single-use credentials.
    "code",
    "state",
)

# "Bearer eyJ…" / "Basic dXNlcjpwYXNz" anywhere in free text.
_AUTH_SCHEME_RE = re.compile(
    r"\b(bearer|basic|token)\s+[A-Za-z0-9\-._~+/=]{8,}",
    re.IGNORECASE,
)

# "code=abc123", "access_token=…", "client_secret=…" inside a URL or message.
_QUERY_SECRET_RE = re.compile(
    r"\b("
    r"code|state|token|access_token|refresh_token|id_token"
    r"|client_secret|api_key|apikey|password"
    r")=[^&\s\"'}\]]+",
    re.IGNORECASE,
)


def _is_sensitive_key(key: Any) -> bool:
    if not isinstance(key, str):
        return False
    lowered = key.lower()
    return any(part in lowered for part in _SENSITIVE_KEY_PARTS)


def scrub_text(value: Any) -> Any:
    """Redact credentials embedded in free text (messages, URLs, values)."""
    if not isinstance(value, str):
        return value
    scrubbed = _AUTH_SCHEME_RE.sub(lambda m: f"{m.group(1)} {FILTERED}", value)
    scrubbed = _QUERY_SECRET_RE.sub(lambda m: f"{m.group(1)}={FILTERED}", scrubbed)
    return scrubbed


def scrub_structure(value: Any, _depth: int = 0) -> Any:
    """Recursively redact sensitive keys and credential-looking strings.

    Depth is bounded so a self-referential or pathological payload cannot turn
    error reporting into the outage it was meant to report.
    """
    if _depth > 8:
        return FILTERED
    if isinstance(value, dict):
        return {
            key: FILTERED if _is_sensitive_key(key) else scrub_structure(item, _depth + 1)
            for key, item in value.items()
        }
    if isinstance(value, (list, tuple)):
        scrubbed = [scrub_structure(item, _depth + 1) for item in value]
        return type(value)(scrubbed) if isinstance(value, tuple) else scrubbed
    return scrub_text(value)


def strip_query(url: Any) -> Any:
    """Drop the query and fragment from a URL, keeping it useful for grouping."""
    if not isinstance(url, str) or not url:
        return url
    try:
        parts = urlsplit(url)
    except ValueError:
        return FILTERED
    if not parts.query and not parts.fragment:
        return url
    return urlunsplit((parts.scheme, parts.netloc, parts.path, "", ""))


def _scrub_request(request: Dict[str, Any]) -> None:
    # Bodies on this service are token exchanges and tool arguments; neither is
    # worth the risk, so the whole thing goes rather than being walked.
    if "data" in request:
        request["data"] = FILTERED
    if request.get("query_string"):
        request["query_string"] = FILTERED
    if "cookies" in request:
        request["cookies"] = FILTERED
    if "url" in request:
        request["url"] = strip_query(request["url"])
    headers = request.get("headers")
    if isinstance(headers, dict):
        request["headers"] = scrub_structure(headers)


def scrub_event(event: Dict[str, Any]) -> Dict[str, Any]:
    """Redact credentials across every part of a Sentry event.

    Pure and importable without ``sentry_sdk`` so it can be unit-tested on its
    own; :func:`init_sentry` installs it as ``before_send``.
    """
    if not isinstance(event, dict):
        return event

    request = event.get("request")
    if isinstance(request, dict):
        _scrub_request(request)

    exception = event.get("exception")
    if isinstance(exception, dict):
        for entry in exception.get("values") or []:
            if isinstance(entry, dict) and "value" in entry:
                entry["value"] = scrub_text(entry["value"])

    logentry = event.get("logentry")
    if isinstance(logentry, dict):
        if "message" in logentry:
            logentry["message"] = scrub_text(logentry["message"])
        if "params" in logentry:
            logentry["params"] = scrub_structure(logentry["params"])

    if "message" in event:
        event["message"] = scrub_text(event["message"])

    for key in ("extra", "contexts", "tags"):
        if key in event:
            event[key] = scrub_structure(event[key])

    breadcrumbs = event.get("breadcrumbs")
    if isinstance(breadcrumbs, dict):
        breadcrumbs["values"] = scrub_structure(breadcrumbs.get("values") or [])
    elif isinstance(breadcrumbs, list):
        event["breadcrumbs"] = scrub_structure(breadcrumbs)

    return event


def _before_send(event: Dict[str, Any], hint: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    try:
        return scrub_event(event)
    except Exception:  # pragma: no cover - defensive
        # A scrubber that raises would drop the event silently on some SDK
        # versions and send it unscrubbed on others. Neither is acceptable, so
        # fail closed: report that something happened, without the payload.
        logger.exception("Sentry before_send scrubbing failed; dropping event payload")
        return {"message": "Event dropped: scrubbing failed", "level": "error"}


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        logger.warning("Ignoring non-numeric %s=%r, using %s", name, raw, default)
        return default


def init_sentry() -> bool:
    """Initialise Sentry when a DSN is configured. Returns True if enabled."""
    dsn = os.environ.get("SENTRY_DSN", "").strip()
    if not dsn:
        return False

    try:
        import sentry_sdk
    except ImportError:
        logger.warning(
            "SENTRY_DSN is set but sentry-sdk is not installed; "
            "install it with: pip install 'norman-mcp-server[sentry]'"
        )
        return False

    sentry_sdk.init(
        dsn=dsn,
        environment=os.environ.get("SENTRY_ENVIRONMENT")
        or os.environ.get("NORMAN_ENVIRONMENT", "production"),
        release=os.environ.get("SENTRY_RELEASE") or None,
        # Errors are the signal here; transactions are the expensive half.
        traces_sample_rate=_env_float("SENTRY_TRACES_SAMPLE_RATE", 0.0),
        profiles_sample_rate=_env_float("SENTRY_PROFILES_SAMPLE_RATE", 0.0),
        send_default_pii=False,
        include_local_variables=False,
        max_request_body_size="never",
        before_send=_before_send,
    )
    logger.info("Sentry error reporting enabled")
    return True
