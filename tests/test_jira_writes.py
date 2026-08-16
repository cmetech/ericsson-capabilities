"""Jira transition writes: intent, approval, and bounded reconciliation."""

from __future__ import annotations

import importlib.util
import hashlib
import json
import sys
import uuid
from collections import UserDict
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


class StringSubclass(str):
    pass


class IntegerSubclass(int):
    pass


class FloatSubclass(float):
    pass


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

    def rest_json_resolved_version(self, method, resource, **kwargs):
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

    @pytest.mark.parametrize(
        ("deployment", "resolved_version", "assignee", "remote_assignee"),
        [
            ("cloud", "3", "cloud-account", {"accountId": "cloud-account"}),
            ("data_center", "2", "legacy-user", {"name": "legacy-user"}),
        ],
    )
    def test_auto_assignment_reconciliation_reads_issue_once_at_resolved_version(
        self, deployment, resolved_version, assignee, remote_assignee
    ):
        class AutoTransport:
            def __init__(self):
                self.calls = []

            def request(self, method, path, **kwargs):
                self.calls.append((method, path, kwargs))
                if path == "/rest/api/3/serverInfo":
                    if deployment == "cloud":
                        return TransportResponse(200, {}, b"{}")
                    return TransportResponse(
                        404,
                        {"content-type": "application/json"},
                        b'{"errorMessages":["REST API v3 endpoint is not available"]}',
                    )
                if path == "/rest/api/2/serverInfo":
                    return TransportResponse(200, {}, b"{}")
                if path == f"/rest/api/{resolved_version}/issue/ABC-1/assignee":
                    return TransportResponse(500, {}, b"")
                if path == f"/rest/api/{resolved_version}/issue/ABC-1":
                    return TransportResponse(
                        200,
                        {},
                        json.dumps(
                            {"key": "ABC-1", "fields": {"assignee": remote_assignee}}
                        ).encode(),
                    )
                if path == "/rest/api/3/issue/ABC-1":
                    return TransportResponse(
                        404,
                        {"content-type": "application/json"},
                        b'{"errorMessages":["REST API v3 endpoint is not available"]}',
                    )
                raise AssertionError(f"unexpected request: {method} {path}")

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
        transport = AutoTransport()

        result = JiraOperations(JiraClient(auth, native_transport=transport)).assign_issue(
            "ABC-1", assignee, confirm=True
        )

        assert result["reconciled"] is True
        issue_gets = [
            (method, path)
            for method, path, _kwargs in transport.calls
            if method == "GET" and path.endswith("/issue/ABC-1")
        ]
        assert issue_gets == [("GET", f"/rest/api/{resolved_version}/issue/ABC-1")]
        assert [method for method, _path, _kwargs in transport.calls].count("PUT") == 1


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


