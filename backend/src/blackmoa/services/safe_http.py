"""Pinned outbound HTTP transport for user-controlled URLs.

The trust boundary here is the resolved IP, not just the URL string. DNS answers
are validated once and the TCP socket is opened directly to one of those exact
addresses. HTTPS still uses the original hostname for SNI/certificate
verification. This closes the validation/connect DNS-rebinding TOCTOU that a
normal HTTP client would otherwise re-introduce.
"""
from __future__ import annotations

import asyncio
import ipaddress
import socket
import ssl
from dataclasses import dataclass
from urllib.parse import quote, urljoin, urlsplit, urlunsplit

from blackmoa.config import get_settings
from blackmoa.core import pools

MAX_HEADER_BYTES = 64 * 1024
DEFAULT_MAX_BODY_BYTES = 5 * 1024 * 1024
_REDIRECT_STATUSES = {301, 302, 303, 307, 308}


@dataclass(frozen=True)
class SafeHTTPResponse:
    status_code: int
    headers: dict[str, str]
    content: bytes
    url: str

    @property
    def encoding(self) -> str:
        ctype = self.headers.get("content-type", "")
        for part in ctype.split(";")[1:]:
            key, sep, value = part.strip().partition("=")
            if sep and key.lower() == "charset":
                return value.strip().strip('"\'') or "utf-8"
        return "utf-8"


@dataclass(frozen=True)
class _Target:
    url: str
    scheme: str
    host: str
    port: int
    request_target: str
    host_header: str
    ips: tuple[str, ...]


def _allowed_ports() -> set[int]:
    raw = get_settings().outbound_allowed_ports
    ports: set[int] = set()
    for piece in raw.split(","):
        piece = piece.strip()
        if not piece:
            continue
        try:
            port = int(piece)
        except ValueError as e:
            raise ValueError("invalid_outbound_port_config") from e
        if not 1 <= port <= 65535:
            raise ValueError("invalid_outbound_port_config")
        ports.add(port)
    return ports or {80, 443}


def _public_ips(host: str, port: int) -> tuple[str, ...]:
    try:
        infos = socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)
    except socket.gaierror as e:
        raise ValueError("dns_failed") from e

    seen: list[str] = []
    for info in infos:
        raw = info[4][0]
        try:
            ip = ipaddress.ip_address(raw)
        except ValueError as e:
            raise ValueError("blocked_host") from e
        # is_global also excludes shared, documentation, benchmark, link-local,
        # loopback and other special-use ranges. Reject the whole hostname if
        # even one DNS answer is non-public so address selection cannot weaken
        # the policy.
        if not ip.is_global:
            raise ValueError("blocked_host")
        value = str(ip)
        if value not in seen:
            seen.append(value)
    if not seen:
        raise ValueError("dns_failed")
    return tuple(seen)


def _normalize_target(url: str) -> tuple[str, str, int, str, str]:
    if "\r" in url or "\n" in url:
        raise ValueError("invalid_url")
    p = urlsplit(url)
    scheme = p.scheme.lower()
    if scheme not in ("http", "https") or not p.hostname:
        raise ValueError("invalid_url")
    if p.username is not None or p.password is not None:
        raise ValueError("url_credentials_forbidden")
    try:
        host = p.hostname.encode("idna").decode("ascii").lower()
        port = p.port or (443 if scheme == "https" else 80)
    except (UnicodeError, ValueError) as e:
        raise ValueError("invalid_url") from e
    if port not in _allowed_ports():
        raise ValueError("blocked_port")

    # Preserve existing percent escapes while encoding raw Unicode safely.
    path = quote(p.path or "/", safe="/%:@!$&'()*+,;=-._~%")
    query = quote(p.query, safe="=&?/:;+,%@!$'()*-._~")
    request_target = path + (f"?{query}" if query else "")
    host_for_header = f"[{host}]" if ":" in host else host
    default_port = 443 if scheme == "https" else 80
    host_header = host_for_header if port == default_port else f"{host_for_header}:{port}"
    normalized = urlunsplit((scheme, host_header, path, query, ""))
    return normalized, host, port, request_target, host_header


def resolve_target(url: str) -> _Target:
    normalized, host, port, request_target, host_header = _normalize_target(url)
    return _Target(
        url=normalized,
        scheme=urlsplit(normalized).scheme,
        host=host,
        port=port,
        request_target=request_target,
        host_header=host_header,
        ips=_public_ips(host, port),
    )


def check_url(url: str) -> str:
    """Synchronously validate a URL for save-time checks.

    Runtime requests must still use :func:`safe_request`; validation alone is
    intentionally not treated as authorization for a later normal HTTP client.
    """
    return resolve_target(url).url


def _header_lines(headers: dict[str, str]) -> bytes:
    out: list[bytes] = []
    for name, value in headers.items():
        if not name or any(ch in name for ch in "\r\n:") or "\r" in value or "\n" in value:
            raise ValueError("invalid_header")
        try:
            out.append(f"{name}: {value}\r\n".encode("latin-1"))
        except UnicodeEncodeError as e:
            raise ValueError("invalid_header") from e
    return b"".join(out)


