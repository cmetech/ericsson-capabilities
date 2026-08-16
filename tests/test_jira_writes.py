"""Jira transition writes: intent, approval, and bounded reconciliation."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from jira_test_support import models, operations


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
JiraError = models.JiraError
JiraOperations = operations.JiraOperations


class FakeClient:
    """Records requests and replays the explicitly scripted remote outcomes."""

    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

        class _Auth:
            authorization = "Bearer secret-token-value"
            rest_api_version = "auto"

        self.auth = _Auth()

    def rest_json(self, method, resource, **kwargs):
        self.calls.append((method, resource, kwargs))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class TestTransitionIntent:
    def test_no_intent_refuses_before_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).transition_issue("ABC-1", "21")

        assert caught.value.category == "confirmation_required"
        assert client.calls == []

    @pytest.mark.parametrize(
        ("dry_run", "confirm"),
        [(1, False), (False, 1), ("true", False), (False, None)],
    )
    def test_intent_flags_require_strict_booleans_before_a_request(
        self, dry_run, confirm
    ):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).transition_issue(
                "ABC-1", "21", dry_run=dry_run, confirm=confirm
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    def test_dry_run_previews_without_a_write_or_read(self):
        client = FakeClient([])

        result = JiraOperations(client).transition_issue(
            "ABC-1", "21", dry_run=True
        )

        assert result == {
            "ok": True,
            "dry_run": True,
            "issue_key": "ABC-1",
            "transition_id": "21",
            "reconciled": False,
        }
        assert client.calls == []

    def test_both_intent_flags_are_refused_before_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).transition_issue(
                "ABC-1", "21", dry_run=True, confirm=True
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []


class TestTransitionExecution:
    def test_confirm_posts_once_to_the_transition_endpoint(self):
        client = FakeClient([None])

        result = JiraOperations(client).transition_issue(
            "ABC-1", "21", confirm=True
        )

        assert client.calls == [
            (
                "POST",
                "issue/ABC-1/transitions",
                {"json_body": {"transition": {"id": "21"}}},
            )
        ]
        assert result == {
            "ok": True,
            "dry_run": False,
            "issue_key": "ABC-1",
            "transition_id": "21",
            "reconciled": False,
        }

    @pytest.mark.parametrize(
        ("key", "transition_id", "expected_status"),
        [
            ("bad key", "21", None),
            ("ABC-1", "21; DROP", None),
            ("ABC-1", 21, None),
            ("ABC-1", "21", "x" * 256),
            ("ABC-1", "21", 10),
        ],
    )
    def test_invalid_caller_arguments_are_rejected_before_a_request(
        self, key, transition_id, expected_status
    ):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).transition_issue(
                key,
                transition_id,
                confirm=True,
                expected_status=expected_status,
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []


class TestTransitionReconciliation:
    def test_ambiguous_write_reconciles_once_only_with_expected_status(self):
        client = FakeClient(
            [
                JiraError("write_ambiguous"),
                {"key": "ABC-1", "fields": {"status": {"name": "Done"}}},
            ]
        )

        result = JiraOperations(client).transition_issue(
            "ABC-1", "31", confirm=True, expected_status="Done"
        )

        assert result["ok"] is True
        assert result["reconciled"] is True
        assert [call[:2] for call in client.calls] == [
            ("POST", "issue/ABC-1/transitions"),
            ("GET", "issue/ABC-1"),
        ]
        assert [call[0] for call in client.calls].count("POST") == 1

    def test_ambiguous_write_with_no_expected_status_does_not_read_or_retry(self):
        client = FakeClient([JiraError("write_ambiguous")])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).transition_issue("ABC-1", "31", confirm=True)

        assert caught.value.category == "write_ambiguous"
        assert [call[0] for call in client.calls] == ["POST"]

    def test_ambiguous_write_that_did_not_land_raises_without_retry(self):
        client = FakeClient(
            [
                JiraError("write_ambiguous"),
                {"key": "ABC-1", "fields": {"status": {"name": "To Do"}}},
            ]
        )

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).transition_issue(
                "ABC-1", "31", confirm=True, expected_status="Done"
            )

        assert caught.value.category == "write_ambiguous"
        assert [call[0] for call in client.calls] == ["POST", "GET"]

    @pytest.mark.parametrize("category", ["permission", "authentication", "conflict"])
    def test_non_ambiguous_errors_are_untouched_without_read_or_retry(self, category):
        client = FakeClient([JiraError(category)])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).transition_issue(
                "ABC-1", "31", confirm=True, expected_status="Done"
            )

        assert caught.value.category == category
        assert [call[0] for call in client.calls] == ["POST"]


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


def _load_plugin():
    name = f"ericsson_jira_writes_{uuid.uuid4().hex}"
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


def _admission(tool_name="jira_transition_issue"):
    return SimpleNamespace(
        approved=True, policy="plugin_approve", tool_name=tool_name
    )


def test_transition_requires_exact_host_admission_before_configuration(monkeypatch):
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    calls = []
    monkeypatch.setattr(
        plugin.jira_tools,
        "invoke",
        lambda name, args, configuration, **options: calls.append(name) or {"ok": True},
    )
    handler = context.registrations["jira_transition_issue"]["handler"]

    for kwargs in (
        {},
        {
            "tool_admission": SimpleNamespace(
                approved=True,
                policy="caller",
                tool_name="jira_transition_issue",
            )
        },
        {"tool_admission": _admission("jira_add_comment")},
    ):
        result = json.loads(
            handler({"key": "ABC-1", "transition_id": "21", "confirm": True}, **kwargs)
        )
        assert result["error"]["category"] == "permission"

    assert context.configuration_calls == 0
    assert calls == []

    result = json.loads(
        handler(
            {"key": "ABC-1", "transition_id": "21", "confirm": True},
            tool_admission=_admission(),
        )
    )
    assert result == {"success": True, "result": {"ok": True}}
    assert calls == ["jira_transition_issue"]


def test_transition_approval_is_argument_scoped_and_names_the_transition():
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    hook = context.hooks["pre_tool_call"]

    first = hook("jira_transition_issue", {"key": "ABC-1", "transition_id": "21"})
    second = hook("jira_transition_issue", {"key": "XYZ-9", "transition_id": "31"})

    assert first["action"] == second["action"] == "approve"
    assert "jira_transition_issue" in first["message"]
    assert "ABC-1" in first["message"] and "21" in first["message"]
    assert "XYZ-9" in second["message"] and "31" in second["message"]
    assert first["rule_key"].startswith("jira_transition_issue:")
    assert first["rule_key"] != second["rule_key"]
