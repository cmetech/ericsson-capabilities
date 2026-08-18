import os
import stat
import sys
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest
import respx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "plugins/ericsson-teams"))
import graph_auth  # noqa: E402


def test_posix_only_ownership_guards_remain_explicitly_annotated():
    source = (Path(__file__).resolve().parents[1] / "plugins/ericsson-teams/graph_auth.py").read_text()
    assert source.count("windows-footgun: ok — POSIX-only path") == 4
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


class _FakeWindowsAcl:
    def __init__(self, events=None, *, insecure=None, fail=None, on_call=None):
        self.events = events if events is not None else []
        self.insecure = insecure
        self.fail = fail
        self.on_call = on_call
        self._counts = {}

    def _record(self, name, path):
        path = Path(path)
        self.events.append((name, path))
        self._counts[name] = self._counts.get(name, 0) + 1
        occurrence = self._counts[name]
        if self.fail == (name, occurrence):
            raise RuntimeError("must-not-leak-host-failure")
        if self.on_call is not None:
            self.on_call(name, path, occurrence)
        return SimpleNamespace(
            secure=self.insecure != (name, occurrence),
            detail=("must-not-leak-acl-detail" if self.insecure == (name, occurrence)
                    else None),
        )

    def restrict_directory_to_current_user(self, path):
        self._record("restrict_directory", path)

    def inspect_directory_acl(self, path):
        return self._record("inspect_directory", path)

    def restrict_file_to_current_user(self, path):
        self._record("restrict_file", path)

    def inspect_file_acl(self, path):
        return self._record("inspect_file", path)


def _install_windows_acl(monkeypatch, fake):
    monkeypatch.setattr(graph_auth, "_platform_name", lambda: "nt", raising=False)
    monkeypatch.setattr(graph_auth, "_windows_acl_api", lambda: fake, raising=False)


def _temporary_cache_files():
    cache = graph_auth.cache_path()
    return list(cache.parent.glob(f".{cache.name}.*.tmp"))


def test_windows_persist_protects_parent_and_temp_before_first_cache_byte(
        home, monkeypatch):
    events = []
    fake = _FakeWindowsAcl(events)
    _install_windows_acl(monkeypatch, fake)
    real_open = graph_auth.os.open
    real_write = graph_auth.os.write

    def recording_open(path, *args, **kwargs):
        events.append(("open", Path(path)))
        return real_open(path, *args, **kwargs)

    def recording_write(descriptor, data):
        events.append(("write", bytes(data)))
        return real_write(descriptor, data)

    monkeypatch.setattr(graph_auth.os, "open", recording_open)
    monkeypatch.setattr(graph_auth.os, "write", recording_write)

    graph_auth._persist(_ChangedCache("secret-refresh-token"))

    cache = graph_auth.cache_path()
    temp = next(path for name, path in events if name == "open")
    assert events.index(("restrict_directory", cache.parent)) < events.index(("open", temp))
    assert events.index(("inspect_directory", cache.parent)) < events.index(("open", temp))
    assert events.index(("restrict_file", temp)) < next(
        index for index, event in enumerate(events) if event[0] == "write"
    )
    assert events.index(("inspect_file", temp)) < next(
        index for index, event in enumerate(events) if event[0] == "write"
    )
    assert cache.read_text(encoding="utf-8") == "secret-refresh-token"


def test_windows_persist_protects_final_destination_after_atomic_replace(home, monkeypatch):
    events = []
    fake = _FakeWindowsAcl(events)
    _install_windows_acl(monkeypatch, fake)
    real_replace = graph_auth.os.replace

    def recording_replace(source, destination):
        events.append(("replace", (Path(source), Path(destination))))
        return real_replace(source, destination)

    monkeypatch.setattr(graph_auth.os, "replace", recording_replace)

    graph_auth._persist(_ChangedCache("new-token"))

    cache = graph_auth.cache_path()
    replace_index = next(index for index, event in enumerate(events) if event[0] == "replace")
    final_restrict = max(
        index for index, event in enumerate(events)
        if event == ("restrict_file", cache)
    )
    final_inspect = max(
        index for index, event in enumerate(events)
        if event == ("inspect_file", cache)
    )
    assert replace_index < final_restrict < final_inspect


