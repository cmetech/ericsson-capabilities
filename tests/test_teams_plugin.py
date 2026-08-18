import os
import stat
import sys
from pathlib import Path

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


def _install_windows_acl(monkeypatch, fake):
    monkeypatch.setattr(graph_auth, "_platform_name", lambda: "nt", raising=False)
    monkeypatch.setattr(graph_auth, "_windows_acl_api", lambda: fake, raising=False)


class _HandleBoundWindowsHost:
    """Portable model of the host's held-handle private-file contract."""

    def __init__(self, *, on_event=None, fail_event=None):
        self.on_event = on_event
        self.fail_event = fail_event
        self.events = []

    def _event(self, name, artifact):
        self.events.append((name, artifact))
        if self.on_event is not None:
            self.on_event(name, artifact)
        if self.fail_event == name:
            raise OSError("must-not-leak-handle-host-failure")

    def open_private_directory(self, path):
        flags = os.O_RDONLY | os.O_DIRECTORY | getattr(os, "O_NOFOLLOW", 0)
        descriptor = os.open(path, flags)
        directory = _HandleBoundDirectory(self, Path(path), descriptor)
        try:
            self._event("parent", directory)
        except Exception:
            directory.close()
            raise
        return directory


class _HandleBoundDirectory:
    def __init__(self, host, path, descriptor):
        self.host = host
        self.path = path
        self.descriptor = descriptor

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def open_file(self, name):
        flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(name, flags, dir_fd=self.descriptor)
        except FileNotFoundError:
            return None
        private_file = _HandleBoundFile(
            self.host,
            self,
            name,
            descriptor,
            delete_armed=False,
        )
        try:
            self.host._event("cache", private_file)
        except Exception:
            private_file.close()
            raise
        return private_file

    def create_file(self, name):
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(name, flags, 0o600, dir_fd=self.descriptor)
        private_file = _HandleBoundFile(
            self.host,
            self,
            name,
            descriptor,
            delete_armed=True,
        )
        try:
            self.host._event("temp", private_file)
        except Exception:
            private_file.close()
            raise
        return private_file

    def close(self):
        descriptor = self.descriptor
        if descriptor is None:
            return
        self.descriptor = None
        os.close(descriptor)


class _HandleBoundFile:
    def __init__(self, host, parent, name, descriptor, *, delete_armed):
        self.host = host
        self.parent = parent
        self.name = name
        self.descriptor = descriptor
        self.delete_armed = delete_armed
        self.identity = os.fstat(descriptor)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        self.close()

    def read_all(self, *, max_bytes):
        self.host._event("read", self)
        chunks = []
        total = 0
        while True:
            chunk = os.read(self.descriptor, 64 * 1024)
            if not chunk:
                return b"".join(chunks)
            total += len(chunk)
            if total > max_bytes:
                raise OSError("private cache is too large")
            chunks.append(chunk)

    def write_all(self, data):
        view = memoryview(data)
        while view:
            written = os.write(self.descriptor, view)
            if written <= 0:
                raise OSError("short private cache write")
            view = view[written:]
        self.host._event("write", self)

    def flush(self):
        os.fsync(self.descriptor)
        self.host._event("flush", self)

    def publish(self, name):
        self.host._event("before_publish", self)
        os.replace(
            self.name,
            name,
            src_dir_fd=self.parent.descriptor,
            dst_dir_fd=self.parent.descriptor,
        )
        self.name = name
        self.host._event("final", self)
        self.delete_armed = False

    def _linked_name(self):
        for name in os.listdir(self.parent.descriptor):
            opened = os.stat(name, dir_fd=self.parent.descriptor, follow_symlinks=False)
            if os.path.samestat(self.identity, opened):
                return name
        return None

    def close(self):
        descriptor = self.descriptor
        if descriptor is None:
            return
        cleanup_error = None
        if self.delete_armed:
            try:
                linked_name = self._linked_name()
                if linked_name is not None:
                    os.unlink(linked_name, dir_fd=self.parent.descriptor)
            except OSError as error:
                cleanup_error = error
        self.descriptor = None
        try:
            os.close(descriptor)
        except OSError as error:
            if cleanup_error is None:
                cleanup_error = error
        try:
            self.host._event("close", self)
        except OSError as error:
            if cleanup_error is None:
                cleanup_error = error
        if cleanup_error is not None:
            raise cleanup_error


def _temporary_cache_files():
    cache = graph_auth.cache_path()
    return list(cache.parent.glob(f".{cache.name}.*.tmp"))


