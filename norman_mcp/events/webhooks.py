"""Standard Webhooks signing and DNS-pinned HTTPS callback delivery."""

import base64
import hashlib
import hmac
import http.client
import ipaddress
import json
import socket
import ssl
import time
from urllib.parse import urlsplit

MAX_BODY = 256 * 1024


def signing_key(secret: str) -> bytes:
    try:
        if not secret.startswith("whsec_"):
            raise ValueError
        key = base64.b64decode(secret[6:], validate=True)
        if not 24 <= len(key) <= 64:
            raise ValueError
        return key
    except (ValueError, TypeError):
        raise ValueError("Invalid webhook signing secret") from None


def headers(
    secret: str, event_id: str, body: bytes, subscription_id: str, timestamp: int | None = None
) -> dict:
    stamp = int(time.time()) if timestamp is None else timestamp
    message = f"{event_id}.{stamp}.".encode() + body
    signature = base64.b64encode(
        hmac.new(signing_key(secret), message, hashlib.sha256).digest()
    ).decode()
    return {
        "Content-Type": "application/json",
        "webhook-id": event_id,
        "webhook-timestamp": str(stamp),
        "webhook-signature": f"v1,{signature}",
        "X-MCP-Subscription-Id": subscription_id,
    }


def destination(url: str) -> tuple[str, int, str, str]:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
        or len(url) > 2048
    ):
        raise ValueError("Callback must be a public HTTPS URL")
    port = parsed.port or 443
    addresses = socket.getaddrinfo(parsed.hostname, port, type=socket.SOCK_STREAM)
    ips = [str(address[4][0]) for address in addresses]
    if not ips or any(not ipaddress.ip_address(ip).is_global for ip in ips):
        raise ValueError("Callback must resolve only to public addresses")
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    return parsed.hostname, port, path, ips[0]


class PinnedHTTPSConnection(http.client.HTTPSConnection):
    def __init__(self, host: str, port: int, address: str):
        self.ssl_context = ssl.create_default_context()
        super().__init__(host, port, timeout=10, context=self.ssl_context)
        self.address = address

    def connect(self) -> None:
        # DNS is validated once per connection, then connect to that exact IP.
        # Preserve the original hostname for SNI and certificate verification.
        raw = socket.create_connection((self.address, self.port), self.timeout)
        try:
            self.sock = self.ssl_context.wrap_socket(raw, server_hostname=self.host)
        except BaseException:
            raw.close()
            raise


def post(
    url: str,
    secret: str,
    subscription_id: str,
    event_id: str,
    payload: dict,
    *,
    old_secret: str | None = None,
) -> tuple[int, dict]:
    body = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    if len(body) > MAX_BODY:
        raise ValueError("Event payload exceeds 256 KiB")
    host, port, path, address = destination(url)
    connection = PinnedHTTPSConnection(host, port, address)
    try:
        signed = headers(secret, event_id, body, subscription_id)
        if old_secret:
            previous = headers(
                old_secret, event_id, body, subscription_id, int(signed["webhook-timestamp"])
            )
            signed["webhook-signature"] += " " + previous["webhook-signature"]
        connection.request("POST", path, body=body, headers=signed)
        response = connection.getresponse()
        # Read a bounded body; never follow a redirect or echo receiver content.
        raw = response.read(4097)
        try:
            data = json.loads(raw) if len(raw) <= 4096 else {}
        except (ValueError, UnicodeDecodeError):
            data = {}
        return response.status, data if isinstance(data, dict) else {}
    finally:
        connection.close()
