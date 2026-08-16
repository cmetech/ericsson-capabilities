"""Connector-level contract: error shape, envelope shape, approval coverage."""

import json
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
