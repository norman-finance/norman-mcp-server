"""Return completed Norman authorization attempts to their trusted MCP client."""

import logging

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from norman_mcp.auth.provider import NormanOAuthProvider, OAuthCallbackError

logger = logging.getLogger(__name__)


_ERRORS = {"access_denied", "temporarily_unavailable", "server_error"}
_HEADERS = {"Cache-Control": "no-store", "Pragma": "no-cache"}


def _unverified_callback() -> HTMLResponse:
    # No callback parameters or exception details belong in the local page.
    # Without a valid transaction there is no trusted client URL to return to.
    return HTMLResponse(
        """<!doctype html>
        <html lang="en"><head><title>Connection could not be completed</title></head>
        <body><h1>Connection could not be completed</h1>
        <p>This connection attempt is invalid, expired or already completed.
        Return to your MCP client and start connecting Norman again.</p></body></html>""",
        status_code=400,
        headers=_HEADERS,
    )


def _redirect(url: str) -> RedirectResponse:
    return RedirectResponse(url=url, status_code=302, headers=_HEADERS)


async def oauth_callback(request: Request, oauth_provider: NormanOAuthProvider) -> Response:
    """Return success or a fixed OAuth error with the original client state.

    Only the provider's validated transaction can supply a return URL. Unknown,
    expired and consumed transactions stay local rather than trusting the request.
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    logger.info(
        "OAuth callback received: has_code=%s, has_state=%s, has_error=%s",
        bool(code),
        bool(state),
        bool(error),
    )

    if error:
        safe_error = error if error in _ERRORS else "server_error"
        redirect_url = oauth_provider.callback_error_redirect(state, safe_error)
        logger.warning("OAuth authorization returned an error: %s", safe_error)
        return _redirect(redirect_url) if redirect_url else _unverified_callback()

    if not code or not state:
        redirect_url = oauth_provider.callback_error_redirect(state, "invalid_request")
        return _redirect(redirect_url) if redirect_url else _unverified_callback()

    try:
        redirect_url = await oauth_provider.handle_oauth_callback(code=code, state=state)
        return _redirect(redirect_url)
    except OAuthCallbackError as error:
        logger.warning("OAuth code exchange failed; returning a safe error to the client")
        return _redirect(error.redirect_url)
    except Exception:
        logger.warning("OAuth callback could not establish a trusted return transaction")
        return _unverified_callback()


def create_norman_auth_routes(oauth_provider: NormanOAuthProvider) -> list[Route]:
    """Create routes for Norman OAuth callback."""

    async def handle_callback(request: Request) -> Response:
        return await oauth_callback(request, oauth_provider)

    return [
        Route(
            "/oauth/callback",
            endpoint=handle_callback,
            methods=["GET"],
        ),
    ]
