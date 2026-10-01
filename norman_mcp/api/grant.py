"""Norman API reads pinned to one stored OAuth grant and company.

Background work acts for someone who is not the current request, so it reads
with exactly that grant: never the request ContextVars, the shared API client
or single-user settings. A Norman 401 gets one refresh through the grant itself
(Norman access tokens last an hour); if that fails, the read fails.
"""

import asyncio
from typing import Any

import httpx

from norman_mcp.security.utils import validate_url

HEADERS = {"User-Agent": "NormanMCPServer/0.1.0", "X-Requested-With": "XMLHttpRequest"}


class GrantAPI:
    """`arequest`-compatible reads for one grant, usable with apps.inbox.read."""

    def __init__(
        self,
        provider: Any,
        mcp_token: str,
        company_id: str | None = None,
        *,
        client: httpx.AsyncClient | None = None,
        timeout: float = 10.0,
    ) -> None:
        self.provider = provider
        self.mcp_token = mcp_token
        self.company_id = company_id
        self.client = client
        self.timeout = timeout

    async def arequest(self, method: str, url: str, **kwargs: Any) -> dict[str, Any]:
        if method != "GET" or not validate_url(url):
            raise ValueError("Grant-pinned access only supports trusted API reads.")
        token = self.provider.get_norman_token(self.mcp_token)
        if not token:
            return {"error": "Norman connection is unavailable.", "status_code": 401}
        params = kwargs.get("params")
        response = await self._get(url, token, params)
        if response is not None and response.status_code == 401:
            refreshed = await asyncio.to_thread(
                self.provider.refresh_norman_token_sync, self.mcp_token
            )
            if refreshed and refreshed != token:
                response = await self._get(url, refreshed, params)
        if response is None:
            return {"error": "Norman is unavailable."}
        if response.status_code != 200:
            return {"error": "Norman request failed.", "status_code": response.status_code}
        try:
            data = response.json()
        except ValueError:
            return {"error": "Norman returned an invalid response."}
        return data if isinstance(data, dict) else {"error": "Norman returned an unexpected response."}

    async def _get(self, url: str, token: str, params: Any) -> httpx.Response | None:
        headers = {**HEADERS, "Authorization": "Bearer " + token}
        if self.company_id:
            headers["X-Company-Id"] = str(self.company_id)
        try:
            if self.client is not None:
                return await self.client.get(url, params=params, headers=headers, timeout=self.timeout)
            async with httpx.AsyncClient(
                timeout=self.timeout, follow_redirects=False, trust_env=False
            ) as client:
                return await client.get(url, params=params, headers=headers)
        except httpx.RequestError:
            return None
