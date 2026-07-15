from __future__ import annotations

import ctypes
import importlib.util
import os
import subprocess
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPT_DIR = REPO / "skills/ericsson/onboard-ericsson-capabilities/scripts"
WINDOWS_SCRIPT = SCRIPT_DIR / "onboarding_state_windows.py"
STATE_SCRIPT = SCRIPT_DIR / "onboarding_state.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


state = load_module(STATE_SCRIPT, "onboarding_state_dispatch_test")
windows = load_module(WINDOWS_SCRIPT, "onboarding_state_windows_test")


class RecordingAPI:
    def __init__(self, *, attributes: int = 0x10, identity=(7, 11)) -> None:
        self.attributes = attributes
        self.identity = identity
        self.events: list[tuple] = []

    def create_file(self, path, access, share, creation, flags):
        self.events.append(("create", str(path), access, share, creation, flags))
        return 17

    def create_relative(
        self, parent, name, *, access, share, disposition, directory, private
    ):
        self.events.append(
            (
                "create-relative", parent, name, access, share, disposition,
                directory, private,
            )
        )
        return 19

    def file_attributes(self, handle):
        self.events.append(("attributes", handle))
        return self.attributes

    def file_identity(self, handle):
        self.events.append(("identity", handle))
        return windows.FileIdentity(*self.identity)

    def apply_private_acl(self, handle):
        self.events.append(("apply-acl", handle))

    def verify_private_acl(self, handle):
        self.events.append(("verify-acl", handle))

    def close_handle(self, handle):
        self.events.append(("close", handle))


def test_backend_kind_dispatches_explicitly() -> None:
    assert state._backend_kind("posix") == "posix"
    assert state._backend_kind("nt") == "windows"
    with pytest.raises(state.StateIOError, match="unavailable"):
        state._backend_kind("java")


def test_public_api_dispatches_encoded_state_to_windows_backend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = {
        "schemaVersion": "1.0",
        "catalogVersion": "0.4.0",
        "selectedCapabilities": ["jira-tools"],
        "maturity": {"jira-tools": "available"},
        "readinessFacts": {
            "jira-tools": {
                "state": "unknown-needs-check",
                "discoverable": None,
                "enabled": None,
                "platformSupported": None,
                "requiredSettingsConfigured": None,
                "permissionAdequate": None,
                "dependencyAvailable": None,
                "authenticationValidated": None,
                "safeProbeSucceeded": None,
            }
        },
        "completedSteps": [],
        "pendingActions": [],
        "artifactPointers": [],
        "nextPrompt": "Check Jira readiness.",
        "createdAt": "2026-07-15T15:00:00Z",
        "updatedAt": "2026-07-15T15:00:00Z",
    }

    class FakeBackend:
        class WindowsStateError(Exception):
            pass

        def __init__(self) -> None:
            self.content: bytes | None = None

        def save_current_bytes(self, home, content):
            self.content = content
            return Path(home) / "onboarding/ericsson/current.json"

        def load_current_bytes(self, home):
            del home
            return self.content

    backend = FakeBackend()
    monkeypatch.setattr(state, "_backend_kind", lambda platform_name=None: "windows")
    monkeypatch.setattr(state, "_WINDOWS_BACKEND", backend)

    expected = tmp_path / "onboarding/ericsson/current.json"
    assert state.save_current(tmp_path, payload) == expected
    assert backend.content and backend.content.endswith(b"\n")
    assert state.load_current(tmp_path) == payload


def test_verified_directory_open_uses_no_delete_share_and_reparse_flag() -> None:
    api = RecordingAPI()
    adapter = windows.Win32Adapter(api=api)

    opened = adapter.open_verified(
        Path("C:/profile/onboarding"), directory=True, creation=windows.OPEN_EXISTING,
        access=windows.FILE_READ_ATTRIBUTES, private=True,
    )

    create = api.events[0]
    assert create[0] == "create"
    assert create[3] & windows.FILE_SHARE_DELETE == 0
    assert create[5] & windows.FILE_FLAG_OPEN_REPARSE_POINT
    assert create[5] & windows.FILE_FLAG_BACKUP_SEMANTICS
    assert api.events[1:] == [
        ("attributes", 17),
        ("identity", 17),
        ("apply-acl", 17),
        ("verify-acl", 17),
    ]
    assert opened.identity == windows.FileIdentity(7, 11)