def test_windows_read_parent_aba_uses_the_host_held_directory(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text("protected-cache", encoding="utf-8")
    parked = home / "parked-parent"
    attacker = home / "attacker-parent"
    attacker.mkdir()
    (attacker / cache.name).write_text("attacker-cache", encoding="utf-8")
    swapped = False

    def parent_aba(name, artifact):
        nonlocal swapped
        if name != "parent" or swapped:
            return
        cache.parent.rename(parked)
        attacker.rename(cache.parent)
        cache.parent.rename(attacker)
        parked.rename(cache.parent)
        swapped = True

    host = _HandleBoundWindowsHost(on_event=parent_aba)
    _install_windows_acl(monkeypatch, host)

    assert graph_auth._read_cache_text() == "protected-cache"
    assert swapped is True


def test_windows_read_cache_aba_reads_the_acl_held_file(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text("protected-cache", encoding="utf-8")
    attacker = cache.parent / "attacker-cache"
    attacker.write_text("attacker-cache", encoding="utf-8")
    parked = cache.parent / "parked-cache"
    swapped = False

    def cache_aba(name, artifact):
        nonlocal swapped
        if name != "cache" or swapped:
            return
        cache.rename(parked)
        attacker.rename(cache)
        cache.rename(attacker)
        parked.rename(cache)
        swapped = True

    host = _HandleBoundWindowsHost(on_event=cache_aba)
    _install_windows_acl(monkeypatch, host)

    assert graph_auth._read_cache_text() == "protected-cache"
    assert swapped is True


def test_windows_persist_temp_aba_writes_the_acl_held_file(home, monkeypatch):
    swapped = False

    def temp_aba(name, artifact):
        nonlocal swapped
        if name != "temp" or swapped:
            return
        temporary = artifact.parent.path / artifact.name
        parked = artifact.parent.path / "parked-temp"
        attacker = artifact.parent.path / "attacker-temp"
        attacker.write_bytes(b"attacker-cache")
        temporary.rename(parked)
        attacker.rename(temporary)
        temporary.rename(attacker)
        parked.rename(temporary)
        swapped = True

    host = _HandleBoundWindowsHost(on_event=temp_aba)
    _install_windows_acl(monkeypatch, host)

    graph_auth._persist(_ChangedCache("synthetic-token-cache"))

    assert (
        graph_auth.cache_path().read_text(encoding="utf-8") == "synthetic-token-cache"
    )
    assert swapped is True


def test_windows_persist_final_aba_keeps_the_acl_held_publication(home, monkeypatch):
    swapped = False

    def final_aba(name, artifact):
        nonlocal swapped
        if name != "final" or swapped:
            return
        final = artifact.parent.path / artifact.name
        parked = artifact.parent.path / "parked-final"
        attacker = artifact.parent.path / "attacker-final"
        attacker.write_bytes(b"attacker-cache")
        final.rename(parked)
        attacker.rename(final)
        final.rename(attacker)
        parked.rename(final)
        swapped = True

    host = _HandleBoundWindowsHost(on_event=final_aba)
    _install_windows_acl(monkeypatch, host)

    graph_auth._persist(_ChangedCache("synthetic-token-cache"))

    assert (
        graph_auth.cache_path().read_text(encoding="utf-8") == "synthetic-token-cache"
    )
    assert swapped is True


def test_windows_failure_cleanup_deletes_moved_real_temp_not_name_replacement(
    home, monkeypatch
):
    state = {}

    def move_and_replace(name, artifact):
        if name != "write" or state:
            return
        original = artifact.parent.path / artifact.name
        moved = artifact.parent.path / "moved-sensitive-temp"
        original.rename(moved)
        original.write_bytes(b"attacker-replacement")
        state.update(original=original, moved=moved)

    host = _HandleBoundWindowsHost(on_event=move_and_replace, fail_event="write")
    _install_windows_acl(monkeypatch, host)

    with pytest.raises(
        graph_auth.AuthRequired, match="could not store.*securely"
    ) as caught:
        graph_auth._persist(_ChangedCache("synthetic-token-cache"))

    assert state["moved"].exists() is False
    assert state["original"].read_bytes() == b"attacker-replacement"
    assert "synthetic-token-cache" not in str(caught.value)
    assert "must-not-leak" not in str(caught.value)


def test_windows_failure_cleanup_never_deletes_replacement_after_temp_unlink(
    home, monkeypatch
):
    state = {}

    def unlink_and_replace(name, artifact):
        if name != "write" or state:
            return
        original = artifact.parent.path / artifact.name
        original.unlink()
        original.write_bytes(b"attacker-replacement")
        state["replacement"] = original

    host = _HandleBoundWindowsHost(on_event=unlink_and_replace, fail_event="write")
    _install_windows_acl(monkeypatch, host)

    with pytest.raises(
        graph_auth.AuthRequired, match="could not store.*securely"
    ) as caught:
        graph_auth._persist(_ChangedCache("synthetic-token-cache"))

    assert state["replacement"].read_bytes() == b"attacker-replacement"
    assert "synthetic-token-cache" not in str(caught.value)
    assert "must-not-leak" not in str(caught.value)


def test_windows_persist_protects_parent_and_temp_before_first_cache_byte(
    home, monkeypatch
):
    host = _HandleBoundWindowsHost()
    _install_windows_acl(monkeypatch, host)

    graph_auth._persist(_ChangedCache("secret-refresh-token"))

    cache = graph_auth.cache_path()
    names = [name for name, _artifact in host.events]
    assert names.index("parent") < names.index("temp") < names.index("write")
    assert cache.read_text(encoding="utf-8") == "secret-refresh-token"


def test_windows_persist_protects_final_destination_after_atomic_replace(
    home, monkeypatch
):
    host = _HandleBoundWindowsHost()
    _install_windows_acl(monkeypatch, host)

    graph_auth._persist(_ChangedCache("new-token"))

    names = [name for name, _artifact in host.events]
    assert names.index("before_publish") < names.index("final")
    assert graph_auth.cache_path().read_text(encoding="utf-8") == "new-token"


def test_windows_read_protects_parent_and_file_before_first_read(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_text("existing-token", encoding="utf-8")
    host = _HandleBoundWindowsHost()
    _install_windows_acl(monkeypatch, host)

    assert graph_auth._read_cache_text() == "existing-token"

    names = [name for name, _artifact in host.events]
    assert names.index("parent") < names.index("cache") < names.index("read")


def test_windows_read_rejects_cache_larger_than_16_mib(home, monkeypatch):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    cache.write_bytes(b"x" * (16 * 1024 * 1024 + 1))
    _install_windows_acl(monkeypatch, _HandleBoundWindowsHost())

    with pytest.raises(graph_auth.AuthRequired, match="could not read.*securely"):
        graph_auth._read_cache_text()


@pytest.mark.parametrize(
    ("operation", "failure_event"),
    [
        ("persist", "parent"),
        ("persist", "temp"),
        ("read", "parent"),
        ("read", "cache"),
    ],
)
def test_windows_host_acl_failure_is_redacted_auth_required(
    home, monkeypatch, operation, failure_event
):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    if operation == "read":
        cache.write_text("secret-refresh-token", encoding="utf-8")
    _install_windows_acl(
        monkeypatch,
        _HandleBoundWindowsHost(fail_event=failure_event),
    )

    with pytest.raises(graph_auth.AuthRequired, match="securely") as caught:
        if operation == "persist":
            graph_auth._persist(_ChangedCache("secret-refresh-token"))
        else:
            graph_auth._read_cache_text()

    assert "secret-refresh-token" not in str(caught.value)
    assert "must-not-leak-handle-host-failure" not in str(caught.value)
    assert _temporary_cache_files() == []


@pytest.mark.parametrize("operation", ["persist", "read"])
def test_windows_missing_host_acl_api_is_redacted_auth_required(
    home, monkeypatch, operation
):
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
    _install_windows_acl(monkeypatch, _HandleBoundWindowsHost())

    with pytest.raises(graph_auth.AuthRequired, match="could not store.*securely"):
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert cache.is_dir()
    assert _temporary_cache_files() == []


def test_windows_read_rejects_reparse_point_before_acl_or_content_read(
    home, monkeypatch
):
    cache = graph_auth.cache_path()
    cache.parent.mkdir(parents=True)
    victim = home / "victim-cache"
    victim.write_text("secret-refresh-token", encoding="utf-8")
    cache.symlink_to(victim)
    host = _HandleBoundWindowsHost()
    _install_windows_acl(monkeypatch, host)

    with pytest.raises(
        graph_auth.AuthRequired, match="could not read.*securely"
    ) as caught:
        graph_auth._read_cache_text()

    assert [name for name, _artifact in host.events] == ["parent"]
    assert "secret-refresh-token" not in str(caught.value)


@pytest.mark.parametrize(
    "failure_event",
    [
        "temp",
        "write",
        "before_publish",
    ],
)
def test_windows_persist_removes_unpublished_temp_and_redacts_failures(
    home, monkeypatch, failure_event
):
    _install_windows_acl(
        monkeypatch,
        _HandleBoundWindowsHost(fail_event=failure_event),
    )

    with pytest.raises(
        graph_auth.AuthRequired, match="could not store.*securely"
    ) as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert _temporary_cache_files() == []
    assert "secret-refresh-token" not in str(caught.value)
    assert "must-not-leak" not in str(caught.value)


def test_windows_persist_final_acl_failure_is_redacted_and_leaves_no_temp(
    home, monkeypatch
):
    _install_windows_acl(monkeypatch, _HandleBoundWindowsHost(fail_event="final"))

    with pytest.raises(
        graph_auth.AuthRequired, match="could not store.*securely"
    ) as caught:
        graph_auth._persist(_ChangedCache("secret-refresh-token"))

    assert graph_auth.cache_path().exists() is False
    assert _temporary_cache_files() == []
    assert "secret-refresh-token" not in str(caught.value)
    assert "must-not-leak-host-failure" not in str(caught.value)


def test_windows_cleanup_failure_is_redacted_after_handle_bound_deletion(
    home, monkeypatch
):
    def fail_close(name, artifact):
        if name == "close":
            raise OSError("must-not-leak-close-failure")

    host = _HandleBoundWindowsHost(on_event=fail_close, fail_event="write")
    _install_windows_acl(monkeypatch, host)

    with pytest.raises(
        graph_auth.AuthRequired, match="could not store.*securely"
    ) as caught:
        graph_auth._persist(_ChangedCache("synthetic-token-cache"))

    assert _temporary_cache_files() == []
    assert "must-not-leak-close-failure" not in str(caught.value)
    assert "synthetic-token-cache" not in str(caught.value)


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
