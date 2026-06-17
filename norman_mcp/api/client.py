import logging
import requests
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from ..config.settings import config
from ..security.utils import validate_input, validate_url
from mcp.server.auth.middleware.auth_context import get_access_token
from norman_mcp.context import (
    get_api_token,
    set_api_token,
    get_api_company_id,
    set_api_company_id,
    get_oauth_provider,
)

# Configure logging
logger = logging.getLogger(__name__)


class NormanAPI:
    """API client for Norman Finance.

    A SINGLE instance is shared across all requests in a server process
    (see server.lifespan). It therefore MUST NOT keep per-user state on the
    instance for the OAuth/remote path — the Norman token and company id for a
    request are resolved per-request from ContextVars / the MCP auth context so
    concurrent users never see each other's data. The instance attributes
    (``access_token``, ``_company_id``) are only used for the single-user
    stdio/env path. See tests/test_concurrency.py.
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        company_id: Optional[str] = None,
        token_source: str = "env",  # can be 'env', 'oauth', or 'direct_login'
        authenticate_on_init: bool = True,
    ):
        self.access_token = access_token
        self.refresh_token = refresh_token
        self._company_id = company_id
        self.token_source = token_source
        self.authenticate_on_init = authenticate_on_init

        # If we already have a token, use it
        if self.access_token:
            return

        # Skip authentication if requested
        if not self.authenticate_on_init:
            logger.info("Skipping automatic authentication on initialization")
            return

        # Check if credentials are available before attempting authentication
        if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
            logger.warning("Norman Finance credentials not set. Please set NORMAN_EMAIL and NORMAN_PASSWORD environment variables.")
            logger.warning("The server will start, but API calls will fail until valid credentials are provided.")
            return

        try:
            self.authenticate()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.warning("Failed to authenticate with Norman Finance API: Invalid credentials.")
                logger.warning("Please check your NORMAN_EMAIL and NORMAN_PASSWORD environment variables.")
                logger.warning("The server will start, but API calls will fail until valid credentials are provided.")
            else:
                raise

    # ------------------------------------------------------------------
    # Per-request identity resolution (OAuth / remote multi-user path)
    # ------------------------------------------------------------------

    def _request_mcp_token(self) -> Optional[str]:
        """Return the MCP access token bound to the CURRENT request, or None.

        Backed by the MCP SDK's per-request auth context (a ContextVar the SDK
        sets in the scope where tools execute), so it is the reliable signal for
        "is this a remote request and who is it".
        """
        try:
            access_token = get_access_token()
        except Exception:
            access_token = None
        return access_token.token if access_token else None

    def _resolve_norman_token(self) -> tuple[Optional[str], Optional[str]]:
        """Resolve ``(norman_token, mcp_token)`` for the current request.

        Never reads or writes shared instance state for the OAuth path — the
        token comes from the request-scoped MCP token via the provider mapping
        (falling back to the request ContextVar). For stdio/env there is a
        single user, so the instance token is fine.
        """
        mcp_token = self._request_mcp_token()
        if mcp_token:
            provider = get_oauth_provider()
            norman_token = (provider.get_norman_token(mcp_token) if provider else None) or get_api_token()
            return norman_token, mcp_token
        # stdio / env single-user: request ContextVar (if any), then instance token
        return (get_api_token() or self.access_token), None

    # ------------------------------------------------------------------
    # Company id — request-scoped for OAuth, instance-scoped for stdio/env
    # ------------------------------------------------------------------

    @property
    def company_id(self) -> Optional[str]:
        """Company id for the current caller.

        For a remote request this is resolved from the request's own Norman
        token and cached in a request ContextVar (so it can never be another
        user's company). For stdio/env it is the instance value resolved at
        login time.
        """
        if self._request_mcp_token():
            cid = get_api_company_id()
            if cid is None:
                cid = self._resolve_company_id_for_request()
                if cid:
                    set_api_company_id(cid)
            return cid
        return self._company_id

    @company_id.setter
    def company_id(self, value: Optional[str]) -> None:
        if self._request_mcp_token():
            set_api_company_id(value)
        else:
            self._company_id = value

    def _resolve_company_id_for_request(self) -> Optional[str]:
        norman_token, _ = self._resolve_norman_token()
        if not norman_token:
            return None
        return self._get_company_id(norman_token)

    def _get_company_id(self, token: str) -> Optional[str]:
        """Fetch the first company's publicId for ``token`` via a direct GET.

        Uses requests directly (not _make_request) to avoid recursion.
        """
        if not token:
            return None
        companies_url = urljoin(config.api_base_url, "api/v1/companies/")
        try:
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "NormanMCPServer/0.1.0",
                "X-Requested-With": "XMLHttpRequest",
            }
            response = requests.get(companies_url, headers=headers, timeout=config.NORMAN_API_TIMEOUT)
            response.raise_for_status()
            companies = response.json().get("results", [])
            if not companies:
                logger.warning("No companies found for user")
                return None
            company_id = companies[0].get("publicId")
            if company_id:
                logger.info(f"✅ Using company ID from API: {company_id}")
            else:
                logger.warning("Company found but no publicId available")
            return company_id
        except Exception as e:
            logger.error(f"Error getting company ID: {str(e)}")
            return None

    def set_token(self, token: str) -> None:
        """Set the access token directly (stdio/env single-user path)."""
        if not token:
            logger.error("Attempted to set empty token!")
            return

        # If we already have a token from direct login, don't override it with OAuth token
        if self.token_source == "direct_login":
            logger.info("Keeping existing direct login token instead of setting OAuth token")
            return

        logger.info("Setting Norman API token")
        self.access_token = token
        self.token_source = "oauth"

        # Try to get company ID with this token only if we don't already have one
        if not self._company_id:
            try:
                logger.info("Attempting to get company ID with token")
                self._set_company_id()
            except Exception as e:
                logger.error(f"Error setting company ID: {str(e)}")
        else:
            logger.info(f"Using existing company ID: {self._company_id}")

    def authenticate(self) -> None:
        """Authenticate with Norman Finance API and get access token."""
        if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
            raise ValueError("Norman Finance credentials not set. Please set NORMAN_EMAIL and NORMAN_PASSWORD environment variables.")

        # Extract username from email (as per instructions)
        username = config.NORMAN_EMAIL.split('@')[0]
        auth_url = urljoin(config.api_base_url, "api/v1/auth/token/")

        payload = {
            "username": username,
            "email": config.NORMAN_EMAIL,
            "password": config.NORMAN_PASSWORD
        }

        try:
            response = requests.post(auth_url, json=payload, timeout=config.NORMAN_API_TIMEOUT)
            response.raise_for_status()

            auth_data = response.json()
            self.access_token = auth_data.get("access")
            self.refresh_token = auth_data.get("refresh")
            self.token_source = "env"

            # Get company ID (user typically has only one company)
            self._set_company_id()

            logger.info("Successfully authenticated with Norman Finance API using environment credentials")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to authenticate with Norman Finance API: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

    def _set_company_id(self) -> None:
        """Resolve and cache the company id on the instance (stdio/env path)."""
        self._company_id = self._get_company_id(self.access_token)

    def _make_request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None,
                     json_data: Optional[Dict[str, Any]] = None,
                     files: Optional[Dict[str, Any]] = None,
                     _retried: bool = False) -> Dict[str, Any]:
        """Make a request to the Norman Finance API with security controls.

        The Norman token is resolved per-request (never from shared instance
        state on the OAuth path) so concurrent users cannot leak tokens.
        """
        norman_token, mcp_token = self._resolve_norman_token()

        # No token for this request.
        if not norman_token:
            if mcp_token:
                # Remote request but no Norman token mapped — session is gone.
                return {
                    "error": (
                        "Your Norman session expired. Please disconnect and reconnect "
                        "the Norman connector in your AI client to re-authenticate."
                    ),
                    "status_code": 401,
                }
            # stdio/env: try environment credentials as a last resort.
            try:
                logger.warning("No Norman token available. Attempting authentication with environment variables...")
                self.authenticate()
                norman_token = self.access_token
            except Exception as e:
                logger.error(f"Authentication failed: {str(e)}")
                return {"error": "No authentication token available. Please authenticate first."}
            if not norman_token:
                return {"error": "No authentication token available. Please authenticate first."}

        # Validate URL to prevent SSRF attacks
        if not validate_url(url):
            logger.error(f"Invalid or potentially dangerous URL: {url}")
            raise ValueError(f"Invalid or potentially dangerous URL: {url}")

        # Set secure headers with the per-request token
        headers = {
            "Authorization": f"Bearer {norman_token}",
            "User-Agent": "NormanMCPServer/0.1.0",
            "X-Requested-With": "XMLHttpRequest",
            # Security headers
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY"
        }

        if params is None:
            params = {}

        # Add company ID to params if the endpoint needs it. Resolved per-request
        # via the company_id property (request-scoped for OAuth callers).
        if not url.endswith("companies/"):
            company_id = self.company_id
            if company_id and "companyId" not in params:
                logger.debug(f"Using company ID for request: {company_id}")
                params["companyId"] = company_id

        # Sanitize parameters to prevent injection
        if params:
            sanitized_params = {}
            for key, value in params.items():
                if isinstance(value, str):
                    sanitized_params[key] = validate_input(value)
                else:
                    sanitized_params[key] = value
            params = sanitized_params

        # Sanitize JSON data to prevent injection
        if json_data:
            sanitized_json = {}
            for key, value in json_data.items():
                if isinstance(value, str):
                    sanitized_json[key] = validate_input(value)
                elif isinstance(value, dict):
                    # Simple one-level deep sanitization for nested dicts
                    sanitized_nested = {}
                    for k, v in value.items():
                        if isinstance(v, str):
                            sanitized_nested[k] = validate_input(v)
                        else:
                            sanitized_nested[k] = v
                    sanitized_json[key] = sanitized_nested
                else:
                    sanitized_json[key] = value
            json_data = sanitized_json

        try:
            if files and json_data:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    data=json_data,
                    files=files,
                    timeout=config.NORMAN_API_TIMEOUT
                )
            else:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    files=files,
                    timeout=config.NORMAN_API_TIMEOUT
                )
            response.raise_for_status()

            # Attempt to parse JSON response, but handle non-JSON responses gracefully
            try:
                if response.content:
                    return response.json()
                return {}
            except ValueError:
                # Not JSON, return content as string if it's not binary
                if response.headers.get('content-type', '').startswith('text/'):
                    return {"content": response.text}
                # For binary content, return success message
                return {"success": True, "message": "Request successful"}

        except requests.exceptions.HTTPError as e:
            # Handle token expiration
            if e.response.status_code == 401:
                if _retried:
                    logger.warning("Still unauthorized after token refresh/re-auth")
                    return {"error": "Authentication failed.", "status_code": 401}

                if mcp_token:
                    # OAuth mode: refresh the Norman token transparently using the
                    # refresh token stored for THIS request's MCP token, then retry.
                    new_norman_token = self._refresh_oauth_norman_token(mcp_token)
                    if new_norman_token:
                        return self._make_request(method, url, params, json_data, files, _retried=True)
                    logger.warning("Cannot refresh Norman token; client must reconnect")
                    return {
                        "error": (
                            "Your Norman session expired. Please disconnect and reconnect "
                            "the Norman connector in your AI client to re-authenticate."
                        ),
                        "status_code": 401,
                    }

                # stdio/env mode: re-authenticate with environment credentials.
                logger.info("Env token expired, re-authenticating...")
                try:
                    self.authenticate()
                except Exception as auth_err:
                    logger.error(f"Re-auth failed: {auth_err}")
                    return {
                        "error": "Authentication failed. Check NORMAN_EMAIL/NORMAN_PASSWORD.",
                        "status_code": 401,
                    }
                return self._make_request(method, url, params, json_data, files, _retried=True)
            elif e.response.status_code == 403:
                logger.error("Access forbidden. Check your account permissions.")
                return {"error": "Access forbidden. Check your account permissions.", "status_code": 403}
            elif e.response.status_code == 404:
                logger.error(f"Resource not found: {url}")
                return {"error": "Resource not found", "status_code": 404}
            elif e.response.status_code == 429:
                logger.error("Rate limit exceeded. Please try again later.")
                return {"error": "Rate limit exceeded. Please try again later.", "status_code": 429}
            else:
                logger.error(f"HTTP error: {str(e)}")
                error_detail = None
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                    try:
                        error_detail = e.response.json()
                    except (ValueError, AttributeError):
                        error_detail = e.response.text
                result = {"error": f"Request failed: {str(e)}", "status_code": e.response.status_code}
                if error_detail:
                    result["detail"] = error_detail
                return result
        except requests.exceptions.ConnectionError:
            logger.error(f"Connection error when accessing {url}")
            return {"error": "Connection error. Please check your network connection."}
        except requests.exceptions.Timeout:
            logger.error(f"Request timed out when accessing {url}")
            return {"error": "Request timed out. Please try again later."}
        except requests.exceptions.RequestException as e:
            logger.error(f"Error making request to {url}: {str(e)}")
            return {"error": f"Request failed: {str(e)}"}
        except Exception as e:
            logger.error(f"Unexpected error making request to {url}: {str(e)}")
            return {"error": f"Unexpected error: {str(e)}"}

    def _refresh_oauth_norman_token(self, mcp_token: Optional[str] = None) -> Optional[str]:
        """Refresh the Norman access token for the current request (OAuth).

        Returns the new Norman access token or None if refresh isn't possible.
        Updates the request ContextVar so the retried request sees the new token.
        """
        try:
            provider = get_oauth_provider()
            if provider is None:
                return None

            if not mcp_token:
                mcp_token = self._request_mcp_token()
            if not mcp_token:
                return None

            new_norman_token = provider.refresh_norman_token_sync(mcp_token)
            if new_norman_token:
                set_api_token(new_norman_token)
            return new_norman_token
        except Exception as e:
            logger.error(f"Transparent Norman refresh failed: {e}")
            return None

    def set_company(self, company_id: str) -> None:
        """Manually set a company ID for the current caller."""
        logger.info(f"Manually setting company ID to: {company_id}")
        self.company_id = company_id
