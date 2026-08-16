import pytest

from ericsson_common.client import BoundedClient
from ericsson_common.errors import ConnectorError
from ericsson_common.transport import Response


class FakeTransport:
    """Scripted transport: each entry is a Response or an exception to raise."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, path, *, params, json_body, timeout_seconds):
        self.calls.append((method, path))
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _client(script, **kwargs):
    clock = FakeClock()
    transport = FakeTransport(script)
    client = BoundedClient(
        transport,
        service="gitlab",
        clock=clock,
        sleep=clock.sleep,
        **kwargs,
    )
    return client, transport, clock


class TestRetryAfter:
    def test_honours_retry_after_header(self):
        client, transport, clock = _client(
            [
                Response(429, {"Retry-After": "3"}, b""),
                Response(200, {}, b"{}"),
            ]
        )
        client.request("GET", "/api/v4/projects")
        assert clock.slept == [3.0]
        assert len(transport.calls) == 2

    def test_rate_limit_retry_never_sleeps_zero(self):
        """The F1 regression guard: a 429 must not be retried immediately."""
        client, _transport, clock = _client(
            [Response(429, {}, b""), Response(200, {}, b"{}")]
        )
        client.request("GET", "/api/v4/projects")
        assert clock.slept and all(delay > 0 for delay in clock.slept)

    def test_falls_back_to_exponential_backoff(self):
        client, _transport, clock = _client(
            [
                Response(503, {}, b""),
                Response(503, {}, b""),
                Response(200, {}, b"{}"),
            ],
            max_retries=2,
        )
        client.request("GET", "/api/v4/projects")
        assert clock.slept == [0.5, 1.0]

    def test_absurd_retry_after_is_ignored(self):
        client, _transport, clock = _client(
            [Response(429, {"Retry-After": "3600"}, b""), Response(200, {}, b"{}")]
        )
        client.request("GET", "/api/v4/projects")
        assert clock.slept == [0.5]

    def test_unparseable_retry_after_falls_back(self):
        client, _transport, clock = _client(
            [Response(429, {"Retry-After": "soon"}, b""), Response(200, {}, b"{}")]
        )
        client.request("GET", "/api/v4/projects")
        assert clock.slept == [0.5]

    def test_gives_up_after_max_retries(self):
        client, transport, _clock = _client(
            [Response(429, {}, b"")] * 3, max_retries=2
        )
        with pytest.raises(ConnectorError) as excinfo:
            client.request("GET", "/api/v4/projects")
        assert excinfo.value.category == "rate_limited"
        assert len(transport.calls) == 3


class TestMethodAwareRetry:
    def test_non_get_is_never_retried_on_retryable_status(self):
        client, transport, _clock = _client([Response(503, {}, b"")])
        with pytest.raises(ConnectorError) as excinfo:
            client.request("POST", "/api/v4/projects/1/merge_requests")
        assert excinfo.value.category == "write_ambiguous"
        assert len(transport.calls) == 1

    def test_non_get_is_never_retried_on_transport_error(self):
        client, transport, _clock = _client([TimeoutError("boom")])
        with pytest.raises(ConnectorError) as excinfo:
            client.request("PUT", "/api/v4/projects/1")
        assert excinfo.value.category == "write_ambiguous"
        assert len(transport.calls) == 1


class TestDeadlines:
    def test_deadline_exhaustion_raises(self):
        client, _transport, clock = _client(
            [Response(429, {"Retry-After": "5"}, b"")], total_timeout_seconds=2.0
        )
        with pytest.raises(ConnectorError) as excinfo:
            client.request("GET", "/api/v4/projects")
        assert excinfo.value.category == "deadline"

    def test_cancellation_is_observed(self):
        cancelled = {"value": False}
        client, _transport, _clock = _client(
            [Response(200, {}, b"{}")],
            cancel_check=lambda: cancelled["value"],
        )
        cancelled["value"] = True
        with pytest.raises(ConnectorError) as excinfo:
            client.request("GET", "/api/v4/projects")
        assert excinfo.value.category == "cancelled"


class TestErrorMapping:
    def test_error_carries_remediation(self):
        client, _transport, _clock = _client([Response(401, {}, b"")])
        with pytest.raises(ConnectorError) as excinfo:
            client.request("GET", "/api/v4/projects")
        assert excinfo.value.category == "authentication"
        assert excinfo.value.remediation
        assert "gitlab" in excinfo.value.remediation.lower()


class TestRaiseOnStatus:
    def test_non_2xx_is_returned_when_raising_is_disabled(self):
        """The Jira connector must inspect a 404 body to decide whether to
        retry against REST v2, so it needs the response, not an exception."""
        client, _transport, _clock = _client([Response(404, {}, b'{"e":1}')])
        response = client.request(
            "GET", "/api/v4/projects", raise_on_status=False
        )
        assert response.status == 404
        assert response.body == b'{"e":1}'

    def test_retry_policy_still_applies_when_raising_is_disabled(self):
        client, transport, clock = _client(
            [Response(429, {"Retry-After": "1"}, b""), Response(200, {}, b"{}")]
        )
        response = client.request(
            "GET", "/api/v4/projects", raise_on_status=False
        )
        assert clock.slept == [1.0]
        assert response.status == 200
        assert len(transport.calls) == 2

    def test_exhausted_retries_return_the_last_response(self):
        client, _transport, _clock = _client(
            [Response(429, {}, b"")] * 3, max_retries=2
        )
        response = client.request(
            "GET", "/api/v4/projects", raise_on_status=False
        )
        assert response.status == 429

    def test_deadline_still_raises_when_raising_is_disabled(self):
        """raise_on_status only suppresses status errors. Deadline,
        cancellation, capacity and write_ambiguous are client-side facts and
        must never be silently swallowed."""
        client, _transport, _clock = _client(
            [Response(429, {"Retry-After": "5"}, b"")], total_timeout_seconds=2.0
        )
        with pytest.raises(ConnectorError) as excinfo:
            client.request("GET", "/api/v4/projects", raise_on_status=False)
        assert excinfo.value.category == "deadline"

    def test_write_ambiguous_still_raises_when_raising_is_disabled(self):
        client, _transport, _clock = _client([Response(503, {}, b"")])
        with pytest.raises(ConnectorError) as excinfo:
            client.request(
                "POST", "/api/v4/projects/1/merge_requests", raise_on_status=False
            )
        assert excinfo.value.category == "write_ambiguous"

    def test_redirect_is_returned_when_raising_is_disabled(self):
        client, _transport, _clock = _client([Response(302, {}, b"")])
        response = client.request(
            "GET", "/api/v4/projects", raise_on_status=False
        )
        assert response.status == 302
