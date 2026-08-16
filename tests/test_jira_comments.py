from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from collections import deque
from pathlib import Path
from types import SimpleNamespace

import pytest

from jira_test_support import client, jira_tools, models, operations

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
JiraAuth = models.JiraAuth
JiraError = models.JiraError
TransportResponse = models.TransportResponse
JiraClient = client.JiraClient
JiraOperations = operations.JiraOperations


def auth(version="3"):
    return JiraAuth(
        origin="https://jira.example.test",
        authorization="Bearer secret-token",
        auth_mode="bearer",
        rest_api_version=version,
        transport="native",
        curl_executable="/usr/bin/curl",
        request_timeout_seconds=30,
        default_max_results=25,
    )


class FakeClient:
    def __init__(self, *outcomes, version="3"):
        self.auth = auth(version)
        self.outcomes = deque(outcomes)
        self.calls = []
        self.deadline_calls = 0

    def operation_deadline(self):
        self.deadline_calls += 1
        return 123.0

    def rest_json(self, method, resource, **kwargs):
        self.calls.append((method, resource, kwargs))
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome

    def rest_json_versioned_mutation(self, method, resource, **kwargs):
        return self.rest_json(method, resource, **kwargs)

    def rest_json_resolved_version(self, method, resource, **kwargs):
        return self.rest_json(method, resource, **kwargs)


def comments(*items):
    return {"comments": list(items), "total": len(items)}


def comment(comment_id, body):
    return {"id": comment_id, "body": body, "author": {"displayName": "A"}}


@pytest.mark.parametrize(
    ("key", "body"),
    [
        ("", "body"),
        ("ABC", "body"),
        ("../ABC-1", "body"),
        ("ABC-1", ""),
        ("ABC-1", "   "),
        ("ABC-1", "x" * 32_001),
    ],
)
def test_comment_validation_fails_before_transport(key, body):
    client = FakeClient()
    with pytest.raises(JiraError) as caught:
        JiraOperations(client).add_comment(key, body)
    assert caught.value.category == "invalid_input"
    assert client.calls == []


def test_dry_run_returns_bounded_preview_without_read_or_write():
    client = FakeClient()

    result = JiraOperations(client).add_comment("ABC-1", "proposed body", dry_run=True)

    assert result == {
        "ok": True,
        "id": None,
        "created": False,
        "duplicate": False,
        "reconciled": False,
        "dry_run": True,
        "issue_key": "ABC-1",
        "body": "proposed body",
    }
    assert client.calls == []


@pytest.mark.parametrize(
    ("version", "expected_body"),
    [
        (
            "3",
            {
                "body": {
                    "type": "doc",
                    "version": 1,
                    "content": [
                        {
                            "type": "paragraph",
                            "content": [{"type": "text", "text": "approved body"}],
                        }
                    ],
                }
            },
        ),
        ("2", {"body": "approved body"}),
    ],
)
def test_comment_uses_version_appropriate_body_and_preserves_result_fields(
    version, expected_body
):
    client = FakeClient(comments(), {"id": "10001"}, version=version)

    result = JiraOperations(client).add_comment("ABC-1", "approved body")

    assert result == {
        "ok": True,
        "id": "10001",
        "created": True,
        "duplicate": False,
        "reconciled": False,
        "dry_run": False,
    }
    assert client.calls[0][:2] == ("GET", "issue/ABC-1/comment")
    assert client.calls[1][2]["json_body_by_version"] == {
        "3": {
            "body": {
                "type": "doc",
                "version": 1,
                "content": [
                    {
                        "type": "paragraph",
                        "content": [{"type": "text", "text": "approved body"}],
                    }
                ],
            }
        },
        "2": {"body": "approved body"},
    }
    assert client.calls[1][2]["json_body_by_version"][version] == expected_body


@pytest.mark.parametrize("deployment", ["cloud", "data_center"])
def test_auto_comment_probes_with_gets_but_posts_exactly_once(deployment):
    class Transport:
        def __init__(self):
            self.calls = []

        @staticmethod
        def unsupported():
            return TransportResponse(
                404,
                {"content-type": "application/json"},
                b'{"errorMessages":["REST API v3 endpoint is not available"]}',
            )

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if path == "/rest/api/3/issue/ABC-1/comment" and method == "GET":
                if deployment == "data_center":
                    return self.unsupported()
                return TransportResponse(200, {}, b'{"comments":[],"total":0}')
            if path == "/rest/api/2/issue/ABC-1/comment" and method == "GET":
                return TransportResponse(200, {}, b'{"comments":[],"total":0}')
            if path == "/rest/api/3/serverInfo":
                if deployment == "data_center":
                    return self.unsupported()
                return TransportResponse(200, {}, b"{}")
            if path == "/rest/api/2/serverInfo":
                return TransportResponse(200, {}, b"{}")
            if method == "POST":
                return TransportResponse(201, {}, b'{"id":"10002"}')
            raise AssertionError((method, path))

        def close(self):
            pass

    transport = Transport()
    client = JiraClient(auth("auto"), native_transport=transport)

    result = JiraOperations(client).add_comment("ABC-1", "approved body")

    assert result["id"] == "10002"
    posts = [call for call in transport.calls if call[0] == "POST"]
    expected_version = "3" if deployment == "cloud" else "2"
    assert [call[:2] for call in posts] == [
        ("POST", f"/rest/api/{expected_version}/issue/ABC-1/comment")
    ]
    assert any(call[1].endswith("/serverInfo") for call in transport.calls)
    if deployment == "cloud":
        assert posts[0][2]["json_body"]["body"]["type"] == "doc"
    else:
        assert posts[0][2]["json_body"] == {"body": "approved body"}


