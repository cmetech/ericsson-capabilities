"""HTTP transport with bounded responses.

Deliberately separate from the retry/breaker policy in client.py: the Jira
connector reaches its instance through a curl fallback on hosts where the
native client is blocked by Cloudflare, and that transport must be
swappable without duplicating retry logic.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

import httpx

if __package__:
    from .errors import ConnectorError
else:  # standalone source tests import modules directly from the plugin root
    from errors import ConnectorError

__all__ = ["Response", "HttpxTransport"]


@dataclass(frozen=True)
class Response:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def header(self, name: str) -> str:
        """Case-insensitive header lookup; missing headers read as empty."""
        lowered = name.lower()
        for key, value in self.headers.items():
            if key.lower() == lowered:
                return value
        return ""


class HttpxTransport:
    """Synchronous transport that streams and caps every response body.

    ``trust_env=False`` and ``follow_redirects=False`` are both deliberate:
    the former stops a corporate proxy environment from silently rerouting
    credentialed requests, the latter stops a redirect from replaying the
    Authorization header to another host.
    """

    def __init__(
        self,
        *,
        base_url: str,
        headers: Mapping[str, str],
        path_prefix: str,
        max_response_bytes: int = 2 * 1024 * 1024,
        connect_timeout_seconds: float = 5.0,
        tls_context: Any = None,
        mock_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self._path_prefix = path_prefix
        self._max_response_bytes = int(max_response_bytes)
        self._connect_timeout_seconds = float(connect_timeout_seconds)
        options: dict[str, Any] = {
            "base_url": base_url,
            "headers": dict(headers),
            "follow_redirects": False,
            "trust_env": False,
        }
        if tls_context is not None:
            options["verify"] = tls_context
        if mock_transport is not None:
            options["transport"] = mock_transport
        self._client = httpx.Client(**options)

    def close(self) -> None:
        self._client.close()

    def _validate_path(self, path: str) -> None:
        parsed = urlsplit(path) if isinstance(path, str) else None
        decoded_segments = unquote(parsed.path).split("/") if parsed else ()
        if (
            not isinstance(path, str)
            or not path.startswith(self._path_prefix)
            or len(path) > 8192
            or parsed.scheme
            or parsed.fragment
            or "\x00" in path
            or any(
                segment in {".", ".."}
                or segment.startswith((".#", "..#"))
                for segment in decoded_segments
            )
        ):
            raise ConnectorError("invalid_input")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json_body: Any | None,
        timeout_seconds: float,
    ) -> Response:
        self._validate_path(path)
        timeout = httpx.Timeout(
            connect=min(self._connect_timeout_seconds, timeout_seconds),
            read=timeout_seconds,
            write=timeout_seconds,
            pool=min(self._connect_timeout_seconds, timeout_seconds),
        )
        body = bytearray()
        with self._client.stream(
            method, path, params=params, json=json_body, timeout=timeout
        ) as response:
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > self._max_response_bytes:
                    raise ConnectorError("capacity")
                body.extend(chunk)
            headers = dict(response.headers)
            status = response.status_code
        return Response(status=status, headers=headers, body=bytes(body))
