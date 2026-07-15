from __future__ import annotations

import importlib
import hashlib
import json
import os
import stat
import subprocess
import sys
import threading
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = (
    REPO / "skills/ericsson/onboard-ericsson-capabilities/scripts"
)
SCRIPT = SCRIPTS / "onboarding_state.py"
sys.path.insert(0, str(SCRIPTS))

import onboarding_state as state  # noqa: E402


FACTS = {
    "state": "unknown-needs-check",
    "discoverable": True,
    "enabled": True,
    "platformSupported": True,
    "requiredSettingsConfigured": False,
    "permissionAdequate": None,
    "dependencyAvailable": None,
    "authenticationValidated": None,
    "safeProbeSucceeded": None,
}


def valid_state(**overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "schemaVersion": "1.0",
        "catalogVersion": "0.4.0",
        "selectedCapabilities": ["jira-tools"],
        "maturity": {"jira-tools": "available"},
        "readinessFacts": {"jira-tools": dict(FACTS)},
        "completedSteps": ["Learned what Jira tools read and may change."],
        "pendingActions": ["Configure Jira in Tools & Keys."],
        "artifactPointers": ["onboarding/demo-summary.json"],
        "nextPrompt": "Help me check Jira readiness.",
        "createdAt": "2026-07-15T14:00:00Z",
        "updatedAt": "2026-07-15T14:05:00Z",
    }
    payload.update(overrides)
    return payload


@pytest.fixture
def home(tmp_path: Path) -> Path:
    return tmp_path / "profile"


def test_resolve_home_prefers_explicit_then_hermes_then_environment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    explicit = tmp_path / "explicit"
    runtime = tmp_path / "runtime"
    env = tmp_path / "environment"
    fake = type(sys)("hermes_constants")
    fake.get_hermes_home = lambda: runtime  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "hermes_constants", fake)
    monkeypatch.setenv("HERMES_HOME", str(env))

    assert state.resolve_home(explicit) == explicit.resolve()
    assert state.resolve_home() == runtime.resolve()

    fake.get_hermes_home = lambda: None  # type: ignore[attr-defined]
    assert state.resolve_home() == env.resolve()


def test_resolve_home_refuses_to_guess_a_default(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("HERMES_HOME", raising=False)
    monkeypatch.delitem(sys.modules, "hermes_constants", raising=False)
    real_import = importlib.import_module

    def absent(name: str, package: str | None = None):
        if name == "hermes_constants":
            raise ModuleNotFoundError(name)
        return real_import(name, package)

    monkeypatch.setattr(importlib, "import_module", absent)

    with pytest.raises(state.StateError, match="active Co-Worker profile home"):
        state.resolve_home()


def test_validate_state_preserves_configuration_and_permission_facts() -> None:
    validated = state.validate_state(valid_state())

    assert validated == valid_state()
    facts = validated["readinessFacts"]["jira-tools"]
    assert facts["requiredSettingsConfigured"] is False
    assert facts["permissionAdequate"] is None
    assert set(facts) == {"state", *state.READINESS_FACT_FIELDS}


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schemaVersion", ""),
        ("catalogVersion", "current" * 100),
        ("selectedCapabilities", ["Not A Slug"]),
        ("selectedCapabilities", ["jira-tools", "jira-tools"]),
        ("maturity", {"jira-tools": "runnable"}),
        ("completedSteps", [7]),
        ("pendingActions", ["x" * 2049]),
        ("nextPrompt", "x" * 4097),
        ("createdAt", "2026-07-15"),
        ("updatedAt", "2026-07-15T14:05:00"),
    ],
)
def test_validate_state_rejects_invalid_schema_values(
    field: str, value: object
) -> None:
    with pytest.raises(state.StateValidationError):
        state.validate_state(valid_state(**{field: value}))


def test_validate_state_rejects_missing_and_unknown_top_level_fields() -> None:
    missing = valid_state()
    missing.pop("catalogVersion")
    unknown = valid_state(unredactedDiagnostics="not allowed")

    with pytest.raises(state.StateValidationError):
        state.validate_state(missing)
    with pytest.raises(state.StateValidationError):
        state.validate_state(unknown)


@pytest.mark.parametrize(
    "mutation",
    [
        {"configured": True},
        {"permissionsValidated": True},
        {"requiredSettingsConfigured": "yes"},
        {"permissionAdequate": 1},
        {"state": "installed"},
    ],
)
def test_validate_state_rejects_renamed_unknown_or_invalid_readiness_facts(
    mutation: dict[str, object],
) -> None:
    facts = dict(FACTS)
    facts.update(mutation)
    if "configured" in mutation:
        facts.pop("requiredSettingsConfigured")
    if "permissionsValidated" in mutation:
        facts.pop("permissionAdequate")

    with pytest.raises(state.StateValidationError):
        state.validate_state(valid_state(readinessFacts={"jira-tools": facts}))


@pytest.mark.parametrize(
    "payload",
    [
        {"resumeToken": "ordinary-looking"},
        {"nested": {"PASSWORD": "ordinary-looking"}},
        {"items": [{"session-cookie": "ordinary-looking"}]},
        {"certificateHint": "ordinary-looking"},
        {"private_key_path": "ordinary-looking"},
        {"clientSecretName": "ordinary-looking"},
    ],
)
def test_validate_state_rejects_sensitive_key_names_recursively(
    payload: dict[str, object],
) -> None:
    candidate = valid_state()
    candidate["pendingActions"] = [payload]

    with pytest.raises(state.StateValidationError) as caught:
        state.validate_state(candidate)

    assert "ordinary-looking" not in str(caught.value)


@pytest.mark.parametrize(
    "protected_value",
    [
        "Bearer abcdefghijklmnopqrstuvwxyz012345",
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123456789",
        "-----BEGIN PRIVATE KEY-----",
        "AKIAIOSFODNN7EXAMPLE",
    ],
)
def test_protected_values_are_rejected_without_writing_or_echoing(
    home: Path, protected_value: str
) -> None:
    payload = valid_state(nextPrompt=protected_value)

    with pytest.raises(state.StateValidationError) as caught:
        state.save_current(home, payload)

    assert protected_value not in str(caught.value)
    assert not (home / "onboarding/ericsson/current.json").exists()


