"""The Confluence connector must be registered and loadable."""

import importlib.util
import json
import sys
import types
import uuid
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-confluence"


def _load_models_module():
    module_name = "ericsson_confluence_manifest_models"
    spec = importlib.util.spec_from_file_location(module_name, PLUGIN / "models.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        sys.modules.pop(module_name, None)
    return module


def _load_tools_module():
    module_name = "ericsson_confluence_manifest_tools"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN / "tools.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)
    finally:
        for loaded_name in tuple(sys.modules):
            if loaded_name == module_name or loaded_name.startswith(module_name + "."):
                sys.modules.pop(loaded_name, None)
    return module


def _load_plugin_package():
    module_name = f"ericsson_confluence_manifest_plugin_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module_name, module


def _unload_package(module_name):
    for loaded_name in tuple(sys.modules):
        if loaded_name == module_name or loaded_name.startswith(module_name + "."):
            sys.modules.pop(loaded_name, None)


class TestManifest:
    def test_plugin_directory_exists(self):
        assert PLUGIN.is_dir()
        assert (PLUGIN / "plugin.yaml").is_file()
        assert (PLUGIN / "__init__.py").is_file()

    def test_declared_in_the_capability_set(self):
        entries = json.loads((REPO / "sets" / "ericsson.json").read_text())["plugins"]
        matches = [
            entry
            for entry in entries
            if type(entry) is dict and entry.get("id") == "ericsson-confluence"
        ]
        assert len(matches) == 1
        assert matches[0]["path"] == "plugins/ericsson-confluence"

    def test_disabled_by_default(self):
        entries = json.loads((REPO / "sets" / "ericsson.json").read_text())["plugins"]
        entry = next(
            item
            for item in entries
            if type(item) is dict and item.get("id") == "ericsson-confluence"
        )
        assert entry["enabled"] is False

    def test_manifest_declares_a_config_schema(self):
        manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text())
        assert manifest["kind"] == "standalone"
        assert manifest["config_schema"] == "config.schema.json"

    def test_token_is_secret_storage(self):
        schema = json.loads((PLUGIN / "config.schema.json").read_text())
        pat = next(field for field in schema["fields"] if field["id"] == "pat")
        assert pat["storage"] == "secret"

    def test_shared_code_is_vendored(self):
        assert (PLUGIN / "_common" / "client.py").is_file(), (
            "run: python scripts/sync_shared.py"
        )


class TestErrors:
    def test_unknown_category_coerces_to_transient(self):
        models = _load_models_module()
        assert models.ConfluenceError("not-a-real-category").category == "transient"

    def test_non_string_category_coerces_to_transient(self):
        models = _load_models_module()
        assert models.ConfluenceError(["authentication"]).category == "transient"

    def test_remediation_only_keeps_connector_owned_guidance(self):
        models = _load_models_module()
        assert models.ConfluenceError(
            "authentication", remediation="token=remote-secret"
        ).remediation is None
        assert models.ConfluenceError(
            "authentication", remediation="Update the Confluence token."
        ).remediation == "Update the Confluence token."

    def test_categories_the_shared_client_raises_are_all_known(self):
        """Unknown categories silently coerce to transient and lose their signal."""
        models = _load_models_module()

        for category in (
            "conflict",
            "confirmation_required",
            "write_ambiguous",
            "circuit_open",
            "capacity",
            "deadline",
            "cancelled",
        ):
            assert category in models.SAFE_ERROR_MESSAGES, category

    def test_unique_loader_does_not_replace_a_foreign_models_module(self, monkeypatch):
        foreign = types.ModuleType("models")
        monkeypatch.setitem(sys.modules, "models", foreign)

        models = _load_models_module()

        assert models.ConfluenceError("authentication").category == "authentication"
        assert sys.modules["models"] is foreign


class _HookContext:
    def __init__(self):
        self.event_name = None
        self.hook = None

    def register_hook(self, event_name, hook):
        self.event_name = event_name
        self.hook = hook


