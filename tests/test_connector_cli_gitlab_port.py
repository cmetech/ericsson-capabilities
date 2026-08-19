"""GitLab model-tool and application-command adapter contract."""

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
PLUGIN = REPO / "plugins" / "ericsson-gitlab"


def _hermes_root() -> Path:
    configured = os.environ.get("HERMES_AGENT_DIR")
    candidates = ([Path(configured)] if configured else []) + [
        ancestor / "hermes-agent" for ancestor in REPO.parents
    ]
    return next(
        candidate
        for candidate in candidates
        if (candidate / "hermes_cli" / "plugins.py").is_file()
    )


sys.path.insert(0, str(_hermes_root()))

from hermes_cli.plugins import (  # noqa: E402
    PluginContext,
    PluginManager,
    PluginManifest,
    resolve_pre_tool_admission,
)
from hermes_cli.plugin_application_commands import (  # noqa: E402
    PluginApplicationCommandDenied,
    PluginApplicationCommandInvalid,
    PluginApplicationCommandInvocation,
    PluginApplicationCommandUnavailable,
)
from tools.registry import registry  # noqa: E402


class Configuration:
    """Opaque marker passed to the shared executor in adapter tests."""


class TestContext(PluginContext):
    __test__ = False

    def __init__(self, manager, *, configuration=Configuration(), failure=None):
        super().__init__(
            PluginManifest(
                name="Ericsson GitLab",
                key="ericsson-gitlab",
                kind="standalone",
                source="bundled",
                path=str(PLUGIN),
            ),
            manager,
        )
        self.configuration_value = configuration
        self.configuration_failure = failure
        self.configuration_calls = 0

    def configuration(self):
        self.configuration_calls += 1
        if self.configuration_failure is not None:
            raise self.configuration_failure
        return self.configuration_value


def _load_plugin():
    name = f"ericsson_gitlab_cli_port_{uuid.uuid4().hex}"
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


def _patch_snapshot(monkeypatch):
    monkeypatch.setattr(
        "hermes_cli.plugin_configuration.connector_capability_snapshot",
        lambda: SimpleNamespace(
            scoped_fingerprint=lambda providers, operations: "profile-fingerprint"
        ),
    )


def _approve(monkeypatch, tool_name, arguments):
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda hook_name, **kwargs: [
            {"action": "approve", "message": "confirm GitLab mutation"}
        ],
    )
    monkeypatch.setattr(
        "tools.approval.request_tool_approval",
        lambda *args, **kwargs: {"approved": True, "message": None},
    )
    decision = resolve_pre_tool_admission(
        tool_name,
        arguments,
        tool_call_id="tool-call-1",
        turn_id="turn-1",
    )
    assert decision.admission is not None
    return decision.admission


@pytest.fixture
def port(monkeypatch):
    plugin = _load_plugin()
    manager = PluginManager()
    context = TestContext(manager)
    for name in plugin.gitlab_tools.SCHEMAS:
        registry.deregister(name)
    plugin.register(context)
    caller = PluginContext(
        PluginManifest(name="Connector CLI", key="ericsson-connector-cli"),
        manager,
    )
    _patch_snapshot(monkeypatch)
    yield plugin, manager, context, caller
    for name in plugin.gitlab_tools.SCHEMAS:
        registry.deregister(name)


def test_registers_every_gitlab_operation_without_resolving_configuration(port):
    plugin, manager, context, _caller = port

    registration = manager._application_command_providers["ericsson-gitlab"]

    assert dict(registration.operations) == {
        name: "write" if name in plugin._WRITE_TOOLS else "read"
        for name in plugin.gitlab_tools.SCHEMAS
    }
    assert len(registration.operations) == 30
    assert registration.allowed_callers == frozenset({"ericsson-connector-cli"})
    assert context.configuration_calls == 0


