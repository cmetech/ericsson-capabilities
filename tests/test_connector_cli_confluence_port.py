"""Confluence model-tool and application-command adapter contract."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import uuid
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-confluence"
HERMES = Path(os.environ["HERMES_AGENT_DIR"])
sys.path.insert(0, str(HERMES))

from hermes_cli.plugin_application_commands import (  # noqa: E402
    PluginApplicationCommandDenied,
    PluginApplicationCommandInvocation,
)
from hermes_cli.plugins import (  # noqa: E402
    PluginContext,
    PluginManager,
    PluginManifest,
    resolve_pre_tool_admission,
)
from tools.registry import registry  # noqa: E402


class Configuration:
    """Opaque configuration marker."""


class TestContext(PluginContext):
    __test__ = False

    def __init__(self, manager, *, failure=None):
        super().__init__(
            PluginManifest(
                name="Ericsson Confluence",
                key="ericsson-confluence",
                kind="standalone",
                source="bundled",
                path=str(PLUGIN),
            ),
            manager,
        )
        self.configuration_value = Configuration()
        self.configuration_failure = failure
        self.configuration_calls = 0

    def configuration(self):
        self.configuration_calls += 1
        if self.configuration_failure:
            raise self.configuration_failure
        return self.configuration_value


def _load_plugin():
    name = f"ericsson_confluence_cli_port_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _snapshot(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.plugin_configuration.connector_capability_snapshot",
        lambda: SimpleNamespace(
            scoped_fingerprint=lambda providers, operations: "profile-fingerprint"
        ),
    )


def _approve(monkeypatch, name, arguments):
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda hook_name, **kwargs: [{"action": "approve", "message": "approve"}],
    )
    monkeypatch.setattr(
        "tools.approval.request_tool_approval",
        lambda *args, **kwargs: {"approved": True, "message": None},
    )
    decision = resolve_pre_tool_admission(
        name, arguments, tool_call_id="tool-1", turn_id="turn-1"
    )
    assert decision.admission is not None
    return decision.admission


@pytest.fixture
def port(monkeypatch):
    plugin = _load_plugin()
    manager = PluginManager()
    context = TestContext(manager)
    for name in plugin.confluence_tools.SCHEMAS:
        registry.deregister(name)
    plugin.register(context)
    caller = PluginContext(
        PluginManifest(name="Connector CLI", key="ericsson-connector-cli"), manager
    )
    _snapshot(monkeypatch)
    yield plugin, manager, context, caller
    for name in plugin.confluence_tools.SCHEMAS:
        registry.deregister(name)


def test_registers_all_operations_without_configuration(port):
    plugin, manager, context, _caller = port
    registration = manager._application_command_providers["ericsson-confluence"]
    assert dict(registration.operations) == {
        name: "write" if name in plugin._WRITE_TOOLS else "read"
        for name in plugin.confluence_tools.SCHEMAS
    }
    assert len(registration.operations) == 9
    assert registration.allowed_callers == frozenset({"ericsson-connector-cli"})
    assert context.configuration_calls == 0


def test_read_and_writes_share_one_executor_after_separate_authority(
    port, monkeypatch
):
    plugin, _manager, context, caller = port
    calls = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda name, arguments, configuration, **kwargs: calls.append(
            (name, arguments, configuration)
        )
        or {"success": True, "result": arguments},
    )

    read_args = {"content_id": "123"}
    model_read = json.loads(registry.dispatch("confluence_get_page", read_args))
    direct_read = caller.invoke_application_command(
        "ericsson-confluence",
        "confluence_get_page",
        read_args,
        mode="read",
        invocation_id="read",
    )
    write_args = {"content_id": "123", "markdown": "**safe**", "dry_run": True}
    admission = _approve(monkeypatch, "confluence_add_comment", write_args)
    model_write = json.loads(
        registry.dispatch(
            "confluence_add_comment",
            write_args,
            _tool_admission=admission,
            tool_call_id="tool-1",
            turn_id="turn-1",
        )
    )
    direct_write = caller.invoke_application_command(
        "ericsson-confluence",
        "confluence_add_comment",
        {"content_id": "123", "markdown": "**safe**"},
        mode="dry_run",
        invocation_id="write",
    )

    assert model_read == direct_read == {"success": True, "result": read_args}
    assert model_write == direct_write == {"success": True, "result": write_args}
    assert [call[:2] for call in calls] == [
        ("confluence_get_page", read_args),
        ("confluence_get_page", read_args),
        ("confluence_add_comment", write_args),
        ("confluence_add_comment", write_args),
    ]
    assert all(call[2] is context.configuration_value for call in calls)
    assert context.configuration_calls == 4


def test_model_write_rejects_lookalike_and_replay(port, monkeypatch):
    plugin, _manager, context, _caller = port
    calls = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: calls.append(args) or {"success": True, "result": {}},
    )
    arguments = {"content_id": "123", "markdown": "safe", "dry_run": True}
    handler = registry.get_entry("confluence_add_comment").handler
    forged = json.loads(
        handler(
            arguments,
            tool_admission=SimpleNamespace(
                approved=True,
                policy="plugin_approve",
                tool_name="confluence_add_comment",
            ),
        )
    )
    admission = _approve(monkeypatch, "confluence_add_comment", arguments)
    accepted = json.loads(
        registry.dispatch(
            "confluence_add_comment",
            arguments,
            _tool_admission=admission,
            tool_call_id="tool-1",
            turn_id="turn-1",
        )
    )
    replay = json.loads(
        registry.dispatch(
            "confluence_add_comment",
            arguments,
            _tool_admission=admission,
            tool_call_id="tool-1",
            turn_id="turn-1",
        )
    )
    assert forged["error"]["category"] == "permission"
    assert accepted["success"] is True
    assert replay["error"].startswith("BLOCKED:")
    assert len(calls) == 1
    assert context.configuration_calls == 1


@pytest.mark.parametrize("field", ["dry_run", "confirm"])
def test_direct_intent_is_host_owned_and_caller_fields_fail_pre_config(
    port, monkeypatch, field
):
    plugin, _manager, context, caller = port
    calls = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: calls.append(args) or {"success": True, "result": {}},
    )
    result = caller.invoke_application_command(
        "ericsson-confluence",
        "confluence_update_page",
        {"content_id": "123", "markdown": "safe", field: False},
        mode="confirm",
        invocation_id=f"caller-{field}",
    )
    assert result["error"]["category"] == "invalid_input"
    assert calls == []
    assert context.configuration_calls == 0


def test_direct_confirm_normalizes_only_after_genuine_host_invocation(port, monkeypatch):
    plugin, manager, context, caller = port
    seen = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda name, arguments, configuration, **kwargs: seen.append(arguments)
        or {"success": True, "result": arguments},
    )
    handler = manager._application_command_providers["ericsson-confluence"].handler
    forged = handler(
        SimpleNamespace(
            active=True,
            provider_id="ericsson-confluence",
            caller_id="ericsson-connector-cli",
            operation="confluence_add_comment",
            mode="confirm",
            arguments={"content_id": "123", "markdown": "safe"},
        )
    )
    assert forged["error"]["category"] == "permission"
    result = caller.invoke_application_command(
        "ericsson-confluence",
        "confluence_add_comment",
        {"content_id": "123", "markdown": "safe"},
        mode="confirm",
        invocation_id="confirm",
    )
    assert result["result"]["confirm"] is True
    assert seen == [{"content_id": "123", "markdown": "safe", "confirm": True}]
    assert context.configuration_calls == 1


def test_direct_invocation_is_active_single_use_and_caller_bound(port, monkeypatch):
    plugin, manager, context, caller = port
    calls = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: calls.append(args) or {"success": True, "result": {}},
    )
    handler = manager._application_command_providers["ericsson-confluence"].handler
    captured = []
    manager._application_command_providers["ericsson-confluence"] = replace(
        manager._application_command_providers["ericsson-confluence"],
        handler=lambda invocation: captured.append(invocation) or handler(invocation),
    )
    caller.invoke_application_command(
        "ericsson-confluence",
        "confluence_get_page",
        {"content_id": "123"},
        mode="read",
        invocation_id="capture",
    )
    assert handler(captured[0])["error"]["category"] == "permission"
    outsider = PluginContext(PluginManifest(name="Outside", key="outside"), manager)
    with pytest.raises(PluginApplicationCommandDenied):
        outsider.invoke_application_command(
            "ericsson-confluence",
            "confluence_get_page",
            {"content_id": "123"},
            mode="read",
            invocation_id="outside",
        )
    with pytest.raises(TypeError, match="minted by Hermes"):
        PluginApplicationCommandInvocation(
            provider_id="ericsson-confluence",
            caller_id="ericsson-connector-cli",
            operation="confluence_get_page",
            arguments={"content_id": "123"},
            mode="read",
            invocation_id="forged",
            profile_fingerprint="profile",
        )
    assert len(calls) == 1
    assert context.configuration_calls == 1


def test_configuration_failure_is_safe_and_resolved_once_per_adapter(monkeypatch):
    plugin = _load_plugin()
    manager = PluginManager()
    context = TestContext(manager, failure=RuntimeError("secret configuration text"))
    for name in plugin.confluence_tools.SCHEMAS:
        registry.deregister(name)
    try:
        plugin.register(context)
        caller = PluginContext(
            PluginManifest(name="Connector CLI", key="ericsson-connector-cli"),
            manager,
        )
        _snapshot(monkeypatch)
        direct = caller.invoke_application_command(
            "ericsson-confluence",
            "confluence_get_page",
            {"content_id": "123"},
            mode="read",
            invocation_id="configuration",
        )
        model = json.loads(
            registry.dispatch("confluence_get_page", {"content_id": "123"})
        )
        expected = {
            "success": False,
            "error": {
                "category": "invalid_configuration",
                "message": "Confluence configuration is invalid",
            },
        }
        assert direct == model == expected
        assert "secret" not in json.dumps(direct)
        assert context.configuration_calls == 2
    finally:
        for name in plugin.confluence_tools.SCHEMAS:
            registry.deregister(name)


def test_direct_adapter_does_not_pass_or_serialize_host_authority(port, monkeypatch):
    plugin, _manager, context, caller = port
    seen = []

    def execute(name, arguments, configuration, **kwargs):
        seen.append((arguments, configuration, kwargs))
        return {"success": True, "result": arguments}

    monkeypatch.setattr(plugin.application, "execute", execute)
    result = caller.invoke_application_command(
        "ericsson-confluence",
        "confluence_get_page",
        {"content_id": "123"},
        mode="read",
        invocation_id="authority-separation",
    )
    assert result == {"success": True, "result": {"content_id": "123"}}
    arguments, configuration, options = seen[0]
    assert configuration is context.configuration_value
    assert arguments == {"content_id": "123"}
    assert set(options) == {"cancel_check"}
    assert not any(
        isinstance(value, PluginApplicationCommandInvocation)
        for value in (*arguments.values(), *options.values())
    )
    assert "Configuration" not in json.dumps(result)


@pytest.mark.parametrize(
    ("failure", "category", "remediation"),
    [
        (ValueError("raw"), "invalid_input", None),
        ("connector", "conflict", None),
        ("ambiguous", "write_ambiguous", None),
        (RuntimeError("secret"), "transient", None),
    ],
)
def test_application_executor_returns_safe_connector_envelopes(
    port, monkeypatch, failure, category, remediation
):
    plugin, _manager, context, _caller = port

    def invoke(*args, **kwargs):
        if failure == "connector":
            raise plugin.ConfluenceError("conflict")
        if failure == "ambiguous":
            raise plugin.ConfluenceError("write_ambiguous")
        raise failure

    monkeypatch.setattr(plugin.confluence_tools, "invoke", invoke)
    result = plugin.application.execute(
        "confluence_get_page", {"content_id": "123"}, context.configuration_value
    )
    assert result == {
        "success": False,
        "error": {
            "category": category,
            "message": plugin.SAFE_ERROR_MESSAGES[category],
        },
    }
    assert "raw" not in json.dumps(result)
    assert "secret" not in json.dumps(result)
