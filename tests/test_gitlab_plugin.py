from __future__ import annotations

import ast
import importlib.util
import json
import sys
import types
import uuid
from pathlib import Path

import httpx
import pytest
import respx
import yaml


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-gitlab"
EXPECTED_TOOLS = {
    "gitlab_resolve_project",
    "gitlab_list_repository_tree",
    "gitlab_read_file",
    "gitlab_read_merge_request",
    "gitlab_list_pipelines",
}


def _load_plugin():
    assert PLUGIN.is_dir(), "Task 8 GitLab plugin production surface is missing"
    module_name = f"ericsson_gitlab_task8_test_{uuid.uuid4().hex}"
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


def test_plugin_package_does_not_resolve_internal_modules_from_process_globals(monkeypatch):
    # GL-AUTH-03 legacy: ericsson_gitlab/README.md:Requirements
    for name in ("auth", "client", "models", "operations", "tools"):
        monkeypatch.setitem(sys.modules, name, types.ModuleType(name))
    monkeypatch.setattr(sys, "path", [entry for entry in sys.path if entry != str(PLUGIN)])
    path_before = tuple(sys.path)
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    assert set(context.registrations) == EXPECTED_TOOLS
    assert tuple(sys.path) == path_before


class Configuration:
    def setting(self, field_id):
        return {
            "origin": "https://gitlab.example.test",
            "client_certificate_path": "",
            "client_key_path": "",
        }[field_id]

    def secret(self, field_id):
        assert field_id == "pat"
        return "secret-pat"


class Context:
    def __init__(self):
        self.registrations = {}
        self.configuration_calls = 0

    def configuration(self):
        self.configuration_calls += 1
        return Configuration()

    def register_tool(self, **registration):
        self.registrations[registration["name"]] = registration


def test_descriptor_is_standalone_static_and_declares_only_current_read_tools():
    # GL-AUTH-03/GL-REVIEW-03 legacy: ericsson_gitlab/README.md:Requirements; ericsson_gitlab/__init__.py:__all__
    _load_plugin()
    manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
    descriptor = json.loads((PLUGIN / "config.schema.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "ericsson-gitlab"
    assert manifest["kind"] == "standalone"
    assert manifest["config_schema"] == "config.schema.json"
    assert set(manifest["provides_tools"]) == EXPECTED_TOOLS
    assert {field["id"] for field in descriptor["fields"]} == {
        "origin",
        "pat",
        "client_certificate_path",
        "client_key_path",
    }
    by_id = {field["id"]: field for field in descriptor["fields"]}
    assert by_id["origin"]["storage"] == "setting"
    assert by_id["pat"]["storage"] == "secret"
    assert by_id["origin"]["readiness"] is True
    assert by_id["pat"]["readiness"] is True
    assert all(
        field.get("validation", {}).get("max_length", 4096) <= 4096
        for field in descriptor["fields"]
    )
    assert "enabled" not in descriptor


def test_register_exposes_exact_five_json_native_bounded_schemas():
    # GL-READ-07/08 legacy: gitlab_file_reader.py:read_files
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    assert set(context.registrations) == EXPECTED_TOOLS
    assert {registration["toolset"] for registration in context.registrations.values()} == {"ericsson-gitlab"}
    for name, registration in context.registrations.items():
        schema = registration["schema"]
        assert schema["name"] == name
        assert schema["parameters"]["type"] == "object"
        assert schema["parameters"]["additionalProperties"] is False


def test_handler_resolves_fresh_host_configuration_on_every_invocation_and_never_accepts_pat():
    # GL-AUTH-01 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    handler = context.registrations["gitlab_resolve_project"]["handler"]
    schema = context.registrations["gitlab_resolve_project"]["schema"]
    assert "pat" not in schema["parameters"]["properties"]
    assert "token" not in schema["parameters"]["properties"]

    with respx.mock:
        route = respx.get("https://gitlab.example.test/api/v4/projects/42")
        route.side_effect = [
            httpx.Response(200, json={"id": 42, "name": "repo", "path_with_namespace": "g/repo", "default_branch": "main", "web_url": "https://gitlab.example.test/g/repo", "namespace": {"kind": "group"}}),
            httpx.Response(200, json={"id": 42, "name": "repo", "path_with_namespace": "g/repo", "default_branch": "main", "web_url": "https://gitlab.example.test/g/repo", "namespace": {"kind": "group"}}),
        ]
        first = json.loads(handler({"project": "42"}))
        second = json.loads(handler({"project": "42"}))
    assert first["success"] is True and second["success"] is True
    assert context.configuration_calls == 2


def test_plugin_error_wrapper_returns_fixed_safe_category_without_remote_or_secret_text():
    # GL-AUTH-01/GL-READ-03 legacy: GitLab session helpers and file response errors
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    handler = context.registrations["gitlab_resolve_project"]["handler"]
    with respx.mock:
        respx.get("https://gitlab.example.test/api/v4/projects/42").mock(
            return_value=httpx.Response(401, text="remote secret-pat diagnostic")
        )
        result = json.loads(handler({"project": "42"}))
    assert result["success"] is False
    assert result["error"]["category"] == "authentication"
    assert result["error"]["message"] == "GitLab authentication failed"
    assert "secret-pat" not in repr(result)
    assert "remote" not in repr(result)


def test_plugin_configuration_lookup_failure_is_stable_and_classified():
    # GL-AUTH-01 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    plugin = _load_plugin()

    class UnconfiguredContext(Context):
        def configuration(self):
            self.configuration_calls += 1
            raise RuntimeError("profile path and credential sentinel")

    context = UnconfiguredContext()
    plugin.register(context)
    result = json.loads(
        context.registrations["gitlab_resolve_project"]["handler"]({"project": "42"})
    )
    assert result == {
        "success": False,
        "error": {
            "category": "invalid_configuration",
            "message": "GitLab configuration is invalid",
        },
    }


def test_direct_handlers_reject_unknown_and_missing_schema_arguments_before_transport():
    # GL-READ-07 legacy: gitlab_file_reader.py:read_files
    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    handler = context.registrations["gitlab_resolve_project"]["handler"]
    for arguments in (
        {"project": "42", "pat": "caller-authored-secret"},
        {},
    ):
        result = json.loads(handler(arguments))
        assert result == {
            "success": False,
            "error": {
                "category": "invalid_input",
                "message": "GitLab request input is invalid",
            },
        }


def test_plugin_source_has_no_local_checkout_subprocess_llm_or_process_env_transport():
    # GL-AUTH-03/GL-READ-08 legacy: ericsson_gitlab/README.md:Requirements; gitlab_file_reader.py:read_files
    _load_plugin()
    forbidden_modules = {
        "subprocess", "git", "glab", "langchain", "ollama", "openai",
        "anthropic", "dotenv",
    }
    for path in sorted(PLUGIN.glob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        imports = set()
        names = set()
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                imports.update(alias.name.split(".", 1)[0] for alias in node.names)
            elif isinstance(node, ast.ImportFrom) and node.module:
                imports.add(node.module.split(".", 1)[0])
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.Name):
                names.add(node.id)
            elif (
                isinstance(node, ast.Attribute)
                and isinstance(node.value, ast.Name)
                and node.value.id == "os"
                and node.attr == "environ"
            ):
                pytest.fail(f"{path.name} reads process-global os.environ")
        assert imports.isdisjoint(forbidden_modules)
        assert "_secret_storage_key" not in names
        assert "PluginConfigurationService" not in names
