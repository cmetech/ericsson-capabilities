import sys
from pathlib import Path

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/ericsson-teams"))
import graph_auth  # noqa: E402
import teams_tools  # noqa: E402

GRAPH = "https://graph.microsoft.com/v1.0"


@pytest.fixture
def teams_env(home, monkeypatch):
    monkeypatch.setenv("ERICSSON_ENV", "1")
    monkeypatch.setattr(graph_auth, "get_token", lambda: "tok")
    return home


def test_check_available(monkeypatch):
    monkeypatch.delenv("ERICSSON_ENV", raising=False)
    assert teams_tools.check_available() is True          # always available; teams_auth guides sign-in


def test_cache_path_under_hermes_home(home):
    assert str(graph_auth.cache_path()).startswith(str(home))
    assert graph_auth.cache_path().name == "msal_token_cache.json"


def test_auth_required_without_cache(home):
    with pytest.raises(graph_auth.AuthRequired, match="teams_auth"):
        graph_auth.get_token()


@respx.mock
def test_teams_list_and_channels(teams_env):
    respx.get(f"{GRAPH}/me/joinedTeams").mock(return_value=httpx.Response(200, json={
        "value": [{"id": "t1", "displayName": "My Team"}]}))
    teams = teams_tools.teams_list()
    assert teams == [{"id": "t1", "name": "My Team"}]

    respx.get(f"{GRAPH}/teams/t1/channels").mock(return_value=httpx.Response(200, json={
        "value": [{"id": "c1", "displayName": "General"}]}))
    assert teams_tools.teams_channels("t1") == [{"id": "c1", "name": "General"}]


@respx.mock
def test_teams_read_send_reply(teams_env):
    respx.get(f"{GRAPH}/teams/t1/channels/c1/messages").mock(
        return_value=httpx.Response(200, json={"value": [
            {"id": "m1", "from": {"user": {"displayName": "A"}},
             "body": {"content": "<p>hello</p>"},
             "createdDateTime": "2026-07-13T08:00:00Z"}]}))
    msgs = teams_tools.teams_read("t1", "c1", limit=5)
    assert msgs[0]["text"] == "hello"          # html stripped

    respx.post(f"{GRAPH}/teams/t1/channels/c1/messages").mock(
        return_value=httpx.Response(201, json={"id": "m2"}))
    assert teams_tools.teams_send("t1", "c1", "hi")["id"] == "m2"

    respx.post(f"{GRAPH}/teams/t1/channels/c1/messages/m1/replies").mock(
        return_value=httpx.Response(201, json={"id": "m3"}))
    assert teams_tools.teams_reply("t1", "c1", "m1", "yo")["id"] == "m3"


@respx.mock
def test_expired_token_actionable(teams_env):
    respx.get(f"{GRAPH}/me/joinedTeams").mock(return_value=httpx.Response(401))
    with pytest.raises(teams_tools.TeamsError, match="teams_auth"):
        teams_tools.teams_list()


def test_schemas_shape():
    assert set(teams_tools.SCHEMAS) == {"teams_auth", "teams_list", "teams_channels",
                                         "teams_read", "teams_send", "teams_reply"}
    for schema in teams_tools.SCHEMAS.values():
        assert set(schema) >= {"name", "description", "parameters"}


class _FakeCache:
    has_state_changed = False


class _FakeApp:
    def __init__(self, result):
        self._result = result

    def acquire_token_by_device_flow(self, flow):
        return self._result


def _pend(result):
    graph_auth._PENDING_FLOW = (_FakeApp(result), _FakeCache(), {"user_code": "X"})


def test_complete_device_flow_pending_keeps_flow():
    _pend({"error": "authorization_pending"})
    out = graph_auth.complete_device_flow()
    assert out["pending"] is True and graph_auth._PENDING_FLOW is not None


def test_complete_device_flow_terminal_clears_flow():
    _pend({"error": "expired_token", "error_description": "code expired"})
    out = graph_auth.complete_device_flow()
    assert out["pending"] is False and "expired" in out["error"]
    assert graph_auth._PENDING_FLOW is None