def test_exact_existing_comment_is_reused_without_posting():
    client = FakeClient(comments(comment("77", "approved body")))

    result = JiraOperations(client).add_comment("ABC-1", "approved body")

    assert result["id"] == "77"
    assert result["created"] is False
    assert result["duplicate"] is True
    assert result["reconciled"] is False
    assert [call[0] for call in client.calls] == ["GET"]


@pytest.mark.parametrize("category", ["conflict", "write_ambiguous"])
def test_conflict_or_unknown_write_outcome_reconciles_read_only_without_retry(category):
    client = FakeClient(
        comments(),
        JiraError(category),
        comments(comment("88", "approved body")),
    )

    result = JiraOperations(client).add_comment("ABC-1", "approved body")

    assert result["id"] == "88"
    assert result["created"] is False
    assert result["duplicate"] is True
    assert result["reconciled"] is True
    assert [call[0] for call in client.calls] == ["GET", "POST", "GET"]


def test_unreconciled_ambiguous_write_is_reported_and_never_retried():
    client = FakeClient(comments(), JiraError("write_ambiguous"), comments())

    with pytest.raises(JiraError) as caught:
        JiraOperations(client).add_comment("ABC-1", "approved body")

    assert caught.value.category == "write_ambiguous"
    assert [call[0] for call in client.calls] == ["GET", "POST", "GET"]


def test_reconciliation_read_failure_preserves_original_write_ambiguity():
    client = FakeClient(
        comments(), JiraError("write_ambiguous"), JiraError("permission")
    )

    with pytest.raises(JiraError) as caught:
        JiraOperations(client).add_comment("ABC-1", "approved body")

    assert caught.value.category == "write_ambiguous"
    assert [call[0] for call in client.calls] == ["GET", "POST", "GET"]


def test_auto_data_center_comment_reconciliation_uses_one_resolved_v2_get():
    class Transport:
        def __init__(self):
            self.calls = []
            self.comment_gets = 0

        @staticmethod
        def unsupported():
            return TransportResponse(
                404,
                {"content-type": "application/json"},
                b'{"errorMessages":["REST API v3 endpoint is not available"]}',
            )

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            if path == "/rest/api/3/issue/ABC-1/comment":
                return self.unsupported()
            if path == "/rest/api/2/issue/ABC-1/comment" and method == "GET":
                self.comment_gets += 1
                body = (
                    b'{"comments":[],"total":0}'
                    if self.comment_gets == 1
                    else b'{"comments":[{"id":"88","body":"approved body"}],"total":1}'
                )
                return TransportResponse(200, {}, body)
            if path == "/rest/api/3/serverInfo":
                return self.unsupported()
            if path == "/rest/api/2/serverInfo":
                return TransportResponse(200, {}, b"{}")
            if method == "POST" and path == "/rest/api/2/issue/ABC-1/comment":
                return TransportResponse(500, {}, b"{}")
            raise AssertionError((method, path))

        def close(self):
            pass

    transport = Transport()
    jira = JiraClient(auth("auto"), native_transport=transport, max_retries=0)

    result = JiraOperations(jira).add_comment("ABC-1", "approved body")

    assert result["id"] == "88"
    assert result["reconciled"] is True
    assert sum(call[0] == "POST" for call in transport.calls) == 1
    post_index = next(i for i, call in enumerate(transport.calls) if call[0] == "POST")
    assert [call[:2] for call in transport.calls[post_index + 1 :]] == [
        ("GET", "/rest/api/2/issue/ABC-1/comment")
    ]


def test_incomplete_success_payload_reconciles_or_reports_write_ambiguous():
    client = FakeClient(comments(), {}, comments())

    with pytest.raises(JiraError) as caught:
        JiraOperations(client).add_comment("ABC-1", "approved body")

    assert caught.value.category == "write_ambiguous"
    assert [call[0] for call in client.calls] == ["GET", "POST", "GET"]
    assert {call[2]["deadline"] for call in client.calls} == {123.0}
    assert client.deadline_calls == 1


def test_invalid_create_comment_id_is_treated_as_ambiguous_without_echo():
    client = FakeClient(comments(), {"id": "secret-token"}, comments())

    with pytest.raises(JiraError) as caught:
        JiraOperations(client).add_comment("ABC-1", "approved body")

    assert caught.value.category == "write_ambiguous"
    assert "secret-token" not in str(caught.value)


