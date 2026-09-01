import asyncio
import logging
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urljoin

import requests
from mcp.server.auth.middleware.auth_context import get_access_token

from norman_mcp.context import (
    get_api_company_id,
    get_api_token,
    get_oauth_provider,
    set_api_company_id,
    set_api_token,
)

from ..config.settings import config
from ..security.utils import validate_input, validate_url

# Configure logging
logger = logging.getLogger(__name__)


@dataclass
class NormanAPI:
    """API client for Norman Finance.

    SECURITY: in OAuth mode this object may be shared between concurrent users
    (SSE/stateful transports reuse one instance; stateless HTTP rebuilds it per
    request). It therefore must NOT hold per-request identity. The Norman token
    is resolved per call by `_resolve_norman_token()` and the company id by the
    `company_id` property -- both request-scoped. `access_token` /
    `_env_company_id` below are only for single-tenant env/stdio mode.
    """

    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_source: str = "env"  # can be 'env', 'oauth', or 'direct_login'
    authenticate_on_init: bool = True  # Whether to authenticate on initialization
    # Single-tenant (env/stdio) company id only. In OAuth mode the company id is
    # per-request and lives in a ContextVar -- see the `company_id` property.
    _env_company_id: Optional[str] = None

    @property
    def company_id(self) -> Optional[str]:
        """The company id for the CURRENT request.

        Resolution order, all scoped to the calling user:
        1. The request-scoped ContextVar (seeded by `load_access_token` from the
           caller's own saved selection, or by an earlier lookup this request).
        2. The caller's persisted `switch_company` choice, by MCP token.
        3. The user's first company from the API.

        Deliberately never a plain attribute in OAuth mode: a shared attribute
        pinned whichever company happened to be looked up first and handed it to
        every later caller.
        """
        if self.token_source == "env":
            return self._env_company_id

        cached = get_api_company_id()
        if cached:
            return cached

        # A selection persisted by switch_company outlives the request that made
        # it, so pick it up before falling back to "first company".
        persisted = self._persisted_company_id()
        if persisted:
            set_api_company_id(persisted)
            return persisted

        token = self._resolve_norman_token()
        if not token:
            return None

        company_id = self._fetch_company_id(token)
        if company_id:
            set_api_company_id(company_id)
        return company_id

    @company_id.setter
    def company_id(self, value: Optional[str]) -> None:
        if self.token_source == "env":
            self._env_company_id = value
            return

        set_api_company_id(value)

        # Persist for this caller's later requests. Only the explicit selection
        # path reaches here (switch_company -> set_company); the lazy "first
        # company" lookup above deliberately does not persist, so a default is
        # never mistaken for a choice.
        mcp_token = self._current_mcp_token()
        provider = get_oauth_provider()
        if mcp_token and provider is not None:
            try:
                provider.set_company_for_token(mcp_token, value)
            except Exception as e:
                logger.error(f"Could not persist company selection: {e}")

    @staticmethod
    def _current_mcp_token() -> Optional[str]:
        """The MCP token of the request being served, if there is one."""
        try:
            access_token = get_access_token()
        except Exception:
            return None
        return getattr(access_token, "token", None) if access_token else None

    def _persisted_company_id(self) -> Optional[str]:
        """The company this caller previously selected via switch_company."""
        mcp_token = self._current_mcp_token()
        provider = get_oauth_provider()
        if not mcp_token or provider is None:
            return None
        try:
            return provider.get_company_for_token(mcp_token)
        except Exception as e:
            logger.error(f"Could not read persisted company selection: {e}")
            return None

    def _resolve_norman_token(self) -> Optional[str]:
        """Resolve the Norman access token for the CURRENT request.

        The order here is a security boundary, not a convenience:

        1. The MCP auth context (`get_access_token()`) is set per request by the
           SDK's auth middleware and is the only trustworthy caller identity in
           a multi-tenant process. Map it to a Norman token via the provider.
        2. The request-scoped ContextVar, for transports with no auth context
           (stdio) and for the transparent-refresh path.
        3. `self.access_token` -- ONLY in single-tenant env mode.

        Never fall back from an authenticated request to shared instance state:
        that is exactly how one user ends up querying with another user's token.
        """
        try:
            access_token = get_access_token()
        except Exception:  # no auth context on this transport
            access_token = None

        if access_token is not None:
            mcp_token = getattr(access_token, "token", None)
            provider = get_oauth_provider()
            if provider is not None and mcp_token:
                norman_token = provider.get_norman_token(mcp_token)
                if norman_token:
                    return norman_token
            # Authenticated but unresolvable: use only the request-scoped value.
            return get_api_token()

        scoped = get_api_token()
        if scoped:
            return scoped

        if self.token_source == "env":
            return self.access_token
        return None

    def __post_init__(self):
        """Initialize the API client by authenticating with Norman Finance."""
        # If we already have a token, use it
        if self.access_token:
            return

        # Skip authentication if requested
        if not self.authenticate_on_init:
            logger.info("Skipping automatic authentication on initialization")
            return

        # Check if credentials are available before attempting authentication
        if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
            logger.warning(
                "Norman Finance credentials not set. Please set NORMAN_EMAIL and NORMAN_PASSWORD environment variables."
            )
            logger.warning(
                "The server will start, but API calls will fail until valid credentials are provided."
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
                    "The server will start, but API calls will fail until valid credentials are provided."
                )
            else:
                raise

    def set_token(self, token: str, single_tenant: bool = False) -> None:
        """Set the access token.

        Args:
            token: the Norman access token.
            single_tenant: True for stdio/env credential login, where the whole
                process serves exactly one user and the token may legitimately
                live on the instance. False (default) for OAuth, where the token
                belongs to one request only and MUST stay request-scoped -- one
                shared instance serves every connected user there.
        """
        if not token:
            logger.error("Attempted to set empty token!")
            return

        # If we already have a token from direct login, don't override it with OAuth token
        if self.token_source == "direct_login":
            logger.info("Keeping existing direct login token instead of setting OAuth token")
            return

        if single_tenant:
            logger.info("Setting Norman API token from credential login (single tenant)")
            self.access_token = token
            self.token_source = "env"
            try:
                self._set_company_id()
            except Exception as e:
                logger.error(f"Error setting company ID: {str(e)}")
            return

        logger.info("Setting Norman API token from OAuth flow")
        self.token_source = "oauth"

        # Do NOT store the token on self: this object can be shared between
        # concurrent users. Keep it request-scoped; _resolve_norman_token()
        # re-derives it per call from the request's own auth context.
        set_api_token(token)

        # The company is NOT resolved here on purpose. `load_access_token` has
        # already seeded this caller's saved switch_company selection, and an
        # eager lookup would overwrite it with their first company. The
        # `company_id` property resolves lazily instead -- which also spares an
        # API round trip on requests that never need a company.

    def authenticate(self) -> None:
        """Authenticate with Norman Finance API and get access token."""
        if not config.NORMAN_EMAIL or not config.NORMAN_PASSWORD:
            raise ValueError(
                "Norman Finance credentials not set. Please set NORMAN_EMAIL and NORMAN_PASSWORD environment variables."
            )

        # Extract username from email (as per instructions)
        username = config.NORMAN_EMAIL.split("@")[0]
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

            # Get company ID (user typically has only one company)
            self._set_company_id()

            logger.info(
                "Successfully authenticated with Norman Finance API using environment credentials"
            )
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to authenticate with Norman Finance API: {str(e)}")
            if hasattr(e, "response") and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise

    def _set_company_id(self) -> None:
        """Resolve and store the company id for the env/stdio token."""
        self.company_id = self._fetch_company_id(self.access_token)

    def _fetch_company_id(self, token: Optional[str], _refreshed: bool = False) -> Optional[str]:
        """Look up the first company for `token`'s owner.

        Pure in the token: it stores nothing on `self`, so it is safe to call
        concurrently for different users.

        Handles its own 401. Norman access tokens live one hour, and this lookup
        runs *before* any `_make_request` (tools need the company id to build
        their URL), so it cannot inherit that method's transparent refresh.
        Without the refresh below, an expired token surfaced to the user as the
        misleading "No company available. Please authenticate first." roughly an
        hour after connecting -- which is why permanent authentication appeared
        impossible.
        """
        if not token:
            return None

        # Use the correct URL for getting companies
        companies_url = urljoin(config.api_base_url, "api/v1/companies/")

        try:
            logger.info(f"Fetching company information with token: {token[:8]}...")

            # Make a request directly, not using self._make_request to avoid recursion
            headers = {
                "Authorization": f"Bearer {token}",
                "User-Agent": "NormanMCPServer/0.1.0",
                "X-Requested-With": "XMLHttpRequest",
            }

            response = requests.get(
                companies_url, headers=headers, timeout=config.NORMAN_API_TIMEOUT
            )

            if response.status_code == 401 and not _refreshed:
                refreshed_token = self._reauthenticate_for_company_lookup()
                if refreshed_token:
                    return self._fetch_company_id(refreshed_token, _refreshed=True)
                logger.warning(
                    "Company lookup got 401 and the Norman token could not be "
                    "refreshed; the client needs to reconnect"
                )
                return None

            response.raise_for_status()
            response_data = response.json()

            companies = response_data.get("results", [])

            if not companies:
                logger.warning("No companies found for user")
                return None

            # Use the first company
            company_id = companies[0].get("publicId")
            if company_id:
                logger.info(f"✅ Using company ID from API: {company_id}")
            else:
                logger.warning("Company found but no publicId available")
            return company_id

        except Exception as e:
            logger.error(f"Error getting company ID: {str(e)}")
            # Don't set a fallback company ID - let API response indicate the error
            return None

    def _reauthenticate_for_company_lookup(self) -> Optional[str]:
        """Get a fresh Norman token after the company lookup returned 401.

        OAuth mode refreshes via the provider (the refresh token is indexed by
        the caller's MCP token, so this stays request-scoped). Single-tenant
        env/stdio mode re-authenticates with its configured credentials.
        """
        if self.token_source == "env":
            try:
                self.authenticate()
                return self.access_token
            except Exception as e:
                logger.error(f"Env re-authentication failed during company lookup: {e}")
                return None

        logger.info("Norman token expired during company lookup; refreshing")
        return self._refresh_oauth_norman_token()

    def _make_request(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        files: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Make a request to the Norman Finance API with security controls."""
        # Resolve the caller's token for THIS request. Keep it in a local: it
        # must never be written to `self`, which is shared across users.
        token = self._resolve_norman_token()

        # No token and single-tenant mode: env credentials are the last resort.
        if not token and self.token_source == "env":
            try:
                logger.warning(
                    "No Norman token available. Attempting authentication with environment variables..."
                )
                self.authenticate()
                token = self.access_token
            except Exception as e:
                logger.error(f"Authentication failed: {str(e)}")
                return {"error": "No authentication token available. Please authenticate first."}

        if not token:
            logger.error("No Norman token resolvable for this request")
            return {"error": "No authentication token available. Please authenticate first."}

        # Validate URL to prevent SSRF attacks
        if not validate_url(url):
            logger.error(f"Invalid or potentially dangerous URL: {url}")
            raise ValueError(f"Invalid or potentially dangerous URL: {url}")

        # Set secure headers with our token
        headers = {
            "Authorization": f"Bearer {token}",
            "User-Agent": "NormanMCPServer/0.1.0",
            "X-Requested-With": "XMLHttpRequest",
            # Security headers
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY",
        }

        # Log token source for debugging
        logger.debug(f"Making API request to {url} with token source: {self.token_source}")

        if params is None:
            params = {}

        # Add company ID to params if we have one and the URL requires it.
        # `self.company_id` is request-scoped (see the property), so this can
        # only ever be the calling user's own company.
        if not url.endswith("companies/"):
            company_id = self.company_id
            if company_id:
                logger.debug(f"Using company ID for request: {company_id}")
                if "companyId" not in params:
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

            # Attempt to parse JSON response, but handle non-JSON responses gracefully
            try:
                if response.content:
                    return response.json()
                return {}
            except ValueError:
                # Not JSON, return content as string if it's not binary
                if response.headers.get("content-type", "").startswith("text/"):
                    return {"content": response.text}
                # For binary content, return success message
                return {"success": True, "message": "Request successful"}

        except requests.exceptions.HTTPError as e:
            # Handle token expiration
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

                # OAuth mode: try to refresh the Norman token transparently
                # using the refresh token we stored at code-exchange time.
                # `refresh_norman_token_sync` rewrites the provider's mapping for
                # this MCP token, so the retry re-resolves the fresh token
                # per-request instead of us caching it on the shared client.
                new_norman_token = self._refresh_oauth_norman_token()
                if new_norman_token:
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
                return {
                    "error": "Access forbidden. Check your account permissions.",
                    "status_code": 403,
                }
            elif e.response.status_code == 404:
                logger.error(f"Resource not found: {url}")
                return {"error": "Resource not found", "status_code": 404}
            elif e.response.status_code == 429:
                logger.error("Rate limit exceeded. Please try again later.")
                return {
                    "error": "Rate limit exceeded. Please try again later.",
                    "status_code": 429,
                }
            else:
                logger.error(f"HTTP error: {str(e)}")
                error_detail = None
                if hasattr(e, "response") and e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                    try:
                        error_detail = e.response.json()
                    except (ValueError, AttributeError):
                        error_detail = e.response.text
                result = {
                    "error": f"Request failed: {str(e)}",
                    "status_code": e.response.status_code,
                }
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

    async def arequest(
        self,
        method: str,
        url: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        files: Optional[Any] = None,
    ) -> Dict[str, Any]:
        """Run the blocking requests client off the MCP event loop."""
        return await asyncio.to_thread(
            self._make_request,
            method,
            url,
            params,
            json_data,
            files,
        )

    def _refresh_oauth_norman_token(self) -> Optional[str]:
        """Refresh the Norman access token for the current MCP request (OAuth).

        Returns the new Norman access token or None if refresh isn't possible.
        Also updates the global `_api_token` so subsequent requests in this
        session see the new token.
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
        """Manually set a company ID for this API client."""
        logger.info(f"Manually setting company ID to: {company_id}")
        self.company_id = company_id
