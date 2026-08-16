from __future__ import annotations

from collections import deque
from datetime import datetime, timezone

import pytest

from jira_test_support import models, operations, tools

JiraAuth = models.JiraAuth
JiraError = models.JiraError
JiraOperations = operations.JiraOperations
SCHEMAS = tools.SCHEMAS


AUTH = JiraAuth(
    origin="https://jira.example.test",
    authorization="Bearer connector-secret",
    auth_mode="bearer",
    rest_api_version="3",
    transport="native",
    curl_executable="/usr/bin/curl",
    request_timeout_seconds=30,
    default_max_results=25,
)


class FakeClient:
    def __init__(self, *payloads):
        self.auth = AUTH
        self.payloads = deque(payloads)
        self.calls = []
        self.deadline_calls = 0

    def operation_deadline(self):
        self.deadline_calls += 1
        return 123.0

    def rest_json(self, method, resource, **kwargs):
        self.calls.append((method, resource, kwargs))
        return self.payloads.popleft()


def issue(
    key,
    *,
    summary="summary",
    status="Open",
    priority="High",
    issue_type="Bug",
    labels=None,
    updated="2026-08-01T12:00:00.000+0000",
    created="2026-07-01T12:00:00.000+0000",
    description="description",
    extra=None,
):
    fields = {
        "summary": summary,
        "status": {"name": status, "statusCategory": {"name": "In Progress"}},
        "priority": {"name": priority},
        "issuetype": {"name": issue_type},
        "labels": labels or [],
        "updated": updated,
        "created": created,
        "description": description,
        **(extra or {}),
    }
    return {"key": key, "fields": fields}


def test_my_tickets_preserves_jql_order_default_limit_and_envelope_shape():
    client = FakeClient(
        {
            "issues": [
                issue(
                    "ABC-1",
                    description=(
                        "See https://gitlab.example.test/g/repo. "
                        "Again https://gitlab.example.test/g/repo)"
                    ),
                )
            ],
            "total": 1,
            "startAt": 0,
            "maxResults": 25,
        }
    )

    result = JiraOperations(client).my_tickets()

    assert result["items"][0]["key"] == "ABC-1"
    assert result["items"][0]["gitlab_urls"] == ["https://gitlab.example.test/g/repo"]
    assert result["returned"] == 1
    assert result["truncated"] is False
    params = client.calls[0][2]["params"]
    assert params["jql"] == (
        "assignee = currentUser() AND resolution = Unresolved "
        "ORDER BY priority DESC, updated DESC"
    )
    assert params["maxResults"] == 25


def test_search_requires_explicit_bounded_jql_limit_and_allowlisted_fields():
    operations = JiraOperations(FakeClient())
    invalid = [
        {"jql": "", "max_results": 10},
        {"jql": "project = ABC", "max_results": 0},
        {"jql": "project = ABC", "max_results": 101},
        {"jql": "project = ABC", "max_results": 10, "fields": ["attachment"]},
        {"jql": "x" * 4097, "max_results": 10},
    ]
    for args in invalid:
        with pytest.raises(JiraError) as caught:
            operations.search_issues(**args)
        assert caught.value.category == "invalid_input"


def test_search_paginates_to_bound_and_returns_explicit_truncation_warning():
    client = FakeClient(
        {"issues": [issue("ABC-1"), issue("ABC-2")], "total": 5, "startAt": 0},
        {"issues": [issue("ABC-3"), issue("ABC-4")], "total": 5, "startAt": 2},
    )

    result = JiraOperations(client).search_issues(
        jql="project = ABC ORDER BY updated DESC",
        max_results=3,
        fields=["summary", "description"],
    )

    assert [row["key"] for row in result["items"]] == ["ABC-1", "ABC-2", "ABC-3"]
    assert result["total"] == 5
    assert result["truncated"] is True
    assert result["hint"] == "More issues match this JQL. Raise max_results or narrow the query."
    assert [call[2]["params"]["startAt"] for call in client.calls] == [0, 2]
    assert set(client.calls[0][2]["params"]["fields"].split(",")) == {
        "summary",
        "description",
    }
    assert {call[2]["deadline"] for call in client.calls} == {123.0}
    assert client.deadline_calls == 1


def test_filters_are_case_insensitive_and_age_thresholds_are_deterministic():
    client = FakeClient(
        {
            "issues": [
                issue("ABC-1", labels=["Backend"], updated="2026-08-02T12:00:00Z"),
                issue("ABC-2", status="Closed", labels=["Backend"], updated="2026-08-02T12:00:00Z"),
                issue("ABC-3", issue_type="Story", labels=["Backend"], updated="2026-08-02T12:00:00Z"),
                issue("ABC-4", priority="Low", labels=["Backend"], updated="2026-08-02T12:00:00Z"),
                issue("ABC-5", labels=["Frontend"], updated="2026-08-02T12:00:00Z"),
                issue("ABC-6", labels=["Backend"], updated="2026-08-11T12:00:00Z"),
                issue("ABC-7", labels=["Backend"], updated="2026-06-01T12:00:00Z"),
            ],
            "total": 7,
            "startAt": 0,
        }
    )
    operations = JiraOperations(
        client, now=lambda: datetime(2026, 8, 12, 12, tzinfo=timezone.utc)
    )

    result = operations.search_issues(
        jql="project = ABC",
        max_results=10,
        statuses=["open"],
        issue_types=["bug"],
        priorities=["HIGH"],
        labels=["backend"],
        min_age_days=5,
        max_age_days=20,
    )

    assert [row["key"] for row in result["items"]] == ["ABC-1"]
    assert result["total"] == 1
    assert result["truncated"] is False