@pytest.mark.parametrize(
    "pointer",
    [
        "../outside.json",
        "safe/../../outside.json",
        "https://example.invalid/result.json",
        "file:///tmp/result.json",
        "bad\x00path",
        "bad\npath",
    ],
)
def test_artifact_pointers_reject_traversal_urls_and_control_characters(
    pointer: str,
) -> None:
    with pytest.raises(state.StateValidationError):
        state.validate_state(valid_state(artifactPointers=[pointer]))


def test_save_load_round_trip_replaces_the_single_current_journey(home: Path) -> None:
    first = valid_state(nextPrompt="First prompt")
    second = valid_state(
        completedSteps=["First", "Second"],
        nextPrompt="Second prompt",
        updatedAt="2026-07-15T14:10:00Z",
    )

    current = state.save_current(home, first)
    assert state.load_current(home) == first
    assert state.save_current(home, second) == current
    assert state.load_current(home) == second
    assert list(current.parent.glob("current*.json")) == [current]
    assert not list(current.parent.glob(".*.tmp"))


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_state_directories_and_file_have_restrictive_modes(home: Path) -> None:
    current = state.save_current(home, valid_state())

    assert stat.S_IMODE(current.stat().st_mode) == 0o600
    assert stat.S_IMODE(current.parent.stat().st_mode) == 0o700
    assert stat.S_IMODE(current.parent.parent.stat().st_mode) == 0o700


