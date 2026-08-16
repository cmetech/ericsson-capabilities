import json
import importlib.util
import sys
import uuid
from pathlib import Path

import httpx
import pytest
import respx
import yaml

from jira_test_support import jira_tools

REPO = Path(__file__).resolve().parents[1]
BASE = "https://jira.internal.ericsson.com"


def test_descriptor_is_standalone_and_preserves_stable_public_identity():
    manifest = yaml.safe_load(
        (REPO / "plugins" / "ericsson-jira" / "plugin.yaml").read_text(
            encoding="utf-8"
        )
    )
    descriptor = json.loads(
        (REPO / "plugins" / "ericsson-jira" / "config.schema.json").read_text(
            encoding="utf-8"
        )
    )

    assert manifest["name"] == "ericsson-jira"
    assert manifest["kind"] == "standalone"
    assert manifest["config_schema"] == "config.schema.json"
    assert manifest["provides_tools"] == [
        "jira_my_tickets",
        "jira_search_issues",
        "jira_get_issue",
        "jira_add_comment",
        "jira_list_fields",
        "jira_get_project",
        "jira_list_transitions",
        "jira_search_assignable_users",
        "jira_transition_issue",
        "jira_assign_issue",
        "jira_update_fields",
    ]
    assert "requires_env" not in manifest
    assert {field["id"] for field in descriptor["fields"]} >= {
        "base_url",
        "auth_mode",
        "pat",
        "email",
        "api_token",
        "rest_api_version",
        "transport",
        "curl_executable",
        "request_timeout_seconds",
        "default_max_results",
    }


@pytest.fixture
def configuration():
    return Configuration()


class Configuration:
    def setting(self, field_id):
        return {
            "base_url": BASE,
            "auth_mode": "bearer",
            "rest_api_version": "2",
            "transport": "native",
            "curl_executable": "/usr/bin/curl",
            "request_timeout_seconds": 30,
            "default_max_results": 25,
        }[field_id]

    def secret(self, field_id):
        return {"pat": "tok", "api_token": ""}[field_id]


class Context:
    def __init__(self):
        self.registrations = {}
        self.configuration_calls = 0

    def configuration(self):
        self.configuration_calls += 1
        return Configuration()

    def register_tool(self, **registration):
        self.registrations[registration["name"]] = registration

    def register_hook(self, name, callback):
        pass


def _load_plugin():
    module_name = f"ericsson_jira_task3_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        REPO / "plugins" / "ericsson-jira" / "__init__.py",
        submodule_search_locations=[str(REPO / "plugins" / "ericsson-jira")],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


def test_check_available_uses_only_opaque_configuration(configuration, monkeypatch):
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_PAT", "environment-must-not-enable")

    assert jira_tools.check_available(configuration) is True
    assert jira_tools.check_available() is False


def test_plugins_do_not_declare_ericsson_toggle():
    for name in ("ericsson-jira", "ericsson-teams"):
        text = (REPO / "plugins" / name / "plugin.yaml").read_text()
        assert "ERICSSON_ENV" not in text


def test_jira_source_imports_do_not_occupy_generic_module_names():
    """Jira and GitLab source tests must coexist in one pytest process."""

    plugin_root = (REPO / "plugins" / "ericsson-jira").resolve()
    for name in ("auth", "client", "models", "operations", "tools", "transport"):
        module = sys.modules.get(name)
        module_file = getattr(module, "__file__", None)
        if module_file is not None:
            assert plugin_root not in Path(module_file).resolve().parents