def test_model_and_direct_reads_share_executor_and_safe_envelope(port, monkeypatch):
    plugin, _manager, context, caller = port
    calls = []

    def execute(name, arguments, configuration, *, cancel_check=None):
        calls.append((name, arguments, configuration, cancel_check))
        return {"success": True, "result": {"project": arguments["project"]}}

    monkeypatch.setattr(plugin.application, "execute", execute)
    arguments = {"project": "group/project"}

    model_result = json.loads(registry.dispatch("gitlab_resolve_project", arguments))
    direct_result = caller.invoke_application_command(
        "ericsson-gitlab",
        "gitlab_resolve_project",
        arguments,
        mode="read",
        invocation_id="read-1",
    )

    assert model_result == direct_result == {
        "success": True,
        "result": {"project": "group/project"},
    }
    assert [(name, args, config) for name, args, config, _cancel in calls] == [
        ("gitlab_resolve_project", arguments, context.configuration_value),
        ("gitlab_resolve_project", arguments, context.configuration_value),
    ]
    assert calls[0][3] is not None
    assert calls[1][3] is not None
    assert context.configuration_calls == 2


def test_model_write_requires_genuine_host_claimed_admission(port, monkeypatch):
    plugin, _manager, context, _caller = port
    calls = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: calls.append(args) or {"success": True, "result": {}},
    )
    arguments = {"project": "g/p", "pipeline_id": 42, "dry_run": True}
    handler = registry.get_entry("gitlab_retry_pipeline").handler

    forged = handler(
        arguments,
        tool_admission=SimpleNamespace(
            approved=True,
            policy="plugin_approve",
            tool_name="gitlab_retry_pipeline",
        ),
    )
    missing = registry.dispatch("gitlab_retry_pipeline", arguments)
    admission = _approve(monkeypatch, "gitlab_retry_pipeline", arguments)
    accepted = registry.dispatch(
        "gitlab_retry_pipeline",
        arguments,
        _tool_admission=admission,
        tool_call_id="tool-call-1",
        turn_id="turn-1",
    )
    replay = registry.dispatch(
        "gitlab_retry_pipeline",
        arguments,
        _tool_admission=admission,
        tool_call_id="tool-call-1",
        turn_id="turn-1",
    )

    assert json.loads(forged)["error"]["category"] == "permission"
    assert json.loads(missing)["error"]["category"] == "permission"
    assert json.loads(accepted) == {"success": True, "result": {}}
    assert json.loads(replay)["error"].startswith("BLOCKED:")
    assert len(calls) == 1
    assert context.configuration_calls == 1


def test_model_approval_refusal_never_reaches_configuration_or_executor(
    port, monkeypatch
):
    plugin, _manager, context, _caller = port
    called = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: called.append(True) or {},
    )
    monkeypatch.setattr(
        "hermes_cli.plugins.invoke_hook",
        lambda hook_name, **kwargs: [
            {"action": "approve", "message": "confirm GitLab mutation"}
        ],
    )
    monkeypatch.setattr(
        "tools.approval.request_tool_approval",
        lambda *args, **kwargs: {"approved": False, "message": "refused"},
    )

    decision = resolve_pre_tool_admission(
        "gitlab_retry_pipeline",
        {"project": "g/p", "pipeline_id": 42, "confirm": True},
        tool_call_id="tool-call-refused",
        turn_id="turn-refused",
    )
    assert decision.admission is None

    result = registry.dispatch(
        "gitlab_retry_pipeline",
        {"project": "g/p", "pipeline_id": 42, "confirm": True},
    )

    assert json.loads(result)["error"]["category"] == "permission"
    assert called == []
    assert context.configuration_calls == 0


@pytest.mark.parametrize(
    ("name", "mode", "model_arguments", "direct_arguments"),
    [
        (
            "gitlab_create_branch",
            "dry_run",
            {
                "project": "g/p",
                "ticket_key": "ABC-1",
                "summary": "safe branch",
                "dry_run": True,
            },
            {"project": "g/p", "ticket_key": "ABC-1", "summary": "safe branch"},
        ),
        (
            "gitlab_retry_pipeline",
            "confirm",
            {"project": "g/p", "pipeline_id": 42, "confirm": True},
            {"project": "g/p", "pipeline_id": 42},
        ),
    ],
)
def test_model_and_direct_writes_are_byte_equivalent_after_separate_authority(
    port, monkeypatch, name, mode, model_arguments, direct_arguments
):
    plugin, _manager, _context, caller = port
    calls = []

    def execute(operation, arguments, configuration, **kwargs):
        calls.append((operation, arguments))
        return {"success": True, "result": {"accepted": arguments}}

    monkeypatch.setattr(plugin.application, "execute", execute)
    admission = _approve(monkeypatch, name, model_arguments)
    model_result = registry.dispatch(
        name,
        model_arguments,
        _tool_admission=admission,
        tool_call_id="tool-call-1",
        turn_id="turn-1",
    )
    direct_result = caller.invoke_application_command(
        "ericsson-gitlab",
        name,
        direct_arguments,
        mode=mode,
        invocation_id=f"equivalent-{mode}",
    )

    assert json.loads(model_result) == direct_result
    assert calls == [(name, model_arguments), (name, model_arguments)]


