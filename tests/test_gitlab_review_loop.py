"""GitLab review loop: notes, discussions, approvals, merge, update."""

import sys
from pathlib import Path

import httpx
import pytest
import respx

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
sys.path.insert(0, str(PLUGIN))

from auth import GitLabAuth  # noqa: E402
from client import GitLabClient  # noqa: E402
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


def _http_ops():
    client = GitLabClient(
        GitLabAuth(
            origin="https://gitlab.test",
            pat="secret-pat-value",
            certificate_pair=None,
        ),
        max_retries=4,
    )
    return _ops(client)


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

    @pytest.mark.parametrize("state", ["opened", "merged"])
    def test_merge_when_pipeline_succeeds_accepts_opened_or_merged(self, state):
        client = FakeClient([{"state": state}])
        result = _ops(client).merge_merge_request(
            "g/p", 42, merge_when_pipeline_succeeds=True, confirm=True
        )
        assert client.calls[0][2]["merge_when_pipeline_succeeds"] is True
        assert result["state"] == state

    def test_immediate_merge_requires_merged_state(self):
        client = FakeClient([{"state": "opened"}])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1


class TestUpdateMergeRequest:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request("g/p", 42, title="New")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_no_change_requested_is_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_title_and_description_are_sent_and_verified(self):
        client = FakeClient(
            [{"iid": 42, "title": "New", "description": "Body", "state": "opened"}]
        )
        result = _ops(client).update_merge_request(
            "g/p", 42, title="New", description="Body", confirm=True
        )
        method, path, body = client.calls[0]
        assert method == "PUT"
        assert path == "/api/v4/projects/7/merge_requests/42"
        assert body == {"title": "New", "description": "Body"}
        assert result["iid"] == 42
        assert result["state"] == "opened"

    def test_labels_use_add_remove_not_wholesale_replace(self):
        """Incremental label edits must not race by replacing the full list."""
        client = FakeClient(
            [{"iid": 42, "labels": ["needs-review"], "state": "opened"}]
        )
        _ops(client).update_merge_request(
            "g/p",
            42,
            add_labels=["needs-review"],
            remove_labels=["wip"],
            confirm=True,
        )
        body = client.calls[0][2]
        assert body["add_labels"] == "needs-review"
        assert body["remove_labels"] == "wip"
        assert "labels" not in body

    @pytest.mark.parametrize(
        ("state_event", "remote_state"), [("close", "closed"), ("reopen", "opened")]
    )
    def test_state_event_requires_the_requested_transition(
        self, state_event, remote_state
    ):
        client = FakeClient([{"iid": 42, "state": remote_state}])
        result = _ops(client).update_merge_request(
            "g/p", 42, state_event=state_event, confirm=True
        )
        assert client.calls[0][2]["state_event"] == state_event
        assert result["state"] == remote_state

    def test_invalid_state_event_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, state_event="delete", confirm=True
            )
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_draft_toggles_via_the_supplied_title(self):
        client = FakeClient(
            [{"iid": 42, "title": "Draft: Fix thing", "state": "opened"}]
        )
        _ops(client).update_merge_request(
            "g/p", 42, title="Fix thing", draft=True, confirm=True
        )
        assert client.calls[0][2]["title"] == "Draft: Fix thing"

    @pytest.mark.parametrize(
        ("draft", "supplied_title", "expected_title"),
        [
            (False, "Draft: WIP: Draft: Fix thing", "Fix thing"),
            (True, "WIP: Draft: WIP: Fix thing", "Draft: Fix thing"),
        ],
    )
    def test_draft_toggle_strips_every_stacked_marker_and_verifies_the_result(
        self, draft, supplied_title, expected_title
    ):
        client = FakeClient(
            [{"iid": 42, "title": expected_title, "state": "opened"}]
        )
        result = _ops(client).update_merge_request(
            "g/p", 42, title=supplied_title, draft=draft, confirm=True
        )
        assert client.calls == [
            (
                "PUT",
                "/api/v4/projects/7/merge_requests/42",
                {"title": expected_title},
            )
        ]
        assert result["requested"] == {"title": expected_title}

    def test_draft_without_a_title_is_rejected_without_a_hidden_read(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, draft=True, confirm=True
            )
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_draft_transformed_title_may_be_exactly_1024_characters(self):
        expected_title = "Draft: " + "x" * 1017
        client = FakeClient(
            [{"iid": 42, "title": expected_title, "state": "opened"}]
        )
        result = _ops(client).update_merge_request(
            "g/p", 42, title="x" * 1017, draft=True, confirm=True
        )
        assert client.calls[0][2]["title"] == expected_title
        assert len(result["requested"]["title"]) == 1024

    def test_draft_transformed_title_over_1024_is_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, title="x" * 1018, draft=True, confirm=True
            )
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_dry_run_previews_the_body_without_a_request(self):
        client = FakeClient()
        result = _ops(client).update_merge_request(
            "g/p", 42, title="New", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["requested"] == {"title": "New"}
        assert client.calls == []

    @pytest.mark.parametrize("remote_iid", [43, True, "42", None])
    def test_response_must_prove_the_requested_iid(self, remote_iid):
        client = FakeClient(
            [{"iid": remote_iid, "title": "New", "state": "opened"}]
        )
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, title="New", confirm=True
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    @pytest.mark.parametrize(
        ("requested", "payload"),
        [
            ({"title": "New"}, {"iid": 42, "title": "Old", "state": "opened"}),
            (
                {"description": "Body"},
                {"iid": 42, "description": "Other", "state": "opened"},
            ),
            (
                {"add_labels": ["needs-review"]},
                {"iid": 42, "labels": [], "state": "opened"},
            ),
            (
                {"remove_labels": ["wip"]},
                {"iid": 42, "labels": ["wip"], "state": "opened"},
            ),
            ({"state_event": "close"}, {"iid": 42, "state": "opened"}),
            ({"state_event": "reopen"}, {"iid": 42, "state": "closed"}),
        ],
    )
    def test_unproven_requested_change_is_write_ambiguous(self, requested, payload):
        client = FakeClient([payload])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, confirm=True, **requested
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    @pytest.mark.parametrize(
        "payload",
        [
            ["not", "a", "mapping"],
            {"iid": 42, "title": "New", "state": True},
            {"iid": 42, "title": "New", "state": " opened "},
        ],
    )
    def test_malformed_success_evidence_is_write_ambiguous(self, payload):
        client = FakeClient([payload])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, title="New", confirm=True
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    def test_unknown_bounded_remote_state_is_write_ambiguous(self):
        client = FakeClient(
            [{"iid": 42, "title": "New", "state": "reviewing"}]
        )
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, title="New", confirm=True
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    def test_inappropriate_success_status_is_write_ambiguous_after_one_attempt(self):
        operations = _http_ops()
        try:
            with respx.mock:
                route = respx.put(
                    "https://gitlab.test/api/v4/projects/7/merge_requests/42"
                ).mock(
                    return_value=httpx.Response(
                        201,
                        json={"iid": 42, "title": "New", "state": "opened"},
                    )
                )
                with pytest.raises(GitLabError) as excinfo:
                    operations.update_merge_request(
                        "g/p", 42, title="New", confirm=True
                    )
                assert route.call_count == 1
                assert len(respx.calls) == 1
            assert excinfo.value.category == "write_ambiguous"
        finally:
            operations.client.close()

    def test_uncertain_write_is_not_retried_or_reconciled(self):
        client = FakeClient([GitLabError("write_ambiguous")])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request(
                "g/p", 42, title="New", confirm=True
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1


class TestMergeMergeRequestResponseSafety:
    @pytest.mark.parametrize(
        ("merge_when_pipeline_succeeds", "state"),
        [
            (False, "closed"),
            (False, "locked"),
            (True, "closed"),
            (True, "locked"),
        ],
    )
    def test_other_bounded_states_are_write_ambiguous(
        self, merge_when_pipeline_succeeds, state
    ):
        client = FakeClient([{"state": state}])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request(
                "g/p",
                42,
                merge_when_pipeline_succeeds=merge_when_pipeline_succeeds,
                confirm=True,
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    def test_malformed_success_mapping_is_write_ambiguous(self):
        client = FakeClient([["not", "a", "mapping"]])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    @pytest.mark.parametrize(
        "merge_commit_sha",
        [True, 123, "", "a" * 39, "A" * 40, "g" * 40],
    )
    def test_malformed_merge_commit_sha_is_write_ambiguous(
        self, merge_commit_sha
    ):
        client = FakeClient(
            [{"state": "merged", "merge_commit_sha": merge_commit_sha}]
        )
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1

    def test_inappropriate_success_status_is_write_ambiguous(self):
        operations = _http_ops()
        try:
            with respx.mock:
                route = respx.put(
                    "https://gitlab.test/api/v4/projects/7/merge_requests/42/merge"
                ).mock(
                    return_value=httpx.Response(201, json={"state": "merged"})
                )
                with pytest.raises(GitLabError) as excinfo:
                    operations.merge_merge_request("g/p", 42, confirm=True)
                assert route.call_count == 1
                assert len(respx.calls) == 1
            assert excinfo.value.category == "write_ambiguous"
        finally:
            operations.client.close()

    def test_conflict_propagates_rather_than_retrying(self):
        client = FakeClient([GitLabError("conflict")])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "conflict"

    @pytest.mark.parametrize("status", [405, 409])
    def test_http_unmergeable_status_is_conflict_without_retry(self, status):
        operations = _http_ops()
        try:
            with respx.mock:
                route = respx.put(
                    "https://gitlab.test/api/v4/projects/7/merge_requests/42/merge"
                ).mock(
                    return_value=httpx.Response(
                        status, text="private merge diagnostic"
                    )
                )
                with pytest.raises(GitLabError) as excinfo:
                    operations.merge_merge_request("g/p", 42, confirm=True)
                assert route.call_count == 1
                assert len(respx.calls) == 1
            assert excinfo.value.category == "conflict"
            assert "private" not in str(excinfo.value)
        finally:
            operations.client.close()

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
