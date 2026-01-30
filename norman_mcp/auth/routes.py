"""Routes for Norman OAuth callback handling."""

import logging
from typing import List

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse
from starlette.routing import Route

from norman_mcp.auth.provider import NormanOAuthProvider

logger = logging.getLogger(__name__)


async def oauth_callback(request: Request, oauth_provider: NormanOAuthProvider) -> RedirectResponse:
    """Handle OAuth callback from Norman.
    
    Norman redirects here after user authorizes with:
    - code: Authorization code
    - state: State parameter to match original request
    """
    code = request.query_params.get("code")
    state = request.query_params.get("state")
    error = request.query_params.get("error")
    error_description = request.query_params.get("error_description", "")
    
    logger.info(f"OAuth callback: code={'yes' if code else 'no'}, state={state}, error={error}")
    
    if error:
        logger.error(f"OAuth error from Norman: {error} - {error_description}")
        return HTMLResponse(
            f"""
            <html>
            <head><title>Authorization Failed</title></head>
            <body>
                <h1>Authorization Failed</h1>
                <p>Error: {error}</p>
                <p>{error_description}</p>
            </body>
            </html>
            """,
            status_code=400
        )
    
    if not code or not state:
        return HTMLResponse(
            """
            <html>
            <head><title>Invalid Callback</title></head>
            <body>
                <h1>Invalid Callback</h1>
                <p>Missing code or state parameter.</p>
            </body>
            </html>
            """,
            status_code=400
        )
    
    try:
        redirect_url = await oauth_provider.handle_oauth_callback(code=code, state=state)
        return RedirectResponse(url=redirect_url, status_code=302)
    except Exception as e:
        logger.error(f"OAuth callback error: {e}")
        return HTMLResponse(
            f"""
            <html>
            <head><title>Authorization Failed</title></head>
            <body>
                <h1>Authorization Failed</h1>
                <p>Error exchanging authorization code: {str(e)}</p>
            </body>
            </html>
            """,
            status_code=500
        )


def create_norman_auth_routes(oauth_provider: NormanOAuthProvider) -> List[Route]:
    """Create routes for Norman OAuth callback."""
    
    async def handle_callback(request: Request) -> RedirectResponse:
        return await oauth_callback(request, oauth_provider)
    
    return [
        Route(
            "/oauth/callback",
            endpoint=handle_callback,
            methods=["GET"],
        ),
    ]