@pytest.mark.parametrize(
    ("name", "mode", "arguments", "expected"),
    [
        (
            "gitlab_retry_pipeline",
            "dry_run",
            {"project": "g/p", "pipeline_id": 42},
            {"project": "g/p", "pipeline_id": 42, "dry_run": True},
        ),
        (
            "gitlab_retry_pipeline",
            "confirm",
            {"project": "g/p", "pipeline_id": 42},
            {"project": "g/p", "pipeline_id": 42, "confirm": True},
        ),
        *[
            (
                operation,
                "confirm",
                arguments,
                {**arguments, "dry_run": False},
            )
            for operation, arguments in (
                (
                    "gitlab_create_branch",
                    {"project": "g/p", "ticket_key": "ABC-1", "summary": "safe"},
                ),
                (
                    "gitlab_commit_changes",
                    {
                        "project": "g/p",
                        "branch": "main",
                        "commit_message": "safe",
                        "actions": [],
                    },
                ),
                (
                    "gitlab_create_merge_request",
                    {
                        "project": "g/p",
                        "source_branch": "safe",
                        "target_branch": "main",
                        "title": "safe",
                    },
                ),
                (
                    "gitlab_create_named_branch",
                    {"project": "g/p", "branch": "release/1.2", "ref": "main"},
                ),
            )
        ],
    ],
)
def test_direct_write_mode_is_the_only_intent_authority(
    port, monkeypatch, name, mode, arguments, expected
):
    plugin, _manager, context, caller = port
    calls = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda operation, args, configuration, **kwargs: calls.append(
            (operation, args, configuration)
        )
        or {"success": True, "result": args},
    )

    result = caller.invoke_application_command(
        "ericsson-gitlab",
        name,
        arguments,
        mode=mode,
        invocation_id=f"{name}-{mode}",
    )

    assert result == {"success": True, "result": expected}
    assert calls == [(name, expected, context.configuration_value)]
    assert context.configuration_calls == 1


@pytest.mark.parametrize("field", ["dry_run", "confirm"])
def test_direct_write_rejects_caller_supplied_intent_flags_before_config(
    port, monkeypatch, field
):
    plugin, _manager, context, caller = port
    called = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: called.append(True) or {},
    )

    result = caller.invoke_application_command(
        "ericsson-gitlab",
        "gitlab_retry_pipeline",
        {"project": "g/p", "pipeline_id": 42, field: False},
        mode="confirm",
        invocation_id=f"caller-{field}",
    )

    assert result == {
        "success": False,
        "error": {
            "category": "invalid_input",
            "message": "GitLab request input is invalid",
        },
    }
    assert context.configuration_calls == 0
    assert called == []


def test_provider_rejects_non_host_invocations_and_replay(port, monkeypatch):
    plugin, manager, context, caller = port
    called = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: called.append(True) or {"success": True, "result": {}},
    )
    handler = manager._application_command_providers["ericsson-gitlab"].handler

    assert (
        handler(
            SimpleNamespace(
                provider_id="ericsson-gitlab",
                caller_id="ericsson-connector-cli",
                operation="gitlab_resolve_project",
                arguments={"project": "g/p"},
                mode="read",
                active=True,
            )
        )["error"]["category"]
        == "permission"
    )
    with pytest.raises(TypeError, match="minted by Hermes"):
        PluginApplicationCommandInvocation(
            provider_id="ericsson-gitlab",
            caller_id="ericsson-connector-cli",
            operation="gitlab_resolve_project",
            arguments={"project": "g/p"},
            mode="read",
            invocation_id="direct",
            profile_fingerprint="profile",
        )

    captured = []
    real_handler = manager._application_command_providers["ericsson-gitlab"].handler

    def capture(invocation):
        captured.append(invocation)
        return real_handler(invocation)

    manager._application_command_providers["ericsson-gitlab"] = replace(
        manager._application_command_providers["ericsson-gitlab"],
        handler=capture,
    )
    caller.invoke_application_command(
        "ericsson-gitlab",
        "gitlab_resolve_project",
        {"project": "g/p"},
        mode="read",
        invocation_id="capture",
    )
    replay = real_handler(captured[0])

    assert replay["error"]["category"] == "permission"
    assert len(called) == 1
    assert context.configuration_calls == 1