def test_atomic_write_cleans_temporary_file_when_replace_fails(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_replace(source, destination, *args, **kwargs) -> None:
        del source, destination, args, kwargs
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(state.StateIOError, match="write onboarding state"):
        state.save_current(home, valid_state())

    root = home / "onboarding/ericsson"
    assert not (root / "current.json").exists()
    assert not list(root.glob(".*.tmp"))


def test_atomic_write_cleans_temporary_file_when_write_fails(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def fail_write(descriptor: int, content) -> int:
        del descriptor, content
        raise OSError("simulated write failure")

    monkeypatch.setattr(os, "write", fail_write)
    with pytest.raises(state.StateIOError, match="write onboarding state"):
        state.save_current(home, valid_state())
    root = home / "onboarding/ericsson"
    assert not (root / "current.json").exists()
    assert not list(root.glob(".*.tmp"))


@pytest.mark.parametrize("failure", ["write", "replace"])
def test_persistent_uuid_temp_cleanup_failure_does_not_mask_write_error(
    home: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    original_unlink = os.unlink

    def fail_temp_unlink(path, *args, **kwargs):
        if str(path).endswith(".tmp"):
            raise OSError("persistent temporary cleanup failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", fail_temp_unlink)
    if failure == "write":
        def fail_write(descriptor: int, content) -> int:
            del descriptor, content
            raise OSError("injected write failure")

        monkeypatch.setattr(os, "write", fail_write)
    else:
        def fail_replace(*args, **kwargs) -> None:
            del args, kwargs
            raise OSError("injected replace failure")

        monkeypatch.setattr(os, "replace", fail_replace)

    with pytest.raises(state.StateIOError) as caught:
        state.save_current(home, valid_state())
    message = str(caught.value).lower()
    assert "write onboarding state" in message
    assert "lock onboarding state" not in message
    assert list((home / "onboarding/ericsson").glob(".*.tmp"))


def test_transaction_body_oserror_is_not_reclassified_as_lock_failure(home: Path) -> None:
    with pytest.raises(OSError, match="transaction body failure") as caught:
        with state._locked_directory(home):
            raise OSError("transaction body failure")
    assert "lock onboarding state" not in str(caught.value).lower()


def test_complete_moves_current_to_timestamped_history_and_clear_removes_active(
    home: Path,
) -> None:
    state.save_current(home, valid_state())
    when = datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)

    history = state.complete_current(home, now=when)

    assert history == home.resolve() / "onboarding/ericsson/history/20260715T151617Z.json"
    assert state.load_current(home) is None
    assert json.loads(history.read_text(encoding="utf-8")) == valid_state()
    assert state.clear_current(home) is False

    state.save_current(home, valid_state())
    assert state.clear_current(home) is True
    assert state.clear_current(home) is False


def test_completion_never_overwrites_existing_history(home: Path) -> None:
    when = datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
    state.save_current(home, valid_state())
    state.complete_current(home, now=when)
    state.save_current(home, valid_state(updatedAt="2026-07-15T15:17:00Z"))

    with pytest.raises(state.StateIOError, match="history entry already exists"):
        state.complete_current(home, now=when)

    assert state.load_current(home) is not None


def test_symlinked_state_paths_are_refused(home: Path, tmp_path: Path) -> None:
    root = home / "onboarding"
    root.mkdir(parents=True)
    target = tmp_path / "outside"
    target.mkdir()
    (root / "ericsson").symlink_to(target, target_is_directory=True)

    with pytest.raises(state.StateIOError, match="symbolic link"):
        state.save_current(home, valid_state())
    assert not (target / "current.json").exists()


def test_state_persistence_fails_closed_without_secure_platform_primitives(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(state, "_SECURE_PLATFORM", False)
    with pytest.raises(state.StateIOError, match="unavailable on this platform"):
        state.save_current(home, valid_state())
    assert not home.exists()


def run_cli(home: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(SCRIPT), "--home", str(home), *args],
        cwd=REPO,
        text=True,
        capture_output=True,
        check=False,
    )


def test_cli_save_show_complete_and_clear_return_safe_json(
    home: Path, tmp_path: Path
) -> None:
    source = tmp_path / "sanitized-state.json"
    source.write_text(json.dumps(valid_state()), encoding="utf-8")

    saved = run_cli(home, "save", "--input", str(source))
    shown = run_cli(home, "show")
    completed = run_cli(home, "complete")
    cleared = run_cli(home, "clear")

    assert saved.returncode == shown.returncode == completed.returncode == 0
    assert json.loads(saved.stdout)["ok"] is True
    assert json.loads(shown.stdout) == {"ok": True, "state": valid_state()}
    assert json.loads(completed.stdout)["path"].endswith(".json")
    assert json.loads(cleared.stdout) == {"ok": True, "cleared": False}


def test_cli_validation_error_never_echoes_rejected_value(
    home: Path, tmp_path: Path
) -> None:
    protected_value = "Bearer abcdefghijklmnopqrstuvwxyz012345"
    source = tmp_path / "unsafe-state.json"
    source.write_text(
        json.dumps(valid_state(nextPrompt=protected_value)), encoding="utf-8"
    )

    result = run_cli(home, "save", "--input", str(source))
    output = json.loads(result.stdout)

    assert result.returncode == 1
    assert output["ok"] is False
    assert protected_value not in result.stdout
    assert "error" in output
    assert not (home / "onboarding/ericsson/current.json").exists()


def test_cli_usage_errors_are_safe_json(home: Path) -> None:
    result = run_cli(home, "save")

    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": "The onboarding state command is invalid.",
        "ok": False,
    }


def test_load_does_not_follow_current_swapped_to_symlink(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save_current(home, valid_state())
    outside = tmp_path / "outside.json"
    outside.write_text(json.dumps(valid_state(nextPrompt="outside")), encoding="utf-8")
    current = home / "onboarding/ericsson/current.json"
    original_open = os.open
    swapped = False

    def swap_after_open(path, flags, *args, **kwargs):
        nonlocal swapped
        descriptor = original_open(path, flags, *args, **kwargs)
        if os.fspath(path) == "current.json" and not swapped:
            swapped = True
            current.unlink()
            current.symlink_to(outside)
        return descriptor

    monkeypatch.setattr(os, "open", swap_after_open)

    assert state.load_current(home) == valid_state()
    assert outside.read_text(encoding="utf-8") == json.dumps(
        valid_state(nextPrompt="outside")
    )


def test_save_never_chmods_symlink_swapped_after_replace(
    home: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    outside = tmp_path / "outside.json"
    outside.write_text("outside", encoding="utf-8")
    outside.chmod(0o644)
    original_replace = os.replace

    def swap_after_replace(source, destination, *args, **kwargs):
        result = original_replace(source, destination, *args, **kwargs)
        destination_path = Path(destination)
        if destination_path.name == "current.json":
            current = home / "onboarding/ericsson/current.json"
            current.unlink()
            current.symlink_to(outside)
        return result

    monkeypatch.setattr(os, "replace", swap_after_replace)

    with pytest.raises(state.StateIOError):
        state.save_current(home, valid_state())
    assert stat.S_IMODE(outside.stat().st_mode) == 0o644
    assert outside.read_text(encoding="utf-8") == "outside"


@pytest.mark.parametrize("component", ["onboarding", "ericsson"])
def test_directory_component_swap_never_redirects_state_write(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    component: str,
) -> None:
    state.save_current(home, valid_state())
    outside = tmp_path / f"outside-{component}"
    outside.mkdir()
    (outside / "current.json").write_text("outside", encoding="utf-8")
    original_replace = os.replace
    swapped = False

    def swap_component_after_replace(source, destination, *args, **kwargs):
        nonlocal swapped
        result = original_replace(source, destination, *args, **kwargs)
        destination_name = os.fspath(destination)
        if str(destination_name).endswith("current.json") and not swapped:
            swapped = True
            if component == "ericsson":
                victim = home / "onboarding/ericsson"
            else:
                victim = home / "onboarding"
            moved = victim.with_name(victim.name + "-moved")
            victim.rename(moved)
            victim.symlink_to(outside, target_is_directory=True)
        return result

    monkeypatch.setattr(os, "replace", swap_component_after_replace)

    with pytest.raises(state.StateIOError):
        state.save_current(home, valid_state(nextPrompt="replacement"))
    assert (outside / "current.json").read_text(encoding="utf-8") == "outside"


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_load_repairs_broad_existing_file_and_directory_modes(home: Path) -> None:
    current = state.save_current(home, valid_state())
    root = current.parent
    onboarding = root.parent
    current.chmod(0o666)
    root.chmod(0o755)
    onboarding.chmod(0o755)

    assert state.load_current(home) == valid_state()
    assert stat.S_IMODE(current.stat().st_mode) == 0o600
    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    assert stat.S_IMODE(onboarding.stat().st_mode) == 0o700


@pytest.mark.skipif(os.name != "posix", reason="POSIX permissions only")
def test_permission_repair_fails_closed(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = state.save_current(home, valid_state())
    current.chmod(0o644)

    def deny_fchmod(fd: int, mode: int) -> None:
        raise PermissionError("denied")

    monkeypatch.setattr(os, "fchmod", deny_fchmod)
    with pytest.raises(state.StateIOError):
        state.load_current(home)


@pytest.mark.parametrize(
    "protected_value",
    [
        "Bearer abcdefghijklmnopqrstuvwxyz012345",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.signature123456789",
        "ghp_0123456789abcdefghijklmnopqrstuvwxyz",
        "glpat-0123456789abcdefghijklmnopqrstuv",
        "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
        "AKIAIOSFODNN7EXAMPLE",
        "-----BEGIN PRIVATE KEY-----",
        "0123456789abcdef0123456789abcdef01234567",
    ],
)
@pytest.mark.parametrize(
    "wrapper",
    [lambda value: f"{value} follows",
     lambda value: f"before {value} after",
     lambda value: f"prefix {value}"],
)
def test_embedded_credential_patterns_are_rejected_without_echo(
    home: Path, protected_value: str, wrapper
) -> None:
    embedded = wrapper(protected_value)
    with pytest.raises(state.StateValidationError) as caught:
        state.save_current(home, valid_state(nextPrompt=embedded))
    assert embedded not in str(caught.value)
    assert protected_value not in str(caught.value)
    assert not (home / "onboarding/ericsson/current.json").exists()


@pytest.mark.parametrize(
    "ordinary",
    [
        "Use a bearer credential through Tools & Keys, never in chat.",
        "The artifact checksum is 0123456789abcdef0123456789abcdef.",
        "Ask the key owner to validate access.",
        "The issue identifier is ERIC-12345 and no credential is stored.",
    ],
)
def test_credential_detection_does_not_reject_ordinary_prose(ordinary: str) -> None:
    assert state.validate_state(valid_state(nextPrompt=ordinary))["nextPrompt"] == ordinary


@pytest.mark.parametrize("constant", ["NaN", "Infinity", "-Infinity"])
def test_cli_rejects_nonstandard_json_constants(
    home: Path, tmp_path: Path, constant: str
) -> None:
    source = tmp_path / "hostile.json"
    text = json.dumps(valid_state()).replace('"unknown-needs-check"', constant, 1)
    source.write_text(text, encoding="utf-8")
    result = run_cli(home, "save", "--input", str(source))
    assert_safe_cli_error(result, constant)
    assert "non-standard number" in json.loads(result.stdout)["error"]


def test_cli_rejects_duplicate_keys_even_when_last_value_looks_safe(
    home: Path, tmp_path: Path
) -> None:
    hidden = "Bearer abcdefghijklmnopqrstuvwxyz012345"
    source = tmp_path / "duplicate.json"
    text = json.dumps(valid_state()).replace(
        '"nextPrompt": "Help me check Jira readiness."',
        f'"nextPrompt": {json.dumps(hidden)}, "nextPrompt": "safe"',
    )
    source.write_text(text, encoding="utf-8")
    result = run_cli(home, "save", "--input", str(source))
    assert_safe_cli_error(result, hidden)


def test_validate_state_rejects_excessive_depth_without_recursion_error() -> None:
    nested: object = "safe"
    for _ in range(100):
        nested = [nested]
    payload = valid_state()
    payload["pendingActions"] = [nested]
    with pytest.raises(state.StateValidationError, match="structure limits"):
        state.validate_state(payload)


@pytest.mark.parametrize("wrong", [["ready"], {"ready": True}, 7])
def test_wrong_enum_types_raise_safe_validation_errors(wrong: object) -> None:
    facts = dict(FACTS)
    facts["state"] = wrong
    with pytest.raises(state.StateValidationError):
        state.validate_state(valid_state(readinessFacts={"jira-tools": facts}))


def test_cli_invalid_home_with_nul_returns_one_safe_json_object(capsys) -> None:
    assert state.main(["--home", "bad\x00home", "show"]) == 1
    captured = capsys.readouterr()
    result = subprocess.CompletedProcess([], 1, captured.out, captured.err)
    assert_safe_cli_error(result, "bad")


def assert_safe_cli_error(
    result: subprocess.CompletedProcess[str], rejected: str
) -> None:
    assert result.returncode == 1
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    output = json.loads(result.stdout)
    assert output["ok"] is False
    assert set(output) == {"ok", "error"}
    assert rejected not in result.stdout


@pytest.mark.parametrize(
    "pointer",
    [
        r"\\server\share\artifact.json",
        "//server/share/artifact.json",
        r"\\?\C:\artifact.json",
        r"\\.\PhysicalDrive0",
        r"\Device\HarddiskVolume1\artifact.json",
        r"C:\safe\artifact.json:stream",
        "safe/artifact.json:stream",
        r"C:\CON\artifact.json",
    ],
)
def test_artifact_pointers_reject_network_device_and_ads_paths(pointer: str) -> None:
    with pytest.raises(state.StateValidationError):
        state.validate_state(valid_state(artifactPointers=[pointer]))


@pytest.mark.parametrize(
    "pointer",
    [
        "/tmp/onboarding/artifact.json",
        "onboarding/artifact.json",
        r"C:\Users\pilot\artifact.json",
    ],
)
def test_artifact_pointers_allow_normal_local_paths(pointer: str) -> None:
    assert state.validate_state(valid_state(artifactPointers=[pointer]))[
        "artifactPointers"
    ] == [pointer]


def test_complete_detects_uncooperative_current_replacement_and_preserves_it(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = valid_state(nextPrompt="original")
    replacement = valid_state(
        nextPrompt="replacement", updatedAt="2026-07-15T14:10:00Z"
    )
    state.save_current(home, original)
    original_link = os.link
    replaced = False

    def replace_current_after_archive(source, destination, *args, **kwargs):
        nonlocal replaced
        result = original_link(source, destination, *args, **kwargs)
        if not replaced:
            replaced = True
            current = home / "onboarding/ericsson/current.json"
            temp = current.with_name("attacker-replacement.json")
            temp.write_text(json.dumps(replacement), encoding="utf-8")
            os.replace(temp, current)
        return result

    monkeypatch.setattr(os, "link", replace_current_after_archive)

    with pytest.raises(state.StateIOError, match="changed"):
        state.complete_current(
            home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
        )
    assert state.load_current(home) == replacement
    assert not list((home / "onboarding/ericsson").glob("*.remove"))


@pytest.mark.parametrize("operation", ["complete", "clear"])
def test_complete_and_clear_never_follow_current_swapped_to_symlink(
    home: Path,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    state.save_current(home, valid_state())
    outside = tmp_path / f"outside-{operation}.json"
    outside.write_text("outside", encoding="utf-8")
    original_rename = os.rename
    swapped = False

    def swap_before_remove(source, destination, *args, **kwargs):
        nonlocal swapped
        if os.fspath(source) == "current.json" and not swapped:
            swapped = True
            current = home / "onboarding/ericsson/current.json"
            current.unlink()
            current.symlink_to(outside)
        return original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", swap_before_remove)
    with pytest.raises(state.StateIOError):
        if operation == "complete":
            state.complete_current(
                home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
            )
        else:
            state.clear_current(home)
    assert outside.read_text(encoding="utf-8") == "outside"


def test_concurrent_save_waits_for_complete_and_new_journey_survives(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = valid_state(nextPrompt="first")
    second = valid_state(nextPrompt="second", updatedAt="2026-07-15T14:10:00Z")
    state.save_current(home, first)
    archived = threading.Event()
    release = threading.Event()
    original_link = os.link

    def pause_after_archive(source, destination, *args, **kwargs):
        result = original_link(source, destination, *args, **kwargs)
        archived.set()
        assert release.wait(5)
        return result

    monkeypatch.setattr(os, "link", pause_after_archive)
    errors: list[BaseException] = []
    complete = threading.Thread(
        target=lambda: _capture_error(
            errors,
            state.complete_current,
            home,
            datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc),
        )
    )
    complete.start()
    assert archived.wait(5)
    save = threading.Thread(target=lambda: _capture_error(errors, state.save_current, home, second))
    save.start()
    release.set()
    complete.join(5)
    save.join(5)
    assert not errors, [
        (repr(error), repr(error.__cause__), getattr(error.__cause__, "filename", None))
        for error in errors
    ]
    assert state.load_current(home) == second


def test_concurrent_save_waits_for_clear_and_new_journey_survives(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    first = valid_state(nextPrompt="first")
    second = valid_state(nextPrompt="second", updatedAt="2026-07-15T14:10:00Z")
    state.save_current(home, first)
    entered = threading.Event()
    release = threading.Event()
    original_rename = os.rename

    def pause_before_rename(source, destination, *args, **kwargs):
        if os.fspath(source) == "current.json" and not entered.is_set():
            entered.set()
            assert release.wait(5)
        return original_rename(source, destination, *args, **kwargs)

    monkeypatch.setattr(os, "rename", pause_before_rename)
    errors: list[BaseException] = []
    clear = threading.Thread(target=lambda: _capture_error(errors, state.clear_current, home))
    clear.start()
    assert entered.wait(5)
    save = threading.Thread(target=lambda: _capture_error(errors, state.save_current, home, second))
    save.start()
    release.set()
    clear.join(5)
    save.join(5)
    assert not errors
    assert state.load_current(home) == second


def _capture_error(errors: list[BaseException], function, *args) -> None:
    try:
        function(*args)
    except BaseException as error:
        errors.append(error)


def test_same_timestamp_double_completion_has_one_archive_and_no_overwrite(
    home: Path,
) -> None:
    state.save_current(home, valid_state())
    when = datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
    barrier = threading.Barrier(3)
    results: list[Path] = []
    errors: list[BaseException] = []

    def complete() -> None:
        barrier.wait()
        try:
            results.append(state.complete_current(home, now=when))
        except BaseException as error:
            errors.append(error)

    threads = [threading.Thread(target=complete) for _ in range(2)]
    for thread in threads:
        thread.start()
    barrier.wait()
    for thread in threads:
        thread.join(5)

    assert len(results) == 1
    assert len(errors) == 1
    history = home / "onboarding/ericsson/history/20260715T151617Z.json"
    assert json.loads(history.read_text(encoding="utf-8")) == valid_state()
    assert state.load_current(home) is None


def test_concurrent_first_saves_safely_share_directory_initialization(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home.mkdir()
    barrier = threading.Barrier(2)
    original_mkdir = os.mkdir

    def synchronized_mkdir(path, *args, **kwargs):
        if os.fspath(path) == "onboarding":
            barrier.wait(timeout=5)
        return original_mkdir(path, *args, **kwargs)

    monkeypatch.setattr(os, "mkdir", synchronized_mkdir)
    errors: list[BaseException] = []
    threads = [
        threading.Thread(
            target=lambda index=index: _capture_error(
                errors,
                state.save_current,
                home,
                valid_state(
                    nextPrompt=f"journey-{index}",
                    updatedAt=f"2026-07-15T14:1{index}:00Z",
                ),
            )
        )
        for index in range(2)
    ]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(5)

    assert not errors, [
        (repr(error), repr(error.__cause__), getattr(error.__cause__, "filename", None))
        for error in errors
    ]
    assert state.load_current(home)["nextPrompt"] in {"journey-0", "journey-1"}


@pytest.mark.parametrize("operation", ["clear", "complete"])
@pytest.mark.parametrize("failure", ["open", "fchmod", "read", "digest", "unlink"])
def test_post_quarantine_failures_restore_accessible_current_and_report_recovery(
    home: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    failure: str,
) -> None:
    payload = valid_state(nextPrompt=f"preserve-after-{failure}")
    state.save_current(home, payload)
    current = home / "onboarding/ericsson/current.json"
    current_inode = current.stat().st_ino
    remove_seen = lambda: not current.exists() and any(
        current.parent.glob(".current.*.remove")
    )

    if failure == "open":
        original = state._open_regular_at

        def fail_open(directory, name, flags=os.O_RDONLY):
            if str(name).endswith(".remove"):
                raise state.StateIOError("injected quarantine open failure")
            return original(directory, name, flags)

        monkeypatch.setattr(state, "_open_regular_at", fail_open)
    elif failure == "fchmod":
        original = os.fchmod
        original_rename = os.rename

        def broaden_after_rename(source, destination, *args, **kwargs):
            result = original_rename(source, destination, *args, **kwargs)
            if str(destination).endswith(".remove"):
                next(current.parent.glob(".current.*.remove")).chmod(0o644)
            return result

        def fail_fchmod(descriptor: int, mode: int) -> None:
            if os.fstat(descriptor).st_ino == current_inode and remove_seen():
                raise PermissionError("injected quarantine fchmod failure")
            original(descriptor, mode)

        monkeypatch.setattr(os, "rename", broaden_after_rename)
        monkeypatch.setattr(os, "fchmod", fail_fchmod)
    elif failure == "read":
        original = os.read

        def fail_read(descriptor: int, amount: int) -> bytes:
            if os.fstat(descriptor).st_ino == current_inode and remove_seen():
                raise OSError("injected quarantine read failure")
            return original(descriptor, amount)

        monkeypatch.setattr(os, "read", fail_read)
    elif failure == "digest":
        original = hashlib.sha256
        calls = 0

        def fail_digest(content=b""):
            nonlocal calls
            calls += 1
            if calls == 2:
                raise RuntimeError("injected quarantine digest failure")
            return original(content)

        monkeypatch.setattr(hashlib, "sha256", fail_digest)
    else:
        original = os.unlink
        failed = False

        def fail_unlink(path, *args, **kwargs):
            nonlocal failed
            if str(path).endswith(".remove") and not failed:
                failed = True
                raise OSError("injected quarantine unlink failure")
            return original(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", fail_unlink)

    with pytest.raises(state.StateIOError) as caught:
        if operation == "complete":
            state.complete_current(
                home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
            )
        else:
            state.clear_current(home)

    message = str(caught.value).lower()
    assert "current.json" in message
    assert "retry" in message or "inspect" in message
    assert state.load_current(home) == payload
    assert not list(current.parent.glob(".current.*.remove"))
    history = current.parent / "history/20260715T151617Z.json"
    if operation == "complete":
        assert history.exists()
        assert "history" in message and "archiv" in message
    else:
        assert not history.exists()


@pytest.mark.parametrize("operation", ["clear", "complete"])
def test_post_unlink_fsync_failure_reports_irreversible_durability_state(
    home: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    state.save_current(home, valid_state())
    root = home / "onboarding/ericsson"
    root_inode = root.stat().st_ino
    original = os.fsync
    failed = False

    def fail_after_unlink(descriptor: int) -> None:
        nonlocal failed
        no_generation = not (root / "current.json").exists() and not list(
            root.glob(".current.*.remove")
        )
        if (
            not failed
            and os.fstat(descriptor).st_ino == root_inode
            and no_generation
        ):
            failed = True
            raise OSError("injected post-unlink fsync failure")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_after_unlink)
    with pytest.raises(state.StateIOError) as caught:
        if operation == "complete":
            state.complete_current(
                home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
            )
        else:
            state.clear_current(home)

    message = str(caught.value).lower()
    assert "durability" in message and "inspect" in message
    assert not (root / "current.json").exists()
    if operation == "complete":
        assert (root / "history/20260715T151617Z.json").exists()
        assert "history" in message


def test_new_directories_fsync_their_parents_in_creation_order(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home.mkdir()
    events: list[tuple[str, object]] = []
    original_mkdir = os.mkdir
    original_fsync = os.fsync

    def record_mkdir(path, *args, **kwargs):
        events.append(("mkdir", os.fspath(path)))
        return original_mkdir(path, *args, **kwargs)

    def record_fsync(descriptor: int) -> None:
        events.append(("fsync", os.fstat(descriptor).st_ino))
        original_fsync(descriptor)

    monkeypatch.setattr(os, "mkdir", record_mkdir)
    monkeypatch.setattr(os, "fsync", record_fsync)
    state.save_current(home, valid_state())
    state.complete_current(
        home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
    )

    mkdir_positions = {
        name: next(index for index, event in enumerate(events) if event == ("mkdir", name))
        for name in ("onboarding", "ericsson", "history")
    }
    home_inode = home.stat().st_ino
    onboarding_inode = (home / "onboarding").stat().st_ino
    root_inode = (home / "onboarding/ericsson").stat().st_ino
    assert any(
        index > mkdir_positions["onboarding"] and event == ("fsync", home_inode)
        for index, event in enumerate(events)
    )
    assert any(
        index > mkdir_positions["ericsson"] and event == ("fsync", onboarding_inode)
        for index, event in enumerate(events)
    )
    assert any(
        index > mkdir_positions["history"] and event == ("fsync", root_inode)
        for index, event in enumerate(events)
    )


def test_permission_repairs_fsync_the_verified_descriptor(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = state.save_current(home, valid_state())
    current.chmod(0o666)
    repaired_inode = current.stat().st_ino
    events: list[tuple[str, int]] = []
    original_fchmod = os.fchmod
    original_fsync = os.fsync

    def record_fchmod(descriptor: int, mode: int) -> None:
        original_fchmod(descriptor, mode)
        if os.fstat(descriptor).st_ino == repaired_inode:
            events.append(("fchmod", repaired_inode))

    def record_fsync(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == repaired_inode:
            events.append(("fsync", repaired_inode))
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fchmod", record_fchmod)
    monkeypatch.setattr(os, "fsync", record_fsync)
    assert state.load_current(home) == valid_state()
    assert events[:2] == [("fchmod", repaired_inode), ("fsync", repaired_inode)]


def test_parent_and_permission_fsync_failures_fail_closed(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    home.mkdir()
    home_inode = home.stat().st_ino
    original = os.fsync

    def fail_parent(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == home_inode:
            raise OSError("injected parent fsync failure")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_parent)
    with pytest.raises(state.StateIOError, match="durably create"):
        state.save_current(home, valid_state())
    assert not (home / "onboarding/ericsson/current.json").exists()


def test_permission_metadata_fsync_failure_fails_closed_with_current_accessible(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    current = state.save_current(home, valid_state())
    current.chmod(0o666)
    current_inode = current.stat().st_ino
    original = os.fsync

    def fail_current(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == current_inode:
            raise OSError("injected mode fsync failure")
        original(descriptor)

    monkeypatch.setattr(os, "fsync", fail_current)
    with pytest.raises(state.StateIOError, match="durably enforce"):
        state.load_current(home)
    assert current.exists()
    assert stat.S_IMODE(current.stat().st_mode) == 0o600


def test_quarantine_rollback_sync_order_is_link_sync_unlink_sync(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save_current(home, valid_state())
    root = home / "onboarding/ericsson"
    root_inode = root.stat().st_ino
    events: list[str] = []
    original_link = os.link
    original_unlink = os.unlink
    original_fsync = os.fsync
    original_digest = hashlib.sha256
    digest_calls = 0

    def record_link(source, destination, *args, **kwargs):
        if str(source).endswith(".remove") and destination == "current.json":
            events.append("link-current")
        return original_link(source, destination, *args, **kwargs)

    def record_unlink(path, *args, **kwargs):
        if str(path).endswith(".remove"):
            events.append("unlink-quarantine")
        return original_unlink(path, *args, **kwargs)

    def record_fsync(descriptor: int) -> None:
        if os.fstat(descriptor).st_ino == root_inode:
            events.append("fsync-root")
        original_fsync(descriptor)

    def fail_second_digest(content=b""):
        nonlocal digest_calls
        digest_calls += 1
        if digest_calls == 2:
            raise RuntimeError("injected digest failure")
        return original_digest(content)

    monkeypatch.setattr(os, "link", record_link)
    monkeypatch.setattr(os, "unlink", record_unlink)
    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(hashlib, "sha256", fail_second_digest)

    with pytest.raises(state.StateIOError):
        state.clear_current(home)
    assert events[-4:] == [
        "link-current",
        "fsync-root",
        "unlink-quarantine",
        "fsync-root",
    ]
    assert state.load_current(home) == valid_state()


def test_quarantine_rollback_sync_failure_keeps_named_recoverable_generations(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save_current(home, valid_state())
    root = home / "onboarding/ericsson"
    root_inode = root.stat().st_ino
    original_fsync = os.fsync
    original_digest = hashlib.sha256
    digest_calls = 0
    failed = False

    def fail_second_digest(content=b""):
        nonlocal digest_calls
        digest_calls += 1
        if digest_calls == 2:
            raise RuntimeError("injected digest failure")
        return original_digest(content)

    def fail_rollback_sync(descriptor: int) -> None:
        nonlocal failed
        if not failed and os.fstat(descriptor).st_ino == root_inode:
            failed = True
            raise OSError("injected rollback sync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(hashlib, "sha256", fail_second_digest)
    monkeypatch.setattr(os, "fsync", fail_rollback_sync)
    with pytest.raises(state.StateIOError) as caught:
        state.clear_current(home)
    message = str(caught.value)
    assert "current.json" in message and "recovery" in message
    assert (root / "current.json").exists()
    recovery = list(root.glob(".current.*.remove"))
    assert len(recovery) == 1
    assert os.path.samefile(root / "current.json", recovery[0])


def test_first_current_and_history_mutations_have_durable_call_order(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    events: list[tuple[str, str]] = []
    original_fsync = os.fsync
    original_replace = os.replace
    original_link = os.link
    original_unlink = os.unlink

    def descriptor_kind(descriptor: int) -> str:
        details = os.fstat(descriptor)
        return "dir" if stat.S_ISDIR(details.st_mode) else "file"

    def record_fsync(descriptor: int) -> None:
        events.append(("fsync", descriptor_kind(descriptor)))
        original_fsync(descriptor)

    def record_replace(source, destination, *args, **kwargs):
        events.append(("replace", str(destination)))
        return original_replace(source, destination, *args, **kwargs)

    def record_link(source, destination, *args, **kwargs):
        events.append(("link", str(destination)))
        return original_link(source, destination, *args, **kwargs)

    def record_unlink(path, *args, **kwargs):
        events.append(("unlink", str(path)))
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "fsync", record_fsync)
    monkeypatch.setattr(os, "replace", record_replace)
    monkeypatch.setattr(os, "link", record_link)
    monkeypatch.setattr(os, "unlink", record_unlink)
    state.save_current(home, valid_state())
    replace_at = events.index(("replace", "current.json"))
    assert ("fsync", "file") in events[:replace_at]
    assert ("fsync", "dir") in events[replace_at + 1 :]

    events.clear()
    state.complete_current(
        home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
    )
    link_at = events.index(("link", "20260715T151617Z.json"))
    history_unlink = next(
        index
        for index, event in enumerate(events)
        if index > link_at and event[0] == "unlink" and event[1].endswith(".tmp")
    )
    assert ("fsync", "file") in events[:link_at]
    assert ("fsync", "dir") in events[history_unlink + 1 :]


@pytest.mark.skipif(os.name != "posix", reason="POSIX lock test")
def test_second_process_lock_timeout_returns_busy_then_recovers(
    home: Path,
) -> None:
    state.save_current(home, valid_state())
    holder_source = """
import fcntl, os, sys, time
from pathlib import Path
sys.path.insert(0, sys.argv[1])
import onboarding_state as state
root = state._StateDirectory.open(Path(sys.argv[2]))
fd = os.open('.state.lock', os.O_RDWR | state._NOFOLLOW, dir_fd=root.root_fd)
fcntl.flock(fd, fcntl.LOCK_EX)
print('locked', flush=True)
time.sleep(1.5)
fcntl.flock(fd, fcntl.LOCK_UN)
os.close(fd)
root.close()
"""
    holder = subprocess.Popen(
        [sys.executable, "-c", holder_source, str(SCRIPTS), str(home)],
        cwd=REPO,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    assert holder.stdout is not None
    assert holder.stdout.readline().strip() == "locked"
    started = time.monotonic()
    busy = run_cli(home, "show")
    elapsed = time.monotonic() - started
    assert busy.returncode == 1
    assert busy.stderr == ""
    assert "busy" in json.loads(busy.stdout)["error"].lower()
    assert elapsed < 1.25
    stdout, stderr = holder.communicate(timeout=3)
    assert stdout == "" and stderr == "" and holder.returncode == 0
    recovered = run_cli(home, "show")
    assert recovered.returncode == 0
    assert json.loads(recovered.stdout)["state"] == valid_state()


def test_post_replace_directory_sync_failure_names_committed_current(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state.save_current(home, valid_state(nextPrompt="old-current"))
    replacement = valid_state(
        nextPrompt="replacement-current",
        updatedAt="2026-07-15T14:10:00Z",
    )
    root = home / "onboarding/ericsson"
    root_inode = root.stat().st_ino
    original_fsync = os.fsync
    failed = False

    def fail_committed_current_sync(descriptor: int) -> None:
        nonlocal failed
        current = root / "current.json"
        committed = (
            current.exists()
            and "replacement-current" in current.read_text(encoding="utf-8")
        )
        if not failed and os.fstat(descriptor).st_ino == root_inode and committed:
            failed = True
            raise OSError("injected post-replacement directory sync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "fsync", fail_committed_current_sync)
    with pytest.raises(state.StateIOError) as caught:
        state.save_current(home, replacement)
    message = str(caught.value).lower()
    assert "current.json" in message
    assert "durability" in message
    assert "inspect" in message and "retry" in message
    monkeypatch.setattr(os, "fsync", original_fsync)
    assert state.load_current(home) == replacement


@pytest.mark.parametrize("failure", ["verify", "temp-unlink", "history-fsync"])
def test_post_history_link_failures_name_partial_archive_and_current(
    home: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    payload = valid_state(nextPrompt=f"history-{failure}")
    state.save_current(home, payload)
    root = home / "onboarding/ericsson"
    history_name = "20260715T151617Z.json"
    history_path = root / "history" / history_name

    if failure == "verify":
        original_verify = state._verify_named_identity

        def fail_history_verify(directory: int, name: str, identity) -> None:
            if name == history_name:
                raise state.StateIOError("injected history verification failure")
            original_verify(directory, name, identity)

        monkeypatch.setattr(state, "_verify_named_identity", fail_history_verify)
    elif failure == "temp-unlink":
        original_unlink = os.unlink
        failed = False

        def fail_history_temp_unlink(path, *args, **kwargs):
            nonlocal failed
            if not failed and str(path).endswith(".tmp") and history_path.exists():
                failed = True
                raise OSError("injected history temporary unlink failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(os, "unlink", fail_history_temp_unlink)
    else:
        original_fsync = os.fsync
        failed = False

        def fail_history_directory_sync(descriptor: int) -> None:
            nonlocal failed
            details = os.fstat(descriptor)
            if (
                not failed
                and stat.S_ISDIR(details.st_mode)
                and history_path.exists()
                and details.st_ino == history_path.parent.stat().st_ino
            ):
                failed = True
                raise OSError("injected history directory sync failure")
            original_fsync(descriptor)

        monkeypatch.setattr(os, "fsync", fail_history_directory_sync)

    with pytest.raises(state.StateIOError) as caught:
        state.complete_current(
            home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
        )
    message = str(caught.value).lower()
    assert f"history/{history_name}".lower() in message
    assert "partial" in message
    assert "current.json remains" in message
    assert "inspect" in message and "retry" in message
    assert history_path.exists()
    assert state.load_current(home) == payload


def test_persistent_post_history_link_temp_unlink_failure_preserves_partial_guidance(
    home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    payload = valid_state(nextPrompt="persistent-history-temp")
    state.save_current(home, payload)
    root = home / "onboarding/ericsson"
    history_name = "20260715T151617Z.json"
    history_path = root / "history" / history_name
    original_unlink = os.unlink

    def persistently_fail_history_temp_unlink(path, *args, **kwargs):
        if str(path).endswith(".tmp") and history_path.exists():
            raise OSError("persistent history temporary unlink failure")
        return original_unlink(path, *args, **kwargs)

    monkeypatch.setattr(os, "unlink", persistently_fail_history_temp_unlink)
    with pytest.raises(state.StateIOError) as caught:
        state.complete_current(
            home, now=datetime(2026, 7, 15, 15, 16, 17, tzinfo=timezone.utc)
        )
    message = str(caught.value).lower()
    assert f"history/{history_name}".lower() in message
    assert "partial" in message
    assert "current.json remains" in message
    assert "leftover temporary" in message
    assert "history/." in message and ".tmp" in message
    assert "lock onboarding state" not in message
    assert history_path.exists()
    assert state.load_current(home) == payload
    assert list(history_path.parent.glob(".*.tmp"))


def test_losing_directory_creator_syncs_parent_before_opening_child(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    parent_fd = os.open(parent, state._DIRECTORY_FLAGS)
    events: list[str] = []
    original_open = os.open
    original_mkdir = os.mkdir
    original_fsync = os.fsync
    first_open = True

    def race_open(path, flags, *args, **kwargs):
        nonlocal first_open
        if os.fspath(path) == "raced" and first_open:
            first_open = False
            events.append("open-missing")
            raise FileNotFoundError("simulated initial absence")
        if os.fspath(path) == "raced":
            events.append("open-child")
        return original_open(path, flags, *args, **kwargs)

    def race_mkdir(path, *args, **kwargs):
        if os.fspath(path) == "raced":
            original_mkdir(path, *args, **kwargs)
            events.append("mkdir-lost-race")
            raise FileExistsError("simulated concurrent creator")
        return original_mkdir(path, *args, **kwargs)

    def record_fsync(descriptor: int) -> None:
        if descriptor == parent_fd:
            events.append("fsync-parent")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "open", race_open)
    monkeypatch.setattr(os, "mkdir", race_mkdir)
    monkeypatch.setattr(os, "fsync", record_fsync)
    child_fd = state._open_dir_at(parent_fd, "raced", create=True, repair=True)
    os.close(child_fd)
    os.close(parent_fd)
    assert events[:4] == [
        "open-missing",
        "mkdir-lost-race",
        "fsync-parent",
        "open-child",
    ]


def test_losing_directory_creator_parent_sync_failure_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    parent = tmp_path / "parent"
    parent.mkdir()
    parent_fd = os.open(parent, state._DIRECTORY_FLAGS)
    original_open = os.open
    original_mkdir = os.mkdir
    original_fsync = os.fsync
    first_open = True

    def race_open(path, flags, *args, **kwargs):
        nonlocal first_open
        if os.fspath(path) == "raced" and first_open:
            first_open = False
            raise FileNotFoundError("simulated initial absence")
        return original_open(path, flags, *args, **kwargs)

    def race_mkdir(path, *args, **kwargs):
        if os.fspath(path) == "raced":
            original_mkdir(path, *args, **kwargs)
            raise FileExistsError("simulated concurrent creator")
        return original_mkdir(path, *args, **kwargs)

    def fail_parent_sync(descriptor: int) -> None:
        if descriptor == parent_fd:
            raise OSError("injected losing-creator parent sync failure")
        original_fsync(descriptor)

    monkeypatch.setattr(os, "open", race_open)
    monkeypatch.setattr(os, "mkdir", race_mkdir)
    monkeypatch.setattr(os, "fsync", fail_parent_sync)
    with pytest.raises(state.StateIOError, match="durably create"):
        state._open_dir_at(parent_fd, "raced", create=True, repair=True)
    os.close(parent_fd)