def _load_plugin_module():
    spec = importlib.util.spec_from_file_location(
        "confluence_task_one_plugin", PLUGIN / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_unknown_write_hook_ignores_untrusted_arguments():
    """Unknown tools never serialize or render their untrusted arguments."""
    plugin = _load_plugin_module()
    ctx = _HookContext()
    recursive = {}
    recursive["loop"] = recursive

    plugin.register(ctx)

    assert ctx.event_name == "pre_tool_call"
    assert ctx.hook("future_confluence_write", recursive) is None


def test_write_contracts_match_the_declared_mutating_tools():
    plugin = _load_plugin_module()
    tools = _load_tools_module()
    declared = set(yaml.safe_load((PLUGIN / "plugin.yaml").read_text())["provides_tools"])

    writes = plugin._WRITE_TOOLS
    assert writes == set(plugin.WRITE_APPROVALS)
    assert writes <= declared
    assert "confluence_create_page" in writes
    assert "confluence_update_page" in writes
    assert "confluence_add_comment" in writes
    assert len(writes) == 3

    mutating = {
        name
        for name, schema in tools.SCHEMAS.items()
        if "confirm" in schema["parameters"]["properties"]
    }
    assert mutating == writes


class _ToolContext:
    def __init__(self):
        self.hooks = {}
        self.tools = {}
        self.configuration_calls = 0

    def configuration(self):
        self.configuration_calls += 1
        return object()

    def register_hook(self, event_name, hook):
        self.hooks[event_name] = hook

    def register_tool(self, *, name, handler, **_kwargs):
        self.tools[name] = handler


def test_create_handler_requires_an_exact_host_admission(monkeypatch):
    """Pre-tool approval is advisory unless the write handler rechecks it."""
    module_name, plugin = _load_plugin_package()
    try:
        ctx = _ToolContext()
        plugin.register(ctx)
        invoked = []
        tools = sys.modules[module_name + ".tools"]
        monkeypatch.setattr(
            tools,
            "invoke",
            lambda *args: invoked.append(args) or {"ok": True},
        )
        handler = ctx.tools["confluence_create_page"]
        arguments = {"space_key": "OPS", "title": "T", "markdown": "B", "confirm": True}

        missing = json.loads(handler(arguments))
        assert missing["success"] is False
        assert missing["error"]["category"] == "permission"

        denied = (
            types.SimpleNamespace(
                approved=True,
                policy="plugin_approve",
                tool_name="confluence_get_page",
            ),
            types.SimpleNamespace(
                approved=True,
                policy="other_policy",
                tool_name="confluence_create_page",
            ),
        )
        for admission in denied:
            payload = json.loads(handler(arguments, tool_admission=admission))
            assert payload["success"] is False
            assert payload["error"]["category"] == "permission"
        assert invoked == []
        assert ctx.configuration_calls == 0

        allowed = types.SimpleNamespace(
            approved=True,
            policy="plugin_approve",
            tool_name="confluence_create_page",
        )
        payload = json.loads(handler(arguments, tool_admission=allowed))
        assert payload == {"success": True, "result": {"ok": True}}
        assert len(invoked) == 1
        assert ctx.configuration_calls == 1
    finally:
        _unload_package(module_name)


def test_update_handler_rejects_admission_for_another_write(monkeypatch):
    module_name, plugin = _load_plugin_package()
    try:
        ctx = _ToolContext()
        plugin.register(ctx)
        invoked = []
        tools = sys.modules[module_name + ".tools"]
        monkeypatch.setattr(
            tools,
            "invoke",
            lambda *args: invoked.append(args) or {"ok": True},
        )
        handler = ctx.tools["confluence_update_page"]
        arguments = {"content_id": "12345", "markdown": "B", "confirm": True}

        wrong = types.SimpleNamespace(
            approved=True,
            policy="plugin_approve",
            tool_name="confluence_create_page",
        )
        payload = json.loads(handler(arguments, tool_admission=wrong))
        assert payload["success"] is False
        assert payload["error"]["category"] == "permission"
        assert invoked == []
        assert ctx.configuration_calls == 0

        allowed = types.SimpleNamespace(
            approved=True,
            policy="plugin_approve",
            tool_name="confluence_update_page",
        )
        payload = json.loads(handler(arguments, tool_admission=allowed))
        assert payload == {"success": True, "result": {"ok": True}}
        assert len(invoked) == 1
    finally:
        _unload_package(module_name)


def test_add_comment_handler_rejects_admission_for_another_write(monkeypatch):
    module_name, plugin = _load_plugin_package()
    try:
        ctx = _ToolContext()
        plugin.register(ctx)
        invoked = []
        tools = sys.modules[module_name + ".tools"]
        monkeypatch.setattr(
            tools,
            "invoke",
            lambda *args: invoked.append(args) or {"ok": True},
        )
        handler = ctx.tools["confluence_add_comment"]
        arguments = {"content_id": "12345", "markdown": "Noted", "confirm": True}

        wrong = types.SimpleNamespace(
            approved=True,
            policy="plugin_approve",
            tool_name="confluence_update_page",
        )
        payload = json.loads(handler(arguments, tool_admission=wrong))
        assert payload["success"] is False
        assert payload["error"]["category"] == "permission"
        assert invoked == []
        assert ctx.configuration_calls == 0

        allowed = types.SimpleNamespace(
            approved=True,
            policy="plugin_approve",
            tool_name="confluence_add_comment",
        )
        payload = json.loads(handler(arguments, tool_admission=allowed))
        assert payload == {"success": True, "result": {"ok": True}}
        assert len(invoked) == 1
    finally:
        _unload_package(module_name)


def test_add_comment_approval_is_argument_scoped():
    plugin = _load_plugin_module()
    ctx = _HookContext()
    plugin.register(ctx)

    first = ctx.hook(
        "confluence_add_comment", {"content_id": "12345", "markdown": "One"}
    )
    same = ctx.hook(
        "confluence_add_comment", {"markdown": "One", "content_id": "12345"}
    )
    second = ctx.hook(
        "confluence_add_comment", {"content_id": "12345", "markdown": "Two"}
    )

    assert first["rule_key"].startswith("confluence_add_comment:")
    assert first["rule_key"] == same["rule_key"]
    assert first["rule_key"] != second["rule_key"]