def test_plugin_registers_stable_toolset_and_resolves_fresh_configuration(monkeypatch):
    plugin = _load_plugin()
    invoked = []

    monkeypatch.setattr(
        plugin.jira_tools,
        "invoke",
        lambda name, args, configuration, **options: invoked.append(name) or {"ok": True},
    )
    context = Context()
    plugin.register(context)

    assert set(context.registrations) == {
        "jira_my_tickets",
        "jira_search_issues",
        "jira_get_issue",
        "jira_add_comment",
        "jira_list_fields",
        "jira_get_project",
        "jira_list_transitions",
        "jira_search_assignable_users",
        "jira_transition_issue",
        "jira_assign_issue",
        "jira_update_fields",
    }
    assert {item["toolset"] for item in context.registrations.values()} == {
        "ericsson-jira"
    }
    handler = context.registrations["jira_get_issue"]["handler"]
    assert json.loads(handler({"key": "PROJ-1"}))["success"] is True
    assert json.loads(handler({"key": "PROJ-1"}))["success"] is True
    assert context.configuration_calls == 2
    assert invoked == ["jira_get_issue", "jira_get_issue"]
    for registration in context.registrations.values():
        properties = registration["schema"]["parameters"]["properties"]
        assert not {"pat", "api_token", "token", "base_url"}.intersection(properties)


@respx.mock
def test_my_tickets_extracts_gitlab_urls(configuration):
    respx.get(f"{BASE}/rest/api/2/search").mock(return_value=httpx.Response(200, json={
        "issues": [{"key": "PROJ-1", "fields": {
            "summary": "Fix crash",
            "status": {"name": "Open"}, "priority": {"name": "High"},
            "updated": "2026-07-13T08:00:00.000+0000",
            "description": "See https://gitlab.internal/group/repo. Also https://gitlab.internal/x/y: end",
        }}]}))
    with jira_tools.client_from_configuration(configuration) as client:
        tickets = jira_tools.my_tickets(max_results=5, client=client)
    assert tickets["items"][0]["key"] == "PROJ-1"
    assert tickets["items"][0]["gitlab_urls"] == ["https://gitlab.internal/group/repo", "https://gitlab.internal/x/y"]


@respx.mock
def test_auth_error_is_stably_classified_without_remote_text(configuration):
    respx.get(f"{BASE}/rest/api/2/search").mock(return_value=httpx.Response(401))
    with jira_tools.client_from_configuration(configuration) as client:
        with pytest.raises(jira_tools.JiraError) as caught:
            jira_tools.my_tickets(client=client)
    assert caught.value.category == "authentication"
    assert str(caught.value) == "Jira authentication failed"
    assert caught.value.remediation
    assert "jira" in caught.value.remediation.lower()


@respx.mock
def test_get_issue_and_add_comment(configuration):
    respx.get(f"{BASE}/rest/api/2/issue/PROJ-1").mock(return_value=httpx.Response(200, json={
        "key": "PROJ-1", "fields": {"summary": "s", "status": {"name": "Open"},
                                     "priority": {"name": "High"},
                                     "description": "d",
                                     "comment": {"comments": [
                                         {"author": {"displayName": "A"}, "body": "hi",
                                          "created": "2026-07-01T00:00:00.000+0000"}]}}}))
    with jira_tools.client_from_configuration(configuration) as client:
        issue = jira_tools.get_issue("PROJ-1", client=client)
    assert issue["summary"] == "s" and issue["comments"][0]["body"] == "hi"

    respx.get(f"{BASE}/rest/api/2/issue/PROJ-1/comment").mock(
        return_value=httpx.Response(200, json={"comments": [], "total": 0})
    )
    respx.post(f"{BASE}/rest/api/2/issue/PROJ-1/comment").mock(
        return_value=httpx.Response(201, json={"id": "10001"}))
    with jira_tools.client_from_configuration(configuration) as client:
        out = jira_tools.add_comment("PROJ-1", "done", client=client)
    assert out == {
        "ok": True,
        "id": "10001",
        "created": True,
        "duplicate": False,
        "reconciled": False,
        "dry_run": False,
    }


def test_schemas_are_openai_function_shaped():
    for schema in jira_tools.SCHEMAS.values():
        assert set(schema) >= {"name", "description", "parameters"}
        assert schema["parameters"]["type"] == "object"