def test_windows_read_protects_parent_and_file_before_first_read(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text("existing-token", encoding="utf-8")
    events = []
    fake = _FakeWindowsAcl(events)
    _install_windows_acl(monkeypatch, fake)
    real_read = graph_auth.os.read

    def recording_read(descriptor, size):
        events.append(("read", size))
        return real_read(descriptor, size)

    monkeypatch.setattr(graph_auth.os, "read", recording_read)

    assert graph_auth._read_cache_text() == "existing-token"

    first_read = next(index for index, event in enumerate(events) if event[0] == "read")
    assert events.index(("restrict_directory", cache.parent)) < first_read
    assert events.index(("inspect_directory", cache.parent)) < first_read
    assert events.index(("restrict_file", cache)) < first_read
    assert events.index(("inspect_file", cache)) < first_read


def test_windows_read_rejects_cache_larger_than_16_mib(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    _install_windows_acl(monkeypatch, _FakeWindowsAcl())

    with pytest.raises(graph_auth.AuthRequired, match="could not read.*securely"):
        graph_auth._read_cache_text()


@pytest.mark.parametrize(
    ("operation", "insecure"),
    [
        ("persist", ("inspect_directory", 1)),
        ("persist", ("inspect_file", 1)),
        ("read", ("inspect_directory", 1)),
        ("read", ("inspect_file", 1)),
    ],
)
def test_windows_insecure_acl_is_redacted_auth_required(
        home, monkeypatch, operation, insecure):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    if operation == "read":
        cache.write_text("secret-refresh-token", encoding="utf-8")
    _install_windows_acl(monkeypatch, _FakeWindowsAcl(insecure=insecure))

    with pytest.raises(graph_auth.AuthRequired, match="securely") as caught:
        if operation == "persist":
            graph_auth._persist(_ChangedCache("secret-refresh-token"))
        else:
            graph_auth._read_cache_text()

    assert "secret-refresh-token" not in str(caught.value)
    assert "must-not-leak-acl-detail" not in str(caught.value)
    assert _temporary_cache_files() == []


@pytest.mark.parametrize("operation", ["persist", "read"])
def test_windows_missing_host_acl_api_is_redacted_auth_required(
        home, monkeypatch, operation):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    if operation == "read":
        cache.write_text("secret-refresh-token", encoding="utf-8")
    monkeypatch.setattr(graph_auth, "_platform_name", lambda: "nt", raising=False)

    def missing_api():
        raise ImportError("must-not-leak-missing-hermes")

    monkeypatch.setattr(graph_auth, "_windows_acl_api", missing_api, raising=False)

    with pytest.raises(graph_auth.AuthRequired, match="securely") as caught:
        if operation == "persist":
            graph_auth._persist(_ChangedCache("secret-refresh-token"))
        else:
            graph_auth._read_cache_text()

    assert "secret-refresh-token" not in str(caught.value)
    assert "must-not-leak-missing-hermes" not in str(caught.value)
    assert _temporary_cache_files() == []


def test_windows_persist_rejects_wrong_destination_type(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.mkdir(parents=True)
    _install_windows_acl(monkeypatch, _FakeWindowsAcl())

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely"):
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert cache.is_dir()
    assert _temporary_cache_files() == []


def test_windows_read_rejects_reparse_point_before_acl_or_content_read(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text("secret-refresh-token", encoding="utf-8")
    fake = _FakeWindowsAcl()
    _install_windows_acl(monkeypatch, fake)
    real_lstat = Path.lstat

    def reparse_lstat(path):
        if path == cache:
            return SimpleNamespace(
                st_mode=stat.S_IFREG | 0o600,
                st_file_attributes=stat.FILE_ATTRIBUTE_REPARSE_POINT,
            )
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", reparse_lstat)

    with pytest.raises(graph_auth.AuthRequired, match="could not read.*securely") as caught:
        graph_auth._read_cache_text()

    assert fake.events == [
        ("restrict_directory", cache.parent),
        ("inspect_directory", cache.parent),
    ]
    assert "secret-refresh-token" not in str(caught.value)


@pytest.mark.parametrize(
    "failure",
    [
        ("restrict_file", 1),
        ("inspect_file", 1),
        ("write", 1),
        ("replace", 1),
    ],
)
def test_windows_persist_removes_unpublished_temp_and_redacts_failures(
        home, monkeypatch, failure):
    fake_failure = failure if failure[0] in {"restrict_file", "inspect_file"} else None
    _install_windows_acl(monkeypatch, _FakeWindowsAcl(fail=fake_failure))
    if failure[0] == "write":
        monkeypatch.setattr(
            graph_auth.os,
            "write",
            lambda *_args: (_ for _ in ()).throw(OSError("must-not-leak-write-failure")),
        )
    if failure[0] == "replace":
        monkeypatch.setattr(
            graph_auth.os,
            "replace",
            lambda *_args: (_ for _ in ()).throw(OSError("must-not-leak-replace-failure")),
        )

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely") as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert _temporary_cache_files() == []
    assert "secret-refresh-token" not in str(caught.value)
    assert "must-not-leak" not in str(caught.value)


def test_windows_persist_final_acl_failure_is_redacted_and_leaves_no_temp(
        home, monkeypatch):
    fake = _FakeWindowsAcl(fail=("inspect_file", 2))
    _install_windows_acl(monkeypatch, fake)

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely") as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert graph_auth.cache_path().read_text(encoding="utf-8") == "secret-refresh-token"
    assert _temporary_cache_files() == []
    assert "secret-refresh-token" not in str(caught.value)
    assert "must-not-leak-host-failure" not in str(caught.value)


def test_windows_persist_rejects_parent_swap_during_temp_open(home, monkeypatch):
    cache = graph_auth.cache_path()
    replaced_parent = home / "replaced-ericsson-parent"
    _install_windows_acl(monkeypatch, _FakeWindowsAcl())
    real_open = graph_auth.os.open
    swapped = False

    def swapping_open(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path).parent == cache.parent:
            swapped = True
            cache.parent.rename(replaced_parent)
            cache.parent.mkdir()
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(graph_auth.os, "open", swapping_open)

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely") as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert swapped is True
    assert not cache.exists()
    assert _temporary_cache_files() == []
    assert "secret-refresh-token" not in str(caught.value)


def test_windows_persist_rejects_temp_path_swap_before_first_write(home, monkeypatch):
    swapped = False

    def swap_temp(name, path, occurrence):
        nonlocal swapped
        if name == "inspect_file" and occurrence == 1:
            replacement = path.parent / "attacker-temp-replacement"
            replacement.write_text("attacker-cache", encoding="utf-8")
            os.replace(replacement, path)
            swapped = True

    _install_windows_acl(monkeypatch, _FakeWindowsAcl(on_call=swap_temp))
    real_write = graph_auth.os.write
    writes = []

    def recording_write(descriptor, data):
        writes.append(bytes(data))
        return real_write(descriptor, data)

    monkeypatch.setattr(graph_auth.os, "write", recording_write)

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely") as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert swapped is True
    assert writes == []
    assert _temporary_cache_files() == []
    assert "secret-refresh-token" not in str(caught.value)


def test_windows_read_rejects_protected_target_swap_before_open(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text("protected-cache", encoding="utf-8")
    attacker = cache.parent / "attacker-cache"
    attacker.write_text("attacker-cache", encoding="utf-8")
    _install_windows_acl(monkeypatch, _FakeWindowsAcl())
    real_open = graph_auth.os.open
    real_read = graph_auth.os.read
    reads = []
    swapped = False

    def swapping_open(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path) == cache:
            os.replace(attacker, cache)
            swapped = True
        return real_open(path, *args, **kwargs)

    def recording_read(descriptor, size):
        reads.append(size)
        return real_read(descriptor, size)

    monkeypatch.setattr(graph_auth.os, "open", swapping_open)
    monkeypatch.setattr(graph_auth.os, "read", recording_read)

    with pytest.raises(graph_auth.AuthRequired, match="could not read.*securely") as caught:
        graph_auth._read_cache_text()

    assert swapped is True
    assert reads == []
    assert "attacker-cache" not in str(caught.value)


def test_windows_read_rejects_parent_swap_even_when_target_identity_matches(
        home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text("protected-cache", encoding="utf-8")
    replaced_parent = home / "replaced-ericsson-parent"
    _install_windows_acl(monkeypatch, _FakeWindowsAcl())
    real_open = graph_auth.os.open
    swapped = False

    def swapping_open(path, *args, **kwargs):
        nonlocal swapped
        if not swapped and Path(path) == cache:
            swapped = True
            cache.parent.rename(replaced_parent)
            cache.parent.mkdir()
            os.link(replaced_parent / cache.name, cache)
        return real_open(path, *args, **kwargs)

    monkeypatch.setattr(graph_auth.os, "open", swapping_open)

    with pytest.raises(graph_auth.AuthRequired, match="could not read.*securely"):
        graph_auth._read_cache_text()

    assert swapped is True


def test_windows_persist_rejects_final_target_swap_after_replace(home, monkeypatch):
    cache = graph_auth.cache_path()
    _install_windows_acl(monkeypatch, _FakeWindowsAcl())
    real_replace = graph_auth.os.replace
    swapped = False

    def swapping_replace(source, destination):
        nonlocal swapped
        real_replace(source, destination)
        attacker = cache.parent / "attacker-final"
        attacker.write_text("attacker-cache", encoding="utf-8")
        real_replace(attacker, destination)
        swapped = True

    monkeypatch.setattr(graph_auth.os, "replace", swapping_replace)

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely") as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert swapped is True
    assert cache.read_text(encoding="utf-8") == "attacker-cache"
    assert _temporary_cache_files() == []
    assert "secret-refresh-token" not in str(caught.value)


def test_windows_persist_unlinks_temp_when_close_reports_failure(home, monkeypatch):
    _install_windows_acl(
        monkeypatch,
        _FakeWindowsAcl(fail=("restrict_file", 1)),
    )
    real_close = graph_auth.os.close
    close_failed = False

    def close_then_fail(descriptor):
        nonlocal close_failed
        real_close(descriptor)
        if not close_failed:
            close_failed = True
            raise OSError("must-not-leak-close-failure")

    monkeypatch.setattr(graph_auth.os, "close", close_then_fail)

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely") as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert close_failed is True
    assert _temporary_cache_files() == []
    assert "must-not-leak-close-failure" not in str(caught.value)
    assert "secret-refresh-token" not in str(caught.value)


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
