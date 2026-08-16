from __future__ import annotations

import gzip
import json
import zlib
from collections import deque

import httpx
import pytest

from jira_test_support import client, models, operations, transport


JiraClient = client.JiraClient
JiraOperations = operations.JiraOperations
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


@pytest.mark.parametrize(
    ("rest_api_version", "expected_path", "expected_body"),
    [
        ("2", "/rest/api/2/issue/ABC-1/assignee", {"name": "jsmith"}),
        ("3", "/rest/api/3/issue/ABC-1/assignee", {"accountId": "jsmith"}),
    ],
)
def test_versioned_mutation_uses_explicit_config_without_a_probe(
    rest_api_version, expected_path, expected_body
):
    transport = FakeTransport(response(204, body=b""))
    jira = JiraClient(auth(rest_api_version=rest_api_version), native_transport=transport)

    assert jira.rest_json_versioned_mutation(
        "PUT",
        "issue/ABC-1/assignee",
        json_body_by_version={
            "3": {"accountId": "jsmith"},
            "2": {"name": "jsmith"},
        },
    ) is None

    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("PUT", expected_path)
    ]
    assert transport.calls[0][2]["json_body"] == expected_body


def test_versioned_mutation_auto_cloud_probes_with_get_then_puts_once():
    transport = FakeTransport(response(payload={}), response(204, body=b""))
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)

    jira.rest_json_versioned_mutation(
        "PUT",
        "issue/ABC-1/assignee",
        json_body_by_version={
            "3": {"accountId": "cloud-account"},
            "2": {"name": "cloud-account"},
        },
    )

    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/3/serverInfo"),
        ("PUT", "/rest/api/3/issue/ABC-1/assignee"),
    ]
    assert transport.calls[1][2]["json_body"] == {"accountId": "cloud-account"}
    assert sum(method == "PUT" for method, _path, _kwargs in transport.calls) == 1


def test_versioned_mutation_auto_data_center_probes_without_a_put_fallback():
    unsupported = response(
        404,
        {"errorMessages": ["REST API v3 endpoint is not available"]},
        headers={"content-type": "application/json"},
    )
    transport = FakeTransport(unsupported, response(payload={}), response(204, body=b""))
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)

    jira.rest_json_versioned_mutation(
        "PUT",
        "issue/ABC-1/assignee",
        json_body_by_version={
            "3": {"accountId": "dc-user"},
            "2": {"name": "dc-user"},
        },
    )

    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/3/serverInfo"),
        ("GET", "/rest/api/2/serverInfo"),
        ("PUT", "/rest/api/2/issue/ABC-1/assignee"),
    ]
    assert transport.calls[2][2]["json_body"] == {"name": "dc-user"}
    assert sum(method == "PUT" for method, _path, _kwargs in transport.calls) == 1


def test_versioned_mutation_does_not_write_when_its_read_only_probe_fails():
    transport = FakeTransport(response(403, payload={}))
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)

    with pytest.raises(JiraError) as caught:
        jira.rest_json_versioned_mutation(
            "PUT",
            "issue/ABC-1/assignee",
            json_body_by_version={
                "3": {"accountId": "cloud-account"},
                "2": {"name": "cloud-account"},
            },
        )

    assert caught.value.category == "permission"
    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/3/serverInfo")
    ]


def test_versioned_mutation_caches_the_auto_probe_result():
    transport = FakeTransport(
        response(payload={}),
        response(204, body=b""),
        response(204, body=b""),
    )
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)
    bodies = {"3": {"accountId": "jsmith"}, "2": {"name": "jsmith"}}

    jira.rest_json_versioned_mutation("PUT", "issue/ABC-1/assignee", json_body_by_version=bodies)
    jira.rest_json_versioned_mutation("PUT", "issue/ABC-2/assignee", json_body_by_version=bodies)

    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/3/serverInfo"),
        ("PUT", "/rest/api/3/issue/ABC-1/assignee"),
        ("PUT", "/rest/api/3/issue/ABC-2/assignee"),
    ]


def test_versioned_mutation_accepts_only_declared_empty_success_statuses():
    transport = FakeTransport(response(201, body=b""))
    jira = JiraClient(auth(rest_api_version="3"), native_transport=transport)

    try:
        result = jira.rest_json_versioned_mutation(
            "POST",
            "issueLink",
            json_body_by_version={"3": {}, "2": {}},
            empty_success_statuses=frozenset({201, 204}),
        )
    except TypeError:
        pytest.fail("versioned mutations do not accept an empty-success contract")

    assert result is None


