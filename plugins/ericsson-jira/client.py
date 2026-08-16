"""Jira REST client with bounded retry and compatibility classification."""

from __future__ import annotations

from contextlib import contextmanager
import json
import re
import time
from typing import Any, Callable, Mapping

if __package__:
    from ._common.client import BoundedClient
    from ._common.errors import RETRYABLE_STATUSES, ConnectorError
    from ._common.transport import Response
    from .models import JiraAuth, JiraError, TransportResponse
    from .transport import NativeTransport
else:
    from _common.client import BoundedClient
    from _common.errors import RETRYABLE_STATUSES, ConnectorError
    from _common.transport import Response
    from models import JiraAuth, JiraError, TransportResponse
    from transport import NativeTransport


_MAX_RESPONSE_BYTES = 1024 * 1024
_STATUS_CATEGORY = {
    400: "invalid_input",
    401: "authentication",
    403: "permission",
    404: "not_found",
    409: "conflict",
    429: "rate_limited",
}
_RESOURCE = re.compile(r"^[A-Za-z0-9._~!$&'()*+,;=:@%/-]+$")
_REST_UNSUPPORTED_MESSAGES = frozenset(
    {
        "REST API v3 endpoint is not available",
        "REST API v3 endpoint is unsupported",
    }
)
_CLOUDFLARE_1010 = re.compile(rb"(?:error\s*1010|access denied[^<]{0,80}1010)", re.I)


@contextmanager
def _as_jira_error():
    """Translate shared errors at the connector boundary without detail leaks."""

    try:
        yield
    except ConnectorError as exc:
        raise JiraError(exc.category, remediation=exc.remediation) from None


class _SharedTransportAdapter:
    """Preserve Jira's native/curl transport behind the shared interface."""

    def __init__(self, transport) -> None:
        self._transport = transport

    def request(self, *args, **kwargs) -> Response:
        try:
            response = self._transport.request(*args, **kwargs)
        except JiraError as exc:
            raise ConnectorError(exc.category, service="jira") from None
        if isinstance(response, Response):
            return response
        return Response(response.status, response.headers, response.body)

    def close(self) -> None:
        try:
            self._transport.close()
        except JiraError as exc:
            raise ConnectorError(exc.category, service="jira") from None


def _header(response: TransportResponse, name: str) -> str:
    lowered = name.lower()
    for key, value in response.headers.items():
        if key.lower() == lowered:
            return value
    return ""


def is_rest_version_unsupported(response: TransportResponse) -> bool:
    """Classify only the bounded, structured v3-missing compatibility response."""

    if response.status != 404 or len(response.body) > 8192:
        return False
    if "application/json" not in _header(response, "content-type").lower():
        return False
    try:
        payload = json.loads(response.body)
    except (UnicodeDecodeError, json.JSONDecodeError):
        return False
    messages = payload.get("errorMessages") if isinstance(payload, dict) else None
    return (
        isinstance(messages, list)
        and len(messages) == 1
        and messages[0] in _REST_UNSUPPORTED_MESSAGES
    )


def is_cloudflare_1010_response(response: TransportResponse) -> bool:
    """Return true only for the approved bounded Cloudflare error-1010 response."""

    if response.status != 403 or len(response.body) > 8192:
        return False
    server = _header(response, "server").lower()
    ray = _header(response, "cf-ray")
    content_type = _header(response, "content-type").lower()
    return (
        server.startswith("cloudflare")
        and bool(ray)
        and ("text/html" in content_type or "text/plain" in content_type)
        and _CLOUDFLARE_1010.search(response.body) is not None
    )


class JiraClient:
    def __init__(
        self,
        authentication: JiraAuth,
        *,
        native_transport=None,
        transport=None,
        max_retries: int = 2,
        cancel_check: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if type(max_retries) is not int or not 0 <= max_retries <= 4:
            raise JiraError("invalid_configuration")
        self.auth = authentication
        self.max_retries = max_retries
        chosen = transport or native_transport
        if chosen is None:
            chosen = NativeTransport(authentication, cancel_check=cancel_check)
        self._transport = chosen
        self._clock = clock
        with _as_jira_error():
            self._client = BoundedClient(
                _SharedTransportAdapter(chosen),
                service="jira",
                max_retries=max_retries,
                total_timeout_seconds=float(authentication.request_timeout_seconds),
                request_timeout_seconds=float(authentication.request_timeout_seconds),
                cancel_check=cancel_check,
                clock=clock,
                sleep=sleep,
            )

    def __repr__(self) -> str:
        return f"JiraClient(origin={self.auth.origin!r})"

    def close(self) -> None:
        with _as_jira_error():
            self._client.close()

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def _perform(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json_body: Any | None,
        deadline: float,
    ) -> Response:
        with _as_jira_error():
            return self._client.request(
                method,
                path,
                params=params,
                json_body=json_body,
                deadline=deadline,
                raise_on_status=False,
            )

    @staticmethod
    def _validate_resource(resource: str) -> None:
        if (
            not isinstance(resource, str)
            or not resource
            or len(resource) > 4096
            or resource.startswith("/")
            or "://" in resource
            or ".." in resource.split("/")
            or _RESOURCE.fullmatch(resource) is None
        ):
            raise JiraError("invalid_input")

    @staticmethod
    def _raise_status(response: TransportResponse, method: str) -> None:
        if response.status < 400:
            if 300 <= response.status < 400:
                raise JiraError("invalid_remote_data")
            return
        if method != "GET" and response.status in RETRYABLE_STATUSES:
            raise JiraError("write_ambiguous")
        category = _STATUS_CATEGORY.get(response.status)
        if category is None:
            category = "transient" if 500 <= response.status <= 599 else "invalid_remote_data"
        raise JiraError(category)

    @staticmethod
    def _decode(response: TransportResponse, method: str) -> Any:
        JiraClient._raise_status(response, method)
        if len(response.body) > _MAX_RESPONSE_BYTES:
            raise JiraError("capacity")
        try:
            return json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise JiraError("invalid_remote_data") from None

    def rest_json(
        self,
        method: str,
        resource: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        json_body_by_version: Mapping[str, Any] | None = None,
        deadline: float | None = None,
    ) -> Any:
        method = method.upper() if isinstance(method, str) else ""
        if method not in {"GET", "POST", "PUT", "DELETE"}:
            raise JiraError("invalid_input")
        self._validate_resource(resource)
        if deadline is None:
            deadline = self._clock() + self.auth.request_timeout_seconds
        versions = (
            ("3", "2")
            if self.auth.rest_api_version == "auto"
            else (self.auth.rest_api_version,)
        )
        if json_body_by_version is not None and (
            not isinstance(json_body_by_version, Mapping)
            or set(json_body_by_version) != {"3", "2"}
        ):
            raise JiraError("invalid_input")

        def body_for(version: str):
            if json_body_by_version is None:
                return json_body
            return json_body_by_version[version]

        first = self._perform(
            method,
            f"/rest/api/{versions[0]}/{resource}",
            params=params,
            json_body=body_for(versions[0]),
            deadline=deadline,
        )
        if len(versions) == 2 and is_rest_version_unsupported(first):
            first = self._perform(
                method,
                f"/rest/api/{versions[1]}/{resource}",
                params=params,
                json_body=body_for(versions[1]),
                deadline=deadline,
            )
        return self._decode(first, method)
