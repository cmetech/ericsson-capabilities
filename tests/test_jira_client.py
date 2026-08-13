from __future__ import annotations

import json
from collections import deque

import httpx
import pytest

from jira_test_support import client, models, transport


JiraClient = client.JiraClient
is_cloudflare_1010_response = client.is_cloudflare_1010_response
is_rest_version_unsupported = client.is_rest_version_unsupported
JiraAuth = models.JiraAuth
JiraError = models.JiraError
TransportResponse = models.TransportResponse
NativeTransport = transport.NativeTransport


def auth(**overrides):
    values = {
        "origin": "https://jira.example.test",
        "authorization": "Bearer secret-token",
        "auth_mode": "bearer",
        "rest_api_version": "auto",
        "transport": "native",
        "curl_executable": "/usr/bin/curl",
        "request_timeout_seconds": 30,
        "default_max_results": 25,
    }
    values.update(overrides)
    return JiraAuth(**values)


def response(status=200, payload=None, *, headers=None, body=None):
    if body is None:
        body = json.dumps({} if payload is None else payload).encode()
    return TransportResponse(status=status, headers=headers or {}, body=body)


class FakeTransport:
    def __init__(self, *outcomes):
        self.outcomes = deque(outcomes)
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def close(self):
        pass


def test_rest_auto_prefers_v3_and_returns_bounded_json():
    transport = FakeTransport(response(payload={"issues": []}))
    client = JiraClient(auth(), native_transport=transport)

    assert client.rest_json("GET", "search", params={"jql": "x"}) == {"issues": []}
    assert transport.calls[0][1] == "/rest/api/3/search"
    assert transport.calls[0][2]["params"] == {"jql": "x"}


def test_rest_auto_falls_back_to_v2_only_for_classified_missing_endpoint():
    unsupported = response(
        404,
        {"errorMessages": ["REST API v3 endpoint is not available"]},
        headers={"content-type": "application/json"},
    )
    transport = FakeTransport(unsupported, response(payload={"issues": [1]}))
    client = JiraClient(auth(), native_transport=transport)

    assert client.rest_json("GET", "search") == {"issues": [1]}
    assert [call[1] for call in transport.calls] == [
        "/rest/api/3/search",
        "/rest/api/2/search",
    ]


@pytest.mark.parametrize(
    "failure",
    [
        response(401, {"errorMessages": ["REST API v3 endpoint is not available"]}),
        response(403, {"errorMessages": ["REST API v3 endpoint is not available"]}),
        response(404, {"errorMessages": ["issue does not exist"]}),
        response(500, {"errorMessages": ["REST API v3 endpoint is not available"]}),
        response(404, body=b"not-json", headers={"content-type": "text/plain"}),
    ],
)
def test_auth_permission_generic_and_malformed_failures_do_not_version_fallback(failure):
    transport = FakeTransport(failure)
    client = JiraClient(auth(), native_transport=transport, max_retries=0)

    with pytest.raises(JiraError):
        client.rest_json("GET", "search")

    assert len(transport.calls) == 1


def test_explicit_rest_version_never_probes_another_version():
    transport = FakeTransport(response(404, payload={"errorMessages": ["REST API v3 endpoint is not available"]}))
    client = JiraClient(auth(rest_api_version="2"), native_transport=transport)

    with pytest.raises(JiraError, match="not found"):
        client.rest_json("GET", "issue/ABC-1")
    assert [call[1] for call in transport.calls] == ["/rest/api/2/issue/ABC-1"]


def test_get_retries_bounded_transient_status_and_honors_retry_after():
    sleeps = []
    transport = FakeTransport(
        response(429, headers={"retry-after": "2"}),
        response(503),
        response(payload={"ok": True}),
    )
    client = JiraClient(auth(), native_transport=transport, sleep=sleeps.append)

    assert client.rest_json("GET", "search") == {"ok": True}
    assert sleeps == [2.0, 1.0]
    assert len(transport.calls) == 3


@pytest.mark.parametrize("status", [401, 403, 400, 404, 409])
def test_non_transient_status_is_never_retried(status):
    transport = FakeTransport(response(status))
    client = JiraClient(auth(), native_transport=transport)

    with pytest.raises(JiraError):
        client.rest_json("GET", "search")
    assert len(transport.calls) == 1