@pytest.mark.parametrize(
    "invalid",
    [set(), {201}, frozenset({199}), frozenset({300}), frozenset({True})],
)
def test_versioned_mutation_rejects_invalid_empty_success_contract(invalid):
    jira = JiraClient(auth(rest_api_version="3"), native_transport=FakeTransport())

    try:
        with pytest.raises(JiraError) as caught:
            jira.rest_json_versioned_mutation(
                "POST",
                "issueLink",
                json_body_by_version={"3": {}, "2": {}},
                empty_success_statuses=invalid,
            )
    except TypeError:
        pytest.fail("versioned mutations do not validate an empty-success contract")

    assert caught.value.category == "invalid_input"


@pytest.mark.parametrize(
    ("rest_api_version", "expected_path", "expected_description"),
    [
        ("2", "/rest/api/2/issue", "Details"),
        (
            "3",
            "/rest/api/3/issue",
            {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "Details"}],
                    }
                ],
            },
        ),
    ],
)
def test_create_issue_uses_one_explicit_versioned_post_with_matching_body(
    rest_api_version, expected_path, expected_description
):
    transport = FakeTransport(response(201, {"key": "PROJ-42"}))
    jira = JiraClient(auth(rest_api_version=rest_api_version), native_transport=transport)

    result = JiraOperations(jira).create_issue(
        "PROJ", "Bug", "Broken", description="Details", confirm=True
    )

    assert result["key"] == "PROJ-42"
    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("POST", expected_path)
    ]
    assert transport.calls[0][2]["json_body"]["fields"]["description"] == expected_description
    assert sum(method == "POST" for method, _path, _kwargs in transport.calls) == 1


@pytest.mark.parametrize(
    ("rest_api_version", "expected_path", "expected_description"),
    [
        ("2", "/rest/api/2/issue", ""),
        (
            "3",
            "/rest/api/3/issue",
            {"type": "doc", "version": 1, "content": []},
        ),
    ],
)
def test_create_issue_empty_description_uses_one_post_with_version_safe_body(
    rest_api_version, expected_path, expected_description
):
    transport = FakeTransport(response(201, {"key": "PROJ-42"}))
    jira = JiraClient(auth(rest_api_version=rest_api_version), native_transport=transport)

    JiraOperations(jira).create_issue(
        "PROJ", "Bug", "Broken", description="", confirm=True
    )

    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("POST", expected_path)
    ]
    assert transport.calls[0][2]["json_body"]["fields"]["description"] == expected_description
    assert sum(method == "POST" for method, _path, _kwargs in transport.calls) == 1


def test_create_issue_auto_cloud_probes_then_posts_v3_once_with_adf():
    transport = FakeTransport(
        response(payload={}), response(201, {"key": "PROJ-42"})
    )
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)

    JiraOperations(jira).create_issue(
        "PROJ", "Bug", "Broken", description="Details", confirm=True
    )

    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/3/serverInfo"),
        ("POST", "/rest/api/3/issue"),
    ]
    assert transport.calls[1][2]["json_body"]["fields"]["description"]["type"] == "doc"
    assert sum(method == "POST" for method, _path, _kwargs in transport.calls) == 1


def test_create_issue_auto_data_center_probes_then_posts_v2_once_with_text():
    unsupported = response(
        404,
        {"errorMessages": ["REST API v3 endpoint is not available"]},
        headers={"content-type": "application/json"},
    )
    transport = FakeTransport(
        unsupported, response(payload={}), response(201, {"key": "PROJ-42"})
    )
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)

    JiraOperations(jira).create_issue(
        "PROJ", "Bug", "Broken", description="Details", confirm=True
    )

    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/3/serverInfo"),
        ("GET", "/rest/api/2/serverInfo"),
        ("POST", "/rest/api/2/issue"),
    ]
    assert transport.calls[2][2]["json_body"]["fields"]["description"] == "Details"
    assert sum(method == "POST" for method, _path, _kwargs in transport.calls) == 1


def test_create_issue_probe_failure_prevents_every_post():
    transport = FakeTransport(response(403, payload={}))
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)

    with pytest.raises(JiraError) as caught:
        JiraOperations(jira).create_issue("PROJ", "Bug", "Broken", confirm=True)

    assert caught.value.category == "permission"
    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/3/serverInfo")
    ]
    assert not any(method == "POST" for method, _path, _kwargs in transport.calls)