def test_invalid_duplicate_comment_id_fails_closed_without_echo():
    client = FakeClient(comments(comment("secret-token", "approved body")))

    with pytest.raises(JiraError) as caught:
        JiraOperations(client).add_comment("ABC-1", "approved body")

    assert caught.value.category == "invalid_remote_data"
    assert "secret-token" not in str(caught.value)


def test_create_comment_id_is_redacted_after_structural_validation():
    client = FakeClient(comments(), {"id": "10001"})
    client.auth = auth("3")
    object.__setattr__(client.auth, "authorization", "Bearer 10001")

    result = JiraOperations(client).add_comment("ABC-1", "approved body")

    assert result["id"] == "<redacted>"


@pytest.mark.parametrize("category", ["authentication", "permission"])
def test_auth_and_permission_failures_do_not_retry_or_reconcile(category):
    client = FakeClient(comments(), JiraError(category))

    with pytest.raises(JiraError) as caught:
        JiraOperations(client).add_comment("ABC-1", "approved body")

    assert caught.value.category == category
    assert [call[0] for call in client.calls] == ["GET", "POST"]


class Configuration:
    def setting(self, field_id):
        return {
            "base_url": "https://jira.example.test",
            "auth_mode": "bearer",
            "rest_api_version": "3",
            "transport": "native",
            "curl_executable": "/usr/bin/curl",
            "request_timeout_seconds": 30,
            "default_max_results": 25,
        }[field_id]

    def secret(self, field_id):
        return {"pat": "secret", "api_token": ""}[field_id]


class Context:
    def __init__(self):
        self.registrations = {}
        self.hooks = {}
        self.configuration_calls = 0

    def configuration(self):
        self.configuration_calls += 1
        return Configuration()

    def register_tool(self, **registration):
        self.registrations[registration["name"]] = registration

    def register_hook(self, name, callback):
        self.hooks[name] = callback


def load_plugin():
    name = f"ericsson_jira_comments_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def admission(tool_name="jira_add_comment"):
    return SimpleNamespace(
        approved=True, policy="plugin_approve", tool_name=tool_name
    )


def test_registered_comment_requires_exact_host_admission_before_configuration(monkeypatch):
    plugin = load_plugin()
    context = Context()
    plugin.register(context)
    calls = []
    monkeypatch.setattr(
        plugin.jira_tools,
        "invoke",
        lambda name, args, configuration, **options: calls.append(name) or {"ok": True},
    )
    handler = context.registrations["jira_add_comment"]["handler"]

    for kwargs in (
        {},
        {"tool_admission": SimpleNamespace(approved=True, policy="caller", tool_name="jira_add_comment")},
        {"tool_admission": admission("jira_get_issue")},
    ):
        result = json.loads(handler({"key": "ABC-1", "body": "x"}, **kwargs))
        assert result == {
            "success": False,
            "error": {"category": "permission", "message": "Jira permission denied"},
        }
    assert context.configuration_calls == 0
    assert calls == []

    result = json.loads(
        handler(
            {"key": "ABC-1", "body": "x"},
            tool_admission=admission(),
        )
    )
    assert result == {"success": True, "result": {"ok": True}}
    assert calls == ["jira_add_comment"]


def test_comment_hook_binds_host_approval_to_exact_issue_and_body():
    plugin = load_plugin()
    context = Context()
    plugin.register(context)

    first = context.hooks["pre_tool_call"](
        "jira_add_comment", {"key": "ABC-1", "body": "first body"}
    )
    second = context.hooks["pre_tool_call"](
        "jira_add_comment", {"key": "XYZ-9", "body": "second body"}
    )

    assert first["action"] == second["action"] == "approve"
    assert "ABC-1" in first["message"] and "first body" in first["message"]
    assert "XYZ-9" in second["message"] and "second body" in second["message"]
    assert first["rule_key"].startswith("jira_add_comment:")
    assert second["rule_key"].startswith("jira_add_comment:")
    assert first["rule_key"] != second["rule_key"]


def test_comment_hook_requests_no_approval_for_read_tools_and_schema_has_no_caller_auth_field():
    plugin = load_plugin()
    context = Context()
    plugin.register(context)

    assert context.hooks["pre_tool_call"]("jira_get_issue", {}) is None
    properties = context.registrations["jira_add_comment"]["schema"]["parameters"]["properties"]
    assert "approved" not in properties
    assert "tool_admission" not in properties
    assert "dry_run" in properties


def test_direct_invoke_rejects_caller_auth_fields_before_configuration(monkeypatch):
    monkeypatch.setattr(
        jira_tools,
        "client_from_configuration",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no transport")),
    )
    for args in (
        {"key": "ABC-1", "body": "x", "approved": True},
        {"key": "ABC-1", "body": "x", "tool_admission": True},
    ):
        with pytest.raises(JiraError) as caught:
            jira_tools.invoke("jira_add_comment", args, Configuration())
        assert caught.value.category == "invalid_input"