def test_write_ambiguity_is_never_retried_on_status_or_transport_failure():
    for outcome in (
        response(503),
        httpx.ConnectError("secret destination diagnostic"),
        httpx.ReadTimeout("secret timeout diagnostic"),
    ):
        transport = FakeTransport(outcome)
        client = JiraClient(auth(), native_transport=transport)
        with pytest.raises(JiraError) as caught:
            client.rest_json("POST", "issue/ABC-1/comment", json_body={"body": "x"})
        assert caught.value.category == "write_ambiguous"
        assert "secret" not in str(caught.value)
        assert len(transport.calls) == 1


def test_read_transport_failure_retries_but_remains_safely_classified():
    transport = FakeTransport(
        httpx.ConnectError("dns secret diagnostic"),
        response(payload={"ok": True}),
    )
    client = JiraClient(auth(), native_transport=transport)

    assert client.rest_json("GET", "search") == {"ok": True}
    assert len(transport.calls) == 2


def test_cancellation_and_deadline_stop_before_transport():
    transport = FakeTransport(response(payload={"ok": True}))
    cancelled = JiraClient(
        auth(), native_transport=transport, cancel_check=lambda: True
    )
    with pytest.raises(JiraError) as caught:
        cancelled.rest_json("GET", "search")
    assert caught.value.category == "cancelled"
    assert transport.calls == []

    clock_values = iter([10.0, 41.0])
    expired = JiraClient(
        auth(request_timeout_seconds=30),
        native_transport=transport,
        clock=lambda: next(clock_values),
    )
    with pytest.raises(JiraError) as caught:
        expired.rest_json("GET", "search")
    assert caught.value.category == "deadline"
    assert transport.calls == []


def test_request_rejects_absolute_cross_origin_and_unsafe_resource_paths():
    transport = FakeTransport(response(payload={}))
    client = JiraClient(auth(), native_transport=transport)

    for resource in (
        "https://other.example.test/rest/api/3/search",
        "//other.example.test/search",
        "../search",
        "search?token=secret-token",
    ):
        with pytest.raises(JiraError) as caught:
            client.rest_json("GET", resource)
        assert caught.value.category == "invalid_input"
    assert transport.calls == []


def test_malformed_or_oversized_success_response_is_rejected_without_body_echo():
    for body in (b"remote secret not json", b"x" * 1_048_577):
        transport = FakeTransport(response(body=body))
        client = JiraClient(auth(), native_transport=transport)
        with pytest.raises(JiraError) as caught:
            client.rest_json("GET", "search")
        assert caught.value.category in {"invalid_remote_data", "capacity"}
        assert "remote secret" not in str(caught.value)


def test_native_transport_pins_origin_headers_deadline_and_redirect_policy():
    requests = []

    def send(request):
        requests.append(request)
        return httpx.Response(200, json={"ok": True})

    transport = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = transport.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert result.status == 200
    assert requests[0].url == "https://jira.example.test/rest/api/3/search"
    assert requests[0].headers["authorization"] == "Bearer secret-token"
    assert requests[0].extensions["timeout"]["read"] == 7


@pytest.mark.parametrize(
    ("candidate", "expected"),
    [
        (
            response(
                403,
                headers={"server": "cloudflare", "cf-ray": "abc", "content-type": "text/html"},
                body=b"<title>Access denied | error 1010</title>",
            ),
            True,
        ),
        (response(403, body=b"error 1010"), False),
        (response(403, headers={"server": "cloudflare"}, body=b"generic forbidden"), False),
        (response(500, headers={"server": "cloudflare", "cf-ray": "abc"}, body=b"error 1010"), False),
        (response(403, headers={"server": "cloudflare", "cf-ray": "abc"}, body=b"x" * 8193 + b"error 1010"), False),
    ],
)
def test_auto_curl_classifier_is_exact_response_data(candidate, expected):
    assert is_cloudflare_1010_response(candidate) is expected


def test_rest_fallback_classifier_is_exact_bounded_json_data():
    classified = response(
        404,
        {"errorMessages": ["REST API v3 endpoint is not available"]},
        headers={"content-type": "application/json"},
    )
    assert is_rest_version_unsupported(classified) is True
    assert is_rest_version_unsupported(response(410, {"errorMessages": ["gone"]})) is False
    assert is_rest_version_unsupported(response(404, body=b"x" * 8193)) is False
