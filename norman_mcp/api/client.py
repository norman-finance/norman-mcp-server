import logging
import requests
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from ..config.settings import config
from ..security.utils import validate_input, validate_url
from mcp.server.auth.middleware.auth_context import get_access_token
from norman_mcp.context import (
    get_api_company_id,
    get_api_token,
    get_api_token_source,
    get_oauth_provider,
    set_api_company_id,
    set_api_token,
    set_api_token_source,
)

# Configure logging
logger = logging.getLogger(__name__)


class NormanAPI:
    """API client for Norman Finance.

    Per-request state (access_token, company_id, token_source) lives in
    ``ContextVar``s defined in ``norman_mcp.context`` so that concurrent
    requests under HTTP/SSE transports don't leak tokens or company ids
    across users. The class itself is effectively stateless for those
    fields — they're exposed as properties that read/write the ContextVar.

    The only instance state is ``refresh_token`` (used only by environment
    credential auth, which is single-user stdio) and ``authenticate_on_init``.
    """

    def __init__(
        self,
        access_token: Optional[str] = None,
        refresh_token: Optional[str] = None,
        company_id: Optional[str] = None,
        token_source: str = "env",
        authenticate_on_init: bool = True,
    ):
        self.refresh_token: Optional[str] = refresh_token
        self.authenticate_on_init = authenticate_on_init

        if access_token is not None:
            set_api_token(access_token)
        if company_id is not None:
            set_api_company_id(company_id)
        if token_source != "env":
            set_api_token_source(token_source)

        if get_api_token():
            return

        if not self.authenticate_on_init:
            logger.info("Skipping automatic authentication on initialization")
            return

        if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
            logger.warning(
                "Norman Finance credentials not set. Please set NORMAN_EMAIL "
                "and NORMAN_PASSWORD environment variables."
            )
            logger.warning(
                "The server will start, but API calls will fail until valid "
                "credentials are provided."
            )
            return

        try:
            self.authenticate()
        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 400:
                logger.warning(
                    "Failed to authenticate with Norman Finance API: Invalid credentials."
                )
                logger.warning(
                    "Please check your NORMAN_EMAIL and NORMAN_PASSWORD environment variables."
                )
                logger.warning(
                    "The server will start, but API calls will fail until valid "
                    "credentials are provided."
                )
            else:
                raise

    # ------------------------------------------------------------------
    # Per-request properties backed by ContextVars
    # ------------------------------------------------------------------

    @property
    def access_token(self) -> Optional[str]:
        return get_api_token()

    @access_token.setter
    def access_token(self, value: Optional[str]) -> None:
        set_api_token(value)

    @property
    def company_id(self) -> Optional[str]:
        return get_api_company_id()

    @company_id.setter
    def company_id(self, value: Optional[str]) -> None:
        set_api_company_id(value)

    @property
    def token_source(self) -> str:
        return get_api_token_source()

    @token_source.setter
    def token_source(self, value: str) -> None:
        set_api_token_source(value)

    # ------------------------------------------------------------------
    # Authentication
    # ------------------------------------------------------------------

    def set_token(self, token: str) -> None:
        """Set the access token directly (used by OAuth flow)."""
        if not token:
            logger.error("Attempted to set empty token!")
            return

        if self.token_source == "direct_login":
            logger.info("Keeping existing direct login token instead of setting OAuth token")
            return

        logger.info("Setting Norman API token from OAuth flow")
        self.access_token = token
        self.token_source = "oauth"

        if not self.company_id:
            try:
                logger.info("Attempting to get company ID with OAuth token")
                self._set_company_id()
            except Exception as e:
                logger.error(f"Error setting company ID with OAuth token: {str(e)}")
        else:
            logger.info(f"Using existing company ID: {self.company_id}")

    def authenticate(self) -> None:
        """Authenticate with Norman Finance API and get access token."""
        if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
            raise ValueError(
                "Norman Finance credentials not set. Please set NORMAN_EMAIL "
                "and NORMAN_PASSWORD environment variables."
            )

        username = config.NORMAN_EMAIL.split('@')[0]
        auth_url = urljoin(config.api_base_url, "api/v1/auth/token/")

        payload = {
            "username": username,
            "email": config.NORMAN_EMAIL,
            "password": config.NORMAN_PASSWORD,
        }

        try:
            response = requests.post(auth_url, json=payload, timeout=config.NORMAN_API_TIMEOUT)
            response.raise_for_status()

            auth_data = response.json()
            self.access_token = auth_data.get("access")
            self.refresh_token = auth_data.get("refresh")
            self.token_source = "env"

            self._set_company_id()

            logger.info(
                "Successfully authenticated with Norman Finance API using environment credentials"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to authenticate with Norman Finance API: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

    def _set_company_id(self) -> None:
        """Get the company ID for the authenticated user and cache it."""
        companies_url = urljoin(config.api_base_url, "api/v1/companies/")
        token = self.access_token
        if not token:
            logger.warning("_set_company_id called with no access token")
            return

        try:
            logger.info(f"Fetching company information with token: {token[:8]}...")

            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "NormanMCPServer/0.1.0",
                "X-Requested-With": "XMLHttpRequest",
            }

            response = requests.get(
                companies_url,
                headers=headers,
                timeout=config.NORMAN_API_TIMEOUT,
            )
            response.raise_for_status()
            response_data = response.json()

            companies = response_data.get("results", [])
            if not companies:
                logger.warning("No companies found for user")
                return

            company_id = companies[0].get("publicId")
            if company_id:
                self.company_id = company_id
                self._persist_company_id_for_session(company_id)
                logger.info(f"✅ Using company ID from API: {company_id}")
            else:
                logger.warning("Company found but no publicId available")
        except Exception as e:
            logger.error(f"Error getting company ID: {str(e)}")

    # ------------------------------------------------------------------
    # Core request
    # ------------------------------------------------------------------

    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        files: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Make a request to the Norman Finance API with security controls."""
        token = get_api_token()

        if not token:
            try:
                logger.warning(
                    "No Norman token available. Attempting authentication with "
                    "environment variables..."
                )
                self.authenticate()
                token = get_api_token()
            except Exception as e:
                logger.error(f"Authentication failed: {str(e)}")
                return {"error": "No authentication token available. Please authenticate first."}

        if not token:
            return {"error": "No authentication token available. Please authenticate first."}

        if not validate_url(url):
            logger.error(f"Invalid or potentially dangerous URL: {url}")
            raise ValueError(f"Invalid or potentially dangerous URL: {url}")

        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "NormanMCPServer/0.1.0",
            "X-Requested-With": "XMLHttpRequest",
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }

        logger.debug(
            f"Making API request to {url} with token source: {self.token_source}"
        )

        company_id = get_api_company_id()

        if not company_id and not url.endswith("companies/"):
            logger.debug(
                "No company ID set yet, will be determined by API or later from companies endpoint"
            )

        if params is None:
            params = {}

        if company_id and not url.endswith("companies/"):
            logger.debug(f"Using company ID for request: {company_id}")
            if "companyId" not in params:
                params["companyId"] = company_id

        if params:
            sanitized_params: Dict[str, Any] = {}
            for key, value in params.items():
                if isinstance(value, str):
                    sanitized_params[key] = validate_input(value)
                else:
                    sanitized_params[key] = value
            params = sanitized_params

        if json_data:
            sanitized_json: Dict[str, Any] = {}
            for key, value in json_data.items():
                if isinstance(value, str):
                    sanitized_json[key] = validate_input(value)
                elif isinstance(value, dict):
                    sanitized_nested: Dict[str, Any] = {}
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
                    timeout=config.NORMAN_API_TIMEOUT,
                )
            else:
                response = requests.request(
                    method=method,
                    url=url,
                    headers=headers,
                    params=params,
                    json=json_data,
                    files=files,
                    timeout=config.NORMAN_API_TIMEOUT,
                )
            response.raise_for_status()

            try:
                if response.content:
                    return response.json()
                return {}
            except ValueError:
                if response.headers.get('content-type', '').startswith('text/'):
                    return {"content": response.text}
                return {"success": True, "message": "Request successful"}

        except requests.exceptions.HTTPError as e:
            if e.response.status_code == 401:
                if self.token_source == "env":
                    logger.info("Env token expired, re-authenticating...")
                    try:
                        self.authenticate()
                    except Exception as auth_err:
                        logger.error(f"Re-auth failed: {auth_err}")
                        return {
                            "error": "Authentication failed. Check NORMAN_EMAIL/NORMAN_PASSWORD.",
                            "status_code": 401,
                        }
                    return self._make_request(method, url, params, json_data, files)

                new_norman_token = self._refresh_oauth_norman_token()
                if new_norman_token:
                    set_api_token(new_norman_token)
                    self.token_source = "global"
                    return self._make_request(method, url, params, json_data, files)

                logger.warning("Cannot refresh Norman token; client must reconnect")
                set_api_token(None)
                return {
                    "error": (
                        "Your Norman session expired. Please disconnect and reconnect "
                        "the Norman connector in your AI client to re-authenticate."
                    ),
                    "status_code": 401,
                }
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

    # ------------------------------------------------------------------
    # OAuth helpers
    # ------------------------------------------------------------------

    def _refresh_oauth_norman_token(self) -> Optional[str]:
        """Refresh the Norman access token for the current MCP request (OAuth).

        Returns the new Norman access token or None if refresh isn't possible.
        Also updates the per-request token so subsequent calls in this
        request see the new token.
        """
        try:
            provider = get_oauth_provider()
            if provider is None:
                return None

            access_token = get_access_token()
            mcp_token = access_token.token if access_token else None
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
        """Set a company id for the current request and persist it for the session."""
        logger.info(f"Manually setting company ID to: {company_id}")
        self.company_id = company_id
        self._persist_company_id_for_session(company_id)

    def _persist_company_id_for_session(self, company_id: str) -> None:
        """Cache the company id against the current MCP token so subsequent requests
        (which each get a fresh ContextVar) pick it up via the provider mapping."""
        try:
            provider = get_oauth_provider()
            if provider is None:
                return
            access_token = get_access_token()
            mcp_token = access_token.token if access_token else None
            if mcp_token and hasattr(provider, "set_company_for_token"):
                provider.set_company_for_token(mcp_token, company_id)
        except Exception as e:
            logger.debug(f"Could not persist company_id to session: {e}")