def test_host_refuses_cross_caller_operation_and_mode(port):
    _plugin, manager, context, caller = port
    outsider = PluginContext(
        PluginManifest(name="Outsider", key="outside-cli"), manager
    )

    with pytest.raises(PluginApplicationCommandDenied):
        outsider.invoke_application_command(
            "ericsson-gitlab",
            "gitlab_resolve_project",
            {"project": "g/p"},
            mode="read",
            invocation_id="outsider",
        )
    with pytest.raises(PluginApplicationCommandInvalid):
        caller.invoke_application_command(
            "ericsson-gitlab",
            "gitlab_not_real",
            {},
            mode="read",
            invocation_id="operation",
        )
    with pytest.raises(PluginApplicationCommandUnavailable):
        caller.invoke_application_command(
            "ericsson-jira",
            "gitlab_resolve_project",
            {"project": "g/p"},
            mode="read",
            invocation_id="provider",
        )
    with pytest.raises(PluginApplicationCommandDenied):
        caller.invoke_application_command(
            "ericsson-gitlab",
            "gitlab_retry_pipeline",
            {"project": "g/p", "pipeline_id": 42},
            mode="read",
            invocation_id="mode",
        )
    assert context.configuration_calls == 0


def test_configuration_failure_is_safe_and_resolved_once_per_call(monkeypatch):
    plugin = _load_plugin()
    manager = PluginManager()
    context = TestContext(manager, failure=RuntimeError("secret configuration text"))
    for name in plugin.gitlab_tools.SCHEMAS:
        registry.deregister(name)
    try:
        plugin.register(context)
        caller = PluginContext(
            PluginManifest(name="Connector CLI", key="ericsson-connector-cli"),
            manager,
        )
        _patch_snapshot(monkeypatch)

        direct = caller.invoke_application_command(
            "ericsson-gitlab",
            "gitlab_resolve_project",
            {"project": "g/p"},
            mode="read",
            invocation_id="configuration",
        )
        model = json.loads(
            registry.dispatch("gitlab_resolve_project", {"project": "g/p"})
        )

        expected = {
            "success": False,
            "error": {
                "category": "invalid_configuration",
                "message": "GitLab configuration is invalid",
            },
        }
        assert direct == model == expected
        assert "secret" not in json.dumps(direct)
        assert context.configuration_calls == 2
    finally:
        for name in plugin.gitlab_tools.SCHEMAS:
            registry.deregister(name)


@pytest.mark.parametrize(
    ("failure", "category", "remediation"),
    [
        ("invalid", "invalid_input", None),
        ("gitlab", "authentication", "shared"),
        ("unsafe-remediation", "authentication", None),
        ("ambiguous", "write_ambiguous", None),
        ("connector", "transient", None),
        ("unexpected", "transient", None),
    ],
)
def test_application_executor_returns_only_safe_classified_envelopes(
    port, monkeypatch, failure, category, remediation
):
    plugin, _manager, context, _caller = port
    shared_remediation = plugin.application.remediation_for("authentication", "gitlab")
    connector_error = importlib.import_module(
        f"{plugin.__name__}._common.errors"
    ).ConnectorError

    def invoke(*args, **kwargs):
        if failure == "invalid":
            raise ValueError("raw invalid text")
        if failure == "gitlab":
            raise plugin.GitLabError("authentication", remediation=shared_remediation)
        if failure == "unsafe-remediation":
            raise plugin.GitLabError(
                "authentication", remediation="secret caller-controlled remediation"
            )
        if failure == "ambiguous":
            raise plugin.GitLabError("write_ambiguous")
        if failure == "connector":
            raise connector_error(
                "authentication", service="gitlab", detail="private connector text"
            )
        raise RuntimeError("secret unexpected text")

    monkeypatch.setattr(plugin.gitlab_tools, "invoke", invoke)
    result = plugin.application.execute(
        "gitlab_resolve_project",
        {"project": "g/p"},
        context.configuration_value,
        cancel_check=lambda: False,
    )

    assert result["success"] is False
    assert result["error"]["category"] == category
    assert result["error"]["message"] == plugin.SAFE_ERROR_MESSAGES[category]
    expected_remediation = shared_remediation if remediation == "shared" else None
    assert result["error"].get("remediation") == expected_remediation
    encoded = json.dumps(result)
    assert "raw invalid" not in encoded
    assert "secret" not in encoded
    assert "private connector" not in encoded
    assert "ConnectorError" not in encoded
    assert "Configuration" not in encoded


