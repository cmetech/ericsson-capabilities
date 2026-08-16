"""Jira connector behaviour must survive the shared-client migration."""

import importlib

import pytest

from jira_test_support import PACKAGE, client, models, transport as jira_transport

common_errors = importlib.import_module(f"{PACKAGE}._common.errors")
common_transport = importlib.import_module(f"{PACKAGE}._common.transport")

ConnectorError = common_errors.ConnectorError
Response = common_transport.Response
JiraClient = client.JiraClient
is_cloudflare_1010_response = client.is_cloudflare_1010_response
is_rest_version_unsupported = client.is_rest_version_unsupported
JiraError = models.JiraError


class FakeTransport:
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


class FakeAuth:
    origin = "https://jira.test"
    rest_api_version = "auto"
    request_timeout_seconds = 30
    default_max_results = 25


def _client(script, **kwargs):
    clock = FakeClock()
    return (
        JiraClient(FakeAuth(), transport=FakeTransport(script), clock=clock,
                   sleep=clock.sleep, **kwargs),
        clock,
    )


def _transport_failure(category, *, outcome_uncertain):
    failure_type = getattr(jira_transport, "_JiraTransportFailure", None)
    assert failure_type is not None, "Jira transport provenance type is missing"
    return failure_type(category, outcome_uncertain=outcome_uncertain)


class TestPreservedBehaviour:
    def test_v3_unsupported_falls_back_to_v2(self):
        v3_missing = Response(
            404,
            {"Content-Type": "application/json"},
            b'{"errorMessages":["REST API v3 endpoint is not available"]}',
        )
        client, _clock = _client([v3_missing, Response(200, {}, b"{}")])
        client.rest_json("GET", "myself")
        assert client._transport.calls == [
            ("GET", "/rest/api/3/myself"),
            ("GET", "/rest/api/2/myself"),
        ]

    def test_write_is_not_retried(self):
        client, _clock = _client([Response(503, {}, b"")])
        with pytest.raises(JiraError) as excinfo:
            client.rest_json("POST", "issue")
        assert excinfo.value.category == "write_ambiguous"
        # ConnectorError is internal to _common; _as_jira_error translates at
        # the boundary so the host only ever sees the connector-local type.
        assert not isinstance(excinfo.value, ConnectorError)

    def test_retry_after_still_honoured(self):
        client, clock = _client(
            [Response(429, {"Retry-After": "1"}, b""), Response(200, {}, b"{}")]
        )
        client.rest_json("GET", "myself")
        assert clock.slept == [1.0]

    def test_resource_path_traversal_rejected(self):
        client, _clock = _client([])
        with pytest.raises(JiraError):
            client.rest_json("GET", "../../admin")

    def test_absolute_resource_rejected(self):
        client, _clock = _client([])
        with pytest.raises(JiraError):
            client.rest_json("GET", "https://evil.test/x")


class TestTransportFailurePolicy:
    def test_unmarked_transient_read_is_retried_then_succeeds(self):
        client, _clock = _client(
            [JiraError("transient"), Response(200, {}, b"{}")]
        )

        assert client.rest_json("GET", "myself") == {}
        assert len(client._transport.calls) == 2

    def test_unmarked_transient_write_is_ambiguous_without_retry(self):
        client, _clock = _client([JiraError("transient")])

        with pytest.raises(JiraError) as excinfo:
            client.rest_json("POST", "issue")

        assert excinfo.value.category == "write_ambiguous"
        assert not isinstance(excinfo.value, ConnectorError)
        assert len(client._transport.calls) == 1

    def test_repeated_transient_reads_open_the_breaker(self):
        client, _clock = _client(
            [JiraError("transient")] * 5,
            max_retries=0,
        )

        for _ in range(5):
            with pytest.raises(JiraError) as excinfo:
                client.rest_json("GET", "myself")
            assert excinfo.value.category == "transient"

        with pytest.raises(JiraError) as excinfo:
            client.rest_json("GET", "myself")
        assert excinfo.value.category == "circuit_open"
        assert len(client._transport.calls) == 5

    @pytest.mark.parametrize(
        "category",
        ["transient", "capacity", "cancelled", "deadline", "invalid_remote_data"],
    )
    def test_uncertain_write_failure_is_ambiguous(self, category):
        client, _clock = _client(
            [_transport_failure(category, outcome_uncertain=True)]
        )

        with pytest.raises(JiraError) as excinfo:
            client.rest_json("POST", "issue")

        assert excinfo.value.category == "write_ambiguous"
        assert len(client._transport.calls) == 1

    @pytest.mark.parametrize("category", ["transient", "capacity", "cancelled"])
    def test_pre_dispatch_failure_preserves_its_category(self, category):
        client, _clock = _client(
            [_transport_failure(category, outcome_uncertain=False)]
        )

        with pytest.raises(JiraError) as excinfo:
            client.rest_json("POST", "issue")

        assert excinfo.value.category == category
        assert len(client._transport.calls) == 1

    @pytest.mark.parametrize(
        "category", ["capacity", "cancelled", "deadline", "invalid_remote_data"]
    )
    def test_uncertain_non_transient_read_preserves_its_category(self, category):
        client, _clock = _client(
            [_transport_failure(category, outcome_uncertain=True)]
        )

        with pytest.raises(JiraError) as excinfo:
            client.rest_json("GET", "myself")

        assert excinfo.value.category == category
        assert len(client._transport.calls) == 1


class TestClassifiers:
    def test_cloudflare_1010_still_detected(self):
        resp = Response(
            403,
            {"Server": "cloudflare", "CF-RAY": "abc", "Content-Type": "text/html"},
            b"<html>error 1010</html>",
        )
        assert is_cloudflare_1010_response(resp) is True

    def test_ordinary_403_is_not_cloudflare(self):
        assert is_cloudflare_1010_response(
            Response(403, {"Content-Type": "application/json"}, b"{}")
        ) is False

    def test_v3_classifier_requires_exact_message(self):
        assert is_rest_version_unsupported(
            Response(
                404,
                {"Content-Type": "application/json"},
                b'{"errorMessages":["Issue does not exist"]}',
            )
        ) is False
