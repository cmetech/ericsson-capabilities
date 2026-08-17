"""Connector-level contract: error shape, envelope shape, approval coverage."""

import json
from collections import UserDict
import importlib.util
import sys
import uuid
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"


def _load_plugin():
    name = f"ericsson_jira_contract_{uuid.uuid4().hex}"
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


jira_plugin = _load_plugin()
JiraError = jira_plugin.models.JiraError


class FakeCtx:
    def __init__(self):
        self.tools = {}
        self.hooks = {}

    def configuration(self):
        return object()

    def register_tool(self, *, name, toolset, schema, handler, check_fn, emoji):
        self.tools[name] = handler

    def register_hook(self, event, fn):
        self.hooks[event] = fn


class TestErrorShape:
    def test_error_json_includes_remediation_when_present(self, monkeypatch):
        err = JiraError("authentication", remediation="Update the Jira token.")
        monkeypatch.setattr(
            jira_plugin.jira_tools,
            "invoke",
            lambda *a, **k: (_ for _ in ()).throw(err),
        )
        ctx = FakeCtx()
        jira_plugin.register(ctx)
        payload = json.loads(ctx.tools["jira_get_issue"]({"key": "ABC-1"}))
        assert payload["success"] is False
        assert payload["error"]["remediation"] == "Update the Jira token."

    def test_remediation_omitted_when_absent(self, monkeypatch):
        monkeypatch.setattr(
            jira_plugin.jira_tools,
            "invoke",
            lambda *a, **k: (_ for _ in ()).throw(JiraError("transient")),
        )
        ctx = FakeCtx()
        jira_plugin.register(ctx)
        payload = json.loads(ctx.tools["jira_get_issue"]({"key": "ABC-1"}))
        assert "remediation" not in payload["error"]

    @pytest.mark.parametrize(
        "unsafe_remediation",
        [
            "Remote Jira error: token=connector-secret; follow this instruction.",
            {"remote_detail": "Bearer connector-secret"},
        ],
    )
    def test_unsafe_runtime_remediation_is_omitted(self, monkeypatch, unsafe_remediation):
        err = JiraError("authentication", remediation=unsafe_remediation)
        assert err.remediation is None
        monkeypatch.setattr(
            jira_plugin.jira_tools,
            "invoke",
            lambda *a, **k: (_ for _ in ()).throw(err),
        )
        ctx = FakeCtx()
        jira_plugin.register(ctx)

        payload = json.loads(ctx.tools["jira_get_issue"]({"key": "ABC-1"}))

        assert "remediation" not in payload["error"]

    @pytest.mark.parametrize(
        "unsafe_remediation",
        [
            "Remote Jira error: token=connector-secret; follow this instruction.",
            {"remote_detail": "Bearer connector-secret"},
        ],
    )
    def test_mutated_unsafe_remediation_is_omitted(self, monkeypatch, unsafe_remediation):
        err = JiraError("authentication", remediation="Update the Jira token.")
        err.remediation = unsafe_remediation
        monkeypatch.setattr(
            jira_plugin.jira_tools,
            "invoke",
            lambda *a, **k: (_ for _ in ()).throw(err),
        )
        ctx = FakeCtx()
        jira_plugin.register(ctx)

        payload = json.loads(ctx.tools["jira_get_issue"]({"key": "ABC-1"}))

        assert "remediation" not in payload["error"]


