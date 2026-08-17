"""Write approvals must be scoped to the specific change, not the tool."""

import importlib.util
import sys
import uuid
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"


def _load_plugin():
    module_name = f"ericsson_gitlab_approval_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


gitlab_plugin = _load_plugin()


class FakeCtx:
    def __init__(self):
        self.hooks = {}
        self.tools = {}

    def configuration(self):
        return object()

    def register_tool(self, *, name, toolset, schema, handler, check_fn, emoji):
        self.tools[name] = handler

    def register_hook(self, event, fn):
        self.hooks[event] = fn


def _hook():
    ctx = FakeCtx()
    gitlab_plugin.register(ctx)
    return ctx.hooks["pre_tool_call"]


class TestApprovalScope:
    def test_different_arguments_get_different_rule_keys(self):
        """Approving 'merge MR !42' must not also approve 'merge MR !43'."""
        hook = _hook()
        first = hook("gitlab_create_merge_request",
                     {"project": "g/p", "source_branch": "a"})
        second = hook("gitlab_create_merge_request",
                      {"project": "g/p", "source_branch": "b"})
        assert first["rule_key"] != second["rule_key"]

    def test_identical_arguments_get_a_stable_rule_key(self):
        hook = _hook()
        args = {"project": "g/p", "source_branch": "a"}
        assert hook("gitlab_create_merge_request", dict(args))["rule_key"] == (
            hook("gitlab_create_merge_request", dict(args))["rule_key"]
        )

    def test_rule_key_is_not_the_bare_tool_name(self):
        hook = _hook()
        result = hook("gitlab_create_merge_request", {"project": "g/p"})
        assert result["rule_key"] != "gitlab_create_merge_request"
        assert result["rule_key"].startswith("gitlab_create_merge_request:")

    def test_argument_order_does_not_change_the_key(self):
        hook = _hook()
        a = hook("gitlab_commit_changes", {"project": "g/p", "branch": "x"})
        b = hook("gitlab_commit_changes", {"branch": "x", "project": "g/p"})
        assert a["rule_key"] == b["rule_key"]


class TestApprovalMessage:
    def test_message_names_the_tool_and_its_target(self):
        hook = _hook()
        message = hook(
            "gitlab_create_merge_request",
            {"project": "group/proj", "source_branch": "fix/x"},
        )["message"]
        assert "gitlab_create_merge_request" in message
        assert "group/proj" in message

    def test_every_write_tool_has_a_summary(self):
        missing = sorted(
            gitlab_plugin._WRITE_TOOLS - set(gitlab_plugin.WRITE_APPROVALS)
        )
        assert not missing, f"write tools with no approval summary: {missing}"

    def test_summary_survives_missing_arguments(self):
        for name, summarise in gitlab_plugin.WRITE_APPROVALS.items():
            assert isinstance(summarise({}), str)

    def test_resolve_discussion_defaults_to_resolved_in_approval_message(self):
        message = _hook()(
            "gitlab_resolve_discussion",
            {"project": "group/proj", "iid": 42, "discussion_id": "abc123"},
        )["message"]
        assert "Set resolved: true" in message

    def test_read_tools_are_not_gated(self):
        assert _hook()("gitlab_read_file", {"project": "g/p"}) is None
