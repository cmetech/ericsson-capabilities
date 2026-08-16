import httpx
import pytest

from ericsson_common.errors import ConnectorError
from ericsson_common.transport import HttpxTransport, RequestControl, Response


class TestResponse:
    def test_header_lookup_is_case_insensitive(self):
        resp = Response(200, {"Retry-After": "3"}, b"")
        assert resp.header("retry-after") == "3"
        assert resp.header("RETRY-AFTER") == "3"

    def test_missing_header_is_empty_string(self):
        assert Response(200, {}, b"").header("absent") == ""


def _transport(handler, **kwargs):
    return HttpxTransport(
        base_url="https://example.test",
        headers={"Accept": "application/json"},
        path_prefix="/api/v4/",
        mock_transport=httpx.MockTransport(handler),
        **kwargs,
    )


class TestHttpxTransport:
    def test_returns_status_headers_and_body(self):
        def handler(request):
            return httpx.Response(200, json={"ok": True}, headers={"X-Total": "7"})

        resp = _transport(handler).request(
            "GET", "/api/v4/projects", params=None, json_body=None,
            timeout_seconds=5,
        )
        assert resp.status == 200
        assert resp.header("x-total") == "7"
        assert b"ok" in resp.body

    def test_response_larger_than_cap_raises_capacity(self):
        def handler(request):
            return httpx.Response(200, content=b"x" * 5000)

        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler, max_response_bytes=1000).request(
                "GET", "/api/v4/projects", params=None, json_body=None,
                timeout_seconds=5,
            )
        assert excinfo.value.category == "capacity"

    def test_stream_capacity_failure_records_post_dispatch_uncertainty(self):
        def handler(request):
            return httpx.Response(200, content=b"x" * 5000)

        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler, max_response_bytes=1000).request(
                "POST", "/api/v4/projects", params=None, json_body={},
                timeout_seconds=5,
            )
        assert excinfo.value.category == "capacity"
        assert excinfo.value.outcome_uncertain is True

    def test_completed_client_error_status_survives_oversized_error_body(self):
        def handler(request):
            return httpx.Response(401, content=b"x" * 1001)

        response = _transport(handler, max_response_bytes=1000).request(
            "POST",
            "/api/v4/projects",
            params=None,
            json_body={},
            timeout_seconds=5,
        )

        assert response.status == 401
        assert response.body == b""

    def test_redirects_are_not_followed(self):
        def handler(request):
            return httpx.Response(302, headers={"Location": "https://elsewhere.test"})

        resp = _transport(handler).request(
            "GET", "/api/v4/projects", params=None, json_body=None,
            timeout_seconds=5,
        )
        assert resp.status == 302

    def test_path_outside_prefix_is_rejected(self):
        def handler(request):  # pragma: no cover - must never be reached
            raise AssertionError("request should not have been issued")

        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler).request(
                "GET", "/admin/secrets", params=None, json_body=None,
                timeout_seconds=5,
            )
        assert excinfo.value.category == "invalid_input"

    def test_absolute_url_is_rejected(self):
        def handler(request):  # pragma: no cover
            raise AssertionError("request should not have been issued")

        with pytest.raises(ConnectorError):
            _transport(handler).request(
                "GET", "https://evil.test/api/v4/x", params=None, json_body=None,
                timeout_seconds=5,
            )

    @pytest.mark.parametrize("path", ["/api/v4/../admin/secrets", "/api/v4/%2e%2e/admin/secrets"])
    def test_dot_segments_cannot_escape_prefix(self, path):
        def handler(request):  # pragma: no cover - must never be reached
            raise AssertionError("request should not have been issued")

        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler).request(
                "GET", path, params=None, json_body=None, timeout_seconds=5,
            )
        assert excinfo.value.category == "invalid_input"

    @pytest.mark.parametrize("path", ["/api/v4/..#ignored", "/api/v4/..%23ignored"])
    def test_fragment_suffix_cannot_escape_prefix(self, path):
        def handler(request):  # pragma: no cover - must never be reached
            raise AssertionError("request should not have been issued")

        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler).request(
                "GET", path, params=None, json_body=None, timeout_seconds=5,
            )
        assert excinfo.value.category == "invalid_input"

    def test_absolute_deadline_is_checked_between_trickled_chunks(self):
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

        def handler(request):
            return httpx.Response(200, stream=Trickle())

        control = RequestControl(
            deadline=1.5,
            cancel_check=lambda: False,
            clock=clock,
            service="gitlab",
        )
        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler).request_with_controls(
                "GET", "/api/v4/projects", params=None, json_body=None,
                timeout_seconds=5, control=control,
            )
        assert excinfo.value.category == "deadline"
        assert excinfo.value.outcome_uncertain is True

    def test_cancellation_is_checked_between_trickled_chunks(self):
        cancelled = {"value": False}

        class Trickle(httpx.SyncByteStream):
            def __iter__(self):
                yield b"first"
                cancelled["value"] = True
                yield b"second"

        def handler(request):
            return httpx.Response(200, stream=Trickle())

        control = RequestControl(
            deadline=10.0,
            cancel_check=lambda: cancelled["value"],
            clock=lambda: 0.0,
            service="gitlab",
        )
        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler).request_with_controls(
                "POST", "/api/v4/projects", params=None, json_body={},
                timeout_seconds=5, control=control,
            )
        assert excinfo.value.category == "cancelled"
        assert excinfo.value.outcome_uncertain is True

    def test_cancellation_after_request_build_stops_before_dispatch(self, monkeypatch):
        cancelled = {"value": False}
        dispatched = []

        def handler(request):  # pragma: no cover - control must stop first
            dispatched.append(request)
            return httpx.Response(201, json={})

        transport = _transport(handler)
        original_build = transport._client.build_request

        def build_then_cancel(*args, **kwargs):
            request = original_build(*args, **kwargs)
            cancelled["value"] = True
            return request

        monkeypatch.setattr(transport._client, "build_request", build_then_cancel)
        control = RequestControl(
            deadline=10.0,
            cancel_check=lambda: cancelled["value"],
            clock=lambda: 0.0,
            service="gitlab",
        )

        with pytest.raises(ConnectorError) as excinfo:
            transport.request_with_controls(
                "POST",
                "/api/v4/projects",
                params=None,
                json_body={},
                timeout_seconds=5,
                control=control,
            )

        assert excinfo.value.category == "cancelled"
        assert excinfo.value.outcome_uncertain is False
        assert dispatched == []


