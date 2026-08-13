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

    def rest_json(self, method, resource, **kwargs):
        self.calls.append((method, resource, kwargs))
        outcome = self.outcomes.popleft()
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


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
    assert client.calls[1][2]["json_body"] == expected_body


def test_auto_v3_missing_endpoint_falls_back_with_v2_plain_body():
    class Transport:
        def __init__(self):
            self.calls = []
            self.responses = deque(
                [
                    TransportResponse(200, {}, b'{"comments":[],"total":0}'),
                    TransportResponse(
                        404,
                        {"content-type": "application/json"},
                        b'{"errorMessages":["REST API v3 endpoint is not available"]}',
                    ),
                    TransportResponse(201, {}, b'{"id":"10002"}'),
                ]
            )

        def request(self, method, path, **kwargs):
            self.calls.append((method, path, kwargs))
            return self.responses.popleft()

        def close(self):
            pass

    transport = Transport()
    client = JiraClient(auth("auto"), native_transport=transport)

    result = JiraOperations(client).add_comment("ABC-1", "approved body")

    assert result["id"] == "10002"
    assert [call[1] for call in transport.calls] == [
        "/rest/api/3/issue/ABC-1/comment",
        "/rest/api/3/issue/ABC-1/comment",
        "/rest/api/2/issue/ABC-1/comment",
    ]
    assert transport.calls[1][2]["json_body"]["body"]["type"] == "doc"
    assert transport.calls[2][2]["json_body"] == {"body": "approved body"}


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


def test_comment_hook_requests_host_approval_and_schema_has_no_caller_auth_field():
    plugin = load_plugin()
    context = Context()
    plugin.register(context)

    assert context.hooks["pre_tool_call"]("jira_add_comment", {"key": "ABC-1"}) == {
        "action": "approve",
        "message": "Approve Ericsson Jira comment",
        "rule_key": "jira_add_comment",
    }
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
