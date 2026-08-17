"""The ARM connector must be registered and loadable."""

import importlib.util
import hashlib
import json
import subprocess
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

    def test_aql_limit_remediation_accepts_only_the_connector_owned_literal(self):
        """Query text must never ride along in an input-validation error."""
        models = _load_models_module()
        remediation = (
            "Do not put .limit() in the query; AQL accepts only one and "
            "the connector supplies it. Use max_results instead."
        )

        assert models.ArmError(
            "invalid_input", remediation=remediation
        ).remediation == remediation
        for unsafe in (
            remediation + " query=items.find({\"repo\":\"secret\"})",
            remediation.replace("max_results", "max-results"),
            "Do not put .limit() in the query; token=remote-secret",
        ):
            assert models.ArmError("invalid_input", remediation=unsafe).remediation is None

    def test_deploy_remediations_are_exact_static_literals(self):
        """Deploy must not reflect local paths or Artifactory output."""
        models = _load_models_module()
        remediations = (
            "source_file must be an absolute path.",
            "source_file does not name a readable file.",
            (
                "This profile confines uploads to its configured deploy source "
                "root."
            ),
            (
                "The file is larger than this profile's maximum upload size. "
                "Raise it in the profile if this is expected."
            ),
            "Artifactory did not return a deploy result.",
            "Artifactory returned no checksums to verify against.",
            (
                "The sha256 checksum Artifactory reported does not match the file "
                "that was sent. Do not treat this artefact as published."
            ),
        )
        for remediation in remediations:
            assert models.ArmError(
                "invalid_remote_data", remediation=remediation
            ).remediation == remediation
            assert models.ArmError(
                "invalid_remote_data", remediation=remediation + " token=secret"
            ).remediation is None

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


def test_delete_approval_digest_binds_a_bounded_probe_source_file():
    """A generic write preview can include deploy's bounded source field."""
    plugin = _load_plugin_module()
    ctx = _HookContext()
    plugin.register(ctx)

    first = ctx.hook("arm_delete", {"repo": "r1", "path": "p1", "source_file": "/a"})
    second = ctx.hook("arm_delete", {"repo": "r2", "path": "p2", "source_file": "/b"})

    assert first["action"] == second["action"] == "approve"
    assert first["rule_key"] != second["rule_key"]


def test_delete_approval_digest_blocks_unsafe_optional_source_file():
    """Only bounded non-empty strings may enter a generic approval digest."""
    plugin = _load_plugin_module()
    ctx = _HookContext()
    plugin.register(ctx)

    for source_file in ("", "x" * 4097, 1):
        outcome = ctx.hook(
            "arm_delete",
            {"repo": "r1", "path": "p1", "source_file": source_file},
        )
        assert outcome["action"] == "block"


class _SkillContext:
    def __init__(self):
        self.skills = []

    def register_hook(self, _event_name, _hook):
        pass

    def register_tool(self, **_kwargs):
        pass

    def register_skill(self, name, path, description):
        self.skills.append((name, path, description))


def _load_skill_plugin_module():
    """Load the plugin as a package, keeping its relative imports isolated."""
    module_name = "ericsson_arm_skill_plugin"
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


def test_register_exposes_the_artifact_research_skill():
    """The plugin advertises the workflow that joins releases to GitLab."""
    plugin = _load_skill_plugin_module()
    ctx = _SkillContext()

    plugin.register(ctx)

    assert ctx.skills == [
        (
            "artifact-research",
            PLUGIN / "skills" / "artifact-research" / "SKILL.md",
            "Trace a release artefact back to the build that made it.",
        )
    ]


def test_catalog_validator_recognizes_all_arm_tool_handlers():
    """ARM's direct schema binding remains visible to catalog validation."""
    result = subprocess.run(
        [
            sys.executable,
            "skills/ericsson/onboard-ericsson-capabilities/scripts/validate_catalog.py",
            "--repo",
            str(REPO),
        ],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )

    payload = json.loads(result.stdout)
    problems = set(payload["problems"])
    arm_handler_problems = {
        problem
        for problem in problems
        if "plugins/ericsson-arm" in problem
    }
    expected_onboarding_gap = {
        f"unrepresented plugin tool: {name}"
        for name in (
            "arm_artifact_info",
            "arm_delete",
            "arm_deploy",
            "arm_get_properties",
            "arm_list_repositories",
            "arm_search_artifacts",
        )
    }

    assert arm_handler_problems == set()
    assert problems <= expected_onboarding_gap


def test_standalone_loader_keeps_foreign_generic_modules_intact(monkeypatch):
    """Synthetic ARM package imports must not replace generic siblings."""
    foreign_tools = types.ModuleType("tools")
    foreign_models = types.ModuleType("models")
    foreign_common = types.ModuleType("_common")
    monkeypatch.setitem(sys.modules, "tools", foreign_tools)
    monkeypatch.setitem(sys.modules, "models", foreign_models)
    monkeypatch.setitem(sys.modules, "_common", foreign_common)

    first = _load_plugin_module()
    second = _load_plugin_module()

    assert first is not second
    assert first.arm_tools.__name__ != "tools"
    assert second.arm_tools.__name__ != "tools"
    assert sys.modules["tools"] is foreign_tools
    assert sys.modules["models"] is foreign_models
    assert sys.modules["_common"] is foreign_common


def test_standalone_loader_does_not_reuse_a_foreign_synthetic_namespace(monkeypatch):
    """A collision receives a fresh ARM-owned namespace instead of reuse."""
    root = str(PLUGIN.resolve())
    namespace = "_ericsson_arm_standalone_" + hashlib.sha256(
        root.encode()
    ).hexdigest()[:16]
    foreign = types.ModuleType(namespace)
    foreign.__path__ = ["/foreign"]
    monkeypatch.setitem(sys.modules, namespace, foreign)

    plugin = _load_plugin_module()

    assert sys.modules[namespace] is foreign
    assert plugin.__package__ != namespace
    package = sys.modules[plugin.__package__]
    assert package._ericsson_arm_root == root
