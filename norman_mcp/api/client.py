import logging
import requests
from dataclasses import dataclass
from typing import Any, Dict, Optional
from urllib.parse import urljoin

from ..config.settings import config
from ..security.utils import validate_input, validate_url

# Configure logging
logger = logging.getLogger(__name__)

@dataclass
class NormanAPI:
    """API client for Norman Finance."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    company_id: Optional[str] = None
    
    def __post_init__(self):
        """Initialize the API client by authenticating with Norman Finance."""
        if not self.access_token:
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
            
            # Get company ID (user typically has only one company)
            self._set_company_id()
            
            logger.info("Successfully authenticated with Norman Finance API")
        except requests.exceptions.RequestException as e:
            logger.error(f"Failed to authenticate with Norman Finance API: {str(e)}")
            if hasattr(e, 'response') and e.response is not None:
                logger.error(f"Response: {e.response.text}")
            raise
    
    def _set_company_id(self) -> None:
        """Get the company ID for the authenticated user."""
        companies_url = urljoin(config.api_base_url, "api/v1/companies/")
        
        try:
            response = self._make_request("GET", companies_url)
            companies = response.get("results", [])
            
            if not companies:
                logger.warning("No companies found for user")
                return
            
            # Use the first company (as per instructions)
            self.company_id = companies[0].get("publicId")
            logger.info(f"Using company ID: {self.company_id}")
        except Exception as e:
            logger.error(f"Error getting company ID: {str(e)}")
            raise
    
    def _make_request(self, method: str, url: str, params: Optional[Dict[str, Any]] = None, 
                     json_data: Optional[Dict[str, Any]] = None, 
                     files: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """Make a request to the Norman Finance API with security controls."""
        if not self.access_token:
            self.authenticate()
        
        # Validate URL to prevent SSRF attacks
        if not validate_url(url):
            logger.error(f"Invalid or potentially dangerous URL: {url}")
            raise ValueError(f"Invalid or potentially dangerous URL: {url}")
        
        # Set secure headers
        headers = {
            "Authorization": f"Bearer {self.access_token}",
            "User-Agent": "NormanMCPServer/0.1.0",
            "X-Requested-With": "XMLHttpRequest",
            # Security headers
            "X-Content-Type-Options": "nosniff",
            "X-Frame-Options": "DENY"
        }
        
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
                logger.info("Token expired, refreshing...")
                self.authenticate()
                # Retry the request once
                return self._make_request(method, url, params, json_data, files)
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
                if hasattr(e, 'response') and e.response is not None:
                    logger.error(f"Response: {e.response.text}")
                return {"error": f"Request failed: {str(e)}", "status_code": e.response.status_code}
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