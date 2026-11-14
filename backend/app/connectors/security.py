import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit

from app.connectors.base import ConnectorError


def validate_public_url(url: str) -> str:
    parts = urlsplit(url)
    if parts.scheme.casefold() not in {"https", "http"} or not parts.hostname or parts.username or parts.password:
        raise ConnectorError("A public HTTP or HTTPS URL is required")
    try:
        _port = parts.port
    except ValueError as exc:
        raise ConnectorError("The URL port is invalid") from exc
    host = parts.hostname.casefold().rstrip(".")
    if host in {"localhost", "localhost.localdomain"} or host.endswith((".localhost", ".local", ".internal")):
        raise ConnectorError("Private or local network URLs are not permitted")
    try:
        address = ipaddress.ip_address(host)
        if not address.is_global:
            raise ConnectorError("Private or reserved network addresses are not permitted")
    except ValueError:
        pass
    return url


async def ensure_public_dns(url: str) -> None:
    validate_public_url(url)
    host = urlsplit(url).hostname
    try:
        results = await asyncio.to_thread(socket.getaddrinfo, host, None, type=socket.SOCK_STREAM)
    except OSError as exc:
        raise ConnectorError("The configured public host could not be resolved") from exc
    addresses = {ipaddress.ip_address(row[4][0]) for row in results}
    if not addresses or any(not address.is_global for address in addresses):
        raise ConnectorError("The configured host resolves to a private or reserved address")