def test_verified_open_rejects_reparse_before_acl() -> None:
    api = RecordingAPI(attributes=0x10 | windows.FILE_ATTRIBUTE_REPARSE_POINT)
    adapter = windows.Win32Adapter(api=api)

    with pytest.raises(windows.WindowsStateError, match="reparse"):
        adapter.open_verified(
            Path("C:/profile/link"), directory=True, creation=windows.OPEN_EXISTING,
            access=windows.FILE_READ_ATTRIBUTES, private=True,
        )

    assert ("apply-acl", 17) not in api.events
    assert api.events[-1] == ("close", 17)


def test_handle_verification_rejects_identity_change() -> None:
    api = RecordingAPI(identity=(2, 3))
    adapter = windows.Win32Adapter(api=api)
    opened = adapter.open_verified(
        Path("C:/profile"), directory=True, creation=windows.OPEN_EXISTING,
        access=windows.FILE_READ_ATTRIBUTES, private=False,
    )
    api.identity = (2, 4)
    with pytest.raises(windows.WindowsStateError, match="changed"):
        adapter.verify_handle(opened)


def test_child_open_verifies_parent_then_uses_relative_native_boundary() -> None:
    api = RecordingAPI()
    adapter = windows.Win32Adapter(api=api)
    parent = windows.WinHandle(
        17, Path("C:/profile"), windows.FileIdentity(7, 11), True
    )

    child = adapter.open_child(
        parent,
        "onboarding",
        directory=True,
        disposition=windows.FILE_OPEN_IF,
        access=windows.FILE_READ_ATTRIBUTES,
        private=True,
    )

    names = [event[0] for event in api.events]
    assert names[:3] == ["identity", "attributes", "create-relative"]
    assert names[3:] == ["attributes", "identity", "apply-acl", "verify-acl"]
    relative = api.events[2]
    assert relative[1:3] == (17, "onboarding")
    assert relative[4] & windows.FILE_SHARE_DELETE == 0
    assert child.path == Path("C:/profile/onboarding")


def test_partial_effect_mapping_names_only_safe_relative_artifacts() -> None:
    current = str(windows._current_partial_effect_error()).lower()
    assert "current.json" in current
    assert "durability" in current and "inspect" in current and "retry" in current

    history = str(
        windows._history_partial_effect_error(
            "20260715T151617Z.json", ".history.uuid.tmp"
        )
    ).lower()
    assert "history/20260715t151617z.json" in history
    assert "current.json remains active" in history
    assert "history/.history.uuid.tmp" in history
    assert "inspect" in history and "retry" in history
    assert "c:\\" not in history and "/users/" not in history


