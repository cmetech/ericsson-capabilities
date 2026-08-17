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


class TestApprovals:
    def test_reads_approval_state(self):
        client = FakeClient([
            {
                "approved": False,
                "approvals_required": 2,
                "approvals_left": 1,
                "approved_by": [{"user": {"username": "alice", "name": "Alice"}}],
            }
        ])
        result = _ops(client).merge_request_approvals("g/p", 42)
        assert client.calls[0][1] == (
            "/api/v4/projects/7/merge_requests/42/approvals"
        )
        assert result["approvals_required"] == 2
        assert result["approvals_left"] == 1
        assert result["approved_by"] == ["alice"]

    def test_malformed_approval_payload_raises(self):
        client = FakeClient([["not", "a", "mapping"]])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_request_approvals("g/p", 42)
        assert excinfo.value.category == "invalid_remote_data"

    @pytest.mark.parametrize(
        ("field", "value"),
        [
            ("approved", "false"),
            ("approvals_required", True),
            ("approvals_left", 1.5),
            ("approvals_required", -1),
        ],
    )
    def test_malformed_approval_scalars_raise(self, field, value):
        payload = {
            "approved": False,
            "approvals_required": 2,
            "approvals_left": 1,
        }
        payload[field] = value
        with pytest.raises(GitLabError) as excinfo:
            _ops(FakeClient([payload])).merge_request_approvals("g/p", 42)
        assert excinfo.value.category == "invalid_remote_data"


class TestApproveMergeRequest:
    def test_neither_flag_is_refused(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).approve_merge_request("g/p", 42)
        assert excinfo.value.category == "confirmation_required"

    def test_confirm_approves(self):
        client = FakeClient([{"approved": True}])
        result = _ops(client).approve_merge_request("g/p", 42, confirm=True)
        method, path, _body = client.calls[0]
        assert method == "POST"
        assert path == "/api/v4/projects/7/merge_requests/42/approve"
        assert result["ok"] is True

    def test_sha_is_forwarded_when_supplied(self):
        """A pinned SHA prevents approval after the reviewed branch moved."""
        client = FakeClient([{"approved": True}])
        _ops(client).approve_merge_request(
            "g/p", 42, sha="a" * 40, confirm=True
        )
        assert client.calls[0][2] == {"sha": "a" * 40}

    def test_malformed_sha_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).approve_merge_request(
                "g/p", 42, sha="not-a-sha", confirm=True
            )
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).approve_merge_request("g/p", 42, dry_run=True)
        assert result["dry_run"] is True
        assert client.calls == []

    def test_success_without_approval_evidence_is_write_ambiguous(self):
        client = FakeClient([{}])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).approve_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "write_ambiguous"


class TestMergeMergeRequest:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42)
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).merge_merge_request("g/p", 42, dry_run=True)
        assert result["dry_run"] is True
        assert client.calls == []

    def test_confirm_merges(self):
        client = FakeClient([{"state": "merged", "merge_commit_sha": "b" * 40}])
        result = _ops(client).merge_merge_request("g/p", 42, confirm=True)
        method, path, _body = client.calls[0]
        assert method == "PUT"
        assert path == "/api/v4/projects/7/merge_requests/42/merge"
        assert result["state"] == "merged"
        assert result["merge_commit_sha"] == "b" * 40

    def test_sha_pins_the_merge(self):
        client = FakeClient([{"state": "merged"}])
        _ops(client).merge_merge_request("g/p", 42, sha="a" * 40, confirm=True)
        assert client.calls[0][2]["sha"] == "a" * 40

    def test_optional_flags_are_omitted_when_not_set(self):
        """Sending squash=false explicitly would override a project default
        the maintainers deliberately configured."""
        client = FakeClient([{"state": "merged"}])
        _ops(client).merge_merge_request("g/p", 42, confirm=True)
        body = client.calls[0][2]
        assert "squash" not in body
        assert "should_remove_source_branch" not in body

    def test_flags_are_sent_when_set(self):
        client = FakeClient([{"state": "merged"}])
        _ops(client).merge_merge_request(
            "g/p", 42, squash=True, remove_source_branch=True, confirm=True
        )
        body = client.calls[0][2]
        assert body["squash"] is True
        assert body["should_remove_source_branch"] is True

    def test_merge_when_pipeline_succeeds(self):
        client = FakeClient([{"state": "opened"}])
        result = _ops(client).merge_merge_request(
            "g/p", 42, merge_when_pipeline_succeeds=True, confirm=True
        )
        assert client.calls[0][2]["merge_when_pipeline_succeeds"] is True
        assert result["state"] == "opened"

    def test_conflict_propagates_rather_than_retrying(self):
        client = FakeClient([GitLabError("conflict")])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "conflict"

    def test_write_ambiguous_is_not_reconciled_silently(self):
        """A merge that may or may not have happened must be reported as
        unknown, never guessed."""
        client = FakeClient([GitLabError("write_ambiguous")])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    @pytest.mark.parametrize("field", ["state", "merge_commit_sha"])
    def test_remote_merge_strings_require_exact_scalar_types(self, field):
        class StringSubclass(str):
            pass

        payload = {"state": "merged", "merge_commit_sha": "b" * 40}
        payload[field] = StringSubclass(payload[field])
        client = FakeClient([payload])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1
