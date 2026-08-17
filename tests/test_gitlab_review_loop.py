"""GitLab review loop: notes, discussions, approvals, merge, update."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
sys.path.insert(0, str(PLUGIN))

from models import GitLabError  # noqa: E402
from operations import GitLabOperations  # noqa: E402


class FakeClient:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.max_pages = 10

        class _Auth:
            origin = "https://gitlab.test"
            pat = "secret-pat-value"

        self.auth = _Auth()

    def operation_deadline(self):
        return 0.0

    def get_json(self, path, *, params=None, deadline=None):
        self.calls.append(("GET", path, params))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def request_json(self, method, path, *, params=None, json_body=None,
                     deadline=None):
        self.calls.append((method, path, json_body))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def request_json_response(self, method, path, *, params=None, json_body=None,
                              deadline=None, raise_on_status=True):
        self.calls.append((method, path, json_body))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return (200 if method == "PUT" else 201), result, {}


def _ops(client):
    operations = GitLabOperations(client)
    operations.resolve_project = lambda project, **_: {"id": 7, "path": "g/p"}
    return operations


class TestCreateMrNote:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).create_mr_note("g/p", 42, "Looks good")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).create_mr_note(
            "g/p", 42, "Looks good", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["body"] == "Looks good"
        assert client.calls == []

    def test_confirm_posts_the_note(self):
        client = FakeClient([{"id": 9001}])
        result = _ops(client).create_mr_note(
            "g/p", 42, "Looks good", confirm=True
        )
        method, path, body = client.calls[0]
        assert method == "POST"
        assert path == "/api/v4/projects/7/merge_requests/42/notes"
        assert body == {"body": "Looks good"}
        assert result["note_id"] == 9001

    def test_empty_body_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).create_mr_note("g/p", 42, "   ", confirm=True)
        assert client.calls == []

    def test_oversized_body_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).create_mr_note("g/p", 42, "x" * 200_000, confirm=True)

    def test_bad_iid_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).create_mr_note("g/p", 0, "body", confirm=True)

    def test_response_without_an_id_is_write_ambiguous(self):
        client = FakeClient([{"unexpected": True}])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).create_mr_note("g/p", 42, "body", confirm=True)
        assert excinfo.value.category == "write_ambiguous"


class TestReplyToDiscussion:
    def test_confirm_posts_to_the_discussion(self):
        client = FakeClient([{"id": 555}])
        result = _ops(client).reply_to_discussion(
            "g/p", 42, "abc123", "Addressed", confirm=True
        )
        method, path, body = client.calls[0]
        assert method == "POST"
        assert path == (
            "/api/v4/projects/7/merge_requests/42/discussions/abc123/notes"
        )
        assert body == {"body": "Addressed"}
        assert result["note_id"] == 555

    def test_neither_flag_is_refused(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).reply_to_discussion("g/p", 42, "abc123", "x")
        assert excinfo.value.category == "confirmation_required"

    def test_malformed_discussion_id_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).reply_to_discussion(
                "g/p", 42, "../../admin", "x", confirm=True
            )
        assert client.calls == []

    def test_response_without_an_id_is_write_ambiguous(self):
        client = FakeClient([{"unexpected": True}])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).reply_to_discussion(
                "g/p", 42, "abc123", "x", confirm=True
            )
        assert excinfo.value.category == "write_ambiguous"


class TestResolveDiscussion:
    def test_confirm_resolves(self):
        client = FakeClient(
            [{
                "id": "abc123",
                "notes": [{"resolvable": True, "resolved": True}],
            }]
        )
        result = _ops(client).resolve_discussion(
            "g/p", 42, "abc123", confirm=True
        )
        method, path, body = client.calls[0]
        assert method == "PUT"
        assert path == "/api/v4/projects/7/merge_requests/42/discussions/abc123"
        assert body == {"resolved": True}
        assert result["resolved"] is True

    def test_unresolve_sends_false(self):
        client = FakeClient(
            [{
                "id": "abc123",
                "notes": [{"resolvable": True, "resolved": False}],
            }]
        )
        result = _ops(client).resolve_discussion(
            "g/p", 42, "abc123", resolved=False, confirm=True
        )
        assert client.calls[0][2] == {"resolved": False}
        assert result["resolved"] is False

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).resolve_discussion(
            "g/p", 42, "abc123", dry_run=True
        )
        assert result["dry_run"] is True
        assert client.calls == []

    def test_non_boolean_resolved_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).resolve_discussion(
                "g/p", 42, "abc123", resolved="yes", confirm=True
            )

    def test_response_without_notes_is_write_ambiguous(self):
        client = FakeClient([{"id": "abc123"}])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).resolve_discussion("g/p", 42, "abc123", confirm=True)
        assert excinfo.value.category == "write_ambiguous"

    def test_response_with_wrong_resolvable_state_is_write_ambiguous(self):
        client = FakeClient(
            [{
                "id": "abc123",
                "notes": [{"resolvable": True, "resolved": False}],
            }]
        )
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).resolve_discussion("g/p", 42, "abc123", confirm=True)
        assert excinfo.value.category == "write_ambiguous"
