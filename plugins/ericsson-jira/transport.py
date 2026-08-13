"""Native bounded HTTP transport for Jira."""

from __future__ import annotations

from typing import Any, Mapping
from urllib.parse import urlsplit

import httpx

if __package__:
    from .models import JiraAuth, JiraError, TransportResponse
else:
    from models import JiraAuth, JiraError, TransportResponse


class NativeTransport:
    def __init__(
        self,
        authentication: JiraAuth,
        *,
        http_transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.auth = authentication
        self._client = httpx.Client(
            base_url=authentication.origin,
            headers={**authentication.headers, "Accept": "application/json"},
            timeout=authentication.request_timeout_seconds,
            follow_redirects=False,
            trust_env=False,
            transport=http_transport,
        )

    def __repr__(self) -> str:
        return f"NativeTransport(origin={self.auth.origin!r})"

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _validate_path(path: str) -> None:
        parsed = urlsplit(path) if isinstance(path, str) else None
        if (
            parsed is None
            or not path.startswith("/rest/api/")
            or len(path) > 8192
            or parsed.scheme
            or parsed.netloc
            or parsed.query
            or parsed.fragment
            or "\x00" in path
            or ".." in path.split("/")
        ):
            raise JiraError("invalid_input")

    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        timeout_seconds: float,
    ) -> TransportResponse:
        self._validate_path(path)
        if method not in {"GET", "POST", "PUT", "DELETE"}:
            raise JiraError("invalid_input")
        response = self._client.request(
            method,
            path,
            params=params,
            json=json_body,
            timeout=httpx.Timeout(timeout_seconds),
        )
        return TransportResponse(
            status=response.status_code,
            headers=dict(response.headers),
            body=response.content,
        )