def test_create_issue_empty_201_remains_ambiguous():
    transport = FakeTransport(response(201, body=b""))
    jira = JiraClient(auth(rest_api_version="3"), native_transport=transport)

    with pytest.raises(JiraError) as caught:
        JiraOperations(jira).create_issue("PROJ", "Bug", "Broken", confirm=True)

    assert caught.value.category == "write_ambiguous"
    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("POST", "/rest/api/3/issue")
    ]


def test_explicit_v2_read_never_probes_or_falls_back():
    transport = FakeTransport(response(payload={"fields": {}}))
    jira = JiraClient(auth(rest_api_version="auto"), native_transport=transport)

    try:
        result = jira.rest_json_v2("GET", "issue/ABC-1")
    except AttributeError:
        pytest.fail("JiraClient does not expose the narrow explicit-v2 read API")

    assert result == {"fields": {}}
    assert [(method, path) for method, path, _kwargs in transport.calls] == [
        ("GET", "/rest/api/2/issue/ABC-1")
    ]


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


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, "invalid_input"),
        (401, "authentication"),
        (403, "permission"),
        (404, "not_found"),
        (409, "conflict"),
        (429, "rate_limited"),
    ],
)
def test_deterministic_mutation_4xx_is_preserved_without_retry(status, category):
    transport = FakeTransport(response(status, body=b"not-json"))
    client = JiraClient(auth(rest_api_version="3"), native_transport=transport)

    with pytest.raises(JiraError) as caught:
        client.rest_json("POST", "issue/ABC-1/comment", json_body={"body": "x"})

    assert caught.value.category == category
    assert len(transport.calls) == 1


