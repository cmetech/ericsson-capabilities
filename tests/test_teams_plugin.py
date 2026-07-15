import os
import stat
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
    monkeypatch.setattr(graph_auth, "get_token", lambda: "tok")
    return home


def test_check_available():
    assert teams_tools.check_available() is True          # always available; teams_auth guides sign-in


def test_cache_path_under_hermes_home(home):
    assert str(graph_auth.cache_path()).startswith(str(home))
    assert graph_auth.cache_path().name == "msal_token_cache.json"


def test_auth_required_without_cache(home):
    with pytest.raises(graph_auth.AuthRequired, match="teams_auth"):
        graph_auth.get_token()


class _ChangedCache:
    has_state_changed = True

    def __init__(self, serialized="secret-refresh-token"):
        self.serialized = serialized

    def serialize(self):
        return self.serialized


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_persist_creates_private_token_cache_and_directory(home):
    graph_auth._persist(_ChangedCache())

    cache = graph_auth.cache_path()
    assert stat.S_IMODE(cache.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert cache.read_text(encoding="utf-8") == "secret-refresh-token"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_persist_repairs_existing_broad_cache_permissions(home):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True, mode=0o777)
    cache.parent.chmod(0o777)
    cache.write_text("old-token", encoding="utf-8")
    cache.chmod(0o666)

    graph_auth._persist(_ChangedCache("new-token"))

    assert stat.S_IMODE(cache.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600
    assert cache.read_text(encoding="utf-8") == "new-token"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission contract")
def test_read_repairs_existing_broad_cache_permissions(home):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True, mode=0o777)
    cache.parent.chmod(0o777)
    cache.write_text("existing-token", encoding="utf-8")
    cache.chmod(0o644)

    assert graph_auth._read_cache_text() == "existing-token"

    assert stat.S_IMODE(cache.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(cache.stat().st_mode) == 0o600


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink contract")
def test_read_rejects_symlink_cache_without_disclosing_victim(home):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True, mode=0o700)
    victim = home / "victim-token-cache"
    victim.write_text("victim-secret-token", encoding="utf-8")
    cache.symlink_to(victim)

    with pytest.raises(graph_auth.AuthRequired, match="securely") as caught:
        graph_auth._read_cache_text()

    assert "victim-secret-token" not in str(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX symlink contract")
def test_persist_rejects_symlink_cache_without_touching_victim(home):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True, mode=0o700)
    victim = home / "victim-token-cache"
    victim.write_text("victim-original", encoding="utf-8")
    cache.symlink_to(victim)

    with pytest.raises(graph_auth.AuthRequired, match="securely") as caught:
        graph_auth._persist(_ChangedCache("must-not-leak"))

    assert victim.read_text(encoding="utf-8") == "victim-original"
    assert "must-not-leak" not in str(caught.value)


@pytest.mark.skipif(os.name != "posix", reason="POSIX atomic-write contract")
def test_persist_cleans_private_temporary_file_after_publish_failure(home, monkeypatch):
    def fail_replace(*args, **kwargs):
        raise OSError("simulated publication failure")

    monkeypatch.setattr(graph_auth.os, "replace", fail_replace)

    with pytest.raises(graph_auth.AuthRequired, match="securely") as caught:
        graph_auth._persist(_ChangedCache("must-not-appear-in-error"))

    cache = graph_auth.cache_path()
    assert not cache.exists()
    assert list(cache.parent.iterdir()) == []
    assert "must-not-appear-in-error" not in str(caught.value)


def test_persist_redacts_serialization_failure_details(home):
    class FailingCache:
        has_state_changed = True

        @staticmethod
        def serialize():
            raise ValueError("must-not-leak-secret-token")

    with pytest.raises(graph_auth.AuthRequired, match="securely") as caught:
        graph_auth._persist(FailingCache())

    assert "must-not-leak-secret-token" not in str(caught.value)


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
