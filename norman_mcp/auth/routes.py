"""Routes for Norman OAuth authentication."""

import logging
from pathlib import Path
from typing import List, Optional
import uuid
import json

from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, JSONResponse
from starlette.routing import Route
from starlette.templating import Jinja2Templates

from norman_mcp.auth.provider import NormanOAuthProvider

logger = logging.getLogger(__name__)

# Setup Jinja2 templates
BASE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))

async def login_page(request: Request, oauth_provider: NormanOAuthProvider) -> HTMLResponse:
    """Render the login page."""
    state = request.query_params.get("state")
    if not state:
        return HTMLResponse("Invalid request: Missing state parameter", status_code=400)
        
    if state not in oauth_provider.state_mapping:
        return HTMLResponse("Invalid request: Unknown state parameter", status_code=400)
    
    error = request.query_params.get("error")
    return templates.TemplateResponse(
        "login.html", {"request": request, "state": state, "error": error}
    )

async def login_handler(request: Request, oauth_provider: NormanOAuthProvider) -> RedirectResponse:
    """Handle login form submission."""
    form_data = await request.form()
    state = form_data.get("state")
    email = form_data.get("email")
    password = form_data.get("password")
    
    if not all([state, email, password]):
        return RedirectResponse(
            url=f"/norman/login?state={state}&error=Missing+required+fields",
            status_code=302,
        )
    
    try:
        # Process login via Norman API
        redirect_url = await oauth_provider.handle_norman_login(
            email=email,
            password=password,
            state=state,
        )
        return RedirectResponse(url=redirect_url, status_code=302)
    except Exception as e:
        logger.error(f"Login error: {str(e)}")
        error_message = "Invalid credentials"
        if hasattr(e, "status_code") and e.status_code == 500:
            error_message = "Server error. Please try again later."
        
        return RedirectResponse(
            url=f"/norman/login?state={state}&error={error_message}",
            status_code=302,
        )

def create_norman_auth_routes(
    oauth_provider: NormanOAuthProvider,
) -> List[Route]:
    """Create routes for Norman OAuth authentication."""
    
    # Create proper async wrapper functions
    async def get_login_page(request: Request) -> HTMLResponse:
        return await login_page(request, oauth_provider)
    
    async def handle_login_form(request: Request) -> RedirectResponse:
        return await login_handler(request, oauth_provider)
    
    
    return [
        Route(
            "/norman/login",
            endpoint=get_login_page,
            methods=["GET"],
        ),
        Route(
            "/norman/login",
            endpoint=handle_login_form,
            methods=["POST"],
        ),
    ] 