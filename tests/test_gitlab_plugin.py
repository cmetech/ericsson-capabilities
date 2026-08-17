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
    "gitlab_list_group_projects",
    "gitlab_list_commits",
    "gitlab_read_commit",
    "gitlab_list_commit_comments",
    "gitlab_list_commit_discussions",
    "gitlab_list_merge_requests",
    "gitlab_list_merge_request_commits",
    "gitlab_list_merge_request_discussions",
    "gitlab_list_repository_tree",
    "gitlab_read_file",
    "gitlab_read_merge_request",
    "gitlab_list_pipelines",
    "gitlab_inspect_ci",
    "gitlab_job_log",
    "gitlab_create_branch",
    "gitlab_commit_changes",
    "gitlab_create_merge_request",
    "gitlab_create_mr_note",
    "gitlab_reply_to_discussion",
    "gitlab_resolve_discussion",
    "gitlab_merge_request_approvals",
    "gitlab_approve_merge_request",
    "gitlab_merge_merge_request",
    "gitlab_update_merge_request",
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
        self.hooks = {}
        self.configuration_calls = 0

    def configuration(self):
        self.configuration_calls += 1
        return Configuration()

    def register_tool(self, **registration):
        self.registrations[registration["name"]] = registration

    def register_hook(self, name, callback):
        self.hooks[name] = callback


def test_descriptor_is_standalone_static_and_declares_exact_current_tools():
    # GL-AUTH-03/GL-REVIEW-03 legacy: ericsson_gitlab/README.md:Requirements; ericsson_gitlab/__init__.py:__all__
    _load_plugin()
    manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
    descriptor = json.loads((PLUGIN / "config.schema.json").read_text(encoding="utf-8"))
    assert manifest["name"] == "ericsson-gitlab"
    assert manifest["kind"] == "standalone"
    assert manifest["config_schema"] == "config.schema.json"
    assert len(EXPECTED_TOOLS) == 25
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


def test_register_exposes_exact_json_native_bounded_schemas():
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


def test_every_schema_registration_binds_its_matching_tool_handler(monkeypatch):
    # GL-CI-11 replacement: gitlab_cicd_collector.py:_collect_all and output methods
    plugin = _load_plugin()
    invoked = []

    def invoke(name, args, configuration, **options):
        invoked.append(name)
        return {"invoked": name}

    monkeypatch.setattr(plugin.gitlab_tools, "invoke", invoke)
    context = Context()
    plugin.register(context)

    for name in sorted(plugin.gitlab_tools.SCHEMAS):
        kwargs = {}
        if name in {
            "gitlab_create_branch",
            "gitlab_commit_changes",
            "gitlab_create_merge_request",
            "gitlab_create_mr_note",
            "gitlab_reply_to_discussion",
            "gitlab_resolve_discussion",
            "gitlab_approve_merge_request",
            "gitlab_merge_merge_request",
            "gitlab_update_merge_request",
        }:
            kwargs["tool_admission"] = types.SimpleNamespace(
                approved=True,
                policy="plugin_approve",
                tool_name=name,
            )
        result = json.loads(context.registrations[name]["handler"]({}, **kwargs))
        assert result == {"success": True, "result": {"invoked": name}}
    assert invoked == sorted(plugin.gitlab_tools.SCHEMAS)


def test_approve_merge_request_requires_argument_specific_write_admission(monkeypatch):
    plugin = _load_plugin()
    invoked = []

    def invoke(name, args, configuration, **options):
        invoked.append((name, args))
        return {"invoked": name}

    monkeypatch.setattr(plugin.gitlab_tools, "invoke", invoke)
    context = Context()
    plugin.register(context)
    handler = context.registrations["gitlab_approve_merge_request"]["handler"]
    arguments = {"project": "g/p", "iid": 42, "sha": "a" * 40, "confirm": True}

    denied = json.loads(handler(arguments))
    assert denied["error"]["category"] == "permission"
    assert invoked == []

    approval = context.hooks["pre_tool_call"](
        "gitlab_approve_merge_request", arguments
    )
    changed_approval = context.hooks["pre_tool_call"](
        "gitlab_approve_merge_request", {**arguments, "iid": 43}
    )
    assert approval["action"] == "approve"
    assert approval["rule_key"] != changed_approval["rule_key"]
    assert "Approve MR: !42" in approval["message"]

    admitted = json.loads(
        handler(
            arguments,
            tool_admission=types.SimpleNamespace(
                approved=True,
                policy="plugin_approve",
                tool_name="gitlab_approve_merge_request",
            ),
        )
    )
    assert admitted == {
        "success": True,
        "result": {"invoked": "gitlab_approve_merge_request"},
    }
    assert invoked == [("gitlab_approve_merge_request", arguments)]


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


@pytest.mark.parametrize("pem_case", ["malformed", "mismatched"])
def test_malformed_or_mismatched_mtls_is_unavailable_and_handler_reports_invalid_configuration(
    tmp_path, pem_case
):
    # GL-AUTH-02 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    from test_gitlab_client import (
        CERTIFICATE_PEM,
        MISMATCHED_PRIVATE_KEY_PEM,
    )

    cert = tmp_path / "private-sensitive-cert.pem"
    key = tmp_path / "private-sensitive-key.pem"
    if pem_case == "malformed":
        cert.write_text("not a certificate", encoding="ascii")
        key.write_text("not a private key", encoding="ascii")
    else:
        cert.write_text(CERTIFICATE_PEM, encoding="ascii")
        key.write_text(MISMATCHED_PRIVATE_KEY_PEM, encoding="ascii")

    class PemConfiguration(Configuration):
        def setting(self, field_id):
            if field_id == "client_certificate_path":
                return str(cert)
            if field_id == "client_key_path":
                return str(key)
            return super().setting(field_id)

    class PemContext(Context):
        def configuration(self):
            self.configuration_calls += 1
            return PemConfiguration()

    plugin = _load_plugin()
    context = PemContext()
    plugin.register(context)
    registration = context.registrations["gitlab_resolve_project"]
    assert registration["check_fn"]() is False
    result = json.loads(registration["handler"]({"project": "42"}))
    assert result == {
        "success": False,
        "error": {
            "category": "invalid_configuration",
            "message": "GitLab configuration is invalid",
        },
    }
    assert "private-sensitive" not in repr(result)


def test_registered_handler_uses_current_thread_interrupt_authority_without_sys_path_mutation(
    monkeypatch,
):
    # GL-AUTH-01 legacy: gitlab_project_resolver.py:GitLabProjectResolver.resolve_project
    interrupt_module = types.ModuleType("tools.interrupt")
    interrupt_module.is_interrupted = lambda: True
    host_tools = types.ModuleType("tools")
    host_tools.__path__ = []
    monkeypatch.setitem(sys.modules, "tools", host_tools)
    monkeypatch.setitem(sys.modules, "tools.interrupt", interrupt_module)
    path_before = tuple(sys.path)

    plugin = _load_plugin()
    context = Context()
    plugin.register(context)
    result = json.loads(
        context.registrations["gitlab_resolve_project"]["handler"]({"project": "42"})
    )

    assert result == {
        "success": False,
        "error": {
            "category": "cancelled",
            "message": "GitLab request was cancelled",
        },
    }
    assert tuple(sys.path) == path_before


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