async def _read_chunked(reader: asyncio.StreamReader, max_bytes: int) -> bytes:
    body = bytearray()
    trailer_bytes = 0
    while True:
        line = await reader.readline()
        if not line or len(line) > 256:
            raise ValueError("invalid_chunked_response")
        try:
            size = int(line.split(b";", 1)[0].strip(), 16)
        except ValueError as e:
            raise ValueError("invalid_chunked_response") from e
        if size < 0 or len(body) + size > max_bytes:
            raise ValueError("response_too_large")
        if size == 0:
            while True:
                trailer = await reader.readline()
                trailer_bytes += len(trailer)
                if trailer_bytes > MAX_HEADER_BYTES:
                    raise ValueError("response_headers_too_large")
                if trailer in (b"\r\n", b"\n", b""):
                    return bytes(body)
        body.extend(await reader.readexactly(size))
        if await reader.readexactly(2) != b"\r\n":
            raise ValueError("invalid_chunked_response")


async def _read_body(
    reader: asyncio.StreamReader,
    *,
    method: str,
    status: int,
    headers: dict[str, str],
    max_bytes: int,
) -> bytes:
    if method == "HEAD" or status in (204, 304) or 100 <= status < 200:
        return b""
    encoding = headers.get("content-encoding", "").strip().lower()
    if encoding not in ("", "identity"):
        raise ValueError("unsupported_content_encoding")
    transfer = headers.get("transfer-encoding", "").lower()
    if "chunked" in transfer:
        return await _read_chunked(reader, max_bytes)
    if "content-length" in headers:
        try:
            length = int(headers["content-length"])
        except ValueError as e:
            raise ValueError("invalid_content_length") from e
        if length < 0 or length > max_bytes:
            raise ValueError("response_too_large")
        return await reader.readexactly(length) if length else b""

    body = bytearray()
    while True:
        chunk = await reader.read(min(64 * 1024, max_bytes + 1 - len(body)))
        if not chunk:
            return bytes(body)
        body.extend(chunk)
        if len(body) > max_bytes:
            raise ValueError("response_too_large")


async def _request_target(
    method: str,
    target: _Target,
    *,
    headers: dict[str, str] | None,
    body: bytes,
    max_bytes: int,
    timeout: float,
) -> SafeHTTPResponse:
    request_headers = {
        "Host": target.host_header,
        "User-Agent": "black-moa/1.0 (+secretary)",
        "Accept": "*/*",
        "Accept-Encoding": "identity",
        "Connection": "close",
    }
    for name, value in (headers or {}).items():
        if name.lower() in {"host", "content-length", "connection", "accept-encoding"}:
            continue
        request_headers[name] = str(value)
    request_headers["Content-Length"] = str(len(body))
    head = (
        f"{method} {target.request_target} HTTP/1.1\r\n".encode("ascii")
        + _header_lines(request_headers)
        + b"\r\n"
    )

    last_error: Exception | None = None
    for ip in target.ips[:8]:
        writer: asyncio.StreamWriter | None = None
        try:
            tls = ssl.create_default_context() if target.scheme == "https" else None
            async with asyncio.timeout(timeout):
                reader, writer = await asyncio.open_connection(
                    ip,
                    target.port,
                    ssl=tls,
                    server_hostname=target.host if tls else None,
                    limit=MAX_HEADER_BYTES + 1024,
                )
                writer.write(head)
                if body:
                    writer.write(body)
                await writer.drain()
                raw_headers = await reader.readuntil(b"\r\n\r\n")
                if len(raw_headers) > MAX_HEADER_BYTES:
                    raise ValueError("response_headers_too_large")
                lines = raw_headers[:-4].split(b"\r\n")
                try:
                    _, raw_status, _ = lines[0].decode("latin-1").split(" ", 2)
                    status = int(raw_status)
                except (ValueError, IndexError) as e:
                    raise ValueError("invalid_http_response") from e
                response_headers: dict[str, str] = {}
                for line in lines[1:]:
                    name, sep, value = line.partition(b":")
                    if not sep:
                        raise ValueError("invalid_http_response")
                    key = name.decode("latin-1").strip().lower()
                    val = value.decode("latin-1").strip()
                    if key in response_headers and key not in {"set-cookie"}:
                        response_headers[key] += ", " + val
                    else:
                        response_headers[key] = val
                content = await _read_body(
                    reader,
                    method=method,
                    status=status,
                    headers=response_headers,
                    max_bytes=max_bytes,
                )
                return SafeHTTPResponse(status, response_headers, content, target.url)
        except (OSError, ssl.SSLError, TimeoutError, asyncio.IncompleteReadError) as e:
            last_error = e
        finally:
            if writer is not None:
                writer.close()
                try:
                    await writer.wait_closed()
                except Exception:
                    pass
    if last_error is not None:
        raise ConnectionError("safe outbound request failed") from last_error
    raise ConnectionError("safe outbound request failed")


async def safe_request(
    method: str,
    url: str,
    *,
    headers: dict[str, str] | None = None,
    body: bytes | None = None,
    max_bytes: int = DEFAULT_MAX_BODY_BYTES,
    timeout: float = 20.0,
    max_redirects: int = 0,
) -> SafeHTTPResponse:
    method = method.upper().strip()
    if method not in {"GET", "HEAD", "POST", "PUT", "PATCH", "DELETE"}:
        raise ValueError("unsupported_method")
    payload = body or b""
    current = url
    for redirect_index in range(max_redirects + 1):
        target = await pools.to_thread("misc", resolve_target, current)
        response = await _request_target(
            method,
            target,
            headers=headers,
            body=payload,
            max_bytes=max_bytes,
            timeout=timeout,
        )
        location = response.headers.get("location")
        if response.status_code not in _REDIRECT_STATUSES or not location:
            return response
        if redirect_index >= max_redirects:
            return response
        current = urljoin(target.url, location)
        if response.status_code == 303 or (response.status_code in {301, 302} and method == "POST"):
            method = "GET"
            payload = b""
    raise ValueError("too_many_redirects")