def test_host_never_serializes_or_passes_authority_objects_to_executor(port, monkeypatch):
    plugin, _manager, _context, caller = port
    seen = []

    def execute(name, arguments, configuration, **kwargs):
        seen.append((arguments, configuration, kwargs))
        return {"success": True, "result": arguments}

    monkeypatch.setattr(plugin.application, "execute", execute)
    result = caller.invoke_application_command(
        "ericsson-gitlab",
        "gitlab_resolve_project",
        {"project": "g/p"},
        mode="read",
        invocation_id="authority-separation",
    )

    assert result == {"success": True, "result": {"project": "g/p"}}
    arguments, _configuration, options = seen[0]
    assert arguments == {"project": "g/p"}
    assert set(options) == {"cancel_check"}
    assert not any(
        isinstance(value, PluginApplicationCommandInvocation)
        for value in (*arguments.values(), *options.values())
    )


def test_malformed_approval_arguments_fail_closed_without_raising(port):
    plugin, manager, context, _caller = port
    hook = manager._hooks["pre_tool_call"][0]
    cyclic = {"project": "g/p"}
    cyclic["nested"] = cyclic

    result = hook("gitlab_create_merge_request", cyclic)

    assert result == {
        "action": "block",
        "message": "GitLab write arguments cannot be safely approved",
    }
    assert context.configuration_calls == 0


def test_over_budget_approval_payload_blocks_before_config_or_execution(
    port, monkeypatch
):
    plugin, manager, context, _caller = port
    executed = []
    monkeypatch.setattr(
        plugin.application,
        "execute",
        lambda *args, **kwargs: executed.append(True) or {},
    )
    hook = manager._hooks["pre_tool_call"][0]
    arguments = {
        "project": "g/p",
        "branch": "main",
        "commit_message": "bounded",
        "actions": [
            {
                "action": "update",
                "file_path": "bounded.txt",
                "content": "x" * (8 * 1024 * 1024 + 1),
            }
        ],
    }

    result = hook("gitlab_commit_changes", arguments)

    assert result == {
        "action": "block",
        "message": "GitLab write arguments cannot be safely approved",
    }
    assert context.configuration_calls == 0
    assert executed == []


def test_maximum_operation_valid_commit_payload_can_bind_approval(port):
    plugin, manager, context, _caller = port
    hook = manager._hooks["pre_tool_call"][0]

    def maximum_escaped_path(index: int) -> str:
        prefix = f"{index:03d}/"
        return prefix + "\x01" * (4096 - len(prefix))

    arguments = {
        "project": "g/p",
        "branch": "main",
        "commit_message": "bounded",
        "actions": [
            {
                "action": "update",
                "file_path": maximum_escaped_path(0),
                "content": "\x01" * (512 * 1024),
            },
            *[
                {
                    "action": "delete",
                    "file_path": maximum_escaped_path(index),
                }
                for index in range(1, 100)
            ],
        ],
    }
    normalized, projected = plugin.gitlab_tools.GitLabOperations._commit_actions(
        arguments["actions"]
    )

    result = hook("gitlab_commit_changes", arguments)

    assert len(normalized) == len(projected) == 100
    assert result["action"] == "approve"
    assert result["rule_key"].startswith("gitlab_commit_changes:")
    assert len(result["rule_key"].removeprefix("gitlab_commit_changes:")) == 64
    assert len(result["message"]) <= 512
    assert context.configuration_calls == 0