class TestRawBodies:
    def test_content_is_sent_verbatim(self):
        seen = {}

        def handler(request):
            seen["body"] = request.content
            seen["content_type"] = request.headers.get("content-type")
            return httpx.Response(200, json={"ok": True})

        _transport(handler).request(
            "POST",
            "/api/v4/projects",
            params=None,
            json_body=None,
            timeout_seconds=5,
            content=b'items.find({"repo":"x"})',
            extra_headers={"Content-Type": "text/plain"},
        )
        assert seen["body"] == b'items.find({"repo":"x"})'
        assert seen["content_type"] == "text/plain"

    def test_extra_headers_do_not_leak_into_later_requests(self):
        """Per-request headers must not mutate the shared client header map."""
        seen = []

        def handler(request):
            seen.append(request.headers.get("content-type"))
            return httpx.Response(200, json={})

        transport = _transport(handler)
        transport.request(
            "POST",
            "/api/v4/projects",
            params=None,
            json_body=None,
            timeout_seconds=5,
            content=b"x",
            extra_headers={"Content-Type": "text/plain"},
        )
        transport.request(
            "GET", "/api/v4/projects", params=None, json_body=None,
            timeout_seconds=5,
        )
        assert seen[0] == "text/plain"
        assert seen[1] != "text/plain"

    def test_content_and_json_body_together_are_rejected(self):
        def handler(request):  # pragma: no cover - must never be reached
            raise AssertionError("request should not have been issued")

        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler).request(
                "PUT",
                "/api/v4/projects",
                params=None,
                json_body={"a": 1},
                timeout_seconds=5,
                content=b"bytes",
            )
        assert excinfo.value.category == "invalid_input"

    def test_a_file_object_streams_without_being_read_into_memory(self, tmp_path):
        source = tmp_path / "artifact.bin"
        source.write_bytes(b"z" * 4096)
        seen = {}

        def handler(request):
            seen["body"] = request.content
            return httpx.Response(201, json={"ok": True})

        with source.open("rb") as handle:
            _transport(handler).request(
                "PUT",
                "/api/v4/projects",
                params=None,
                json_body=None,
                timeout_seconds=5,
                content=handle,
            )
        assert seen["body"] == b"z" * 4096

    def test_content_and_headers_flow_through_controlled_request(self):
        seen = {}

        def handler(request):
            seen["body"] = request.content
            seen["checksum"] = request.headers.get("x-checksum-sha256")
            return httpx.Response(201, json={})

        control = RequestControl(
            deadline=10.0,
            cancel_check=lambda: False,
            clock=lambda: 0.0,
            service="arm",
        )
        _transport(handler).request_with_controls(
            "PUT",
            "/api/v4/projects",
            params=None,
            json_body=None,
            timeout_seconds=5,
            content=b"artifact-bytes",
            extra_headers={"X-Checksum-Sha256": "abc"},
            control=control,
        )
        assert seen == {
            "body": b"artifact-bytes",
            "checksum": "abc",
        }
