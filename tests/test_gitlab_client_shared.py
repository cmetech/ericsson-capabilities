"""GitLab connector must inherit the shared retry policy (F1 regression)."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
sys.path.insert(0, str(PLUGIN))

from _common.errors import ConnectorError  # noqa: E402
from _common.transport import Response  # noqa: E402
from client import GitLabClient  # noqa: E402
from models import SAFE_ERROR_MESSAGES, GitLabAuth, GitLabError  # noqa: E402


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


class FailingCloseTransport(FakeTransport):
    def close(self):
        raise ConnectorError(
            "authentication",
            service="gitlab",
            detail="private-close-detail",
        )


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _client(script):
    clock = FakeClock()
    auth = GitLabAuth(origin="https://gitlab.test", pat="tok", tls_context=None)
    return (
        GitLabClient(auth, transport=FakeTransport(script), clock=clock,
                     sleep=clock.sleep),
        clock,
    )


def test_rate_limit_retry_waits_instead_of_hammering():
    """Before this migration a 429 was retried immediately, up to 3 requests
    in a row with no delay. That is finding F1."""
    client, clock = _client(
        [Response(429, {"Retry-After": "2"}, b""), Response(200, {}, b"{}")]
    )
    client.get_json("/api/v4/projects")
    assert clock.slept == [2.0]


def test_write_is_not_retried():
    client, _clock = _client([Response(503, {}, b"")])
    with pytest.raises(GitLabError) as excinfo:
        client.request_json("POST", "/api/v4/projects/1/merge_requests")
    assert excinfo.value.category == "write_ambiguous"


def test_write_ambiguous_is_a_known_category_not_coerced_to_transient():
    """GitLab's table historically had no write_ambiguous entry, and both
    error classes silently coerce unknown categories to 'transient'. Without
    the Step 3 addition this migration would destroy the signal rather than
    fail loudly."""
    assert "write_ambiguous" in SAFE_ERROR_MESSAGES


def test_shared_error_type_never_escapes_to_the_host():
    """GitLabError guarantees no remote or secret text reaches the host;
    ConnectorError.detail carries no such guarantee, so it must be
    translated at the boundary."""
    client, _clock = _client([Response(401, {}, b"")])
    with pytest.raises(GitLabError) as excinfo:
        client.get_json("/api/v4/projects")
    assert not isinstance(excinfo.value, ConnectorError)
    assert excinfo.value.category == "authentication"
    assert excinfo.value.remediation


def test_shared_error_type_never_escapes_from_close():
    auth = GitLabAuth(origin="https://gitlab.test", pat="tok", tls_context=None)
    client = GitLabClient(auth, transport=FailingCloseTransport([]))
    with pytest.raises(GitLabError) as excinfo:
        client.close()
    assert not isinstance(excinfo.value, ConnectorError)
    assert excinfo.value.category == "authentication"
    assert excinfo.value.remediation
    assert "private-close-detail" not in str(excinfo.value)


def test_bounded_attributes_survive_for_operations_py():
    client, _clock = _client([])
    for attribute in (
        "max_pages", "max_ref_pages", "max_diff_bytes", "max_changes",
    ):
        assert isinstance(getattr(client, attribute), int)


def test_get_json_page_still_returns_headers_for_pagination():
    client, _clock = _client(
        [Response(200, {"X-Total": "42"}, b"[]")]
    )
    _value, headers = client.get_json_page("/api/v4/projects")
    assert headers.get("X-Total") == "42"