class TestUpdateFields:
    def test_neither_intent_flag_is_refused_before_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields("ABC-1", {"summary": "New"})

        assert caught.value.category == "confirmation_required"
        assert client.calls == []

    @pytest.mark.parametrize(
        ("dry_run", "confirm"),
        [(1, False), (False, 1), (True, True)],
    )
    def test_intent_flags_require_strict_booleans_before_a_request(
        self, dry_run, confirm
    ):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields(
                "ABC-1", {"summary": "New"}, dry_run=dry_run, confirm=confirm
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    def test_dry_run_echoes_the_bounded_change_without_a_request(self):
        client = FakeClient([])

        result = JiraOperations(client).update_fields(
            "ABC-1", {"summary": "New"}, dry_run=True
        )

        assert result == {
            "ok": True,
            "dry_run": True,
            "issue_key": "ABC-1",
            "fields": {"summary": "New"},
            "reconciled": False,
        }
        assert client.calls == []

    def test_confirm_uses_the_resolved_version_mutation_path_with_one_body(self):
        client = FakeClient([None])

        result = JiraOperations(client).update_fields(
            "ABC-1", {"summary": "New"}, confirm=True
        )

        assert client.calls == [
            (
                "PUT",
                "issue/ABC-1",
                {
                    "json_body_by_version": {
                        "3": {"fields": {"summary": "New"}},
                        "2": {"fields": {"summary": "New"}},
                    }
                },
            )
        ]
        assert result["reconciled"] is False

    def test_custom_field_priority_and_labels_are_allowed(self):
        client = FakeClient([None])
        fields = {
            "customfield_10234": {"value": "5"},
            "priority": {"id": "3"},
            "labels": ["release", "customer-facing"],
        }

        JiraOperations(client).update_fields("ABC-1", fields, confirm=True)

        assert client.calls[0][2]["json_body_by_version"]["3"] == {
            "fields": fields
        }

    @pytest.mark.parametrize(
        "fields",
        [
            {"security": {"id": "1"}},
            {"reporter": {"name": "user"}},
            {},
            ["summary"],
            {f"customfield_{index}": index for index in range(21)},
            {"customfield_not_an_id": 1},
            {1: "not-a-field-name"},
        ],
    )
    def test_invalid_field_map_is_rejected_before_a_request(self, fields):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields("ABC-1", fields, confirm=True)

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    def test_non_json_value_is_rejected_before_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields(
                "ABC-1", {"priority": {"id": object()}}, confirm=True
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    def test_excessively_nested_value_is_rejected_before_a_request(self):
        client = FakeClient([])
        value = "leaf"
        for _ in range(33):
            value = [value]

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields(
                "ABC-1", {"customfield_10234": value}, confirm=True
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    def test_oversized_serialized_value_is_rejected_before_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields(
                "ABC-1", {"description": "x" * 65_537}, confirm=True
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    def test_ambiguous_write_is_preserved_without_a_retry(self):
        client = FakeClient([JiraError("write_ambiguous")])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields(
                "ABC-1", {"summary": "New"}, confirm=True
            )

        assert caught.value.category == "write_ambiguous"
        assert [call[0] for call in client.calls] == ["PUT"]

    @pytest.mark.parametrize(
        "fields",
        [
            UserDict({"summary": "New"}),
            type("FieldsSubclass", (dict,), {})({"summary": "New"}),
            {"priority": UserDict({"id": "3"})},
            {"priority": type("ValueSubclass", (dict,), {})({"id": "3"})},
            {"labels": type("LabelsSubclass", (list,), {})(["release"])},
        ],
    )
    def test_non_json_container_fields_are_refused_before_a_put(self, fields):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields("ABC-1", fields, confirm=True)

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    @pytest.mark.parametrize(
        "args",
        [
            UserDict(
                {
                    "key": "ABC-1",
                    "fields": {"summary": "New"},
                    "confirm": True,
                }
            ),
            type("ArgsSubclass", (dict,), {})
            (
                {
                    "key": "ABC-1",
                    "fields": {"summary": "New"},
                    "confirm": True,
                }
            ),
        ],
    )
    def test_non_json_outer_tool_arguments_are_refused_before_configuration(self, args):
        from jira_test_support import tools

        with pytest.raises(JiraError) as caught:
            tools.invoke("jira_update_fields", args, object())

        assert caught.value.category == "invalid_input"


class TestManageLabels:
    def test_add_uses_one_version_resolved_put_with_add_operations(self):
        client = FakeClient([None])

        result = JiraOperations(client).manage_labels(
            "ABC-1", "add", ["alpha", "beta"], confirm=True
        )

        assert client.calls == [
            (
                "PUT",
                "issue/ABC-1",
                {
                    "json_body_by_version": {
                        "3": {
                            "update": {
                                "labels": [{"add": "alpha"}, {"add": "beta"}]
                            }
                        },
                        "2": {
                            "update": {
                                "labels": [{"add": "alpha"}, {"add": "beta"}]
                            }
                        },
                    }
                },
            )
        ]
        assert result == {
            "ok": True,
            "dry_run": False,
            "issue_key": "ABC-1",
            "operation": "add",
            "labels": ["alpha", "beta"],
            "reconciled": False,
        }

    def test_remove_uses_remove_operations(self):
        client = FakeClient([None])

        JiraOperations(client).manage_labels(
            "ABC-1", "remove", ["alpha"], confirm=True
        )

        assert client.calls[0][2]["json_body_by_version"]["3"] == {
            "update": {"labels": [{"remove": "alpha"}]}
        }

    def test_all_validation_precedes_intent_and_io(self):
        invalid_arguments = [
            ("bad key", "add", ["alpha"], True, False),
            ("ABC-1", "replace", ["alpha"], True, False),
            ("ABC-1", StringSubclass("add"), ["alpha"], True, False),
            ("ABC-1", "add", [], True, False),
            ("ABC-1", "add", ["has space"], True, False),
            ("ABC-1", "add", ["has\ttab"], True, False),
            ("ABC-1", "add", ["x" * 256], True, False),
            ("ABC-1", "add", [f"label-{index}" for index in range(51)], True, False),
            ("ABC-1", "add", type("LabelsSubclass", (list,), {})(["alpha"]), True, False),
            ("ABC-1", "add", [StringSubclass("alpha")], True, False),
            ("ABC-1", "add", ["alpha"], 1, False),
            ("ABC-1", "add", ["alpha"], False, 1),
            ("ABC-1", "add", ["alpha"], True, True),
        ]

        for key, operation, labels, dry_run, confirm in invalid_arguments:
            client = FakeClient([])
            with pytest.raises(JiraError) as caught:
                JiraOperations(client).manage_labels(
                    key,
                    operation,
                    labels,
                    dry_run=dry_run,
                    confirm=confirm,
                )
            assert caught.value.category == "invalid_input"
            assert client.calls == []

    def test_neither_intent_flag_is_refused_before_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).manage_labels("ABC-1", "add", ["alpha"])

        assert caught.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_returns_only_requested_labels_without_io(self):
        client = FakeClient([])

        result = JiraOperations(client).manage_labels(
            "ABC-1", "add", ["alpha"], dry_run=True
        )

        assert result == {
            "ok": True,
            "dry_run": True,
            "issue_key": "ABC-1",
            "operation": "add",
            "labels": ["alpha"],
            "reconciled": False,
        }
        assert client.calls == []

    @pytest.mark.parametrize(
        ("operation", "requested", "remote_labels"),
        [
            ("add", ["alpha", "beta"], ["alpha", "beta", "remote-only"]),
            ("remove", ["alpha", "beta"], ["remote-only"]),
        ],
    )
    def test_ambiguous_write_reconciles_label_membership_once_without_remote_labels(
        self, operation, requested, remote_labels
    ):
        client = FakeClient(
            [
                JiraError("write_ambiguous"),
                {"key": "ABC-1", "fields": {"labels": remote_labels}},
            ]
        )

        result = JiraOperations(client).manage_labels(
            "ABC-1", operation, requested, confirm=True
        )

        assert result == {
            "ok": True,
            "dry_run": False,
            "issue_key": "ABC-1",
            "operation": operation,
            "labels": requested,
            "reconciled": True,
        }
        assert [call[:2] for call in client.calls] == [
            ("PUT", "issue/ABC-1"),
            ("GET", "issue/ABC-1"),
        ]

    @pytest.mark.parametrize(
        "reconciliation_outcome",
        [
            JiraError("authentication"),
            {"fields": {"labels": "malformed"}},
            {"fields": {"labels": ["other"]}},
        ],
    )
    def test_reconciliation_failure_or_mismatch_reraises_the_original_ambiguity(
        self, reconciliation_outcome
    ):
        original = JiraError("write_ambiguous")
        client = FakeClient([original, reconciliation_outcome])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).manage_labels(
                "ABC-1", "add", ["alpha"], confirm=True
            )

        assert caught.value is original
        assert [call[:2] for call in client.calls] == [
            ("PUT", "issue/ABC-1"),
            ("GET", "issue/ABC-1"),
        ]

    @pytest.mark.parametrize(
        ("deployment", "rest_api_version", "resolved_version"),
        [
            ("cloud", "auto", "3"),
            ("data_center", "auto", "2"),
            ("cloud", "3", "3"),
            ("data_center", "2", "2"),
        ],
    )
    def test_reconciliation_uses_one_put_and_one_resolved_version_get(
        self, deployment, rest_api_version, resolved_version
    ):
        class AutoTransport:
            def __init__(self):
                self.calls = []

            def request(self, method, path, **kwargs):
                self.calls.append((method, path, kwargs))
                if path == "/rest/api/3/serverInfo":
                    if deployment == "cloud":
                        return TransportResponse(200, {}, b"{}")
                    return TransportResponse(
                        404,
                        {"content-type": "application/json"},
                        b'{"errorMessages":["REST API v3 endpoint is not available"]}',
                    )
                if path == "/rest/api/2/serverInfo":
                    return TransportResponse(200, {}, b"{}")
                if path == f"/rest/api/{resolved_version}/issue/ABC-1":
                    if method == "PUT":
                        return TransportResponse(500, {}, b"")
                    return TransportResponse(
                        200,
                        {},
                        json.dumps(
                            {"key": "ABC-1", "fields": {"labels": ["alpha"]}}
                        ).encode(),
                    )
                raise AssertionError(f"unexpected request: {method} {path}")

            def close(self):
                pass

        auth = JiraAuth(
            origin="https://jira.example.test",
            authorization="Bearer secret-token-value",
            auth_mode="bearer",
            rest_api_version=rest_api_version,
            transport="native",
            curl_executable="/usr/bin/curl",
            request_timeout_seconds=30,
            default_max_results=25,
        )
        transport = AutoTransport()

        result = JiraOperations(
            JiraClient(auth, native_transport=transport)
        ).manage_labels("ABC-1", "add", ["alpha"], confirm=True)

        assert result["reconciled"] is True
        assert [method for method, _path, _kwargs in transport.calls].count("PUT") == 1
        issue_gets = [
            (method, path)
            for method, path, _kwargs in transport.calls
            if method == "GET" and path.endswith("/issue/ABC-1")
        ]
        assert issue_gets == [("GET", f"/rest/api/{resolved_version}/issue/ABC-1")]


class TestWriteScalarSubclasses:
    @pytest.mark.parametrize(
        "write",
        [
            lambda operation: operation.add_comment(
                StringSubclass("ABC-1"), "body"
            ),
            lambda operation: operation.add_comment(
                "ABC-1", StringSubclass("body")
            ),
            lambda operation: operation.transition_issue(
                StringSubclass("ABC-1"), "21", confirm=True
            ),
            lambda operation: operation.transition_issue(
                "ABC-1", StringSubclass("21"), confirm=True
            ),
            lambda operation: operation.transition_issue(
                "ABC-1", "21", confirm=True,
                expected_status=StringSubclass("Done"),
            ),
            lambda operation: operation.assign_issue(
                StringSubclass("ABC-1"), "jsmith", confirm=True
            ),
            lambda operation: operation.assign_issue(
                "ABC-1", StringSubclass("jsmith"), confirm=True
            ),
            lambda operation: operation.update_fields(
                StringSubclass("ABC-1"), {"summary": "New"}, confirm=True
            ),
            lambda operation: operation.update_fields(
                "ABC-1", {"summary": StringSubclass("New")}, confirm=True
            ),
        ],
    )
    def test_string_subclasses_are_refused_before_any_write(self, write):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            write(JiraOperations(client))

        assert caught.value.category == "invalid_input"
        assert client.calls == []

    @pytest.mark.parametrize("value", [IntegerSubclass(5), FloatSubclass(1.5)])
    def test_numeric_subclasses_in_update_fields_are_refused_before_a_put(self, value):
        client = FakeClient([])

        with pytest.raises(JiraError) as caught:
            JiraOperations(client).update_fields(
                "ABC-1", {"customfield_10234": value}, confirm=True
            )

        assert caught.value.category == "invalid_input"
        assert client.calls == []


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


def test_update_fields_schema_exposes_only_the_bounded_write_arguments():
    from jira_test_support import tools

    schema = tools.SCHEMAS["jira_update_fields"]["parameters"]

    assert schema["required"] == ["key", "fields"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {"key", "fields", "dry_run", "confirm"}
    assert schema["properties"]["fields"] == {
        "type": "object",
        "minProperties": 1,
        "maxProperties": 20,
    }


def test_update_fields_requires_matching_host_admission_before_configuration(
    monkeypatch,
):
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    calls = []
    monkeypatch.setattr(
        plugin.jira_tools,
        "invoke",
        lambda name, args, configuration, **options: calls.append(name) or {"ok": True},
    )
    handler = context.registrations["jira_update_fields"]["handler"]
    args = {"key": "ABC-1", "fields": {"summary": "New"}, "confirm": True}

    refused = json.loads(handler(args))

    assert refused["error"]["category"] == "permission"
    assert context.configuration_calls == 0
    assert calls == []

    accepted = json.loads(
        handler(args, tool_admission=_admission("jira_update_fields"))
    )

    assert accepted == {"success": True, "result": {"ok": True}}
    assert calls == ["jira_update_fields"]


def test_update_fields_approval_is_bounded_and_argument_scoped():
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    hook = context.hooks["pre_tool_call"]

    first = hook(
        "jira_update_fields", {"key": "ABC-1", "fields": {"summary": "New"}}
    )
    second = hook(
        "jira_update_fields", {"key": "XYZ-9", "fields": {"labels": ["new"]}}
    )

    assert "jira_update_fields" in first["message"]
    assert "ABC-1" in first["message"]
    assert "summary" in first["message"]
    assert len(first["message"]) <= 600
    assert first["rule_key"].startswith("jira_update_fields:")
    assert first["rule_key"] != second["rule_key"]


def test_update_fields_approval_handles_invalid_caller_values_without_echoing_them():
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    hook = context.hooks["pre_tool_call"]

    request = hook(
        "jira_update_fields",
        {"key": "ABC-1", "fields": {"summary": object()}},
    )

    assert request["action"] == "approve"
    assert "<unsupported>" in request["message"]
    assert len(request["message"]) <= 600


def test_manage_labels_has_complete_schema_wiring_and_bound_approval_digest():
    from jira_test_support import tools

    schema = tools.SCHEMAS["jira_manage_labels"]["parameters"]
    assert schema["required"] == ["key", "operation", "labels"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "key", "operation", "labels", "dry_run", "confirm"
    }
    assert schema["properties"]["operation"] == {
        "type": "string",
        "enum": ["add", "remove"],
    }
    assert schema["properties"]["labels"] == {
        "type": "array",
        "items": {"type": "string", "minLength": 1, "maxLength": 255},
        "minItems": 1,
        "maxItems": 50,
    }

    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    hook = context.hooks["pre_tool_call"]
    labels = [f"label-{index}" for index in range(50)]
    alternate_labels = [*labels[:-1], "different-label"]
    first = hook(
        "jira_manage_labels",
        {"key": "ABC-1", "operation": "add", "labels": labels, "confirm": True},
    )
    second = hook(
        "jira_manage_labels",
        {
            "key": "ABC-1",
            "operation": "add",
            "labels": alternate_labels,
            "confirm": True,
        },
    )

    assert "jira_manage_labels" in first["message"]
    assert "ABC-1" in first["message"]
    assert "add" in first["message"]
    assert first["rule_key"].startswith("jira_manage_labels:")
    assert first["rule_key"] != second["rule_key"]
    assert first["rule_key"] != "jira_manage_labels:" + hashlib.sha256(
        plugin._INVALID_APPROVAL_ARGS.encode("utf-8")
    ).hexdigest()


def test_manage_labels_requires_matching_host_admission_before_configuration(
    monkeypatch,
):
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    calls = []
    monkeypatch.setattr(
        plugin.jira_tools,
        "invoke",
        lambda name, args, configuration, **options: calls.append(name) or {"ok": True},
    )
    handler = context.registrations["jira_manage_labels"]["handler"]
    args = {
        "key": "ABC-1",
        "operation": "add",
        "labels": ["alpha"],
        "confirm": True,
    }

    refused = json.loads(handler(args))

    assert refused["error"]["category"] == "permission"
    assert context.configuration_calls == 0
    assert calls == []

    accepted = json.loads(
        handler(args, tool_admission=_admission("jira_manage_labels"))
    )

    assert accepted == {"success": True, "result": {"ok": True}}
    assert calls == ["jira_manage_labels"]
