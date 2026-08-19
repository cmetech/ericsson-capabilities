"""ARM model-tool and application-command adapter contract."""

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
PLUGIN = REPO / "plugins" / "ericsson-arm"
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
                name="Ericsson ARM",
                key="ericsson-arm",
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
    name = f"ericsson_arm_cli_port_{uuid.uuid4().hex}"
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
    for name in plugin.arm_tools.SCHEMAS:
        registry.deregister(name)
    plugin.register(context)
    caller = PluginContext(
        PluginManifest(name="Connector CLI", key="ericsson-connector-cli"), manager
    )
    _snapshot(monkeypatch)
    yield plugin, manager, context, caller
    for name in plugin.arm_tools.SCHEMAS:
        registry.deregister(name)


def test_registers_all_operations_without_configuration(port):
    plugin, manager, context, _caller = port
    registration = manager._application_command_providers["ericsson-arm"]
    assert dict(registration.operations) == {
        name: "write" if name in plugin._WRITE_TOOLS else "read"
        for name in plugin.arm_tools.SCHEMAS
    }
    assert len(registration.operations) == 6
    assert registration.allowed_callers == frozenset({"ericsson-connector-cli"})
    assert context.configuration_calls == 0


def test_read_and_dry_run_share_one_executor_after_separate_authority(
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

    read_args = {"repo": "generic-local", "path": "team/app.tgz"}
    model_read = json.loads(registry.dispatch("arm_artifact_info", read_args))
    direct_read = caller.invoke_application_command(
        "ericsson-arm",
        "arm_artifact_info",
        read_args,
        mode="read",
        invocation_id="read",
    )
    write_args = {**read_args, "dry_run": True}
    admission = _approve(monkeypatch, "arm_delete", write_args)
    model_write = json.loads(
        registry.dispatch(
            "arm_delete",
            write_args,
            _tool_admission=admission,
            tool_call_id="tool-1",
            turn_id="turn-1",
        )
    )
    direct_write = caller.invoke_application_command(
        "ericsson-arm",
        "arm_delete",
        read_args,
        mode="dry_run",
        invocation_id="write",
    )

    assert model_read == direct_read == {"success": True, "result": read_args}
    assert model_write == direct_write == {"success": True, "result": write_args}
    assert [call[:2] for call in calls] == [
        ("arm_artifact_info", read_args),
        ("arm_artifact_info", read_args),
        ("arm_delete", write_args),
        ("arm_delete", write_args),
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
    arguments = {
        "repo": "generic-local",
        "path": "team/app.tgz",
        "dry_run": True,
    }
    handler = registry.get_entry("arm_delete").handler
    forged = json.loads(
        handler(
            arguments,
            tool_admission=SimpleNamespace(
                approved=True, policy="plugin_approve", tool_name="arm_delete"
            ),
        )
    )
    admission = _approve(monkeypatch, "arm_delete", arguments)
    accepted = json.loads(
        registry.dispatch(
            "arm_delete",
            arguments,
            _tool_admission=admission,
            tool_call_id="tool-1",
            turn_id="turn-1",
        )
    )
    replay = json.loads(
        registry.dispatch(
            "arm_delete",
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
def test_direct_caller_intent_fields_fail_before_configuration(
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
        "ericsson-arm",
        "arm_delete",
        {"repo": "generic-local", "path": "team/app.tgz", field: False},
        mode="confirm",
        invocation_id=f"caller-{field}",
    )
    assert result["error"]["category"] == "invalid_input"
    assert calls == []
    assert context.configuration_calls == 0


@pytest.mark.parametrize(
    ("mode", "expected_field"), [("dry_run", "dry_run"), ("confirm", "confirm")]
)
def test_direct_mode_normalizes_only_after_genuine_host_invocation(
    port, monkeypatch, mode, expected_field
):
    plugin, manager, context, caller = port
    seen = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda name, arguments, configuration, **kwargs: seen.append(arguments)
        or {"success": True, "result": arguments},
    )
    handler = manager._application_command_providers["ericsson-arm"].handler
    forged = handler(
        SimpleNamespace(
            active=True,
            provider_id="ericsson-arm",
            caller_id="ericsson-connector-cli",
            operation="arm_delete",
            mode=mode,
            arguments={"repo": "generic-local", "path": "team/app.tgz"},
        )
    )
    assert forged["error"]["category"] == "permission"
    result = caller.invoke_application_command(
        "ericsson-arm",
        "arm_delete",
        {"repo": "generic-local", "path": "team/app.tgz"},
        mode=mode,
        invocation_id=mode,
    )
    assert result["result"][expected_field] is True
    assert seen == [
        {"repo": "generic-local", "path": "team/app.tgz", expected_field: True}
    ]
    assert context.configuration_calls == 1


def test_direct_invocation_is_active_single_use_and_caller_bound(port, monkeypatch):
    plugin, manager, context, caller = port
    calls = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: calls.append(args) or {"success": True, "result": {}},
    )
    handler = manager._application_command_providers["ericsson-arm"].handler
    captured = []
    manager._application_command_providers["ericsson-arm"] = replace(
        manager._application_command_providers["ericsson-arm"],
        handler=lambda invocation: captured.append(invocation) or handler(invocation),
    )
    caller.invoke_application_command(
        "ericsson-arm",
        "arm_list_repositories",
        {},
        mode="read",
        invocation_id="capture",
    )
    assert handler(captured[0])["error"]["category"] == "permission"
    outsider = PluginContext(PluginManifest(name="Outside", key="outside"), manager)
    with pytest.raises(PluginApplicationCommandDenied):
        outsider.invoke_application_command(
            "ericsson-arm",
            "arm_list_repositories",
            {},
            mode="read",
            invocation_id="outside",
        )
    with pytest.raises(TypeError, match="minted by Hermes"):
        PluginApplicationCommandInvocation(
            provider_id="ericsson-arm",
            caller_id="ericsson-connector-cli",
            operation="arm_list_repositories",
            arguments={},
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
    for name in plugin.arm_tools.SCHEMAS:
        registry.deregister(name)
    try:
        plugin.register(context)
        caller = PluginContext(
            PluginManifest(name="Connector CLI", key="ericsson-connector-cli"),
            manager,
        )
        _snapshot(monkeypatch)
        direct = caller.invoke_application_command(
            "ericsson-arm",
            "arm_list_repositories",
            {},
            mode="read",
            invocation_id="configuration",
        )
        model = json.loads(registry.dispatch("arm_list_repositories", {}))
        expected = {
            "success": False,
            "error": {
                "category": "invalid_configuration",
                "message": "Artifactory configuration is invalid",
            },
        }
        assert direct == model == expected
        assert "secret" not in json.dumps(direct)
        assert context.configuration_calls == 2
    finally:
        for name in plugin.arm_tools.SCHEMAS:
            registry.deregister(name)


def test_direct_adapter_does_not_pass_or_serialize_host_authority(port, monkeypatch):
    plugin, _manager, context, caller = port
    seen = []

    def execute(name, arguments, configuration, **kwargs):
        seen.append((arguments, configuration, kwargs))
        return {"success": True, "result": arguments}

    monkeypatch.setattr(plugin.application, "execute", execute)
    result = caller.invoke_application_command(
        "ericsson-arm",
        "arm_list_repositories",
        {},
        mode="read",
        invocation_id="authority-separation",
    )
    assert result == {"success": True, "result": {}}
    arguments, configuration, options = seen[0]
    assert configuration is context.configuration_value
    assert arguments == {}
    assert set(options) == {"cancel_check"}
    assert not any(
        isinstance(value, PluginApplicationCommandInvocation)
        for value in (*arguments.values(), *options.values())
    )
    assert "Configuration" not in json.dumps(result)


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (ValueError("raw"), "invalid_input"),
        ("edge", "edge_authentication"),
        ("ambiguous", "write_ambiguous"),
        (RuntimeError("secret"), "transient"),
    ],
)
def test_application_executor_returns_safe_connector_envelopes(
    port, monkeypatch, failure, category
):
    plugin, _manager, context, _caller = port

    def invoke(*args, **kwargs):
        if failure == "edge":
            raise plugin.ArmError("edge_authentication")
        if failure == "ambiguous":
            raise plugin.ArmError("write_ambiguous")
        raise failure

    monkeypatch.setattr(plugin.arm_tools, "invoke", invoke)
    result = plugin.application.execute(
        "arm_list_repositories", {}, context.configuration_value
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
