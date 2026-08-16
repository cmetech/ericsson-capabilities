"""The Confluence connector must be registered and loadable."""

import importlib.util
import json
import sys
import types
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


def test_empty_write_approval_hook_ignores_untrusted_arguments():
    """Task 1 has no writes, so no input should be serialized by the hook."""
    plugin = _load_plugin_module()
    ctx = _HookContext()
    recursive = {}
    recursive["loop"] = recursive

    plugin.register(ctx)

    assert ctx.event_name == "pre_tool_call"
    assert ctx.hook("future_confluence_write", recursive) is None


def test_write_contracts_are_empty_until_tools_exist():
    plugin = _load_plugin_module()

    assert plugin._WRITE_TOOLS == frozenset()
    assert plugin.WRITE_APPROVALS == {}
