import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/ericsson-jira"))
import jira_tools  # noqa: E402

BASE = "https://jira.internal.ericsson.com"


@pytest.fixture
def jira_env(monkeypatch):
    monkeypatch.setenv("ERICSSON_ENV", "1")
    monkeypatch.setenv("JIRA_BASE_URL", BASE)
    monkeypatch.setenv("JIRA_PAT", "tok")


def test_check_available(jira_env, monkeypatch):
    assert jira_tools.check_available() is True          # jira_env sets BASE_URL + PAT
    monkeypatch.delenv("JIRA_PAT")
    assert jira_tools.check_available() is False          # no PAT -> unavailable
    monkeypatch.delenv("ERICSSON_ENV", raising=False)     # ERICSSON_ENV now irrelevant
    monkeypatch.setenv("JIRA_PAT", "tok")
    assert jira_tools.check_available() is True


def test_missing_env_raises(monkeypatch):
    monkeypatch.delenv("JIRA_BASE_URL", raising=False)
    with pytest.raises(jira_tools.JiraError, match="JIRA_BASE_URL"):
        jira_tools.my_tickets()


@respx.mock
def test_my_tickets_extracts_gitlab_urls(jira_env):
    respx.get(f"{BASE}/rest/api/2/search").mock(return_value=httpx.Response(200, json={
        "issues": [{"key": "PROJ-1", "fields": {
            "summary": "Fix crash",
            "status": {"name": "Open"}, "priority": {"name": "High"},
            "updated": "2026-07-13T08:00:00.000+0000",
            "description": "See https://gitlab.internal/group/repo. Also https://gitlab.internal/x/y: end",
        }}]}))
    tickets = jira_tools.my_tickets(max_results=5)
    assert tickets[0]["key"] == "PROJ-1"
    assert tickets[0]["gitlab_urls"] == ["https://gitlab.internal/group/repo", "https://gitlab.internal/x/y"]


@respx.mock
def test_auth_error_actionable(jira_env):
    respx.get(f"{BASE}/rest/api/2/search").mock(return_value=httpx.Response(401))
    with pytest.raises(jira_tools.JiraError, match="JIRA_PAT"):
        jira_tools.my_tickets()


@respx.mock
def test_get_issue_and_add_comment(jira_env):
    respx.get(f"{BASE}/rest/api/2/issue/PROJ-1").mock(return_value=httpx.Response(200, json={
        "key": "PROJ-1", "fields": {"summary": "s", "status": {"name": "Open"},
                                     "priority": {"name": "High"},
                                     "description": "d",
                                     "comment": {"comments": [
                                         {"author": {"displayName": "A"}, "body": "hi",
                                          "created": "2026-07-01T00:00:00.000+0000"}]}}}))
    issue = jira_tools.get_issue("PROJ-1")
    assert issue["summary"] == "s" and issue["comments"][0]["body"] == "hi"

    respx.post(f"{BASE}/rest/api/2/issue/PROJ-1/comment").mock(
        return_value=httpx.Response(201, json={"id": "10001"}))
    out = jira_tools.add_comment("PROJ-1", "done")
    assert out == {"ok": True, "id": "10001"}


def test_schemas_are_openai_function_shaped():
    for schema in jira_tools.SCHEMAS.values():
        assert set(schema) >= {"name", "description", "parameters"}
        assert schema["parameters"]["type"] == "object"
