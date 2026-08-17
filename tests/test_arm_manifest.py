"""The ARM connector must be registered and loadable."""

import importlib.util
import json
import sys
import types
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-arm"


def _load_models_module():
    module_name = "ericsson_arm_manifest_models"
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
            if type(entry) is dict and entry.get("id") == "ericsson-arm"
        ]
        assert len(matches) == 1
        assert matches[0]["path"] == "plugins/ericsson-arm"

    def test_disabled_by_default(self):
        entries = json.loads((REPO / "sets" / "ericsson.json").read_text())["plugins"]
        entry = next(
            item
            for item in entries
            if type(item) is dict and item.get("id") == "ericsson-arm"
        )
        assert entry["enabled"] is False

    def test_manifest_declares_a_config_schema(self):
        manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text())
        assert manifest["kind"] == "standalone"
        assert manifest["config_schema"] == "config.schema.json"

    def test_token_is_secret_storage(self):
        schema = json.loads((PLUGIN / "config.schema.json").read_text())
        token = next(field for field in schema["fields"] if field["id"] == "token")
        assert token["storage"] == "secret"

    def test_auth_mode_offers_both_header_schemes(self):
        """The unresolved JFrog header choice remains explicit configuration."""
        schema = json.loads((PLUGIN / "config.schema.json").read_text())
        mode = next(field for field in schema["fields"] if field["id"] == "auth_mode")
        assert set(mode["validation"]["enum"]) == {"bearer", "api_key"}
        assert mode["default"] == "bearer"

    def test_client_certificate_paths_are_settings_not_secrets(self):
        schema = json.loads((PLUGIN / "config.schema.json").read_text())
        fields = {field["id"]: field for field in schema["fields"]}
        assert fields["client_cert_path"]["storage"] == "setting"
        assert fields["client_key_path"]["storage"] == "setting"

    def test_shared_code_is_vendored(self):
        assert (PLUGIN / "_common" / "client.py").is_file(), (
            "run: python scripts/sync_shared.py"
        )


class TestErrors:
    def test_unknown_category_coerces_to_transient(self):
        models = _load_models_module()
        assert models.ArmError("not-a-real-category").category == "transient"

    def test_non_string_category_coerces_to_transient(self):
        models = _load_models_module()
        assert models.ArmError(["authentication"]).category == "transient"

    def test_remediation_only_keeps_connector_owned_guidance(self):
        models = _load_models_module()
        assert models.ArmError(
            "authentication", remediation="token=remote-secret"
        ).remediation is None
        assert models.ArmError(
            "authentication", remediation="Update the Artifactory token."
        ).remediation == "Update the Artifactory token."

    def test_client_static_remediations_preserve_only_exact_owned_literals(self):
        models = _load_models_module()
        access_guidance = (
            "Access to this Artifactory was refused at the edge, before the request "
            "reached Artifactory. This is normally an expired or missing mTLS client "
            "certificate rather than a problem with the Artifactory token. Check the "
            "client certificate and key configured for this profile."
        )
        assert models.ArmError(
            "edge_authentication", remediation=access_guidance
        ).remediation == access_guidance
        assert models.ArmError(
            "authentication", remediation=(
                "The arm token is missing, expired, or invalid. Update the arm "
                "personal access token in the connector's configuration."
            ),
        ).remediation
        assert models.ArmError(
            "edge_authentication", remediation=f"{access_guidance} token=secret"
        ).remediation is None

    def test_certificate_expiry_remediation_accepts_only_a_strict_owned_date(self):
        models = _load_models_module()
        remediation = models.certificate_expiry_remediation("2026-03-21")

        assert models.ArmError(
            "certificate_invalid", remediation=remediation
        ).remediation == (
            "The client certificate expired on 2026-03-21. Renew it and update "
            "the certificate and key paths in this profile. Until then every "
            "request is refused at the edge before it reaches Artifactory."
        )
        for unsafe_date in (
            "2026-3-21",
            "2026-03-21 token=remote-secret",
            "../../2026-03-21",
            "not-a-date",
        ):
            assert models.certificate_expiry_remediation(unsafe_date) is None
        assert models.ArmError(
            "certificate_invalid",
            remediation="The client certificate expired on 2026-03-21 token=remote-secret.",
        ).remediation is None

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

    def test_arm_specific_categories_exist(self):
        models = _load_models_module()

        for category in ("edge_authentication", "certificate_invalid"):
            assert category in models.SAFE_ERROR_MESSAGES, category

    def test_edge_authentication_is_distinct_from_authentication(self):
        models = _load_models_module()

        assert (
            models.SAFE_ERROR_MESSAGES["edge_authentication"]
            != models.SAFE_ERROR_MESSAGES["authentication"]
        )

    def test_unique_loader_does_not_replace_a_foreign_models_module(self, monkeypatch):
        foreign = types.ModuleType("models")
        monkeypatch.setitem(sys.modules, "models", foreign)

        models = _load_models_module()

        assert models.ArmError("authentication").category == "authentication"
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
        "arm_task_one_plugin", PLUGIN / "__init__.py"
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_empty_write_approval_hook_ignores_untrusted_arguments():
    """Task 1 has no writes, so no input may be serialized by the hook."""
    plugin = _load_plugin_module()
    ctx = _HookContext()
    recursive = {}
    recursive["loop"] = recursive

    plugin.register(ctx)

    assert ctx.event_name == "pre_tool_call"
    assert ctx.hook("future_arm_write", recursive) is None
