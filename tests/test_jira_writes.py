"""Jira transition writes: intent, approval, and bounded reconciliation."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from jira_test_support import client as jira_client, models, operations


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
JiraError = models.JiraError
JiraOperations = operations.JiraOperations
JiraAuth = models.JiraAuth
JiraClient = jira_client.JiraClient
TransportResponse = models.TransportResponse


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

    def rest_json_v2_mutation(self, method, resource, **kwargs):
        return self.rest_json(method, resource, **kwargs)

    def rest_json_versioned_mutation(self, method, resource, **kwargs):
        return self.rest_json(method, resource, **kwargs)


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

    def test_default_auto_client_uses_one_pinned_v2_post_for_data_center(self):
        """A v3 probe followed by v2 fallback would be two mutations."""

        class AutoDataCenterTransport:
            def __init__(self):
                self.calls = []

            def request(self, method, path, **kwargs):
                self.calls.append((method, path, kwargs))
                if path.startswith("/rest/api/3/"):
                    return TransportResponse(
                        404,
                        {"content-type": "application/json"},
                        b'{"errorMessages":["REST API v3 endpoint is not available"]}',
                    )
                # Jira's transition endpoint succeeds with 204 No Content.
                return TransportResponse(204, {}, b"")

            def close(self):
                pass

        auth = JiraAuth(
            origin="https://jira.example.test",
            authorization="Bearer secret-token-value",
            auth_mode="bearer",
            rest_api_version="auto",
            transport="native",
            curl_executable="/usr/bin/curl",
            request_timeout_seconds=30,
            default_max_results=25,
        )
        transport = AutoDataCenterTransport()
        client = JiraClient(auth, native_transport=transport)

        result = JiraOperations(client).transition_issue(
            "ABC-1", "21", confirm=True
        )

        assert result["ok"] is True
        assert [call[:2] for call in transport.calls] == [
            ("POST", "/rest/api/2/issue/ABC-1/transitions")
        ]

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


class TestAssignIssue:
    def test_neither_intent_flag_is_refused_before_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).assign_issue("ABC-1", "jsmith")

        assert caught.value.category == "confirmation_required"
        assert client.calls == []

    @pytest.mark.parametrize(
        ("dry_run", "confirm"),
        [(1, False), (False, 1), (True, True)],
    )
    def test_invalid_intent_flags_are_refused_before_a_request(self, dry_run, confirm):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).assign_issue(
                "ABC-1", "jsmith", dry_run=dry_run, confirm=confirm
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    def test_dry_run_previews_without_a_write_or_probe(self):
        client = FakeClient([])

        result = JiraOperations(client).assign_issue(
            "ABC-1", "jsmith", dry_run=True
        )

        assert result == {
            "ok": True,
            "dry_run": True,
            "issue_key": "ABC-1",
            "assignee": "jsmith",
            "reconciled": False,
        }
        assert client.calls == []

    def test_confirm_performs_one_version_aware_put(self):
        client = FakeClient([None])

        result = JiraOperations(client).assign_issue(
            "ABC-1", "jsmith", confirm=True
        )

        assert client.calls == [
            (
                "PUT",
                "issue/ABC-1/assignee",
                {
                    "json_body_by_version": {
                        "3": {"accountId": "jsmith"},
                        "2": {"name": "jsmith"},
                    }
                },
            )
        ]
        assert result == {
            "ok": True,
            "dry_run": False,
            "issue_key": "ABC-1",
            "assignee": "jsmith",
            "reconciled": False,
        }

    def test_unassign_sends_null_in_both_version_bodies(self):
        client = FakeClient([None])

        JiraOperations(client).assign_issue("ABC-1", None, confirm=True)

        assert client.calls[0][2]["json_body_by_version"] == {
            "3": {"accountId": None},
            "2": {"name": None},
        }

    @pytest.mark.parametrize(
        ("assignee", "remote_assignee"),
        [
            ("legacy-user", {"name": "legacy-user"}),
            ("cloud-account-id", {"accountId": "cloud-account-id"}),
            (None, None),
        ],
    )
    def test_ambiguous_write_reconciles_assignee_across_jira_versions(
        self, assignee, remote_assignee
    ):
        client = FakeClient(
            [
                JiraError("write_ambiguous"),
                {"key": "ABC-1", "fields": {"assignee": remote_assignee}},
            ]
        )

        result = JiraOperations(client).assign_issue(
            "ABC-1", assignee, confirm=True
        )

        assert result["reconciled"] is True
        assert [call[:2] for call in client.calls] == [
            ("PUT", "issue/ABC-1/assignee"),
            ("GET", "issue/ABC-1"),
        ]

    def test_failed_reconciliation_preserves_original_write_ambiguity(self):
        client = FakeClient([JiraError("write_ambiguous"), JiraError("authentication")])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).assign_issue("ABC-1", "jsmith", confirm=True)

        assert caught.value.category == "write_ambiguous"
        assert [call[:2] for call in client.calls] == [
            ("PUT", "issue/ABC-1/assignee"),
            ("GET", "issue/ABC-1"),
        ]

    def test_ambiguous_write_that_did_not_land_raises_without_retry(self):
        client = FakeClient(
            [
                JiraError("write_ambiguous"),
                {"key": "ABC-1", "fields": {"assignee": {"name": "other"}}},
            ]
        )

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).assign_issue("ABC-1", "jsmith", confirm=True)

        assert caught.value.category == "write_ambiguous"
        assert [call[0] for call in client.calls] == ["PUT", "GET"]

    @pytest.mark.parametrize(
        "assignee", ["", "x" * 256, 1, True]
    )
    def test_invalid_assignee_is_refused_before_a_request(self, assignee):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).assign_issue("ABC-1", assignee, confirm=True)

        assert caught.value.category == "invalid_input"
        assert client.calls == []


class TestTransitionReconciliationRemainder:
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

    @pytest.mark.parametrize("read_category", ["authentication", "transient"])
    def test_failed_reconciliation_preserves_original_write_ambiguity(
        self, read_category
    ):
        client = FakeClient(
            [JiraError("write_ambiguous"), JiraError(read_category)]
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