def test_selection_limited_filtered_search_omits_unknown_total():
    client = FakeClient(
        {
            "issues": [issue("ABC-1"), issue("ABC-2"), issue("ABC-3")],
            "total": 4,
            "startAt": 0,
        }
    )

    result = JiraOperations(client).search_issues(
        jql="project = ABC", max_results=2, statuses=["Open"]
    )

    assert [row["key"] for row in result["items"]] == ["ABC-1", "ABC-2"]
    assert "total" not in result
    assert result["truncated"] is True
    assert "unscanned" in result["hint"]


def test_max_page_limited_filtered_search_omits_unknown_total():
    client = FakeClient(
        {
            "issues": [issue("ABC-1", status="Closed"), issue("ABC-2", status="Closed")],
            "total": 4,
            "startAt": 0,
        }
    )

    result = JiraOperations(client, max_pages=1).search_issues(
        jql="project = ABC", max_results=2, statuses=["Open"]
    )

    assert result["items"] == []
    assert "total" not in result
    assert result["truncated"] is True
    assert "unscanned" in result["hint"]


def test_get_issue_normalizes_adf_context_and_safe_comment_projection():
    description = {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "failure context connector-secret"}]}],
    }
    comment_body = {
        "type": "doc",
        "version": 1,
        "content": [{"type": "paragraph", "content": [{"type": "text", "text": "investigating"}]}],
    }
    payload = issue(
        "ABC-1",
        description=description,
        extra={
            "environment": "production",
            "comment": {
                "comments": [
                    {
                        "author": {
                            "displayName": "Alice",
                            "emailAddress": "private@example.test",
                            "avatarUrls": {"48x48": "private"},
                        },
                        "body": comment_body,
                        "created": "2026-08-10T12:00:00Z",
                        "internal-secret": "connector-secret",
                    }
                ]
            },
            "attachment": [{"content": "raw-secret"}],
        },
    )
    client = FakeClient(payload)

    result = JiraOperations(client).get_issue("ABC-1")

    assert result["description"] == "failure context <redacted>"
    assert result["environment"] == "production"
    assert result["content_warning"] == operations.UNTRUSTED_CONTENT_WARNING
    assert result["problem_summary"] == "failure context <redacted>"
    assert result["issue_url"] == "https://jira.example.test/browse/ABC-1"
    assert result["comments"] == [
        {
            "author": "Alice",
            "body": "investigating",
            "created": "2026-08-10T12:00:00Z",
        }
    ]
    assert "private@example.test" not in repr(result)
    assert "raw-secret" not in repr(result)
    assert "connector-secret" not in repr(result)


def test_remote_issue_projection_redacts_key_timestamps_comment_created_and_url():
    payload = issue(
        "ABC-1",
        updated="updated ABC-1",
        created="created ABC-1",
        extra={
            "comment": {
                "comments": [
                    {
                        "id": "10001",
                        "author": {"displayName": "A"},
                        "body": "body",
                        "created": "comment ABC-1",
                    }
                ]
            }
        },
    )
    remote_client = FakeClient(payload)
    remote_client.auth = JiraAuth(
        origin="https://jira.example.test",
        authorization="Bearer ABC-1",
        auth_mode="bearer",
        rest_api_version="3",
        transport="native",
        curl_executable="/usr/bin/curl",
        request_timeout_seconds=30,
        default_max_results=25,
    )

    result = JiraOperations(remote_client).get_issue("ABC-1")

    assert result["key"] == "<redacted>"
    assert result["updated"] == "updated <redacted>"
    assert result["created"] == "created <redacted>"
    assert result["comments"][0]["created"] == "comment <redacted>"
    assert result["issue_url"] == "https://jira.example.test/browse/<redacted>"
    assert "ABC-1" not in repr(result)


def test_invalid_remote_issue_key_fails_closed_without_echo():
    with pytest.raises(JiraError) as caught:
        JiraOperations(FakeClient(issue("remote-secret"))).search_issues(
            jql="project = ABC", max_results=10
        )

    assert caught.value.category == "invalid_remote_data"
    assert "remote-secret" not in str(caught.value)


def test_malformed_search_and_issue_payloads_fail_closed_without_raw_echo():
    for payload in (
        {"issues": "remote-secret"},
        {"issues": [{"key": "ABC-1", "fields": "remote-secret"}]},
    ):
        with pytest.raises(JiraError) as caught:
            JiraOperations(FakeClient(payload)).search_issues(
                jql="project = ABC", max_results=10
            )
        assert caught.value.category == "invalid_remote_data"
        assert "remote-secret" not in str(caught.value)


def test_tool_schemas_register_exact_bounded_public_surface_without_raw_fields():
    assert set(SCHEMAS) == {
        "jira_my_tickets",
        "jira_search_issues",
        "jira_get_issue",
        "jira_add_comment",
        "jira_list_fields",
        "jira_get_project",
        "jira_list_transitions",
        "jira_search_assignable_users",
        "jira_transition_issue",
        "jira_assign_issue",
        "jira_update_fields",
        "jira_manage_labels",
        "jira_create_issue",
        "jira_list_link_types",
        "jira_link_issues",
    }
    search = SCHEMAS["jira_search_issues"]["parameters"]
    assert search["additionalProperties"] is False
    assert search["properties"]["max_results"]["maximum"] == 100
    assert set(search["properties"]["fields"]["items"]["enum"]) == {
        "summary",
        "status",
        "priority",
        "updated",
        "created",
        "description",
        "environment",
        "issuetype",
        "labels",
    }
    assert "raw_fields" not in repr(SCHEMAS)
    assert "attachment" not in repr(SCHEMAS)