def test_dispatch_preserves_safe_windows_error_text(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FailingBackend:
        class WindowsStateError(Exception):
            pass

        @staticmethod
        def load_current_bytes(home):
            del home
            raise FailingBackend.WindowsStateError(
                "current.json may require inspection before retrying."
            )

    monkeypatch.setattr(state, "_backend_kind", lambda platform_name=None: "windows")
    monkeypatch.setattr(state, "_WINDOWS_BACKEND", FailingBackend())
    with pytest.raises(state.StateIOError, match="current.json.*inspection.*retrying"):
        state.load_current("C:/profile")


def test_lock_retry_is_bounded_and_maps_busy() -> None:
    class BusyAPI(RecordingAPI):
        def try_lock(self, handle):
            self.events.append(("try-lock", handle))
            return False

        def monotonic(self):
            return 1.0 + 0.3 * sum(event[0] == "try-lock" for event in self.events)

        def sleep(self, seconds):
            self.events.append(("sleep", seconds))

    api = BusyAPI()
    adapter = windows.Win32Adapter(api=api)
    with pytest.raises(windows.WindowsStateError, match="busy; retry"):
        adapter.acquire_lock(17, timeout=0.5, retry=0.01)
    assert 1 < sum(event[0] == "try-lock" for event in api.events) < 5


@pytest.mark.parametrize(
    ("pointer_size", "expected_offset", "expected_structure_size"),
    [(4, 12, 16), (8, 20, 24)],
)
def test_file_rename_marshalling_uses_windows_abi_and_full_buffer(
    pointer_size: int, expected_offset: int, expected_structure_size: int
) -> None:
    name = "current.json"
    encoded = name.encode("utf-16-le")
    buffer, information_type = windows._marshal_rename_info(
        0x1234, name, replace=True, pointer_size=pointer_size
    )
    information = information_type.from_buffer(buffer)

    assert information_type.FileName.offset == expected_offset
    assert ctypes.sizeof(information_type) == expected_structure_size
    assert ctypes.alignment(information_type) == pointer_size
    assert len(buffer) == expected_structure_size + len(encoded) + 2
    assert information.ReplaceIfExists == 1
    assert information.RootDirectory == 0x1234
    assert information.FileNameLength == len(encoded)
    start = information_type.FileName.offset
    assert buffer.raw[start : start + len(encoded)] == encoded
    assert len(buffer) - (start + len(encoded)) >= 4
    assert buffer.raw[-2:] == b"\x00\x00"


def test_rename_handle_passes_full_marshaled_buffer_to_kernel() -> None:
    captured: dict[str, object] = {}

    class FakeKernel32:
        @staticmethod
        def SetFileInformationByHandle(source, info_class, buffer, size):
            captured.update(
                source=source,
                info_class=info_class,
                raw=bytes(buffer.raw[:size]),
                size=size,
            )
            return True

    api = object.__new__(windows.Kernel32API)
    api.kernel32 = FakeKernel32()
    api.rename_handle(41, 73, "history.json", replace=False)

    pointer_size = ctypes.sizeof(ctypes.c_void_p)
    information_type = windows._file_rename_info_type(pointer_size)
    encoded = "history.json".encode("utf-16-le")
    assert captured["source"] == 41
    assert captured["info_class"] == windows.FILE_RENAME_INFO_CLASS
    assert captured["size"] == ctypes.sizeof(information_type) + len(encoded) + 2
    information = information_type.from_buffer_copy(captured["raw"])
    assert information.ReplaceIfExists == 0
    assert information.RootDirectory == 73
    assert information.FileNameLength == len(encoded)


def test_ancestor_access_is_exactly_read_and_traverse_only() -> None:
    assert windows.ANCESTOR_DIRECTORY_ACCESS == (
        windows.FILE_LIST_DIRECTORY
        | windows.FILE_TRAVERSE
        | windows.FILE_READ_ATTRIBUTES
        | windows.SYNCHRONIZE
    )
    assert windows.ANCESTOR_DIRECTORY_ACCESS & windows.FILE_WRITE_ATTRIBUTES == 0
    assert windows.ANCESTOR_DIRECTORY_ACCESS & windows.WRITE_DAC == 0
    assert windows.ANCESTOR_DIRECTORY_ACCESS & windows.WRITE_OWNER == 0
    assert windows.PRIVATE_DIRECTORY_ACCESS & windows.FILE_WRITE_ATTRIBUTES
    assert windows.PRIVATE_DIRECTORY_ACCESS & windows.WRITE_DAC
    assert windows.PRIVATE_DIRECTORY_ACCESS & windows.WRITE_OWNER


def test_private_acl_requires_exact_owner_and_two_exact_allow_aces() -> None:
    current = "S-1-5-21-1000"
    exact = (
        "D:P(A;;FA;;;SY)"
        "(A;;FA;;;S-1-5-21-1000)"
    )
    windows._validate_private_acl(current, exact, current, directory=False)
    windows._validate_private_acl(
        current,
        "D:P(A;OICI;FA;;;SY)(A;OICI;FA;;;S-1-5-21-1000)",
        current,
        directory=True,
    )

    with pytest.raises(windows.WindowsStateError, match="owner"):
        windows._validate_private_acl(
            "S-1-5-21-9999", exact, current, directory=False
        )
    with pytest.raises(windows.WindowsStateError, match="ACL"):
        windows._validate_private_acl(
            current, exact + "(A;;FA;;;WD)", current, directory=False
        )


def test_obj_dont_reparse_status_maps_without_dos_conversion() -> None:
    class FakeNtDll:
        @staticmethod
        def NtCreateFile(*args):
            del args
            return windows.STATUS_REPARSE_POINT_ENCOUNTERED

        @staticmethod
        def RtlNtStatusToDosError(status):
            del status
            raise AssertionError("documented reparse status must be handled directly")

    api = object.__new__(windows.Kernel32API)
    api.ntdll = FakeNtDll()
    with pytest.raises(windows.WindowsStateError, match="reparse"):
        api.create_relative(
            17,
            "junction",
            access=windows.FILE_READ_ATTRIBUTES,
            share=windows.SECURE_SHARE_MODE,
            disposition=windows.FILE_OPEN,
            directory=True,
            private=False,
        )


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_round_trip_and_profile_isolation(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    windows.save_current_bytes(first, b'{"profile":"first"}\n')
    windows.save_current_bytes(second, b'{"profile":"second"}\n')
    assert windows.load_current_bytes(first) == b'{"profile":"first"}\n'
    assert windows.load_current_bytes(second) == b'{"profile":"second"}\n'


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_round_trip_beneath_default_user_profile() -> None:
    user_profile = Path(os.environ["USERPROFILE"])
    with tempfile.TemporaryDirectory(
        prefix="coworker-onboarding-", dir=user_profile
    ) as directory:
        home = Path(directory)
        windows.save_current_bytes(home, b'{"profile":"default-user"}\n')
        assert windows.load_current_bytes(home) == b'{"profile":"default-user"}\n'


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_private_acl_apply_and_verify(tmp_path: Path) -> None:
    path = windows.save_current_bytes(tmp_path, b"{}\n")
    assert windows.native_acl_is_private(path)
    assert windows.native_acl_is_private(path.parent)
    assert windows.native_acl_is_private(path.parent / "history")


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_reparse_component_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    link = tmp_path / "profile-link"
    try:
        os.symlink(target, link, target_is_directory=True)
    except OSError as error:
        pytest.skip(f"reparse creation unavailable: {error}")
    with pytest.raises(windows.WindowsStateError, match="reparse"):
        windows.save_current_bytes(link, b"{}\n")


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_junction_component_is_rejected(tmp_path: Path) -> None:
    target = tmp_path / "junction-target"
    target.mkdir()
    junction = tmp_path / "profile-junction"
    created = subprocess.run(
        ["cmd", "/c", "mklink", "/J", str(junction), str(target)],
        capture_output=True,
        text=True,
        check=False,
    )
    if created.returncode:
        pytest.skip(f"junction creation unavailable: {created.stderr.strip()}")
    with pytest.raises(windows.WindowsStateError, match="reparse"):
        windows.save_current_bytes(junction, b"{}\n")


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_acl_rejects_extra_ace_and_repairs_owner_when_fixture_allows(
    tmp_path: Path,
) -> None:
    path = windows.save_current_bytes(tmp_path, b"{}\n")
    extra = subprocess.run(
        ["icacls", str(path), "/grant", "*S-1-1-0:F"],
        capture_output=True,
        text=True,
        check=False,
    )
    if extra.returncode:
        pytest.skip(f"ACL mutation unavailable: {extra.stderr.strip()}")
    assert not windows.native_acl_is_private(path)
    assert windows.load_current_bytes(tmp_path) == b"{}\n"
    assert windows.native_acl_is_private(path)

    foreign = subprocess.run(
        ["icacls", str(path), "/setowner", "*S-1-5-18"],
        capture_output=True,
        text=True,
        check=False,
    )
    if foreign.returncode:
        pytest.skip("foreign-owner fixture requires Windows ownership privilege")
    assert not windows.native_acl_is_private(path)
    assert windows.load_current_bytes(tmp_path) == b"{}\n"
    assert windows.native_acl_is_private(path)


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_atomic_replacement_and_no_replace_history(tmp_path: Path) -> None:
    windows.save_current_bytes(tmp_path, b'{"generation":1}\n')
    windows.save_current_bytes(tmp_path, b'{"generation":2}\n')
    assert windows.load_current_bytes(tmp_path) == b'{"generation":2}\n'
    name = "20260715T151617Z.json"
    history = windows.complete_current_bytes(tmp_path, name, lambda value: value)
    assert history.read_bytes() == b'{"generation":2}\n'
    windows.save_current_bytes(tmp_path, b'{"generation":3}\n')
    with pytest.raises(windows.WindowsStateError, match="already exists"):
        windows.complete_current_bytes(tmp_path, name, lambda value: value)


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_clear_and_generation_conflict(tmp_path: Path) -> None:
    windows.save_current_bytes(tmp_path, b'{"generation":1}\n')
    assert windows.clear_current_bytes(tmp_path, lambda value: value)
    assert windows.load_current_bytes(tmp_path) is None
    assert not windows.clear_current_bytes(tmp_path, lambda value: value)


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_lock_timeout_and_recovery(tmp_path: Path) -> None:
    holder_code = r"""
import importlib.util, pathlib, sys
path = pathlib.Path(sys.argv[1])
spec = importlib.util.spec_from_file_location("onboarding_state_windows_holder", path)
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
with module.native_locked_profile(sys.argv[2]):
    print("locked", flush=True)
    sys.stdin.readline()
"""
    process = subprocess.Popen(
        [sys.executable, "-c", holder_code, str(WINDOWS_SCRIPT), str(tmp_path)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    try:
        assert process.stdout is not None
        assert process.stdout.readline().strip() == "locked"
        with pytest.raises(windows.WindowsStateError, match="busy; retry"):
            windows.load_current_bytes(tmp_path, lock_timeout=0.05)
        assert process.stdin is not None
        process.stdin.write("release\n")
        process.stdin.flush()
        assert process.wait(timeout=5) == 0
    finally:
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
    assert windows.load_current_bytes(tmp_path) is None


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_concurrent_save_complete_clear_remain_consistent(tmp_path: Path) -> None:
    from concurrent.futures import ThreadPoolExecutor

    windows.save_current_bytes(tmp_path, b'{"generation":0}\n')
    when = datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
    name = when.strftime("%Y%m%dT%H%M%SZ.json")
    with ThreadPoolExecutor(max_workers=3) as pool:
        outcomes = [
            pool.submit(windows.save_current_bytes, tmp_path, b'{"generation":1}\n'),
            pool.submit(windows.complete_current_bytes, tmp_path, name, lambda value: value),
            pool.submit(windows.clear_current_bytes, tmp_path, lambda value: value),
        ]
        for outcome in outcomes:
            try:
                outcome.result()
            except windows.WindowsStateError:
                pass
    current = windows.load_current_bytes(tmp_path)
    assert current in (None, b'{"generation":1}\n')


@pytest.mark.skipif(os.name != "nt", reason="Windows native resume acceptance")
def test_native_injected_post_commit_failure_reports_partial_effect(tmp_path: Path) -> None:
    class FailingFlush(windows.Win32Adapter):
        def flush_directory(self, directory):
            if (directory.path / "current.json").exists():
                raise windows.WindowsStateError("injected directory flush failure")
            super().flush_directory(directory)

    with pytest.raises(windows.WindowsStateError, match="current.json"):
        windows.save_current_bytes(tmp_path, b"{}\n", adapter=FailingFlush())
    assert (tmp_path / "onboarding/ericsson/current.json").exists()
