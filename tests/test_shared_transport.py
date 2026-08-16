import httpx
import pytest

from ericsson_common.errors import ConnectorError
from ericsson_common.transport import HttpxTransport, Response


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