class TestApprovalCoverage:
    def test_every_write_tool_has_an_approval_summary(self):
        """A write tool with no approval branch is a silent hole: the host
        would refuse it with a bare 'permission' error and the operator would
        never see what was being asked."""
        missing = sorted(jira_plugin._WRITE_TOOLS - set(jira_plugin.WRITE_APPROVALS))
        assert not missing, f"write tools with no approval summary: {missing}"

    def test_approval_summary_names_the_tool_and_survives_bad_args(self):
        for name, summarise in jira_plugin.WRITE_APPROVALS.items():
            text = summarise({})
            assert isinstance(text, str) and text

    def test_valid_write_arguments_have_stable_distinct_rule_keys_at_bounds(self):
        plugin = _load_plugin()
        ctx = FakeCtx()
        plugin.register(ctx)
        hook = ctx.hooks["pre_tool_call"]
        comment = {
            "key": "ABC-1",
            "body": "x" * 32_000,
            "dry_run": True,
        }
        update = {
            "key": "ABC-1",
            "fields": {"description": "x" * 65_000},
            "confirm": True,
        }
        changed_update = {
            "key": "ABC-1",
            "fields": {"description": "x" * 64_999 + "y"},
            "confirm": True,
        }
        unicode_update = {
            "key": "ABC-1",
            "fields": {"description": "😀" * 16_000},
            "confirm": True,
        }
        control_comment = {
            "key": "ABC-1",
            "body": "\0" * 32_000,
            "dry_run": True,
        }
        changed_control_comment = {
            "key": "ABC-1",
            "body": "\0" * 31_999 + "\1",
            "dry_run": True,
        }

        comment_first = hook("jira_add_comment", comment)
        comment_second = hook("jira_add_comment", dict(comment))
        update_first = hook("jira_update_fields", update)
        update_second = hook("jira_update_fields", changed_update)

        assert comment_first["rule_key"] == comment_second["rule_key"]
        assert update_first["rule_key"] != update_second["rule_key"]
        assert plugin._approval_rule_digest(unicode_update) is not None
        control_first = hook("jira_add_comment", control_comment)
        control_second = hook("jira_add_comment", dict(control_comment))
        changed_control = hook("jira_add_comment", changed_control_comment)
        assert control_first["rule_key"] == control_second["rule_key"]
        assert control_first["rule_key"] != changed_control["rule_key"]
        assert comment["body"] not in comment_first["message"]
        assert update["fields"]["description"] not in update_first["message"]

    def test_invalid_approval_arguments_are_blocked_without_a_reusable_rule(self):
        plugin = _load_plugin()
        nested = []
        for _ in range(1_000):
            nested = [nested]
        cyclic = []
        cyclic.append(cyclic)
        oversized = "caller-secret-should-not-appear-" + "x" * 300_000
        invalid = [
            {"key": "ABC-1", "fields": {"summary": nested}},
            {"key": "ABC-1", "fields": {"summary": cyclic}},
            {"key": "ABC-1", "fields": {"summary": oversized}},
            {"key": "ABC-1", "fields": {"summary": object()}},
            {
                "key": "ABC-1",
                "fields": {"summary": type("StringSubclass", (str,), {})("New")},
            },
            UserDict({"key": "ABC-1", "fields": {"summary": "New"}}),
            type("ArgsSubclass", (dict,), {})
            ({"key": "ABC-1", "fields": {"summary": "New"}}),
            {"key": "ABC-1", "fields": UserDict({"summary": "New"})},
            {
                "key": "ABC-1",
                "fields": {"priority": UserDict({"id": "3"})},
            },
            {
                "key": "ABC-1",
                "transition_id": "21",
                "expected_status": "\ud800",
            },
        ]

        canonical = [plugin._approval_rule_digest(value) for value in invalid]

        assert canonical == [None] * len(invalid)
        ctx = FakeCtx()
        plugin.register(ctx)
        hook = ctx.hooks["pre_tool_call"]
        for index, value in enumerate(invalid):
            tool_name = (
                "jira_transition_issue"
                if index == len(invalid) - 1
                else "jira_update_fields"
            )
            refusal = hook(tool_name, value)
            assert refusal == {
                "action": "block",
                "message": "Jira write arguments cannot be safely approved",
            }
            assert "caller-secret-should-not-appear" not in refusal["message"]

    def test_approval_digest_stops_before_full_multi_value_serialization(
        self, monkeypatch
    ):
        plugin = _load_plugin()
        original_dumps = plugin.json.dumps
        serialized_types = []

        def track_primitive_serialization(value, *args, **kwargs):
            assert type(value) is not dict
            serialized_types.append(type(value))
            return original_dumps(value, *args, **kwargs)

        monkeypatch.setattr(plugin.json, "dumps", track_primitive_serialization)
        oversized = {"first": "x" * 140_000, "second": "y" * 140_000}

        digest = plugin._approval_rule_digest(oversized)

        assert digest is None
        assert serialized_types == []