def test_write_ambiguity_is_never_retried_on_status_or_transport_failure():
    for outcome in (
        response(500),
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


@pytest.mark.parametrize(
    ("body", "legacy_category"),
    [
        (b"remote secret not json", "invalid_remote_data"),
        (b"x" * 1_048_577, "capacity"),
    ],
)
def test_post_dispatch_success_decode_failures_are_ambiguous(body, legacy_category):
    transport = FakeTransport(response(201, body=body))
    client = JiraClient(auth(rest_api_version="3"), native_transport=transport)

    with pytest.raises(JiraError) as caught:
        client.rest_json("POST", "issue/ABC-1/comment", json_body={"body": "x"})

    assert caught.value.category == "write_ambiguous", legacy_category
    assert "remote secret" not in str(caught.value)
    assert len(transport.calls) == 1


def test_read_transport_failure_retries_but_remains_safely_classified():
    sleeps = []
    transport = FakeTransport(
        httpx.ConnectError("dns secret diagnostic"),
        response(payload={"ok": True}),
    )
    client = JiraClient(auth(), native_transport=transport, sleep=sleeps.append)

    assert client.rest_json("GET", "search") == {"ok": True}
    assert len(transport.calls) == 2
    assert sleeps == [0.5]


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
        "./search",
        "%2e%2e/search",
        "%252e%252e%252fadmin",
        "issue%2fABC-1",
        "issue/%5cadmin",
        "issue/%00secret",
        "issue/%23fragment",
        "issue/%3fquery",
        "search%",
        "search#fragment",
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
        assert caught.value.__context__ is None
        assert caught.value.__cause__ is None


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
    assert requests[0].headers["accept-encoding"] == "gzip, deflate"
    assert requests[0].extensions["timeout"]["read"] == 7


def test_native_transport_streams_and_stops_at_response_capacity():
    emitted = {"count": 0}

    class LargeStream(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(2048):
                emitted["count"] += 1
                yield b"x" * 1024

    def send(_request):
        return httpx.Response(200, stream=LargeStream())

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    with pytest.raises(JiraError) as caught:
        native.request("POST", "/rest/api/3/issue", timeout_seconds=7)

    assert caught.value.category == "capacity"
    assert caught.value.outcome_uncertain is True
    assert emitted["count"] == 1025


def test_native_transport_accepts_response_at_exact_capacity():
    class ExactStream(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * (512 * 1024)
            yield b"y" * (512 * 1024)

    def send(_request):
        return httpx.Response(200, stream=ExactStream())

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = native.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert len(result.body) == 1024 * 1024
    assert result.body[:1] == b"x"
    assert result.body[-1:] == b"y"


def test_native_gzip_decompression_never_materializes_output_larger_than_bound(
    monkeypatch,
):
    decoded_chunk_sizes = []
    real_decompressobj = zlib.decompressobj

    class RecordingDecompressor:
        def __init__(self, wrapped):
            self._wrapped = wrapped

        def __getattr__(self, name):
            return getattr(self._wrapped, name)

        def decompress(self, data, max_length=0):
            decoded = self._wrapped.decompress(data, max_length)
            decoded_chunk_sizes.append(len(decoded))
            return decoded

        def flush(self, length=zlib.DEF_BUF_SIZE):
            decoded = self._wrapped.flush(length)
            decoded_chunk_sizes.append(len(decoded))
            return decoded

    def recording_decompressobj(*args, **kwargs):
        return RecordingDecompressor(real_decompressobj(*args, **kwargs))

    monkeypatch.setattr(zlib, "decompressobj", recording_decompressobj)
    compressed = gzip.compress(b"x" * (8 * 1024 * 1024))

    class GzipStream(httpx.SyncByteStream):
        def __iter__(self):
            yield compressed

    def send(_request):
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=GzipStream(),
        )

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    with pytest.raises(JiraError) as caught:
        native.request("POST", "/rest/api/3/issue", timeout_seconds=7)

    assert caught.value.category == "capacity"
    assert caught.value.outcome_uncertain is True
    assert decoded_chunk_sizes
    assert max(decoded_chunk_sizes) <= 64 * 1024


def test_native_transport_accepts_gzip_response_at_exact_decoded_capacity():
    compressed = gzip.compress(b"x" * (1024 * 1024))

    class GzipStream(httpx.SyncByteStream):
        def __iter__(self):
            yield compressed

    def send(_request):
        return httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
            stream=GzipStream(),
        )

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = native.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert result.body == b"x" * (1024 * 1024)


def test_native_transport_decodes_bounded_deflate_response():
    compressed = zlib.compress(b'{"ok":true}')

    class DeflateStream(httpx.SyncByteStream):
        def __iter__(self):
            yield compressed[:1]
            yield compressed[1:]

    def send(_request):
        return httpx.Response(
            200,
            headers={"content-encoding": "deflate"},
            stream=DeflateStream(),
        )

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = native.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert result.body == b'{"ok":true}'


def test_native_transport_decodes_raw_deflate_split_after_one_byte():
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    compressed = compressor.compress(b'{"raw":true}') + compressor.flush()

    class RawDeflateStream(httpx.SyncByteStream):
        def __iter__(self):
            yield compressed[:1]
            yield compressed[1:2]
            yield compressed[2:]

    def send(_request):
        return httpx.Response(
            200,
            headers={"content-encoding": "deflate"},
            stream=RawDeflateStream(),
        )

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = native.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert result.body == b'{"raw":true}'


def test_native_transport_decodes_raw_deflate_with_zlib_header_collision():
    raw_deflate = bytes.fromhex("78 01 00 fe ff 41 01 00 00 ff ff")

    class RawDeflateStream(httpx.SyncByteStream):
        def __iter__(self):
            yield raw_deflate[:1]
            yield raw_deflate[1:2]
            yield raw_deflate[2:6]
            yield raw_deflate[6:]

    def send(_request):
        return httpx.Response(
            200,
            headers={"content-encoding": "deflate"},
            stream=RawDeflateStream(),
        )

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = native.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert result.body == b"A"


def test_native_transport_accepts_fragmented_raw_deflate_at_exact_decoded_capacity():
    payload = b"x" * (1024 * 1024)
    compressor = zlib.compressobj(wbits=-zlib.MAX_WBITS)
    compressed = compressor.compress(payload) + compressor.flush()

    class RawDeflateStream(httpx.SyncByteStream):
        def __iter__(self):
            yield compressed[:1]
            yield compressed[1:]

    def send(_request):
        return httpx.Response(
            200,
            headers={"content-encoding": "deflate"},
            stream=RawDeflateStream(),
        )

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = native.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert result.body == payload


@pytest.mark.parametrize("content_encoding", ["br", "zstd", "gzip, deflate"])
def test_native_transport_fails_closed_for_unbounded_content_encoding(
    content_encoding,
):
    emitted = {"count": 0}

    class EncodedStream(httpx.SyncByteStream):
        def __iter__(self):
            emitted["count"] += 1
            yield b"encoded"

    def send(_request):
        return httpx.Response(
            200,
            headers={"content-encoding": content_encoding},
            stream=EncodedStream(),
        )

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    with pytest.raises(JiraError) as caught:
        native.request("GET", "/rest/api/3/search", timeout_seconds=7)

    assert caught.value.category == "invalid_remote_data"
    assert caught.value.outcome_uncertain is True
    assert emitted["count"] == 0


def test_native_transport_preserves_4xx_when_error_body_exceeds_capacity():
    class OversizedError(httpx.SyncByteStream):
        def __iter__(self):
            yield b"x" * (1024 * 1024 + 1)

    def send(_request):
        return httpx.Response(401, stream=OversizedError())

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    result = native.request(
        "POST", "/rest/api/3/issue/ABC-1/comment", timeout_seconds=7
    )

    assert result.status == 401
    assert result.body == b""


def test_native_rechecks_cancellation_after_local_preparation_before_dispatch(
    monkeypatch,
):
    cancelled = {"value": False}
    dispatched = []

    def prepare(_body):
        cancelled["value"] = True
        return b"{}"

    def send(request):  # pragma: no cover - cancellation must stop first
        dispatched.append(request)
        return httpx.Response(201, json={})

    monkeypatch.setattr(
        transport.CurlTransport, "_request_body", staticmethod(prepare)
    )
    native = NativeTransport(
        auth(),
        http_transport=httpx.MockTransport(send),
        cancel_check=lambda: cancelled["value"],
    )

    with pytest.raises(JiraError) as caught:
        native.request(
            "POST", "/rest/api/3/issue/ABC-1/comment", json_body={}, timeout_seconds=7
        )

    assert caught.value.category == "cancelled"
    assert caught.value.outcome_uncertain is False
    assert dispatched == []


def test_native_transport_observes_absolute_deadline_during_trickle():
    common_transport = __import__(
        f"{transport.__package__}._common.transport", fromlist=["RequestControl"]
    )

    class Clock:
        now = 0.0

        def __call__(self):
            return self.now

    clock = Clock()

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            for _ in range(3):
                clock.now += 0.8
                yield b"x"

    def send(_request):
        return httpx.Response(200, stream=Trickle())

    control = common_transport.RequestControl(
        deadline=1.5,
        cancel_check=lambda: False,
        clock=clock,
        service="jira",
    )
    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    with pytest.raises(JiraError) as caught:
        native.request_with_controls(
            "GET", "/rest/api/3/search", timeout_seconds=7, control=control
        )

    assert caught.value.category == "deadline"
    assert caught.value.outcome_uncertain is True


def test_native_transport_observes_cancellation_during_trickle():
    common_transport = __import__(
        f"{transport.__package__}._common.transport", fromlist=["RequestControl"]
    )
    cancelled = {"value": False}

    class Trickle(httpx.SyncByteStream):
        def __iter__(self):
            yield b"first"
            cancelled["value"] = True
            yield b"second"

    def send(_request):
        return httpx.Response(200, stream=Trickle())

    control = common_transport.RequestControl(
        deadline=10.0,
        cancel_check=lambda: cancelled["value"],
        clock=lambda: 0.0,
        service="jira",
    )
    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    with pytest.raises(JiraError) as caught:
        native.request_with_controls(
            "POST", "/rest/api/3/issue", timeout_seconds=7, control=control
        )

    assert caught.value.category == "cancelled"
    assert caught.value.outcome_uncertain is True


@pytest.mark.parametrize(
    "path",
    [
        "/rest/api/3/../admin",
        "/rest/api/3/%2e%2e/admin",
        "/rest/api/3/%252e%252e%252fadmin",
        "/rest/api/3/issue%2f..%2fadmin",
        "/rest/api/3/issue%5cadmin",
        "/rest/api/3/issue%00secret",
        "/rest/api/3/search%",
        "/rest/api/3/search#fragment",
    ],
)
def test_native_transport_rejects_ambiguous_decoded_paths_before_dispatch(path):
    dispatched = []

    def send(request):  # pragma: no cover - validation must stop first
        dispatched.append(request)
        return httpx.Response(200, json={})

    native = NativeTransport(auth(), http_transport=httpx.MockTransport(send))
    with pytest.raises(JiraError) as caught:
        native.request("GET", path, timeout_seconds=7)

    assert caught.value.category == "invalid_input"
    assert dispatched == []


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
