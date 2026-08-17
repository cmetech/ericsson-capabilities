"""Confluence client rides the shared transport policy."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-confluence"
sys.path.insert(0, str(PLUGIN))

from _common.errors import ConnectorError  # noqa: E402
from _common.transport import Response  # noqa: E402
from client import ConfluenceClient  # noqa: E402
from models import ConfluenceAuth, ConfluenceError  # noqa: E402


class FakeTransport:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, path, *, params, json_body, timeout_seconds):
        self.calls.append((method, path, params, json_body))
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


def _auth(api_base="https://wiki.test/rest/api"):
    return ConfluenceAuth(
        origin="https://wiki.test",
        api_base=api_base,
        authorization="Bearer secret-token-value",
        request_timeout_seconds=30,
        default_max_results=25,
    )


def _client(script, api_base="https://wiki.test/rest/api"):
    clock = FakeClock()
    return (
        ConfluenceClient(_auth(api_base), transport=FakeTransport(script),
                         clock=clock, sleep=clock.sleep),
        clock,
    )


class TestClient:
    def test_constructor_translates_shared_configuration_error(self):
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceClient(_auth(), transport=FakeTransport([]), max_retries=-1)
        assert excinfo.value.category == "invalid_configuration"
        assert not isinstance(excinfo.value, ConnectorError)

    def test_decodes_json(self):
        client, _clock = _client([Response(200, {}, b'{"id":"1"}')])
        assert client.get_json("/rest/api/content/1") == {"id": "1"}

    def test_retry_after_is_honoured(self):
        client, clock = _client(
            [Response(429, {"Retry-After": "2"}, b""), Response(200, {}, b"{}")]
        )
        client.get_json("/rest/api/content/1")
        assert clock.slept == [2.0]

    def test_writes_are_not_retried(self):
        client, _clock = _client([Response(503, {}, b"")])
        with pytest.raises(ConfluenceError) as excinfo:
            client.request_json("PUT", "/rest/api/content/1", json_body={})
        assert excinfo.value.category == "write_ambiguous"

    def test_409_surfaces_as_conflict(self):
        """Confluence uses optimistic concurrency, so 409 is routine."""
        client, _clock = _client([Response(409, {}, b"")])
        with pytest.raises(ConfluenceError) as excinfo:
            client.request_json("PUT", "/rest/api/content/1", json_body={})
        assert excinfo.value.category == "conflict"

    def test_shared_error_type_never_escapes(self):
        client, _clock = _client([Response(401, {}, b"")])
        with pytest.raises(ConfluenceError) as excinfo:
            client.get_json("/rest/api/content/1")
        assert not isinstance(excinfo.value, ConnectorError)
        assert excinfo.value.remediation

    def test_html_body_raises_invalid_remote_data(self):
        """An HTML body where JSON was expected means an SSO login page --
        the same signal super-cli detects for Jira."""
        client, _clock = _client([Response(200, {}, b"<html>login</html>")])
        with pytest.raises(ConfluenceError) as excinfo:
            client.get_json("/rest/api/content/1")
        assert excinfo.value.category == "invalid_remote_data"

    def test_empty_body_is_none_not_an_error(self):
        """DELETE returns 204 with no body."""
        client, _clock = _client([Response(204, {}, b"")])
        assert client.request_json("DELETE", "/rest/api/content/1") is None

    def test_path_outside_the_api_base_is_rejected(self):
        client, _clock = _client([])
        with pytest.raises(ConfluenceError):
            client.get_json("/admin/secrets")

    def test_cloud_api_base_accepts_wiki_paths(self):
        client, _clock = _client(
            [Response(200, {}, b"{}")],
            api_base="https://x.atlassian.net/wiki/rest/api",
        )
        client.get_json("/wiki/rest/api/content/1")
        assert client._transport.calls[0][1] == "/wiki/rest/api/content/1"

    def test_cloud_client_rejects_a_data_center_path(self):
        client, _clock = _client([], api_base="https://x.atlassian.net/wiki/rest/api")
        with pytest.raises(ConfluenceError):
            client.get_json("/rest/api/content/1")
