"""Frozen Task 11 convergence matrix (A01-D03).

These tests intentionally exercise the public catalog/lint behavior and the
operating-system boundary.  They are not snapshots of implementation details:
the assertions describe the bounded source-ingestion contract shared by all
Task 11 static consumers.
"""

from __future__ import annotations

import ast
import errno
import ctypes
import importlib
import importlib.util
import inspect
import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
from collections.abc import Set as AbstractSet
from ctypes import wintypes
from dataclasses import FrozenInstanceError
from enum import StrEnum
from types import MappingProxyType
from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
CATALOG_SCRIPTS = REPO / "skills/ericsson/onboard-ericsson-capabilities/scripts"
ROOT_SCRIPTS = REPO / "scripts"
sys.path.insert(0, str(CATALOG_SCRIPTS))
sys.path.insert(0, str(ROOT_SCRIPTS))

import catalog_lib  # noqa: E402
import lint_manifest  # noqa: E402
from catalog_lib import CatalogError  # noqa: E402
from test_onboarding_catalog import (  # noqa: E402
    RepoFixture,
    _configure_descriptor_fixture,
    _configure_flat_archon_fixture,
    _descriptor_configuration,
    _nested_sidecar_value,
    _sidecar_bytes,
)


SIDE_CAR_LIMIT = 65_536
SIDE_CAR_SENTINEL_LIMIT = 65_537
SIDE_CAR_DEPTH_LIMIT = 24
SIDE_CAR_ENTRY_LIMIT = 2_048
CONFIG_SCHEMA_LIMIT = 512 * 1_024
WORKFLOW_METADATA_LIMIT = 512 * 1_024
FIXED_INVALID_SOURCE = "workflow sidecar is not a safe regular file"
FIXED_INVALID_YAML = "workflow sidecar is not valid bounded YAML"


@pytest.fixture
def matrix_repo(tmp_path: Path) -> RepoFixture:
    fixture = RepoFixture(tmp_path)
    sidecar = _configure_flat_archon_fixture(fixture)
    sidecar.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
    return fixture


def _entries(fixture: RepoFixture) -> list[dict]:
    return catalog_lib.load_entries(fixture.root)


def _catalog_problems(fixture: RepoFixture) -> list[str]:
    return catalog_lib.validate_repository(fixture.root, _entries(fixture))


def _lint_problems(fixture: RepoFixture, monkeypatch: pytest.MonkeyPatch) -> list[str]:
    monkeypatch.setattr(lint_manifest, "REPO", fixture.root)
    return lint_manifest.lint(fixture.root / "sets/ericsson.json")


def _cli(
    script: Path, fixture: RepoFixture, *args: str
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(script), *args, "--repo", str(fixture.root)],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )


def _manifest_cli(fixture: RepoFixture) -> subprocess.CompletedProcess[str]:
    # Exercise the real entry point and its explicit isolated-repository seam.
    return subprocess.run(
        [
            sys.executable,
            str(ROOT_SCRIPTS / "lint_manifest.py"),
            str(fixture.root / "sets/ericsson.json"),
            "--repo",
            str(fixture.root),
        ],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )


def _bounded_source():
    return importlib.import_module("bounded_source")


def _json_result(result: subprocess.CompletedProcess[str]) -> dict[str, object]:
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert isinstance(payload, dict)
    return payload


def _assert_fixed_cli_failure(result: subprocess.CompletedProcess[str]) -> None:
    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert isinstance(payload["problems"], list) and payload["problems"]
    rendered = json.dumps(payload)
    assert "Traceback" not in rendered
    assert "PRIVATE-SENTINEL" not in rendered


def test_A01_all_sidecar_consumers_share_identical_accept_reject_facts(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A01: library, CLIs, build/check, and lint share one contract."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_text(
        "language_compatibility: archon-2026-07\n"
        "language_compatibility: hermes-legacy\n",
        encoding="utf-8",
    )

    with pytest.raises(CatalogError, match="duplicate mapping key"):
        _catalog_problems(matrix_repo)
    lint_problems = _lint_problems(matrix_repo, monkeypatch)
    assert lint_problems == ["workflow sidecar contains duplicate mapping key"]

    validate = _cli(CATALOG_SCRIPTS / "validate_catalog.py", matrix_repo)
    lint = _manifest_cli(matrix_repo)
    build = _cli(CATALOG_SCRIPTS / "build_catalog.py", matrix_repo)
    check = _cli(CATALOG_SCRIPTS / "build_catalog.py", matrix_repo, "--check")
    for result in (validate, lint, build, check):
        assert result.returncode == 1
        assert "duplicate mapping key" in result.stdout
        assert result.stderr == ""


def _set_sidecar_case(fixture: RepoFixture, case: str) -> None:
    sidecar = fixture.root / "workflows/example.hermes.yaml"
    if case == "valid":
        return
    sidecar.unlink()
    if case == "missing":
        return
    if case == "directory":
        sidecar.mkdir()
    elif case == "fifo":
        os.mkfifo(sidecar)
    elif case == "symlink":
        target = sidecar.with_name("target.yaml")
        target.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
        sidecar.symlink_to(target)
    elif case == "permission":
        sidecar.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
        sidecar.chmod(0)
    elif case == "duplicate":
        sidecar.write_text(
            "language_compatibility: archon-2026-07\n"
            "language_compatibility: hermes-legacy\n",
            encoding="utf-8",
        )
    elif case == "merge":
        sidecar.write_text(_merge_amplification_fixture(), encoding="utf-8")
    elif case == "invalid-utf8":
        sidecar.write_bytes(b"\xff\xfePRIVATE-SENTINEL")
    elif case == "syntax":
        sidecar.write_text("language_compatibility: [\n", encoding="utf-8")
    elif case == "oversize":
        sidecar.write_bytes(_sidecar_bytes(SIDE_CAR_LIMIT + 1))
    elif case == "alias-overflow":
        aliases = ",".join("*a" for _ in range(129))
        sidecar.write_text(
            "language_compatibility: archon-2026-07\n"
            "delivery_defaults:\n  value: &a {}\n"
            f"  aliases: [{aliases}]\n",
            encoding="utf-8",
        )
    elif case == "parser-depth":
        sidecar.write_text(
            "language_compatibility: archon-2026-07\ndelivery_defaults: "
            + "[" * 25
            + "x"
            + "]" * 25
            + "\n",
            encoding="utf-8",
        )
    elif case == "parser-nodes":
        sidecar.write_text(
            "language_compatibility: archon-2026-07\ndelivery_defaults: ["
            + ",".join("{}" for _ in range(2_100))
            + "]\n",
            encoding="utf-8",
        )
    elif case == "cycle":
        sidecar.write_text(
            "language_compatibility: archon-2026-07\n"
            "delivery_defaults: &self {next: *self}\n",
            encoding="utf-8",
        )
    elif case == "mixed-key":
        sidecar.write_text(
            "language_compatibility: archon-2026-07\nlimits: {7: 1}\n",
            encoding="utf-8",
        )
    elif case == "scalar-root":
        sidecar.write_text("scalar\n", encoding="utf-8")
    else:  # pragma: no cover - table is frozen below
        raise AssertionError(case)


@pytest.mark.parametrize(
    "case,accepted",
    [
        ("valid", True),
        ("missing", False),
        ("directory", False),
        ("fifo", False),
        ("symlink", False),
        ("permission", False),
        ("duplicate", False),
        ("merge", False),
        ("invalid-utf8", False),
        ("syntax", False),
        ("oversize", False),
        ("alias-overflow", False),
        ("parser-depth", False),
        ("parser-nodes", False),
        ("cycle", False),
        ("mixed-key", False),
        ("scalar-root", False),
    ],
)
def test_A01_B08_real_surface_differential_for_every_failure_class(
    matrix_repo: RepoFixture,
    case: str,
    accepted: bool,
) -> None:
    """A01/B08: real library/validate/lint/build/check agree on facts."""
    if (
        os.name != "posix"
        or (case == "permission" and hasattr(os, "geteuid") and os.geteuid() == 0)
    ) and case in {"fifo", "permission", "symlink"}:
        pytest.skip(
            f"{case} real-object probe is covered by deterministic platform mocks"
        )
    _set_sidecar_case(matrix_repo, case)

    try:
        library_accepted = _catalog_problems(matrix_repo) == []
    except CatalogError:
        library_accepted = False
    validate = _cli(CATALOG_SCRIPTS / "validate_catalog.py", matrix_repo)
    lint = _manifest_cli(matrix_repo)
    build = _cli(CATALOG_SCRIPTS / "build_catalog.py", matrix_repo)
    check = _cli(CATALOG_SCRIPTS / "build_catalog.py", matrix_repo, "--check")

    facts = [library_accepted] + [
        item.returncode == 0 for item in (validate, lint, build, check)
    ]
    assert facts == [accepted] * 5
    for result in (validate, lint, build, check):
        assert result.stderr == ""
        if not accepted:
            payload = _json_result(result)
            assert payload["ok"] is False
            rendered = json.dumps(payload)
            assert len(rendered) < 2_048
            assert "PRIVATE-SENTINEL" not in rendered
            assert str(matrix_repo.root) not in rendered


@pytest.mark.parametrize("check", [False, True], ids=("build", "check"))
def test_A01_build_and_check_load_entries_and_inventory_once(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    check: bool,
) -> None:
    """A01/C01: build/check validate and serialize one coherent snapshot."""
    spec = importlib.util.spec_from_file_location(
        "task11_build_catalog", CATALOG_SCRIPTS / "build_catalog.py"
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    loads = 0
    inventories = 0
    original_load = module.load_entries
    original_collect = module.collect_repository_inventory

    def load(repo: Path):
        nonlocal loads
        loads += 1
        return original_load(repo)

    def collect(repo: Path):
        nonlocal inventories
        inventories += 1
        return original_collect(repo)

    monkeypatch.setattr(module, "load_entries", load)
    monkeypatch.setattr(module, "collect_repository_inventory", collect)
    arguments = ["build_catalog.py", "--repo", str(matrix_repo.root)]
    if check:
        # Seed the expected bytes using the same explicit entries without a
        # second CLI-side load.
        entries = catalog_lib.load_entries(matrix_repo.root)
        target = matrix_repo.root / module.CATALOG_PATH
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            catalog_lib.serialize_catalog(
                catalog_lib.build_catalog(matrix_repo.root, entries=entries)
            ),
            encoding="utf-8",
        )
        arguments.append("--check")
    monkeypatch.setattr(sys, "argv", arguments)
    assert module.main() == 0
    assert loads == 1
    assert inventories == 1


@pytest.mark.parametrize("check", [False, True], ids=("build", "check"))
@pytest.mark.parametrize(
    "failure",
    [
        "sidecar-duplicate",
        "workflow-overflow",
        "config-utf8",
        "config-link",
        "validation",
    ],
)
def test_A01_build_check_failures_never_write_or_leave_tempfiles(
    matrix_repo: RepoFixture, check: bool, failure: str
) -> None:
    """A01/B08: every source/validation failure preserves target bytes atomically."""
    if os.name != "posix" and failure == "config-link":
        pytest.skip("real symlink covered by deterministic Windows reparse tests")
    if failure == "sidecar-duplicate":
        _set_sidecar_case(matrix_repo, "duplicate")
    elif failure == "workflow-overflow":
        workflow = matrix_repo.root / "workflows/example.yml"
        workflow.write_text(
            workflow.read_text(encoding="utf-8") + "#" + "x" * WORKFLOW_METADATA_LIMIT,
            encoding="utf-8",
        )
    elif failure in {"config-utf8", "config-link"}:
        _configure_descriptor_fixture(matrix_repo)
        matrix_repo.write_complete_entry(configuration=_descriptor_configuration())
        schema = matrix_repo.root / "plugins/ericsson-example/config.schema.json"
        if failure == "config-utf8":
            schema.write_bytes(b"\xffPRIVATE-SENTINEL")
        else:
            target = schema.with_name("PRIVATE-SENTINEL.json")
            target.write_text('{"version":1,"fields":[]}', encoding="utf-8")
            schema.unlink()
            schema.symlink_to(target)
    else:
        matrix_repo.write_complete_entry(
            implementation={
                "skills": [],
                "plugins": [],
                "mcp_servers": [],
                "workflows": [],
                "tools": [],
            }
        )

    target = (
        matrix_repo.root
        / "skills/ericsson/onboard-ericsson-capabilities/references/catalog.json"
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    original = b'{"PRIVATE-SENTINEL":"unchanged"}\n'
    target.write_bytes(original)
    args = [sys.executable, str(CATALOG_SCRIPTS / "build_catalog.py")]
    if check:
        args.append("--check")
    args += ["--repo", str(matrix_repo.root)]
    result = subprocess.run(
        args, text=True, capture_output=True, timeout=10, check=False
    )
    assert result.returncode == 1
    _assert_fixed_cli_failure(result)
    assert target.read_bytes() == original
    assert list(target.parent.glob(".catalog.json.*")) == []


@pytest.mark.skipif(os.name != "posix", reason="A02/A03 real object controls are POSIX")
@pytest.mark.parametrize("kind", ["directory", "fifo", "socket", "broken-symlink"])
def test_A02_existing_nonregular_sidecar_is_invalid_not_absent(
    matrix_repo: RepoFixture, kind: str
) -> None:
    """A02: only ENOENT is the optional-absent result."""
    short_root: Path | None = None
    if kind == "socket":
        # Darwin's AF_UNIX path cap is shorter than pytest's parametrized temp
        # paths.  Keep the real socket probe at the exact sibling path in a
        # deliberately short isolated repository.
        short_root = Path(tempfile.mkdtemp(prefix="t11-", dir="/tmp"))
        matrix_repo = RepoFixture(short_root)
        short_sidecar = _configure_flat_archon_fixture(matrix_repo)
        short_sidecar.write_text(
            "language_compatibility: archon-2026-07\n", encoding="utf-8"
        )
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.unlink()
    listener: socket.socket | None = None
    if kind == "directory":
        sidecar.mkdir()
    elif kind == "fifo":
        os.mkfifo(sidecar)
    elif kind == "socket":
        listener = socket.socket(socket.AF_UNIX)
        listener.bind(str(sidecar))
    else:
        sidecar.symlink_to(sidecar.with_name("missing-target"))
    try:
        with pytest.raises(CatalogError, match=FIXED_INVALID_SOURCE):
            _catalog_problems(matrix_repo)
    finally:
        if listener is not None:
            listener.close()
        if short_root is not None:
            shutil.rmtree(short_root)


def test_A02_true_missing_is_the_only_typed_absent_result(tmp_path: Path) -> None:
    """A02/A07: contract optionality, never message matching, represents absence."""
    bounded = _bounded_source()
    missing = tmp_path / "missing.hermes.yaml"
    assert bounded.load_yaml_mapping(missing, bounded.WORKFLOW_SIDECAR_CONTRACT) is None


@pytest.mark.parametrize("mode", ["directory", "character-device", "block-device"])
def test_A02_mocked_nonregular_descriptor_modes_fail_before_read(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, mode: str
) -> None:
    """A02/D01: deterministic nonregular controls cover unavailable real devices."""
    bounded = _bounded_source()
    source = tmp_path / "example.hermes.yaml"
    source.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
    real = os.stat(source)
    type_bits = {
        "directory": 0o040000,
        "character-device": 0o020000,
        "block-device": 0o060000,
    }[mode]
    fake = list(real)
    fake[0] = type_bits | 0o600
    reads: list[int] = []
    monkeypatch.setattr(bounded, "_fstat_descriptor", lambda _fd: os.stat_result(fake))
    monkeypatch.setattr(
        bounded, "_read_descriptor", lambda _fd, size: reads.append(size) or b""
    )
    with pytest.raises(CatalogError) as exc:
        bounded.load_yaml_mapping(source, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert exc.value.code == "unsafe_source"
    assert reads == []


@pytest.mark.skipif(os.name != "posix", reason="A03 link controls are POSIX")
def test_A03_symlinks_rejected_before_content_and_hardlinks_allowed(
    matrix_repo: RepoFixture, tmp_path: Path
) -> None:
    """A03: no-follow sibling policy; stable regular hardlinks remain valid."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    content = sidecar.read_bytes()
    target = tmp_path / "PRIVATE-SENTINEL.yaml"
    target.write_bytes(content)
    sidecar.unlink()
    sidecar.symlink_to(target)
    with pytest.raises(CatalogError, match=FIXED_INVALID_SOURCE) as exc:
        _catalog_problems(matrix_repo)
    assert "PRIVATE-SENTINEL" not in str(exc.value)

    sidecar.unlink()
    os.link(target, sidecar)
    assert _catalog_problems(matrix_repo) == []


@pytest.mark.skipif(os.name != "posix", reason="A03 real links are POSIX")
@pytest.mark.parametrize("target_kind", ["internal", "external", "broken", "directory"])
def test_A03_every_symlink_shape_rejected_without_target_read(
    matrix_repo: RepoFixture,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    target_kind: str,
) -> None:
    """A03: exact sibling must itself be regular; target bytes stay unread."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.unlink()
    if target_kind == "internal":
        target = sidecar.with_name("internal.yaml")
        target.write_text("PRIVATE-SENTINEL: true\n", encoding="utf-8")
    elif target_kind == "external":
        target = tmp_path / "PRIVATE-SENTINEL.yaml"
        target.write_text("PRIVATE-SENTINEL: true\n", encoding="utf-8")
    elif target_kind == "directory":
        target = tmp_path / "target-directory"
        target.mkdir()
    else:
        target = tmp_path / "missing-PRIVATE-SENTINEL"
    sidecar.symlink_to(target)
    reads: list[int] = []
    monkeypatch.setattr(
        bounded,
        "_read_descriptor",
        lambda _fd, size: reads.append(size) or b"PRIVATE-SENTINEL",
    )
    with pytest.raises(CatalogError) as exc:
        bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert exc.value.code == "unsafe_source"
    assert reads == []
    assert "PRIVATE-SENTINEL" not in str(exc.value)


@pytest.mark.skipif(os.name != "posix", reason="A04 requires POSIX FIFO semantics")
def test_A04_fifo_and_regular_to_fifo_replacement_never_block(
    matrix_repo: RepoFixture, tmp_path: Path
) -> None:
    """A04: O_NONBLOCK/O_NOFOLLOW acquisition prevents replacement hangs."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.unlink()
    os.mkfifo(sidecar)
    result = _cli(CATALOG_SCRIPTS / "validate_catalog.py", matrix_repo)
    _assert_fixed_cli_failure(result)
    assert FIXED_INVALID_SOURCE in result.stdout

    # The same subprocess timeout is the executable anti-blocking guarantee
    # for a path replaced with a FIFO immediately before acquisition.
    sidecar.unlink()
    sidecar.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
    hook = tmp_path / "hook"
    hook.mkdir()
    (hook / "sitecustomize.py").write_text(
        "import os\nfrom pathlib import Path\n"
        "p=Path(os.environ['REPLACE_SIDECAR'])\n"
        "p.unlink(); os.mkfifo(p)\n",
        encoding="utf-8",
    )
    environment = os.environ | {
        "REPLACE_SIDECAR": str(sidecar),
        "PYTHONPATH": os.pathsep.join([str(hook), os.environ.get("PYTHONPATH", "")]),
    }
    replaced = subprocess.run(
        [
            sys.executable,
            str(CATALOG_SCRIPTS / "validate_catalog.py"),
            "--repo",
            str(matrix_repo.root),
        ],
        text=True,
        capture_output=True,
        timeout=5,
        env=environment,
        check=False,
    )
    _assert_fixed_cli_failure(replaced)
    assert FIXED_INVALID_SOURCE in replaced.stdout


@pytest.mark.skipif(os.name != "posix", reason="A04 requires POSIX FIFO semantics")
def test_A04_replacement_inside_acquisition_is_nonblocking(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A04: race at the open seam, not interpreter startup, cannot hang."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    original = bounded._posix_open_regular

    def raced(path: Path) -> int:
        path.unlink()
        os.mkfifo(path)
        return original(path)

    monkeypatch.setattr(bounded, "_posix_open_regular", raced)
    with pytest.raises(CatalogError) as exc:
        bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert exc.value.code == "unsafe_source"


def test_A05_one_descriptor_captures_original_bytes_and_closes(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A05: path replacement after open cannot switch the source descriptor."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    bounded = _bounded_source()
    original_open = bounded._open_source_descriptor
    opens: list[int] = []
    closes: list[int] = []

    def replacing_open(path: Path) -> int:
        descriptor = original_open(path)
        if Path(path) == sidecar:
            opens.append(descriptor)
            replacement = sidecar.with_suffix(".replacement")
            replacement.write_text("PRIVATE-SENTINEL: true\n", encoding="utf-8")
            os.replace(replacement, sidecar)
        return descriptor

    original_close = bounded._close_descriptor

    def tracked_close(descriptor: int) -> None:
        if descriptor in opens:
            closes.append(descriptor)
        original_close(descriptor)

    monkeypatch.setattr(bounded, "_open_source_descriptor", replacing_open)
    monkeypatch.setattr(bounded, "_close_descriptor", tracked_close)
    assert _catalog_problems(matrix_repo) == []
    assert len(opens) == 1
    assert closes == opens


@pytest.mark.parametrize(
    "size,accepted", [(65_535, True), (65_536, True), (65_537, False)]
)
def test_A06_D03_exact_sidecar_read_boundary_and_constant(
    matrix_repo: RepoFixture, size: int, accepted: bool
) -> None:
    """A06/D03: 64 KiB cap, one sentinel byte, stable named constants."""
    assert catalog_lib._WORKFLOW_SIDECAR_MAX_BYTES == SIDE_CAR_LIMIT
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_bytes(_sidecar_bytes(size))
    if accepted:
        assert _catalog_problems(matrix_repo) == []
    else:
        with pytest.raises(
            CatalogError, match="workflow sidecar exceeds safe byte limit"
        ):
            _catalog_problems(matrix_repo)


@pytest.mark.parametrize("operation", ["open", "fstat", "read"])
def test_A06_A07_io_errors_are_fixed_and_descriptor_is_closed(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """A06/A07: open/fstat/read failures and EINTR do not leak paths or fds."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    bounded = _bounded_source()
    original_open, original_fstat, original_read, original_close = (
        bounded._open_source_descriptor,
        bounded._fstat_descriptor,
        bounded._read_descriptor,
        bounded._close_descriptor,
    )
    acquired: list[int] = []
    closed: list[int] = []
    interrupted = False

    def tracked_open(path: Path) -> int:
        if operation == "open" and Path(path) == sidecar:
            raise PermissionError(errno.EACCES, "PRIVATE-SENTINEL")
        fd = original_open(path)
        if Path(path) == sidecar:
            acquired.append(fd)
        return fd

    def tracked_fstat(fd):
        nonlocal interrupted
        if operation == "fstat" and fd in acquired:
            if not interrupted:
                interrupted = True
                raise InterruptedError(errno.EINTR, "PRIVATE-SENTINEL")
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")
        return original_fstat(fd)

    def tracked_read(fd, size):
        if operation == "read" and fd in acquired:
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")
        return original_read(fd, size)

    def tracked_close(fd):
        if fd in acquired:
            closed.append(fd)
        original_close(fd)

    monkeypatch.setattr(bounded, "_open_source_descriptor", tracked_open)
    monkeypatch.setattr(bounded, "_fstat_descriptor", tracked_fstat)
    monkeypatch.setattr(bounded, "_read_descriptor", tracked_read)
    monkeypatch.setattr(bounded, "_close_descriptor", tracked_close)
    with pytest.raises(CatalogError) as exc:
        _catalog_problems(matrix_repo)
    assert str(exc.value) == FIXED_INVALID_SOURCE
    assert "PRIVATE-SENTINEL" not in str(exc.value)
    assert not acquired or closed == acquired


@pytest.mark.parametrize("shape", ["growth", "shrink", "short-read", "early-eof"])
def test_A06_growth_shrink_short_read_and_eof_are_bounded(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    shape: str,
) -> None:
    """A06/D03: bounded reads retain at most cap+1 under changing files."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    original_read = bounded._read_descriptor
    original_fstat = bounded._fstat_descriptor
    requests: list[int] = []
    first = True

    def changed_read(fd: int, size: int) -> bytes:
        nonlocal first
        requests.append(size)
        assert 0 < size <= SIDE_CAR_SENTINEL_LIMIT
        if first:
            first = False
            if shape == "growth":
                sidecar.write_bytes(_sidecar_bytes(SIDE_CAR_LIMIT * 2))
            elif shape == "shrink":
                sidecar.write_text(
                    "language_compatibility: archon-2026-07\n", encoding="utf-8"
                )
            elif shape == "early-eof":
                return b""
        chunk = original_read(fd, min(size, 7) if shape == "short-read" else size)
        return chunk

    def inflated_fstat(fd: int):
        metadata = original_fstat(fd)
        if shape == "shrink":
            values = list(metadata)
            values[6] = SIDE_CAR_LIMIT
            return os.stat_result(values)
        return metadata

    monkeypatch.setattr(bounded, "_read_descriptor", changed_read)
    monkeypatch.setattr(bounded, "_fstat_descriptor", inflated_fstat)
    if shape == "growth":
        with pytest.raises(CatalogError) as exc:
            bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
        assert exc.value.code == "byte_limit"
        assert sum(requests) >= SIDE_CAR_SENTINEL_LIMIT
    elif shape == "early-eof":
        with pytest.raises(CatalogError) as exc:
            bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
        assert exc.value.code == "invalid_yaml"
    else:
        loaded = bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
        assert loaded["language_compatibility"] == "archon-2026-07"
    assert requests and -1 not in requests
    assert all(request <= SIDE_CAR_SENTINEL_LIMIT for request in requests)


@pytest.mark.parametrize("operation", ["open", "fstat", "read"])
@pytest.mark.parametrize(
    "interrupts", [1, 4], ids=("eintr-then-success", "repeated-eintr")
)
def test_A07_eintr_policy_is_bounded_and_closes_owned_descriptor(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    interrupts: int,
) -> None:
    """A07: each syscall retries boundedly; repeated EINTR is fixed failure."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    names = {
        "open": "_open_source_descriptor",
        "fstat": "_fstat_descriptor",
        "read": "_read_descriptor",
    }
    seam = names[operation]
    original = getattr(bounded, seam)
    attempts = 0
    closes: list[int] = []
    original_close = bounded._close_descriptor

    def interrupted(*args):
        nonlocal attempts
        attempts += 1
        if attempts <= interrupts:
            raise InterruptedError(errno.EINTR, "PRIVATE-SENTINEL")
        return original(*args)

    def close(fd: int) -> None:
        closes.append(fd)
        original_close(fd)

    monkeypatch.setattr(bounded, seam, interrupted)
    monkeypatch.setattr(bounded, "_close_descriptor", close)
    if interrupts == 1:
        loaded = bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
        assert loaded["language_compatibility"] == "archon-2026-07"
        # Reads require one final call to observe actual EOF; open/fstat return
        # the authoritative fact on their first successful retry.
        assert attempts == (3 if operation == "read" else 2)
    else:
        with pytest.raises(CatalogError) as exc:
            bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
        assert exc.value.code == "io_error"
        assert attempts == 3
    if operation != "open" or interrupts == 1:
        assert len(closes) == 1


@pytest.mark.parametrize(
    "payload",
    [
        _sidecar_bytes(SIDE_CAR_LIMIT + 1),
        b"\xff",
        b"language_compatibility: [",
        b"language_compatibility: archon-2026-07\nlanguage_compatibility: legacy\n",
        b"language_compatibility: archon-2026-07\nx: &x {}\ny: {<<: *x}\n",
        b"language_compatibility: archon-2026-07\ndelivery_defaults: &x {self: *x}\n",
        b"language_compatibility: archon-2026-07\ndelivery_defaults: "
        + b"[" * 25
        + b"x"
        + b"]" * 25
        + b"\n",
    ],
    ids=("byte", "decode", "yaml", "duplicate", "merge", "cycle", "structure"),
)
def test_A07_descriptor_closes_before_every_parse_or_structure_failure(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    payload: bytes,
) -> None:
    """A07: every post-open failure closes the single owned descriptor."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_bytes(payload)
    closes: list[int] = []
    original = bounded._close_descriptor

    def close(fd: int) -> None:
        closes.append(fd)
        original(fd)

    monkeypatch.setattr(bounded, "_close_descriptor", close)
    with pytest.raises(CatalogError):
        bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert len(closes) == 1


@pytest.mark.parametrize(
    "primary_failure", [False, True], ids=("success", "primary-failure")
)
def test_A07_close_eintr_ownership_and_error_precedence(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    primary_failure: bool,
) -> None:
    """A07: close EINTR is fixed; it never masks an earlier parse failure."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    if primary_failure:
        sidecar.write_bytes(b"\xff")
    original = bounded._close_descriptor
    closed: list[int] = []

    def interrupted(fd: int) -> None:
        closed.append(fd)
        original(fd)
        raise InterruptedError(errno.EINTR, "PRIVATE-SENTINEL")

    monkeypatch.setattr(bounded, "_close_descriptor", interrupted)
    with pytest.raises(CatalogError) as exc:
        bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert exc.value.code == ("invalid_yaml" if primary_failure else "io_error")
    assert len(closed) == 1
    with pytest.raises(OSError):
        os.fstat(closed[0])


@pytest.mark.parametrize(
    "payload",
    [
        b"\xff\xfePRIVATE-SENTINEL",
        b"language_compatibility: [unterminated PRIVATE-SENTINEL",
        b"language_compatibility: !PRIVATE-SENTINEL tag",
        b"language_compatibility: " + b"9" * 5_000 + b"\n",
    ],
    ids=("utf8", "scanner", "tag", "constructor-value-error"),
)
def test_B01_B08_all_decode_and_yaml_failures_are_fixed_no_leak(
    matrix_repo: RepoFixture, payload: bytes
) -> None:
    """B01/B08: all decode/parser/constructor errors are bounded and redacted."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_bytes(payload)
    with pytest.raises(CatalogError) as exc:
        _catalog_problems(matrix_repo)
    assert str(exc.value) == FIXED_INVALID_YAML
    result = _cli(CATALOG_SCRIPTS / "validate_catalog.py", matrix_repo)
    _assert_fixed_cli_failure(result)
    assert result.stdout.count('{"') == 1


@pytest.mark.parametrize(
    "payload",
    [
        "language_compatibility: archon-2026-07\nlanguage_compatibility: hermes-legacy\n",
        "language_compatibility: archon-2026-07\nlimits:\n  max_parallel_nodes: 1\n  max_parallel_nodes: 2\n",
    ],
    ids=("root", "nested"),
)
def test_B02_duplicate_mapping_keys_rejected_before_last_wins(
    matrix_repo: RepoFixture, payload: str
) -> None:
    """B02: duplicate keys are a composition error at every depth."""
    (matrix_repo.root / "workflows/example.hermes.yaml").write_text(
        payload, encoding="utf-8"
    )
    with pytest.raises(CatalogError, match="duplicate mapping key"):
        _catalog_problems(matrix_repo)


def test_B03_merge_keys_rejected_before_expansion(matrix_repo: RepoFixture) -> None:
    """B03: YAML merge is outside contract and rejected before expansion."""
    bounded = _bounded_source()
    payload = _merge_amplification_fixture()
    assert len(payload.encode()) == 531
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_text(payload, encoding="utf-8")
    flattened = 0
    constructed = 0
    original_flatten = bounded._BoundedSafeLoader.flatten_mapping
    original_construct = bounded._BoundedSafeLoader.construct_object

    def flatten(loader, node) -> None:
        nonlocal flattened
        flattened += 1
        original_flatten(loader, node)

    def construct(loader, node, deep=False):
        nonlocal constructed
        constructed += 1
        return original_construct(loader, node, deep=deep)

    with pytest.MonkeyPatch.context() as patch:
        patch.setattr(bounded._BoundedSafeLoader, "flatten_mapping", flatten)
        patch.setattr(bounded._BoundedSafeLoader, "construct_object", construct)
        with pytest.raises(CatalogError) as exc:
            bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert exc.value.code == "merge_key"
    assert flattened == 0
    assert constructed == 0

    sidecar.write_text(
        "language_compatibility: archon-2026-07\n"
        'delivery_defaults: {"<<": ordinary-string-key}\n',
        encoding="utf-8",
    )
    assert _catalog_problems(matrix_repo) == []


def _merge_amplification_fixture() -> str:
    """Audited 531-byte, seven-level, ten-way merge amplification input."""
    letters = "abcdefghij"
    anchors: list[str] = []
    for index, anchor in enumerate(letters):
        nested = str(index)
        for _ in range(7):
            nested = "{x:" + nested + "}"
        anchors.append(f" {anchor}: &{anchor} {nested}")
    payload = (
        "language_compatibility: archon-2026-07\n"
        "delivery_defaults:\n"
        + "\n".join(anchors)
        + "\n z:\n  <<: ["
        + ",".join(f"*{anchor}" for anchor in letters)
        + "]\n"
    )
    padding = 531 - len(payload.encode("utf-8"))
    assert padding >= 2
    return payload + "#" + "p" * (padding - 2) + "\n"


def test_B04_parser_node_alias_depth_budgets_precede_construction(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B04/D03: hostile compact YAML cannot construct beyond parser budgets."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_text(
        "language_compatibility: archon-2026-07\n"
        "delivery_defaults: [" + ",".join("{}" for _ in range(10_000)) + "]\n",
        encoding="utf-8",
    )
    original = yaml.SafeLoader.construct_object
    constructed = 0

    def counted(loader, node, deep=False):
        nonlocal constructed
        constructed += 1
        return original(loader, node, deep=deep)

    monkeypatch.setattr(yaml.SafeLoader, "construct_object", counted)
    with pytest.raises(CatalogError, match="safe YAML composition limits"):
        _catalog_problems(matrix_repo)
    assert constructed <= SIDE_CAR_ENTRY_LIMIT + SIDE_CAR_DEPTH_LIMIT + 8


@pytest.mark.parametrize("aliases,accepted", [(128, True), (129, False)])
def test_B04_B05_exact_alias_boundary_for_sidecars_and_clis(
    matrix_repo: RepoFixture, aliases: int, accepted: bool
) -> None:
    """B04/B05: alias event 128 passes and event 129 stops composition."""
    joined = ",".join("*a" for _ in range(aliases))
    (matrix_repo.root / "workflows/example.hermes.yaml").write_text(
        "language_compatibility: archon-2026-07\n"
        "delivery_defaults:\n  shared: &a {}\n"
        f"  aliases: [{joined}]\n",
        encoding="utf-8",
    )
    try:
        library = _catalog_problems(matrix_repo) == []
    except CatalogError:
        library = False
    results = [
        _cli(CATALOG_SCRIPTS / "validate_catalog.py", matrix_repo),
        _manifest_cli(matrix_repo),
        _cli(CATALOG_SCRIPTS / "build_catalog.py", matrix_repo),
        _cli(CATALOG_SCRIPTS / "build_catalog.py", matrix_repo, "--check"),
    ]
    assert [library] + [result.returncode == 0 for result in results] == [accepted] * 5


@pytest.mark.parametrize(
    "depth,accepted",
    [(22, True), (23, False)],
    ids=("depth-24", "depth-25"),
)
def test_B04_B06_exact_depth_boundary_before_construction(
    matrix_repo: RepoFixture, depth: int, accepted: bool
) -> None:
    """B04/B06: mapping-key traversal excluded; graph depth 24/25 is exact."""
    document = {
        "language_compatibility": "archon-2026-07",
        "delivery_defaults": {"value": _nested_sidecar_value(depth)},
    }
    (matrix_repo.root / "workflows/example.hermes.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )
    if accepted:
        assert _catalog_problems(matrix_repo) == []
    else:
        with pytest.raises(CatalogError, match="safe YAML composition limits"):
            _catalog_problems(matrix_repo)


@pytest.mark.parametrize(
    "fields,accepted",
    [(2_045, True), (2_046, False)],
    ids=("entries-2048", "entries-2049"),
)
def test_B04_B06_graph_entries_exclude_mapping_keys_at_boundary(
    matrix_repo: RepoFixture, fields: int, accepted: bool
) -> None:
    """B04/B06: root + mapping values is the preserved 2,048 metric."""
    document = {
        "language_compatibility": "archon-2026-07",
        "delivery_defaults": {f"field-{index}": "x" for index in range(fields)},
    }
    (matrix_repo.root / "workflows/example.hermes.yaml").write_text(
        yaml.safe_dump(document, sort_keys=False), encoding="utf-8"
    )
    if accepted:
        assert _catalog_problems(matrix_repo) == []
    else:
        with pytest.raises(CatalogError, match="safe YAML composition limits"):
            _catalog_problems(matrix_repo)


def test_B02_B04_rejection_precedes_mapping_construction(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """B02/B04/D03: duplicate and capacity failures construct no mapping."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    payloads = [
        "language_compatibility: archon-2026-07\nlanguage_compatibility: legacy\n",
        "language_compatibility: archon-2026-07\ndelivery_defaults: ["
        + ",".join("{}" for _ in range(SIDE_CAR_ENTRY_LIMIT + 1))
        + "]\n",
    ]
    original = bounded._BoundedSafeLoader.construct_mapping
    for payload in payloads:
        constructed = 0

        def counted(loader, node, deep=False):
            nonlocal constructed
            constructed += 1
            return original(loader, node, deep=deep)

        monkeypatch.setattr(bounded._BoundedSafeLoader, "construct_mapping", counted)
        sidecar.write_text(payload, encoding="utf-8")
        with pytest.raises(CatalogError):
            bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
        assert constructed == 0


def test_B02_decoded_duplicate_key_rejects_before_second_value_composition(
    matrix_repo: RepoFixture,
) -> None:
    """B02: plain and !!str keys collide; undefined duplicate value is untouched."""
    bounded = _bounded_source()
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_text(
        "language_compatibility: archon-2026-07\n"
        "plain: first\n"
        "!!str plain: *PRIVATE_UNDEFINED_ALIAS\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError) as exc:
        bounded.load_yaml_mapping(sidecar, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert exc.value.code == "duplicate_key"


def test_B06_instrumented_100k_mapping_rejects_before_iteration() -> None:
    """B06/D03: adjacent-known container size avoids hostile iteration."""

    class HugeMapping(dict[str, object]):
        iterations = 0

        def __iter__(self):
            self.iterations += 1
            return super().__iter__()

        def values(self):
            self.iterations += 1
            return super().values()

    huge = HugeMapping({str(index): "x" for index in range(100_000)})
    with pytest.raises(CatalogError, match="safe structure limits"):
        catalog_lib.validate_workflow_sidecar(
            {
                "language_compatibility": "archon-2026-07",
                "delivery_defaults": huge,
            },
            node_ids=set(),
        )
    assert huge.iterations == 0


@pytest.mark.parametrize(
    "payload,accepted",
    [
        (
            "delivery_defaults:\n  shared: &s {value: one}\n  a: *s\n  b: *s\n",
            True,
        ),
        ("delivery_defaults: &self {next: *self}\n", False),
        ("delivery_defaults: &a {next: &b {next: *a}}\n", False),
    ],
    ids=("diamond", "self-cycle", "mutual-cycle"),
)
def test_B05_alias_graph_controls(
    matrix_repo: RepoFixture, payload: str, accepted: bool
) -> None:
    """B05: shared acyclic aliases pass; active-path cycles fail fixed."""
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    sidecar.write_text(
        "language_compatibility: archon-2026-07\n" + payload, encoding="utf-8"
    )
    if accepted:
        assert _catalog_problems(matrix_repo) == []
    else:
        with pytest.raises(CatalogError, match="must not contain cycles"):
            _catalog_problems(matrix_repo)


@pytest.mark.parametrize("root", ["null\n", "[]\n", "scalar\n", "{7: value}\n"])
def test_B06_root_and_nested_mapping_shape_is_fixed(
    matrix_repo: RepoFixture, root: str
) -> None:
    """B06: root mapping and recursive string-key contract."""
    (matrix_repo.root / "workflows/example.hermes.yaml").write_text(
        root, encoding="utf-8"
    )
    with pytest.raises(CatalogError):
        _catalog_problems(matrix_repo)


@pytest.mark.parametrize(
    "payload",
    [
        "language_compatibility: []\n",
        "language_compatibility: {}\n",
        "execution_environment: []\nlanguage_compatibility: archon-2026-07\n",
        "overlap_policy: {}\nlanguage_compatibility: archon-2026-07\n",
    ],
)
def test_B07_unvalidated_containers_never_reach_hash_or_equality(
    matrix_repo: RepoFixture, payload: str
) -> None:
    """B07: invalid enum containers return diagnostics, never TypeError."""
    (matrix_repo.root / "workflows/example.hermes.yaml").write_text(
        payload, encoding="utf-8"
    )
    problems = _catalog_problems(matrix_repo)
    assert any("invalid workflow sidecar" in item for item in problems)


@pytest.mark.parametrize(
    "field,value",
    [
        ("language_compatibility", []),
        ("language_compatibility", {}),
        ("delivery_defaults", []),
        ("retention", []),
        ("limits", []),
        ("resource_limits", []),
        ("scheduling", []),
        ("required_services", {}),
        ("tags", {}),
        ("outward_action_nodes", {}),
        ("required_secrets", {}),
        ("outward_action_policy", []),
        ("concurrency_key", {}),
        ("execution_environment", []),
        ("overlap_policy", {}),
        ("pause_lane_policy", []),
    ],
)
def test_B07_every_schema_field_class_validates_type_before_membership(
    field: str, value: object
) -> None:
    """B07: maps/lists/strings/enums/profile all fail as diagnostics."""
    metadata: dict[str, object] = {
        "language_compatibility": "archon-2026-07",
        field: value,
    }
    problems = catalog_lib.validate_workflow_sidecar(metadata, node_ids=set())
    assert field in problems


def test_C01_inventory_is_collected_once_and_reused(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C01: one immutable inventory snapshot feeds all comparisons."""
    original = catalog_lib.collect_repository_inventory
    calls = 0

    def tracked(repo: Path):
        nonlocal calls
        calls += 1
        inventory = original(repo)
        if calls == 1:
            plugin_path = repo / "plugins/ericsson-example/plugin.yaml"
            plugin = yaml.safe_load(plugin_path.read_text(encoding="utf-8"))
            plugin["provides_tools"] = []
            plugin_path.write_text(yaml.safe_dump(plugin), encoding="utf-8")
        return inventory

    monkeypatch.setattr(catalog_lib, "collect_repository_inventory", tracked)
    problems = catalog_lib.validate_repository(matrix_repo.root, _entries(matrix_repo))
    assert calls == 1
    assert problems == []


def test_C01_inventory_is_deeply_immutable_and_each_workflow_is_read_once(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C01: one recursively frozen snapshot owns one workflow document read."""
    workflow = matrix_repo.root / "workflows/example.yml"
    original = catalog_lib._load_yaml_mapping
    workflow_reads = 0

    def tracked(path: Path, *, label: str):
        nonlocal workflow_reads
        if path == workflow:
            workflow_reads += 1
        return original(path, label=label)

    monkeypatch.setattr(catalog_lib, "_load_yaml_mapping", tracked)
    inventory = catalog_lib.collect_repository_inventory(matrix_repo.root)
    assert workflow_reads == 1

    def assert_frozen(value: object) -> None:
        assert not isinstance(value, (dict, list, set))
        if isinstance(value, MappingProxyType):
            for nested in value.values():
                assert_frozen(nested)
        elif isinstance(value, tuple | frozenset):
            for nested in value:
                assert_frozen(nested)

    assert isinstance(inventory, MappingProxyType)
    assert_frozen(inventory)
    with pytest.raises(TypeError):
        inventory["tools"] = frozenset()  # type: ignore[index]

    workflow_reads = 0
    assert (
        catalog_lib.validate_repository(matrix_repo.root, _entries(matrix_repo)) == []
    )
    assert workflow_reads == 1


@pytest.mark.parametrize(
    "size,accepted", [(CONFIG_SCHEMA_LIMIT, True), (CONFIG_SCHEMA_LIMIT + 1, False)]
)
def test_C02_config_schema_same_descriptor_exact_cap(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch, size: int, accepted: bool
) -> None:
    """C02: config_schema uses a same-fd 512 KiB bounded JSON source."""
    _configure_descriptor_fixture(matrix_repo)
    matrix_repo.write_complete_entry(configuration=_descriptor_configuration())
    schema = matrix_repo.root / "plugins/ericsson-example/config.schema.json"
    base = schema.read_bytes().rstrip()
    schema.write_bytes(base + b" " * (size - len(base)))
    if accepted:
        assert _catalog_problems(matrix_repo) == []
    else:
        assert any(
            "invalid plugin config schema" in p for p in _catalog_problems(matrix_repo)
        )

    external = schema.with_name("external.json")
    external.write_bytes(base)
    schema.unlink()
    schema.symlink_to(external)
    assert any(
        "invalid plugin config schema" in p for p in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "size,accepted", [(524_287, True), (524_288, True), (524_289, False)]
)
def test_C02_config_json_exact_byte_boundary_before_parse(
    tmp_path: Path, size: int, accepted: bool
) -> None:
    """C02/D03: config JSON reads at most cap+1 and has exact byte edges."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    prefix = b'{"version":1,"fields":[]}'
    path.write_bytes(prefix + b" " * (size - len(prefix)))
    if accepted:
        assert (
            bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)["version"]
            == 1
        )
    else:
        with pytest.raises(CatalogError) as exc:
            bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
        assert exc.value.code == "byte_limit"


@pytest.mark.parametrize(
    "payload,code",
    [
        (b'{"version":1,"version":1,"fields":[]}', "duplicate_key"),
        (b'{"version":' + b"9" * 5_000 + b',"fields":[]}', "parser_limit"),
        (b"\xffPRIVATE-SENTINEL", "invalid_json"),
        (
            b'{"version":1,"fields":['
            + b",".join(b"{}" for _ in range(SIDE_CAR_ENTRY_LIMIT + 1))
            + b"]}",
            "parser_limit",
        ),
        (
            b'{"version":1,"fields":[],"nested":' + b"[" * 25 + b"0" + b"]" * 25 + b"}",
            "parser_limit",
        ),
    ],
    ids=("duplicate", "huge-int", "utf8", "nodes", "depth"),
)
def test_C02_config_json_is_bounded_during_parsing(
    tmp_path: Path, payload: bytes, code: str
) -> None:
    """C02: duplicate/node/depth/integer limits precede JSON materialization."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_bytes(payload)
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert exc.value.code == code


def test_C02_json_decoded_duplicate_rejects_before_second_value_parse(
    tmp_path: Path,
) -> None:
    """C02: escaped and literal keys collide before parsing the second value."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text(
        '{"plain":"first","pl\\u0061in":PRIVATE_UNDEFINED_VALUE}',
        encoding="utf-8",
    )
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert exc.value.code == "duplicate_key"


@pytest.mark.parametrize(
    "payload",
    ["null", "[]", '"scalar"', "17", "true"],
    ids=("null", "list", "string", "number", "boolean"),
)
def test_C02_json_root_must_be_a_mapping(tmp_path: Path, payload: str) -> None:
    """C02: every valid non-object JSON root fails the fixed shape contract."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert exc.value.code == "structure_limit"


def test_C02_json_parser_preserves_standard_scalar_semantics(tmp_path: Path) -> None:
    """C02: bounded parsing remains compatible with ordinary RFC 8259 values."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text(
        r'{"string":"quote:\" slash:\/ backslash:\\ controls:\b\f\n\r\t",'
        r'"unicode":"\u00e9 \ud83d\ude00","true":true,"false":false,'
        r'"null":null,"integer":-17,"fraction":-1.25,"exponent":6.02e23}',
        encoding="utf-8",
    )
    loaded = bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert loaded == {
        "string": 'quote:" slash:/ backslash:\\ controls:\b\f\n\r\t',
        "unicode": "é 😀",
        "true": True,
        "false": False,
        "null": None,
        "integer": -17,
        "fraction": -1.25,
        "exponent": 6.02e23,
    }


@pytest.mark.parametrize(
    "payload",
    [
        '{"value":1} trailing',
        '{"value":01}',
        '{"value":-01}',
        '{"value":"raw\ncontrol"}',
        '{"value":+1}',
        '{"value":1.}',
        '{"value":1e}',
    ],
    ids=(
        "trailing-input",
        "leading-zero",
        "negative-leading-zero",
        "raw-control",
        "leading-plus",
        "missing-fraction",
        "missing-exponent",
    ),
)
def test_C02_json_parser_rejects_nonstandard_or_trailing_input(
    tmp_path: Path, payload: str
) -> None:
    """C02: the custom bounded parser rejects invalid JSON grammar exactly."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert exc.value.code == "invalid_json"


@pytest.mark.parametrize("digits,accepted", [(128, True), (129, False)])
def test_C02_json_numeric_token_boundary_is_named_and_exact(
    tmp_path: Path, digits: int, accepted: bool
) -> None:
    """C02/D03: JSON numeric tokens cap at named 128/129 boundary."""
    bounded = _bounded_source()
    assert bounded.JSON_MAX_NUMBER_CHARS == 128
    path = tmp_path / "config.schema.json"
    token = "1" + "0" * (digits - 1)
    path.write_text('{"number":' + token + "}", encoding="utf-8")
    if accepted:
        assert bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)[
            "number"
        ] == int(token)
    else:
        with pytest.raises(CatalogError) as exc:
            bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
        assert exc.value.code == "parser_limit"


@pytest.mark.parametrize("items,accepted", [(2_046, True), (2_047, False)])
def test_C02_json_graph_entry_boundary_is_exact(
    tmp_path: Path, items: int, accepted: bool
) -> None:
    """C02: root + mapping value + array items gives graph 2048/2049."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text('{"items":[' + ",".join("0" for _ in range(items)) + "]}")
    if accepted:
        loaded = bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
        assert len(loaded["items"]) == items
    else:
        with pytest.raises(CatalogError) as exc:
            bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
        assert exc.value.code == "parser_limit"


@pytest.mark.parametrize("wrappers,accepted", [(23, True), (24, False)])
def test_C02_json_depth_boundary_is_exact(
    tmp_path: Path, wrappers: int, accepted: bool
) -> None:
    """C02: root depth zero makes 23 wrappers depth24, 24 depth25."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text(
        '{"value":' + "[" * wrappers + "0" + "]" * wrappers + "}",
        encoding="utf-8",
    )
    if accepted:
        assert "value" in bounded.load_json_mapping(
            path, bounded.CONFIG_SCHEMA_CONTRACT
        )
    else:
        with pytest.raises(CatalogError) as exc:
            bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
        assert exc.value.code == "parser_limit"


def test_C02_config_descriptor_replacement_after_open_keeps_original(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C02: config identity and bytes belong to one descriptor."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text('{"version":1,"fields":[]}', encoding="utf-8")
    replacement = tmp_path / "replacement.json"
    replacement.write_text('{"PRIVATE-SENTINEL":true}', encoding="utf-8")
    original = bounded._open_source_descriptor

    def replaced(source: Path) -> int:
        fd = original(source)
        os.replace(replacement, source)
        return fd

    monkeypatch.setattr(bounded, "_open_source_descriptor", replaced)
    loaded = bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert loaded == {"version": 1, "fields": []}


def test_C02_config_identity_is_lexical_and_never_pre_resolved(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C02: safe relative descriptor reaches no-follow loader unchanged."""
    _configure_descriptor_fixture(matrix_repo)
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    metadata = yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
    seen: list[tuple[Path, str]] = []
    bounded = _bounded_source()
    original = getattr(bounded, "load_json_mapping_relative", None)

    def loaded(directory: Path, basename: str, contract):
        seen.append((directory, basename))
        if original is None:
            return bounded.load_json_mapping(directory / basename, contract)
        return original(directory, basename, contract)

    monkeypatch.setattr(bounded, "load_json_mapping_relative", loaded, raising=False)
    monkeypatch.setattr(
        Path,
        "resolve",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("resolve erased link identity")
        ),
    )
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugin_dir, metadata, "plugins/ericsson-example", problems
    )
    assert not problems
    assert required == {"origin", "token"}
    assert optional == {"certificate_path"}
    assert seen == [(plugin_dir, "config.schema.json")]


@pytest.mark.parametrize("shape", ["directory", "symlink"])
def test_C02_config_nonregular_and_link_sources_fail_closed(
    tmp_path: Path, shape: str
) -> None:
    """C02: config descriptors use the identical regular no-follow policy."""
    if os.name != "posix" and shape == "symlink":
        pytest.skip("real symlink covered by deterministic Windows reparse tests")
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    if shape == "directory":
        path.mkdir()
    else:
        target = tmp_path / "target.json"
        target.write_text('{"PRIVATE-SENTINEL":true}', encoding="utf-8")
        path.symlink_to(target)
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert exc.value.code == "unsafe_source"
    assert "PRIVATE-SENTINEL" not in str(exc.value)


def test_C02_missing_required_config_is_not_optional_absence(tmp_path: Path) -> None:
    """C02: config contract distinguishes ENOENT without message inspection."""
    bounded = _bounded_source()
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(
            tmp_path / "missing.schema.json", bounded.CONFIG_SCHEMA_CONTRACT
        )
    assert exc.value.code == "missing_source"


@pytest.mark.parametrize(
    "descriptor",
    [
        "",
        ".",
        "nested/../config.json",
        "nested/config.json",
        "..\\config.json",
        "C:\\config.json",
        "\\\\server\\share\\config.json",
        "\\\\.\\device\\config.json",
        "/absolute/config.json",
        "CON",
        "con.json",
        "PRN.yaml",
        "AUX",
        "NUL.txt",
        "COM1.json",
        "com9",
        "LPT1.schema",
        "lpt9.json",
        "config.json.",
        "config.json ",
    ],
    ids=(
        "empty",
        "dot",
        "nested-dotdot",
        "intermediate-component",
        "backslash",
        "drive",
        "unc",
        "device-namespace",
        "absolute",
        "dos-con",
        "dos-con-extension",
        "dos-prn",
        "dos-aux",
        "dos-nul",
        "dos-com1",
        "dos-com9",
        "dos-lpt1",
        "dos-lpt9",
        "trailing-dot",
        "trailing-space",
    ),
)
def test_C02_config_descriptor_is_one_portable_lexical_basename(
    matrix_repo: RepoFixture, descriptor: str
) -> None:
    """C02: basename-only policy closes POSIX symlink/Windows junction traversal."""
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    metadata = yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
    metadata["config_schema"] = descriptor
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugin_dir, metadata, "plugins/ericsson-example", problems
    )
    assert required == optional == set()
    assert problems == ["unsafe plugin config schema: plugins/ericsson-example"]


@pytest.mark.skipif(os.name != "posix", reason="real intermediate symlink is POSIX")
def test_C02_intermediate_symlink_is_rejected_lexically_before_target_access(
    matrix_repo: RepoFixture, tmp_path: Path
) -> None:
    """C02: nested descriptor cannot traverse an internal/external symlink."""
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    external = tmp_path / "PRIVATE-SENTINEL"
    external.mkdir()
    (external / "config.json").write_text('{"PRIVATE-SENTINEL":true}', encoding="utf-8")
    (plugin_dir / "nested").symlink_to(external, target_is_directory=True)
    metadata = yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
    metadata["config_schema"] = "nested/config.json"
    problems: list[str] = []
    catalog_lib._plugin_config_schema_contract(
        plugin_dir, metadata, "plugins/ericsson-example", problems
    )
    assert problems == ["unsafe plugin config schema: plugins/ericsson-example"]


def test_C02_windows_intermediate_junction_shape_never_reaches_loader(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C02/D01: basename gate rejects junction-capable intermediate components."""
    bounded = _bounded_source()
    calls: list[Path] = []
    monkeypatch.setattr(bounded, "_platform_name", lambda: "nt")
    monkeypatch.setattr(
        bounded,
        "load_json_mapping",
        lambda path, _contract: calls.append(path) or {},
    )
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    metadata = yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
    metadata["config_schema"] = "junction/config.json"
    problems: list[str] = []
    catalog_lib._plugin_config_schema_contract(
        plugin_dir, metadata, "plugins/ericsson-example", problems
    )
    assert problems == ["unsafe plugin config schema: plugins/ericsson-example"]
    assert calls == []


@pytest.mark.parametrize("shape", ["growth", "short-read"])
def test_C02_config_growth_and_short_reads_remain_bounded(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, shape: str
) -> None:
    """C02: post-fstat growth and fragmented descriptor reads share cap."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text('{"version":1,"fields":[]}', encoding="utf-8")
    original = bounded._read_descriptor
    first = True
    requests: list[int] = []

    def read(fd: int, size: int) -> bytes:
        nonlocal first
        requests.append(size)
        if first and shape == "growth":
            first = False
            path.write_bytes(b"{" + b'"x":1,' * 100_000 + b'"z":0}')
        return original(fd, min(size, 11) if shape == "short-read" else size)

    monkeypatch.setattr(bounded, "_read_descriptor", read)
    if shape == "growth":
        with pytest.raises(CatalogError) as exc:
            bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
        assert exc.value.code == "byte_limit"
    else:
        assert (
            bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)["version"]
            == 1
        )
    assert requests and all(0 < size <= CONFIG_SCHEMA_LIMIT + 1 for size in requests)


@pytest.mark.parametrize("operation", ["open", "fstat", "read", "close"])
def test_C02_config_descriptor_errors_are_fixed_and_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """C02: every descriptor-stage error has fixed code and no JSON leakage."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text('{"version":1,"fields":[]}', encoding="utf-8")
    seam = {
        "open": "_open_source_descriptor",
        "fstat": "_fstat_descriptor",
        "read": "_read_descriptor",
        "close": "_close_descriptor",
    }[operation]
    original = getattr(bounded, seam)
    closed = False
    owned: list[int] = []

    def fail(*args):
        nonlocal closed
        if operation in {"fstat", "read", "close"}:
            owned.append(args[0])
        if operation == "close":
            original(*args)
            closed = True
        raise OSError(errno.EIO, "PRIVATE-SENTINEL")

    monkeypatch.setattr(bounded, seam, fail)
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert exc.value.code == "io_error"
    assert "PRIVATE-SENTINEL" not in str(exc.value)
    if operation == "close":
        assert closed
    if operation in {"fstat", "read", "close"}:
        assert len(owned) == 1
        with pytest.raises(OSError):
            os.fstat(owned[0])


@pytest.mark.parametrize("failure", ["utf8", "parser", "duplicate", "io", "close"])
def test_C02_config_real_caller_diagnostics_are_fixed_and_redacted(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    failure: str,
) -> None:
    """C02/B08: real config consumer never projects path/value/OS details."""
    bounded = _bounded_source()
    _configure_descriptor_fixture(matrix_repo)
    matrix_repo.write_complete_entry(configuration=_descriptor_configuration())
    schema = matrix_repo.root / "plugins/ericsson-example/config.schema.json"
    if failure == "utf8":
        schema.write_bytes(b"\xffPRIVATE-SENTINEL")
    elif failure == "parser":
        schema.write_text('{"version": PRIVATE-SENTINEL', encoding="utf-8")
    elif failure == "duplicate":
        schema.write_text(
            '{"version":1,"version":"PRIVATE-SENTINEL","fields":[]}',
            encoding="utf-8",
        )
    else:
        seam = "_read_descriptor" if failure == "io" else "_close_descriptor"
        original = getattr(bounded, seam)
        identity = (schema.stat().st_dev, schema.stat().st_ino)
        attempts: list[int] = []

        def fail(*args):
            metadata = os.fstat(args[0])
            if (metadata.st_dev, metadata.st_ino) == identity:
                attempts.append(args[0])
                if failure == "close":
                    original(*args)
                raise OSError(errno.EIO, "PRIVATE-SENTINEL")
            return original(*args)

        monkeypatch.setattr(bounded, seam, fail)
    problems = _catalog_problems(matrix_repo)
    expected = (
        "invalid plugin config schema: plugins/ericsson-example: config.schema.json"
    )
    assert expected in problems
    rendered = json.dumps(problems)
    assert "PRIVATE-SENTINEL" not in rendered
    assert str(matrix_repo.root) not in rendered
    if failure in {"utf8", "parser", "duplicate"}:
        result = _cli(CATALOG_SCRIPTS / "validate_catalog.py", matrix_repo)
        _assert_fixed_cli_failure(result)
        assert str(matrix_repo.root) not in result.stdout
    else:
        assert len(attempts) == 1


@pytest.mark.parametrize("flat", [True, False], ids=("archon", "v1"))
def test_C03_workflow_definitions_are_bounded_before_yaml_materialization(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch, flat: bool
) -> None:
    """C03: both Archon and V1 workflow definitions share bounded YAML."""
    workflow = matrix_repo.root / "workflows/example.yml"
    if not flat:
        workflow.write_text(
            "name: example\nrequires: {env: []}\nnodes: []\n", encoding="utf-8"
        )
        (matrix_repo.root / "workflows/example.hermes.yaml").unlink()
    workflow.write_text(
        workflow.read_text() + "#" + "x" * WORKFLOW_METADATA_LIMIT,
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="workflow metadata exceeds safe byte limit"):
        _catalog_problems(matrix_repo)
    monkeypatch.setattr(lint_manifest, "REPO", matrix_repo.root)
    assert lint_manifest.lint(matrix_repo.root / "sets/ericsson.json") == [
        "workflows/example.yml: workflow metadata exceeds safe byte limit"
    ]


def _workflow_document(*, archon: bool, tag_aliases: int = 0) -> str:
    aliases = ""
    if tag_aliases:
        aliases = (
            "tags: [&tag probe," + ",".join("*tag" for _ in range(tag_aliases)) + "]\n"
        )
    if archon:
        return (
            "name: example\ndescription: Example\nrequires: [ericsson-example]\n"
            + aliases
            + "nodes:\n  - id: inspect\n    prompt: Use example_tool\n"
            "    allowed_tools: [example_tool]\n"
        )
    return (
        "name: example\ndescription: Example\nversion: 1.0.0\n"
        "requires: {toolsets: [ericsson-example], mcp_servers: [], env: []}\n"
        + aliases
        + "nodes:\n  - id: inspect\n    kind: tool\n    tools: [example_tool]\n"
        "    prompt: Use example_tool\n"
    )


@pytest.mark.parametrize("archon", [True, False], ids=("archon", "v1"))
@pytest.mark.parametrize(
    "size,accepted", [(524_287, True), (524_288, True), (524_289, False)]
)
def test_C03_workflow_exact_byte_edges_through_catalog_and_real_lint(
    matrix_repo: RepoFixture, archon: bool, size: int, accepted: bool
) -> None:
    """C03: both workflow languages have exact 512 KiB source boundaries."""
    workflow = matrix_repo.root / "workflows/example.yml"
    content = _workflow_document(archon=archon).encode()
    assert len(content) < size
    workflow.write_bytes(content + b"#" + b"x" * (size - len(content) - 2) + b"\n")
    sidecar = matrix_repo.root / "workflows/example.hermes.yaml"
    if not archon:
        sidecar.unlink()
    try:
        catalog_ok = _catalog_problems(matrix_repo) == []
    except CatalogError:
        catalog_ok = False
    lint_ok = _manifest_cli(matrix_repo).returncode == 0
    assert [catalog_ok, lint_ok] == [accepted, accepted]


@pytest.mark.parametrize("archon", [True, False], ids=("archon", "v1"))
@pytest.mark.parametrize("aliases,accepted", [(128, True), (129, False)])
def test_C03_every_workflow_language_has_exact_alias_boundary(
    matrix_repo: RepoFixture, archon: bool, aliases: int, accepted: bool
) -> None:
    """C03: alias 128/129 applies equally to Archon and V1 sources."""
    workflow = matrix_repo.root / "workflows/example.yml"
    workflow.write_text(
        _workflow_document(archon=archon, tag_aliases=aliases), encoding="utf-8"
    )
    if not archon:
        (matrix_repo.root / "workflows/example.hermes.yaml").unlink()
    try:
        catalog_ok = _catalog_problems(matrix_repo) == []
    except CatalogError:
        catalog_ok = False
    lint_ok = _manifest_cli(matrix_repo).returncode == 0
    assert [catalog_ok, lint_ok] == [accepted, accepted]


@pytest.mark.parametrize("archon", [True, False], ids=("archon", "v1"))
@pytest.mark.parametrize(
    "adjacent", [False, True], ids=("entries-2048", "entries-2049")
)
def test_C03_workflow_graph_entry_boundary_is_exact_for_both_languages(
    matrix_repo: RepoFixture, archon: bool, adjacent: bool
) -> None:
    """C03: preserved root+values/items metric is exact for both formats."""
    tag_count = (2_036 if archon else 2_031) + int(adjacent)
    content = (
        _workflow_document(archon=archon)
        + "tags: ["
        + ",".join("x" for _ in range(tag_count))
        + "]\n"
    )
    (matrix_repo.root / "workflows/example.yml").write_text(content, encoding="utf-8")
    if not archon:
        (matrix_repo.root / "workflows/example.hermes.yaml").unlink()
    if adjacent:
        with pytest.raises(CatalogError) as exc:
            _catalog_problems(matrix_repo)
        assert exc.value.code == "parser_limit"
        _assert_fixed_cli_failure(_manifest_cli(matrix_repo))
    else:
        assert _catalog_problems(matrix_repo) == []
        assert _manifest_cli(matrix_repo).returncode == 0


@pytest.mark.parametrize("archon", [True, False], ids=("archon", "v1"))
@pytest.mark.parametrize("depth,accepted", [(23, True), (24, False)])
def test_C03_workflow_depth_boundary_is_exact_for_both_languages(
    matrix_repo: RepoFixture, archon: bool, depth: int, accepted: bool
) -> None:
    """C03: mapping-key traversal excluded from workflow depth 24/25."""
    content = (
        _workflow_document(archon=archon)
        + "tags: "
        + "[" * depth
        + "x"
        + "]" * depth
        + "\n"
    )
    (matrix_repo.root / "workflows/example.yml").write_text(content, encoding="utf-8")
    if not archon:
        (matrix_repo.root / "workflows/example.hermes.yaml").unlink()
    try:
        catalog_ok = _catalog_problems(matrix_repo) == []
    except CatalogError:
        catalog_ok = False
    lint_ok = _manifest_cli(matrix_repo).returncode == 0
    assert [catalog_ok, lint_ok] == [accepted, accepted]


@pytest.mark.parametrize("archon", [True, False], ids=("archon", "v1"))
@pytest.mark.parametrize("failure", ["duplicate", "merge", "nodes", "depth"])
def test_C03_workflow_parser_failure_matrix_through_both_consumers(
    matrix_repo: RepoFixture, archon: bool, failure: str
) -> None:
    """C03: duplicate/merge/node/depth bounds precede either validator."""
    base = _workflow_document(archon=archon)
    if failure == "duplicate":
        content = base + "name: second\n"
    elif failure == "merge":
        content = base + "probe: &p {}\nmerged: {<<: *p}\n"
    elif failure == "nodes":
        content = base + "tags: [" + ",".join("x" for _ in range(2_100)) + "]\n"
    else:
        content = base + "tags: " + "[" * 25 + "x" + "]" * 25 + "\n"
    (matrix_repo.root / "workflows/example.yml").write_text(content, encoding="utf-8")
    if not archon:
        (matrix_repo.root / "workflows/example.hermes.yaml").unlink()
    with pytest.raises(CatalogError):
        _catalog_problems(matrix_repo)
    lint = _manifest_cli(matrix_repo)
    _assert_fixed_cli_failure(lint)


@pytest.mark.parametrize("failure", ["utf8", "parser", "duplicate"])
def test_C03_workflow_real_caller_diagnostics_are_label_only_and_redacted(
    matrix_repo: RepoFixture, failure: str
) -> None:
    """C03/B08: catalog and real lint CLI expose fixed workflow labels only."""
    workflow = matrix_repo.root / "workflows/example.yml"
    if failure == "utf8":
        workflow.write_bytes(b"\xffPRIVATE-SENTINEL")
    elif failure == "parser":
        workflow.write_text("name: [PRIVATE-SENTINEL\n", encoding="utf-8")
    else:
        workflow.write_text(
            "name: example\n!!str name: PRIVATE-SENTINEL\n",
            encoding="utf-8",
        )
    with pytest.raises(CatalogError) as exc:
        _catalog_problems(matrix_repo)
    assert exc.value.code in {"invalid_yaml", "duplicate_key"}
    assert str(matrix_repo.root) not in str(exc.value)
    assert "PRIVATE-SENTINEL" not in str(exc.value)
    for result in (
        _cli(CATALOG_SCRIPTS / "validate_catalog.py", matrix_repo),
        _manifest_cli(matrix_repo),
    ):
        _assert_fixed_cli_failure(result)
        assert str(matrix_repo.root) not in result.stdout


@pytest.mark.parametrize("operation", ["io", "close"])
def test_C03_workflow_descriptor_failures_are_fixed_through_real_caller(
    matrix_repo: RepoFixture,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """C03: real repository validation redacts descriptor and close failures."""
    bounded = _bounded_source()
    seam = "_read_descriptor" if operation == "io" else "_close_descriptor"
    original = getattr(bounded, seam)
    workflow = matrix_repo.root / "workflows/example.yml"
    target_identity = (workflow.stat().st_dev, workflow.stat().st_ino)
    attempts: list[int] = []

    def fail(*args):
        metadata = os.fstat(args[0])
        if (metadata.st_dev, metadata.st_ino) == target_identity:
            attempts.append(args[0])
            if operation == "close":
                original(*args)
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")
        return original(*args)

    monkeypatch.setattr(bounded, seam, fail)
    with pytest.raises(CatalogError) as exc:
        _catalog_problems(matrix_repo)
    assert exc.value.code == "io_error"
    assert str(exc.value) == "workflow metadata could not be read safely"
    assert "PRIVATE-SENTINEL" not in str(exc.value)
    assert len(attempts) == 1


def test_C04_approval_ancestry_is_iterative_bounded_for_deep_wide_cycle() -> None:
    """C04: validated graph traversal must not recurse or loop."""
    nodes = [{"id": "approve", "approval": {"message": "approve"}}]
    for index in range(1_500):
        nodes.append(
            {
                "id": f"n{index}",
                "depends_on": ["approve" if index == 0 else f"n{index - 1}"],
                "prompt": "read",
                "allowed_tools": [],
            }
        )
    nodes[-1]["allowed_tools"] = ["example_write"]
    nodes[-1]["depends_on"].extend(f"n{index}" for index in range(0, 1_500, 25))
    nodes[1]["depends_on"].append(nodes[-1]["id"])
    problems = lint_manifest._lint_archon_workflow(
        {"name": "deep", "description": "deep", "requires": ["tools"], "nodes": nodes}
    )
    assert problems == ["workflow dependency graph contains a cycle"]


def _archon_graph(nodes: list[dict[str, object]]) -> dict[str, object]:
    return {
        "name": "graph",
        "description": "Graph probe",
        "requires": ["tools"],
        "nodes": nodes,
    }


@pytest.mark.parametrize("approved", [True, False], ids=("approved", "unapproved"))
def test_C04_deep_ancestry_is_iterative_and_truthful(approved: bool) -> None:
    """C04: 1,500-deep reachability does not recurse and preserves result."""
    if approved:
        nodes: list[dict[str, object]] = [
            {"id": "root", "approval": {"message": "approve"}}
        ]
    else:
        nodes = [{"id": "root", "prompt": "read", "allowed_tools": []}]
    for index in range(1_500):
        nodes.append(
            {
                "id": f"n{index}",
                "depends_on": ["root" if index == 0 else f"n{index - 1}"],
                "prompt": "read",
                "allowed_tools": [],
            }
        )
    nodes[-1]["allowed_tools"] = ["example_write"]
    problems = lint_manifest._lint_archon_workflow(_archon_graph(nodes))
    if approved:
        assert problems == []
    else:
        assert problems == ["node n1499: outward tool requires approval ancestor"]


def test_C04_wide_shared_ancestry_is_computed_once_per_graph() -> None:
    """C04/D03: wide shared predecessors remain O(N+E), not per-write DFS."""
    yielded = 0

    class CountingParents(AbstractSet[str]):
        def __init__(self, values: set[str]) -> None:
            self.values = values

        def __contains__(self, value: object) -> bool:
            return value in self.values

        def __len__(self) -> int:
            return len(self.values)

        def __iter__(self):
            nonlocal yielded
            for value in self.values:
                yielded += 1
                yield value

    raw: dict[str, set[str]] = {"approve": set()}
    previous = "approve"
    for index in range(700):
        current = f"shared{index}"
        raw[current] = {previous}
        previous = current
    for index in range(700):
        raw[f"write{index}"] = {previous}
    dependencies = {node: CountingParents(parents) for node, parents in raw.items()}
    reachable, cyclic = lint_manifest._approval_reachability(dependencies, {"approve"})
    assert not cyclic
    assert all(reachable[f"write{index}"] for index in range(700))
    edge_count = sum(len(parents) for parents in dependencies.values())
    assert yielded <= 2 * edge_count


@pytest.mark.parametrize("nodes,accepted", [(2_048, True), (2_049, False)])
def test_C04_archon_node_limit_is_named_and_exact(nodes: int, accepted: bool) -> None:
    """C04: named static node budget accepts 2048 and rejects 2049."""
    assert lint_manifest.MAX_ARCHON_NODES == 2_048
    document = _archon_graph(
        [
            {"id": f"n{index}", "prompt": "read", "allowed_tools": []}
            for index in range(nodes)
        ]
    )
    problems = lint_manifest._lint_archon_workflow(document)
    assert (problems == []) is accepted
    if not accepted:
        assert problems == ["workflow exceeds safe node limit"]


@pytest.mark.parametrize("edges,accepted", [(8_192, True), (8_193, False)])
def test_C04_archon_dependency_edge_limit_is_named_and_exact(
    edges: int, accepted: bool
) -> None:
    """C04: named dependency edge budget accepts 8192 and rejects 8193."""
    assert lint_manifest.MAX_ARCHON_DEPENDENCY_EDGES == 8_192
    sources = [
        {"id": f"s{index}", "prompt": "read", "allowed_tools": []}
        for index in range(2_044)
    ]
    source_ids = [node["id"] for node in sources]
    sinks = [
        {
            "id": f"sink{index}",
            "depends_on": source_ids,
            "prompt": "read",
            "allowed_tools": [],
        }
        for index in range(4)
    ]
    for index in range(1, 17 + int(not accepted)):
        sources[index]["depends_on"] = ["s0"]
    document = _archon_graph(sources + sinks)
    problems = lint_manifest._lint_archon_workflow(document)
    assert (problems == []) is accepted
    if not accepted:
        assert problems == ["workflow exceeds safe dependency edge limit"]


def test_C04_unknown_dependency_and_cycle_have_stable_diagnostics() -> None:
    """C04: bounded graph analysis retains unknown/cycle facts."""
    unknown = _archon_graph(
        [
            {
                "id": "write",
                "depends_on": ["missing"],
                "prompt": "write",
                "allowed_tools": ["example_write"],
            }
        ]
    )
    problems = lint_manifest._lint_archon_workflow(unknown)
    assert "node write: unknown dependency: missing" in problems
    assert "node write: outward tool requires approval ancestor" in problems

    cyclic = _archon_graph(
        [
            {"id": "a", "depends_on": ["b"], "prompt": "read", "allowed_tools": []},
            {
                "id": "b",
                "depends_on": ["a"],
                "prompt": "write",
                "allowed_tools": ["example_write"],
            },
        ]
    )
    cycle_problems = lint_manifest._lint_archon_workflow(cyclic)
    assert "workflow dependency graph contains a cycle" in cycle_problems


@pytest.mark.parametrize(
    "factory,registration,accepted",
    [
        (
            "def handler(name):\n        def invoke(args): return (name,args)\n        return invoke",
            "handler(name)",
            True,
        ),
        (
            "def handler(name):\n        def invoke(args): return missing(args)\n        return invoke",
            "handler(name)",
            True,
        ),
        (
            "def handler(name):\n        return lambda args: missing(args)",
            "handler(name)",
            True,
        ),
        ("def handler(name):\n        return None", "handler(name)", False),
        ("def handler(name):\n        return 7", "handler(name)", False),
        (
            "def handler(other):\n        def invoke(args): return other\n        return invoke",
            "handler(name)",
            False,
        ),
        (
            "def unrelated(name):\n        def invoke(args): return args\n        return invoke",
            "handler(name)",
            False,
        ),
        (
            "def handler(name):\n        def invoke(args): return name\n        return invoke",
            "handler(schema)",
            False,
        ),
    ],
)
def test_C05_handler_factory_proof_is_structural_and_fail_closed(
    matrix_repo: RepoFixture, factory: str, registration: str, accepted: bool
) -> None:
    """C05: factory, nested callable, loop variable and schema binding are proven."""
    source = (
        "import example_tools\n\ndef register(ctx):\n    "
        + factory
        + "\n    for name, schema in example_tools.SCHEMAS.items():\n"
        + f"        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler={registration})\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    problems = _catalog_problems(matrix_repo)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in problems) is accepted


@pytest.mark.parametrize(
    "source",
    [
        # Registered schema is not the schema variable paired with name.
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n        def invoke(args): return name\n        return invoke\n"
        "    wrong = {}\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=wrong, handler=handler(name))\n",
        # Factory is outside the owning register scope.
        "import example_tools\ndef handler(name):\n"
        "    def invoke(args): return name\n    return invoke\n"
        "def register(ctx):\n    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n",
        # Same-shaped loop is disconnected from SCHEMAS.
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n        def invoke(args): return name\n        return invoke\n"
        "    other = {'example_tool': {}}\n    for name, schema in other.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n",
        # Conditional/fallthrough factory does not prove one callable result.
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n        def invoke(args): return name\n"
        "        if name: return invoke\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n",
        # Every literal map value must itself be a callable expression.
        "import example_tools\ndef register(ctx):\n"
        "    handlers = {'example_tool': None}\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handlers[name])\n",
        # The SCHEMAS owner must still be the imported local schema module.
        "import example_tools\nexample_tools = None\ndef register(ctx):\n"
        "    def handler(name):\n        def invoke(args): return args\n        return invoke\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n",
    ],
    ids=(
        "mismatched-schema",
        "module-factory",
        "disconnected-loop",
        "conditional-fallthrough",
        "literal-map-noncallable",
        "schema-module-rebound",
    ),
)
def test_C05_additional_lexical_factory_negatives_fail_closed(
    matrix_repo: RepoFixture, source: str
) -> None:
    """C05: exact scope/control-flow/schema-source proof is mandatory."""
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


def test_C05_actual_gitlab_factory_and_literal_callable_map_controls() -> None:
    """C05/D02: real generic factory passes without weakening literal maps."""
    assert catalog_lib.validate_repository(REPO, catalog_lib.load_entries(REPO)) == []


@pytest.mark.parametrize(
    "register_head,receiver,accepted",
    [
        ("def register(ctx):", "ctx", True),
        ("def register():", "ctx", False),
        ("def register(ctx, other):", "ctx", False),
        ("def register(ctx, other=None):", "ctx", False),
        ("def register(ctx):", "other", False),
    ],
)
def test_C05_register_signature_and_receiver_are_exact(
    matrix_repo: RepoFixture,
    register_head: str,
    receiver: str,
    accepted: bool,
) -> None:
    """C05: the direct one-parameter register authority owns registration."""
    source = (
        "import example_tools\n" + register_head + "\n    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        f"        {receiver}.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "body,accepted",
    [
        (
            "    def handler(name):\n"
            "        def invoke(args): return args\n"
            "        return invoke\n"
            "    handler = None\n",
            False,
        ),
        (
            "    def handler(name):\n"
            "        def invoke(args): return args\n"
            "        return invoke\n",
            True,
        ),
        (
            "    def invoke(args): return args\n"
            "    invoke = None\n"
            "    handlers = {'example_tool': invoke}\n",
            False,
        ),
    ],
)
def test_C05_active_binding_at_registration_is_statement_ordered(
    matrix_repo: RepoFixture, body: str, accepted: bool
) -> None:
    """C05: earlier definitions can be rebound, while later ones are not retroactive."""
    source = "import example_tools\ndef register(ctx):\n" + body
    if "handlers" in body:
        handler = "handlers[name]"
    else:
        handler = "handler(name)"
    source += (
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        f"        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler={handler})\n"
    )
    if accepted:
        source += (
            "    def handler(name):\n"
            "        def later(args): return args\n"
            "        return later\n"
        )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


def test_C05_schema_inventory_is_direct_module_scope_only() -> None:
    """C05: nested/local SCHEMAS definitions never enter module inventory."""
    tree = ast.parse(
        "def build():\n    SCHEMAS = {'ghost': {'name': 'ghost'}}\n    return SCHEMAS\n"
    )
    assert catalog_lib._schema_contract(tree) == (set(), {})


@pytest.mark.parametrize(
    "module_members",
    [
        "def invoke(args): return args\nHANDLERS = {'example_tool': invoke}\n",
        (
            "def wrap(fn):\n"
            "    def invoke(args): return fn(args)\n"
            "    return invoke\n"
            "HANDLERS = {'example_tool': wrap(example_tools.invoke)}\n"
        ),
    ],
)
def test_C05_module_literal_maps_preserve_active_callable_bindings(
    matrix_repo: RepoFixture, module_members: str
) -> None:
    """C05: the legacy module-level literal callable-map form remains valid."""
    source = (
        "import example_tools\n" + module_members + "def register(ctx):\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=HANDLERS[name])\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        not in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "mutation",
    [
        "    if flag:\n        handler = None\n",
        "    for handler in values:\n        pass\n",
        "    with resource as handler:\n        pass\n",
        "    try:\n        pass\n    except Exception as handler:\n        pass\n",
        "    match value:\n        case {'handler': handler}:\n            pass\n",
        "    (handler, *rest) = values\n",
        "    handler: object = None\n",
        "    handler += value\n",
        "    value = (handler := None)\n",
        "    del handler\n",
        "    import other as handler\n",
        "    class handler:\n        pass\n",
    ],
)
def test_C05_compound_and_target_bindings_invalidate_factory_authority(
    matrix_repo: RepoFixture, mutation: str
) -> None:
    """C05: every direct register-scope binding form affects active authority."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        + mutation
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "loop,body",
    [
        (
            "for ctx, schema in example_tools.SCHEMAS.items():",
            "ctx.register_tool(name=ctx, toolset='ericsson-example', schema=schema, handler=handler(ctx))",
        ),
        (
            "for handler, schema in example_tools.SCHEMAS.items():",
            "ctx.register_tool(name=handler, toolset='ericsson-example', schema=schema, handler=handler(handler))",
        ),
        (
            "for name, schema in example_tools.SCHEMAS.items():",
            "ctx = None\n        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))",
        ),
        (
            "for name, schema in example_tools.SCHEMAS.items():",
            "handler = None\n        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))",
        ),
    ],
)
def test_C05_loop_overlay_and_pre_call_bindings_fail_closed(
    matrix_repo: RepoFixture, loop: str, body: str
) -> None:
    """C05: loop targets and preceding loop-body binds overlay outer authority."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        f"    {loop}\n        {body}\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


def test_C05_schema_contract_uses_only_final_direct_binding() -> None:
    """C05: an overwritten SCHEMAS dict cannot leave stale inventory behind."""
    tree = ast.parse(
        "SCHEMAS = {'stale': {'name': 'stale'}}\n"
        "SCHEMAS = {'active': {'name': 'active'}}\n"
    )
    assert catalog_lib._schema_contract(tree) == ({"active"}, {"active": "active"})
    overwritten = ast.parse("SCHEMAS = {'stale': {'name': 'stale'}}\nSCHEMAS = None\n")
    assert catalog_lib._schema_contract(overwritten) == (set(), {})


@pytest.mark.parametrize(
    "import_source,accepted",
    [
        ("import example_tools", True),
        ("from . import example_tools as schema_module", True),
        ("import foreign.example_tools as example_tools", False),
    ],
)
def test_C05_schema_import_provenance_is_exact_local_module(
    matrix_repo: RepoFixture, import_source: str, accepted: bool
) -> None:
    """C05: basename borrowing cannot impersonate a local schema module."""
    binding = "schema_module" if import_source.startswith("from") else "example_tools"
    source = (
        import_source + "\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        f"    for name, schema in {binding}.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


def test_C05_register_local_schema_import_shadow_fails_closed(
    matrix_repo: RepoFixture,
) -> None:
    """C05: a register-local binding shadows the module schema authority."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    import other as example_tools\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "module_callable,local_map",
    [
        (
            "def invoke(args): return args\n",
            "handlers = {'example_tool': invoke}",
        ),
        (
            "def wrap(fn):\n    def invoke(args): return fn(args)\n    return invoke\n",
            "handlers = {'example_tool': wrap(example_tools.invoke)}",
        ),
    ],
)
def test_C05_local_map_may_use_unshadowed_module_callable(
    matrix_repo: RepoFixture, module_callable: str, local_map: str
) -> None:
    """C05: local literal maps preserve active module callable compatibility."""
    source = (
        "import example_tools\n" + module_callable + "def register(ctx):\n"
        f"    {local_map}\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handlers[name])\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        not in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "isolated_target",
    ["ctx", "name", "schema", "handler", "example_tools"],
)
def test_C05_comprehension_targets_do_not_escape_their_lexical_scope(
    matrix_repo: RepoFixture, isolated_target: str
) -> None:
    """C05: comprehension-local target names do not rebind register authority."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        f"    values = [{isolated_target} for {isolated_target} in items]\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        not in _catalog_problems(matrix_repo)
    )


def test_C05_comprehension_target_named_schemas_does_not_replace_module_binding() -> (
    None
):
    """C05: a comprehension target cannot overwrite module SCHEMAS inventory."""
    tree = ast.parse(
        "SCHEMAS = {'active': {'name': 'active'}}\n"
        "values = [SCHEMAS for SCHEMAS in rows]\n"
    )
    assert catalog_lib._schema_contract(tree) == ({"active"}, {"active": "active"})


@pytest.mark.parametrize(
    "eager_statement",
    [
        "    @((handler := decorator))\n    def helper():\n        pass\n",
        "    def helper(value=(handler := None)):\n        pass\n",
        "    @((handler := decorator))\n    class Helper:\n        pass\n",
        "    class Helper((handler := Base)):\n        pass\n",
        "    value = lambda arg=(handler := None): arg\n",
        "    values = [item for item in items if (handler := item)]\n",
    ],
)
def test_C05_eager_definition_and_comprehension_expressions_bind_outer_scope(
    matrix_repo: RepoFixture, eager_statement: str
) -> None:
    """C05: eager expressions remain visible while nested bodies stay opaque."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        + eager_statement
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "prefix,suffix,accepted",
    [
        ("def register():\n    pass\n", "", True),
        ("", "register = None\n", False),
        ("", "if flag:\n    register = None\n", False),
        ("", "value = (register := None)\n", False),
    ],
)
def test_C05_final_active_register_binding_controls_authority(
    matrix_repo: RepoFixture, prefix: str, suffix: str, accepted: bool
) -> None:
    """C05: the final active direct register binding is authoritative."""
    valid = (
        "def register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text(
        "plugins/ericsson-example/__init__.py",
        "import example_tools\n" + prefix + valid + suffix,
    )
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "tail,accepted",
    [
        ("    HANDLERS = None\n", False),
        ("    if flag:\n        HANDLERS = None\n", False),
        ("    values = [HANDLERS for HANDLERS in items]\n", True),
    ],
)
def test_C05_module_map_fallback_uses_whole_function_lexical_locals(
    matrix_repo: RepoFixture, tail: str, accepted: bool
) -> None:
    """C05: real function locals block module maps; comprehension targets do not."""
    source = (
        "import example_tools\n"
        "def invoke(args): return args\n"
        "HANDLERS = {'example_tool': invoke}\n"
        "def register(ctx):\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=HANDLERS[name])\n"
        + tail
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "import_line,accepted",
    [
        (
            "import example_tools as schema_module, foreign.example_tools as schema_module",
            False,
        ),
        (
            "import foreign.example_tools as schema_module, example_tools as schema_module",
            True,
        ),
        (
            "from . import example_tools as schema_module, other as schema_module",
            False,
        ),
        (
            "from . import other as schema_module, example_tools as schema_module",
            True,
        ),
    ],
)
def test_C05_same_statement_import_aliases_use_left_to_right_final_binding(
    matrix_repo: RepoFixture, import_line: str, accepted: bool
) -> None:
    """C05: a later alias in one import statement supersedes earlier aliases."""
    source = (
        import_line + "\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        "    for name, schema in schema_module.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "module_members,register_body",
    [
        (
            "import example_tools as ctx\n",
            "    def handler(name):\n"
            "        def invoke(args): return args\n"
            "        return invoke\n"
            "    for name, schema in ctx.SCHEMAS.items():\n"
            "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n",
        ),
        (
            "import example_tools\ndef invoke(args): return args\nctx = {'example_tool': invoke}\n",
            "    for name, schema in example_tools.SCHEMAS.items():\n"
            "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=ctx[name])\n",
        ),
        (
            "import example_tools\ndef ctx(args): return args\n",
            "    handlers = {'example_tool': ctx}\n"
            "    for name, schema in example_tools.SCHEMAS.items():\n"
            "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handlers[name])\n",
        ),
        (
            "import example_tools\n"
            "def ctx(fn):\n    def invoke(args): return fn(args)\n    return invoke\n",
            "    handlers = {'example_tool': ctx(example_tools.invoke)}\n"
            "    for name, schema in example_tools.SCHEMAS.items():\n"
            "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handlers[name])\n",
        ),
    ],
)
def test_C05_register_parameter_shadows_every_other_authority(
    matrix_repo: RepoFixture, module_members: str, register_body: str
) -> None:
    """C05: the ctx parameter cannot double as schema/map/callable authority."""
    matrix_repo._write_text(
        "plugins/ericsson-example/__init__.py",
        module_members + "def register(ctx):\n" + register_body,
    )
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize("scope", ["module", "register"])
def test_C05_chained_literal_map_assignments_preserve_simple_target(
    matrix_repo: RepoFixture, scope: str
) -> None:
    """C05: any simple target sharing one literal map value is recognized."""
    module_map = (
        "A = HANDLERS = {'example_tool': invoke}\n" if scope == "module" else ""
    )
    local_map = (
        "    A = HANDLERS = {'example_tool': invoke}\n" if scope == "register" else ""
    )
    source = (
        "import example_tools\ndef invoke(args): return args\n"
        + module_map
        + "def register(ctx):\n"
        + local_map
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=HANDLERS[name])\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        not in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "directive,body",
    [
        (
            "    global handler\n",
            "    def handler(name):\n"
            "        def invoke(args): return args\n"
            "        return invoke\n",
        ),
        (
            "    global HANDLERS\n",
            "    def invoke(args): return args\n"
            "    HANDLERS = {'example_tool': invoke}\n",
        ),
    ],
)
def test_C05_global_directive_cannot_credit_local_factory_or_map(
    matrix_repo: RepoFixture, directive: str, body: str
) -> None:
    """C05: global/nonlocal directives remove names from local authority."""
    handler = "handler(name)" if "handler" in directive else "HANDLERS[name]"
    source = (
        "import example_tools\ndef register(ctx):\n"
        + directive
        + body
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        f"        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler={handler})\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "except_type,accepted",
    [
        ("(handler := Exception)", False),
        ("build([handler for handler in items])", True),
    ],
)
def test_C05_except_type_is_eager_but_comprehension_target_is_isolated(
    matrix_repo: RepoFixture, except_type: str, accepted: bool
) -> None:
    """C05: except type expressions bind eagerly; their target remains separate."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        f"    try:\n        pass\n    except {except_type}:\n        pass\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "module_prefix,accepted",
    [
        ("import example_tools\nfrom foreign import *\n", False),
        ("from foreign import *\nimport example_tools\n", True),
    ],
)
def test_C05_wildcard_import_order_controls_schema_provenance(
    matrix_repo: RepoFixture, module_prefix: str, accepted: bool
) -> None:
    """C05: wildcard imports ambiguously bind schema authority at their position."""
    source = (
        module_prefix + "def register(ctx):\n"
        "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "definitions,accepted,local_map",
    [
        (
            "from foreign import *\nimport example_tools\ndef invoke(args): return args\nHANDLERS = {'example_tool': invoke}\n",
            True,
            False,
        ),
        (
            "import example_tools\ndef invoke(args): return args\nHANDLERS = {'example_tool': invoke}\nfrom foreign import *\n",
            False,
            False,
        ),
        (
            "from foreign import *\nimport example_tools\ndef invoke(args): return args\n",
            True,
            True,
        ),
        (
            "import example_tools\ndef invoke(args): return args\nfrom foreign import *\n",
            False,
            True,
        ),
    ],
)
def test_C05_wildcard_order_controls_module_map_and_callable_authority(
    matrix_repo: RepoFixture,
    definitions: str,
    accepted: bool,
    local_map: bool,
) -> None:
    """C05: later exact maps/callables supersede wildcard ambiguity, not vice versa."""
    map_statement = "    handlers = {'example_tool': invoke}\n" if local_map else ""
    map_name = "handlers" if local_map else "HANDLERS"
    source = (
        definitions
        + "def register(ctx):\n"
        + map_statement
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        f"        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler={map_name}[name])\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


def test_C05_register_scope_wildcard_binding_is_statement_ordered() -> None:
    """C05: the unified binder models wildcard order even in parsed register scope."""
    before = ast.parse(
        "def register(ctx):\n"
        "    from foreign import *\n"
        "    def handler(name):\n"
        "        return lambda args: args\n"
    ).body[0]
    after = ast.parse(
        "def register(ctx):\n"
        "    def handler(name):\n"
        "        return lambda args: args\n"
        "    from foreign import *\n"
    ).body[0]
    assert isinstance(before, ast.FunctionDef)
    assert isinstance(after, ast.FunctionDef)
    assert isinstance(
        catalog_lib._active_binding(before.body, len(before.body), "handler")[1],
        ast.FunctionDef,
    )
    assert catalog_lib._active_binding(after.body, len(after.body), "handler") == (
        1,
        None,
    )


@pytest.mark.parametrize(
    "authority,body,accepted",
    [
        (
            "HANDLERS",
            "    global HANDLERS\n",
            True,
        ),
        (
            "HANDLERS",
            "    global HANDLERS\n    HANDLERS = None\n",
            False,
        ),
        (
            "handlers",
            "    global invoke\n    handlers = {'example_tool': invoke}\n",
            True,
        ),
        (
            "handlers",
            "    global invoke\n    invoke = None\n    handlers = {'example_tool': invoke}\n",
            False,
        ),
    ],
)
def test_C05_bare_global_preserves_module_map_and_callable_authority(
    matrix_repo: RepoFixture, authority: str, body: str, accepted: bool
) -> None:
    """C05: a directive changes scope; only a binding overwrites module authority."""
    source = (
        "import example_tools\ndef invoke(args): return args\n"
        "HANDLERS = {'example_tool': invoke}\n"
        "def register(ctx):\n"
        + body
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        f"        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler={authority}[name])\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize("rebind", [False, True])
def test_C05_bare_global_preserves_schema_alias_until_rebound(
    matrix_repo: RepoFixture, rebind: bool
) -> None:
    """C05: global schema alias provenance survives only without a real write."""
    write = "    example_tools = None\n" if rebind else ""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    global example_tools\n" + write + "    def handler(name):\n"
        "        def invoke(args): return args\n"
        "        return invoke\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is (not rebind)


@pytest.mark.parametrize(
    "module_prefix,accepted",
    [
        ("if enabled:\n    from foreign import *\nimport example_tools\n", True),
        ("import example_tools\nif enabled:\n    from foreign import *\n", False),
    ],
)
def test_C05_nested_module_wildcard_is_statement_ordered(
    matrix_repo: RepoFixture, module_prefix: str, accepted: bool
) -> None:
    """C05: a compound-statement wildcard binds every authority at that point."""
    source = (
        module_prefix + "def register(ctx):\n"
        "    def handler(name):\n"
        "        return lambda args: args\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


def test_C05_nested_register_wildcard_is_statement_ordered() -> None:
    """C05: nested register wildcards invalidate only earlier authorities."""
    wildcard = ast.parse("if enabled:\n    from foreign import *\n").body[0]
    factory = ast.parse("def handler(name):\n    return lambda args: args\n").body[0]
    assert catalog_lib._active_binding([wildcard, factory], 2, "handler") == (
        1,
        factory,
    )
    assert catalog_lib._active_binding([factory, wildcard], 2, "handler") == (
        1,
        None,
    )


@pytest.mark.parametrize(
    "write_position,accepted", [("prefix", False), ("suffix", True), ("none", True)]
)
def test_C05_global_schema_write_is_bounded_by_loop_iterator_use(
    matrix_repo: RepoFixture, write_position: str, accepted: bool
) -> None:
    """C05: schema-owner writes matter only before iterator evaluation."""
    before = "    example_tools = None\n" if write_position == "prefix" else ""
    after = "    example_tools = None\n" if write_position == "suffix" else ""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    global example_tools\n"
        "    def handler(name):\n"
        "        return lambda args: args\n"
        + before
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
        + after
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "write_position,accepted", [("prefix", False), ("suffix", True), ("none", True)]
)
def test_C05_global_module_map_write_is_bounded_by_handler_lookup(
    matrix_repo: RepoFixture, write_position: str, accepted: bool
) -> None:
    """C05: module-map writes matter only before the handler lookup."""
    before = "    HANDLERS = None\n" if write_position == "prefix" else ""
    after = "    HANDLERS = None\n" if write_position == "suffix" else ""
    source = (
        "import example_tools\ndef invoke(args): return args\n"
        "HANDLERS = {'example_tool': invoke}\n"
        "def register(ctx):\n"
        "    global HANDLERS\n"
        + before
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=HANDLERS[name])\n"
        + after
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "write_position,accepted",
    [("before_capture", False), ("after_capture", True), ("after_use", True)],
)
def test_C05_local_map_captures_module_callable_at_construction(
    matrix_repo: RepoFixture, write_position: str, accepted: bool
) -> None:
    """C05: a local map captures its module callable at construction."""
    before = "    invoke = None\n" if write_position == "before_capture" else ""
    middle = "    invoke = None\n" if write_position == "after_capture" else ""
    after = "    invoke = None\n" if write_position == "after_use" else ""
    source = (
        "import example_tools\ndef invoke(args): return args\n"
        "def register(ctx):\n"
        "    global invoke\n"
        + before
        + "    handlers = {'example_tool': invoke}\n"
        + middle
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handlers[name])\n"
        + after
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize("write_position", ["prefix", "suffix", "none"])
def test_C05_preconstructed_module_map_ignores_global_callable_writes(
    matrix_repo: RepoFixture, write_position: str
) -> None:
    """C05: module maps captured callable values before register runs."""
    before = "    invoke = None\n" if write_position == "prefix" else ""
    after = "    invoke = None\n" if write_position == "suffix" else ""
    source = (
        "import example_tools\ndef invoke(args): return args\n"
        "HANDLERS = {'example_tool': invoke}\n"
        "def register(ctx):\n"
        "    global invoke\n"
        + before
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=HANDLERS[name])\n"
        + after
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        not in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "suffix",
    [
        "    example_tools = None\n",
        "    import foreign as example_tools\n",
        "    del example_tools\n",
        "    def example_tools():\n        pass\n",
        "    example_tools, other = (None, None)\n",
        "    if enabled:\n        example_tools = None\n",
        "    if (example_tools := None):\n        pass\n",
    ],
    ids=("assign", "import", "delete", "def", "destructure", "conditional", "walrus"),
)
def test_C05_ordinary_suffix_schema_binding_is_whole_function_local(
    matrix_repo: RepoFixture, suffix: str
) -> None:
    """C05: ordinary register locals shadow schema authority for the whole function."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        return lambda args: args\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
        + suffix
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "suffix",
    [
        "    values = [item for example_tools in items]\n",
        "    def later():\n        example_tools = None\n",
    ],
    ids=("comprehension-target", "nested-function"),
)
def test_C05_isolated_suffix_schema_names_do_not_shadow_module(
    matrix_repo: RepoFixture, suffix: str
) -> None:
    """C05: isolated comprehension/nested scopes do not create register locals."""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    def handler(name):\n"
        "        return lambda args: args\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
        + suffix
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        not in _catalog_problems(matrix_repo)
    )


@pytest.mark.parametrize(
    "binding",
    [
        "    example_tools = None\n",
        "    import foreign as example_tools\n",
        "    del example_tools\n",
        "    def example_tools():\n        pass\n",
        "    example_tools, other = (None, None)\n",
        "    if enabled:\n        example_tools = None\n",
        "    if (example_tools := None):\n        pass\n",
    ],
    ids=("assign", "import", "delete", "def", "destructure", "conditional", "walrus"),
)
@pytest.mark.parametrize("position,accepted", [("prefix", False), ("suffix", True)])
def test_C05_global_schema_binding_is_prefix_bounded_for_every_binder(
    matrix_repo: RepoFixture, binding: str, position: str, accepted: bool
) -> None:
    """C05: actual global writes are ordered around schema iterator evaluation."""
    before = binding if position == "prefix" else ""
    after = binding if position == "suffix" else ""
    source = (
        "import example_tools\ndef register(ctx):\n"
        "    global example_tools\n"
        "    def handler(name):\n"
        "        return lambda args: args\n"
        + before
        + "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', schema=schema, handler=handler(name))\n"
        + after
    )
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    missing = "plugin tool missing handler: plugins/ericsson-example: example_tool"
    assert (missing not in _catalog_problems(matrix_repo)) is accepted


@pytest.mark.parametrize(
    "kind",
    ["sidecar", "workflow", "config"],
)
def test_final_round1_A06_aligned_short_reads_detect_post_fstat_growth(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, kind: str
) -> None:
    """A06/C02/C03: stale size never substitutes for descriptor EOF."""
    bounded = _bounded_source()
    if kind == "sidecar":
        path = tmp_path / "workflow.hermes.yaml"
        contract = bounded.WORKFLOW_SIDECAR_CONTRACT
        loader = bounded.load_yaml_mapping
        prefix = b"language_compatibility: archon-2026-07\n"
    elif kind == "workflow":
        path = tmp_path / "workflow.yml"
        contract = bounded.WORKFLOW_METADATA_CONTRACT
        loader = bounded.load_yaml_mapping
        prefix = b"name: example\nrequires: []\nnodes: []\n"
    else:
        path = tmp_path / "config.schema.json"
        contract = bounded.CONFIG_SCHEMA_CONTRACT
        loader = bounded.load_json_mapping
        prefix = b'{"version":1,"fields":[]}'
    initial = prefix + b" " * (1_024 - len(prefix))
    path.write_bytes(initial)
    original_read = bounded._read_descriptor
    reads: list[int] = []
    grown = False

    def aligned_read(fd: int, size: int) -> bytes:
        nonlocal grown
        reads.append(size)
        if not grown:
            grown = True
            path.write_bytes(initial + b" " * (contract.max_bytes + 1 - len(initial)))
        return original_read(fd, min(size, 512))

    monkeypatch.setattr(bounded, "_read_descriptor", aligned_read)
    with pytest.raises(CatalogError) as exc:
        loader(path, contract)
    assert exc.value.code == "byte_limit"
    assert len(reads) > 2
    assert sum(min(size, 512) for size in reads) <= contract.max_bytes + 1


def test_final_round1_C04_self_approval_is_not_a_strict_ancestor() -> None:
    """C04: an outward node cannot satisfy approval with its own policy."""
    problems = lint_manifest._lint_archon_workflow(
        _archon_graph(
            [
                {
                    "id": "write",
                    "approval": {"message": "approve me"},
                    "prompt": "write",
                    "allowed_tools": ["example_write"],
                }
            ]
        )
    )
    assert problems == ["node write: outward tool requires approval ancestor"]


def test_final_round1_C04_complete_linter_is_linear_in_nodes_and_edges(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """C04/D03: the public whole-graph lint performs O(N+E) ID work."""
    original_set = set
    known_id_materializations = 0

    def counted_set(value=()):
        nonlocal known_id_materializations
        if isinstance(value, dict):
            known_id_materializations += 1
        return original_set(value)

    monkeypatch.setattr(lint_manifest, "set", counted_set, raising=False)
    count = 1_200
    root = "approve"
    nodes: list[dict[str, object]] = [{"id": root, "approval": {"message": "approve"}}]
    previous = root
    for index in range(count):
        current = f"node-{index}"
        nodes.append(
            {
                "id": current,
                "depends_on": [previous],
                "prompt": "read",
                "allowed_tools": [],
            }
        )
        previous = current
    nodes[-1]["allowed_tools"] = ["example_write"]
    assert lint_manifest._lint_archon_workflow(_archon_graph(nodes)) == []
    # One materialization validates unknown dependencies and one initializes
    # approval reachability; the count is constant, never once per node.
    assert known_id_materializations <= 2


@pytest.mark.skipif(os.name != "posix", reason="real directory symlink is POSIX")
def test_final_round1_C02_symlinked_plugin_directory_cannot_escape(
    matrix_repo: RepoFixture, tmp_path: Path
) -> None:
    """C02: every config path component is acquired without following links."""
    external = tmp_path / "external-plugin"
    external.mkdir()
    (external / "config.schema.json").write_text(
        '{"version":1,"fields":[]}', encoding="utf-8"
    )
    plugin_dir = matrix_repo.root / "plugins/ericsson-linked"
    plugin_dir.symlink_to(external, target_is_directory=True)
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugin_dir,
        {"config_schema": "config.schema.json"},
        "plugins/ericsson-linked",
        problems,
    )
    assert required == optional == set()
    assert problems == ["unsafe plugin config schema: plugins/ericsson-linked"]


@pytest.mark.parametrize("field", ["description", "personas"])
def test_final_round1_D02_manifest_preserves_existing_required_fields(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch, field: str
) -> None:
    """D02: convergence cannot weaken the pre-existing manifest contract."""
    manifest_path = matrix_repo.root / "sets/ericsson.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest.pop(field)
    matrix_repo._write_json("sets/ericsson.json", manifest)
    assert f"missing required key: {field}" in _lint_problems(matrix_repo, monkeypatch)


@pytest.mark.parametrize("operation", ["open", "fstat", "read", "close"])
@pytest.mark.parametrize("exception_type", [KeyboardInterrupt, SystemExit, MemoryError])
def test_final_round1_A07_control_flow_exceptions_propagate_after_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
    exception_type: type[BaseException],
) -> None:
    """A07: process control exceptions are never rendered as source errors."""
    bounded = _bounded_source()
    path = tmp_path / "workflow.hermes.yaml"
    path.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
    original_open = bounded._open_source_descriptor
    original_close = bounded._close_descriptor
    owned: list[int] = []
    closed: list[int] = []

    def opened(source: Path) -> int:
        if operation == "open":
            raise exception_type()
        descriptor = original_open(source)
        owned.append(descriptor)
        return descriptor

    def failed_stage(*args):
        raise exception_type()

    def closed_stage(descriptor: int) -> None:
        closed.append(descriptor)
        original_close(descriptor)
        if operation == "close":
            raise exception_type()

    monkeypatch.setattr(bounded, "_open_source_descriptor", opened)
    monkeypatch.setattr(bounded, "_close_descriptor", closed_stage)
    if operation == "fstat":
        monkeypatch.setattr(bounded, "_fstat_descriptor", failed_stage)
    elif operation == "read":
        monkeypatch.setattr(bounded, "_read_descriptor", failed_stage)
    with pytest.raises(exception_type):
        bounded.load_yaml_mapping(path, bounded.WORKFLOW_SIDECAR_CONTRACT)
    if operation != "open":
        assert closed == owned


@pytest.mark.parametrize(
    "payload",
    [
        '{"value":1١}',
        '{"value":-1١}',
        '{"value":1.2٣}',
        '{"value":1e2٣}',
    ],
    ids=("integer", "negative-integer", "fraction", "exponent"),
)
def test_final_round1_C02_json_numbers_accept_ascii_digits_only(
    tmp_path: Path, payload: str
) -> None:
    """C02: every JSON numeric position follows RFC 8259 ASCII grammar."""
    bounded = _bounded_source()
    path = tmp_path / "config.schema.json"
    path.write_text(payload, encoding="utf-8")
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping(path, bounded.CONFIG_SCHEMA_CONTRACT)
    assert exc.value.code == "invalid_json"


@pytest.mark.parametrize(
    "invalid",
    ["<", ">", '"', "|", "?", "*", *[chr(value) for value in range(32)]],
    ids=[
        "less-than",
        "greater-than",
        "quote",
        "pipe",
        "question",
        "asterisk",
        *[f"control-{value}" for value in range(32)],
    ],
)
def test_final_round1_C02_config_basename_rejects_all_windows_invalid_characters(
    matrix_repo: RepoFixture, invalid: str
) -> None:
    """C02: a portable descriptor basename is representable on Windows."""
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    metadata = yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
    metadata["config_schema"] = f"bad{invalid}name.json"
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugin_dir, metadata, "plugins/ericsson-example", problems
    )
    assert required == optional == set()
    assert problems == ["unsafe plugin config schema: plugins/ericsson-example"]


def test_final_round1_D02_current_repository_preservation_control() -> None:
    """D02: the complete real Task 11 catalog/manifest remains represented."""
    assert catalog_lib.validate_repository(REPO, catalog_lib.load_entries(REPO)) == []
    assert lint_manifest.lint(REPO / "sets/ericsson.json") == []


@pytest.mark.skipif(os.name != "posix", reason="real component links are POSIX")
def test_final_round2_C02_symlinked_plugins_root_is_never_followed(
    matrix_repo: RepoFixture, tmp_path: Path
) -> None:
    """C02/D01: every directory component is opened relative and no-follow."""
    plugins = matrix_repo.root / "plugins"
    internal = matrix_repo.root / "plugins-internal"
    plugins.rename(internal)
    external = tmp_path / "external-plugins"
    shutil.copytree(internal, external)
    schema = external / "ericsson-example/config.schema.json"
    schema.write_text(
        '{"version":1,"fields":[{"id":"outside","storage":"secret",'
        '"type":"string","required":false}]}',
        encoding="utf-8",
    )
    plugins.symlink_to(external, target_is_directory=True)
    metadata = {"config_schema": "config.schema.json"}
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugins / "ericsson-example",
        metadata,
        "plugins/ericsson-example",
        problems,
    )
    assert required == optional == set()
    assert problems == [
        "invalid plugin config schema: plugins/ericsson-example: config.schema.json"
    ]


@pytest.mark.skipif(os.name != "posix", reason="real component replacement is POSIX")
def test_final_round2_C02_directory_fd_binds_replacement_before_relative_open(
    matrix_repo: RepoFixture, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C02/D01: replacement after directory open cannot redirect config bytes."""
    _configure_descriptor_fixture(matrix_repo)
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    metadata = yaml.safe_load((plugin_dir / "plugin.yaml").read_text())
    external = tmp_path / "external-plugin"
    shutil.copytree(plugin_dir, external)
    (external / "config.schema.json").write_text(
        '{"version":1,"fields":[{"id":"outside","storage":"secret",'
        '"type":"string","required":false}]}',
        encoding="utf-8",
    )
    preserved = plugin_dir.with_name("ericsson-example-preserved")
    original_open = os.open
    replaced = False

    def racing_open(source, flags, mode=0o777, *, dir_fd=None):
        nonlocal replaced
        rendered = os.fspath(source)
        is_directory_open = (
            dir_fd is None
            and Path(rendered) == plugin_dir
            or dir_fd is not None
            and rendered == plugin_dir.name
        ) and flags & getattr(os, "O_DIRECTORY", 0)
        is_legacy_full_file_open = dir_fd is None and Path(rendered) == (
            plugin_dir / "config.schema.json"
        )
        if not replaced and is_legacy_full_file_open:
            plugin_dir.rename(preserved)
            plugin_dir.symlink_to(external, target_is_directory=True)
            replaced = True
        descriptor = original_open(rendered, flags, mode, dir_fd=dir_fd)
        if not replaced and is_directory_open:
            plugin_dir.rename(preserved)
            plugin_dir.symlink_to(external, target_is_directory=True)
            replaced = True
        return descriptor

    monkeypatch.setattr(os, "open", racing_open)
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugin_dir, metadata, "plugins/ericsson-example", problems
    )
    assert not problems
    assert required == {"origin", "token"}
    assert optional == {"certificate_path"}
    assert replaced


def test_final_round2_D01_windows_relative_acquisition_rejects_reparse_component(
    matrix_repo: RepoFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """C02/D01: Win32 relative acquisition rejects a raced junction component."""
    bounded = _bounded_source()
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    metadata = {"config_schema": "config.schema.json"}
    external = matrix_repo.root / "external.json"
    external.write_text(
        '{"version":1,"fields":[{"id":"outside","storage":"secret",'
        '"type":"string","required":false}]}',
        encoding="utf-8",
    )

    class FakeRelativeWin32:
        def __init__(self) -> None:
            self.relative_files: list[str] = []
            self.closed: list[int] = []

        def open_reparse(self, _path: Path) -> int:
            return 99

        def open_directory(self, _path: Path) -> int:
            return 10

        def open_relative(self, _parent: int, name: str, *, directory: bool) -> int:
            if directory and name == "plugins":
                return 20
            if not directory:
                self.relative_files.append(name)
            return 30

        def inspect(self, handle: int) -> SimpleNamespace:
            if handle == 20:
                return SimpleNamespace(
                    file_type=bounded._WIN_FILE_TYPE_DISK,
                    attributes=bounded._WIN_FILE_ATTRIBUTE_DIRECTORY
                    | bounded._WIN_FILE_ATTRIBUTE_REPARSE_POINT,
                )
            return SimpleNamespace(
                file_type=bounded._WIN_FILE_TYPE_DISK,
                attributes=(
                    bounded._WIN_FILE_ATTRIBUTE_DIRECTORY if handle == 10 else 0
                ),
            )

        def descriptor_from_handle(self, _handle: int) -> int:
            return os.open(external, os.O_RDONLY)

        def close_handle(self, handle: int) -> None:
            self.closed.append(handle)

    fake = FakeRelativeWin32()
    monkeypatch.setattr(bounded, "_platform_name", lambda: "nt")
    monkeypatch.setattr(bounded, "_win32_api", lambda: fake)
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugin_dir, metadata, "plugins/ericsson-example", problems
    )
    assert required == optional == set()
    assert problems == [
        "invalid plugin config schema: plugins/ericsson-example: config.schema.json"
    ]
    assert fake.relative_files == []


@pytest.mark.parametrize(
    "descriptor",
    [
        "COM¹.json",
        "com².JSON",
        "CoM³",
        "LPT¹.json",
        "lpt².JSON",
        "LpT³",
        "CONIN$.json",
        "conin$",
        "CONOUT$.json",
        "conout$",
    ],
)
def test_final_round2_D01_extended_windows_reserved_basenames_reject(
    matrix_repo: RepoFixture, descriptor: str
) -> None:
    """D01: portable basenames match Windows reserved-name semantics."""
    plugin_dir = matrix_repo.root / "plugins/ericsson-example"
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        plugin_dir,
        {"config_schema": descriptor},
        "plugins/ericsson-example",
        problems,
    )
    assert required == optional == set()
    assert problems == ["unsafe plugin config schema: plugins/ericsson-example"]


def test_final_round2_B08_lint_missing_argument_is_one_json_result() -> None:
    """B08/D02: invalid invocation preserves bounded JSON stdout compatibility."""
    result = subprocess.run(
        [sys.executable, str(ROOT_SCRIPTS / "lint_manifest.py")],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    payload = json.loads(result.stdout)
    assert payload == {"error": "usage: lint_manifest.py <manifest.json>"}


# Final review round 3: the complete two-review union is frozen here before
# any corresponding production correction.


@pytest.mark.parametrize(
    "failure",
    ["component-parent-close", "final-parent-close", "primary-and-parent-close"],
)
def test_final_round3_D01_posix_relative_open_owns_every_descriptor(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """D01: transition failures close each distinct acquired fd exactly once."""
    bounded = _bounded_source()
    opened: list[int] = []
    closed: list[int] = []
    descriptors = iter((10, 11, 12))

    def open_component(_parent, _name, _flags):
        descriptor = next(descriptors)
        opened.append(descriptor)
        if failure == "primary-and-parent-close" and descriptor == 12:
            raise bounded.SourceError(
                "PRIVATE-SENTINEL", code=bounded.SourceErrorCode.MISSING_SOURCE
            )
        return descriptor

    def close_descriptor(descriptor: int) -> None:
        closed.append(descriptor)
        if descriptor == (10 if failure == "component-parent-close" else 11):
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")

    monkeypatch.setattr(bounded, "_posix_open_component", open_component)
    monkeypatch.setattr(bounded, "_close_descriptor", close_descriptor)
    with pytest.raises(CatalogError) as exc:
        bounded._posix_open_relative_regular(Path("component"), "schema.json")
    expected = "missing_source" if failure == "primary-and-parent-close" else "io_error"
    assert exc.value.code == expected
    assert len(closed) == len(set(closed))
    if failure == "component-parent-close":
        assert set(closed) == {10, 11}
    elif failure == "primary-and-parent-close":
        assert set(closed) == {10, 11}
    else:
        assert set(closed) == {10, 11, 12}


class _Round3RelativeWin32:
    def __init__(self, failure: str) -> None:
        self.failure = failure
        self.closed: list[int] = []

    def open_directory(self, _path: Path) -> int:
        return 10

    def open_relative(self, _parent: int, _name: str, *, directory: bool) -> int:
        if not directory and self.failure == "primary-and-parent-close":
            raise CatalogError("PRIVATE-SENTINEL", code="missing_source")
        return 20 if directory else 30

    def inspect(self, handle: int) -> SimpleNamespace:
        return SimpleNamespace(
            file_type=1,
            attributes=0x10 if handle == 20 else 0,
        )

    def descriptor_from_handle(self, _handle: int) -> int:
        return 40

    def close_handle(self, handle: int) -> None:
        self.closed.append(handle)
        if handle == (10 if self.failure == "component-parent-close" else 20):
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")


@pytest.mark.parametrize(
    "failure",
    ["component-parent-close", "final-parent-close", "primary-and-parent-close"],
)
def test_final_round3_D01_win32_relative_open_owns_every_handle_and_fd(
    monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    """D01: Win32 transition failures clean child handles and transferred fds."""
    bounded = _bounded_source()
    fake = _Round3RelativeWin32(failure)
    closed_fds: list[int] = []
    monkeypatch.setattr(bounded, "_win32_api", lambda: fake)
    monkeypatch.setattr(bounded, "_close_descriptor", closed_fds.append)
    with pytest.raises(CatalogError) as exc:
        bounded._win32_open_relative_regular(Path("component"), "schema.json")
    expected = "missing_source" if failure == "primary-and-parent-close" else "io_error"
    assert exc.value.code == expected
    assert len(fake.closed) == len(set(fake.closed))
    if failure == "component-parent-close":
        assert set(fake.closed) == {10, 20}
    else:
        assert set(fake.closed) == {10, 20}
    assert closed_fds == ([40] if failure == "final-parent-close" else [])


def _round3_win32_api(status: int = 0):
    captured: dict[str, object] = {}

    def nt_create(
        handle,
        access,
        attributes,
        _status_block,
        _allocation,
        file_attributes,
        share,
        disposition,
        options,
        _ea,
        _ea_length,
    ):
        captured.update(
            access=access,
            attributes=attributes._obj,
            file_attributes=file_attributes,
            share=share,
            disposition=disposition,
            options=options,
        )
        if status == 0:
            handle._obj.value = 222
        return status

    ntdll = SimpleNamespace(
        NtCreateFile=_FakeCFunction(nt_create),
        RtlNtStatusToDosError=_FakeCFunction(lambda _status: 5),
    )
    kernel32 = SimpleNamespace(
        CreateFileW=_FakeCFunction(lambda *_args: 101),
        GetFileType=_FakeCFunction(lambda _handle: 1),
        GetFileInformationByHandle=_FakeCFunction(lambda *_args: 1),
        CloseHandle=_FakeCFunction(lambda _handle: 1),
        GetLastError=_FakeCFunction(lambda: 0),
    )
    api = _bounded_source()._Win32Api(
        kernel32=kernel32,
        msvcrt=SimpleNamespace(open_osfhandle=lambda *_args: 7),
        ntdll=ntdll,
    )
    return api, ntdll, captured


def test_final_round3_D01_real_win32_relative_api_abi_and_status() -> None:
    """D01: NtCreateFile is root-relative, no-follow, synchronous, and typed."""
    bounded = _bounded_source()
    api, ntdll, captured = _round3_win32_api()
    assert api.open_relative(111, "schema.json", directory=False) == 222
    attributes = captured["attributes"]
    assert attributes.RootDirectory == 111
    assert ctypes.wstring_at(attributes.ObjectName.contents.Buffer) == "schema.json"
    assert captured["disposition"] == bounded._WIN_FILE_OPEN
    assert captured["options"] & bounded._WIN_FILE_OPEN_REPARSE_POINT
    assert captured["options"] & bounded._WIN_FILE_NON_DIRECTORY_FILE
    assert ntdll.NtCreateFile.argtypes is not None
    failed, _ntdll, _captured = _round3_win32_api(-1)
    with pytest.raises(CatalogError) as exc:
        failed.open_relative(111, "PRIVATE-SENTINEL", directory=True)
    assert exc.value.code == "unsafe_source"
    assert "PRIVATE-SENTINEL" not in str(exc.value)


@pytest.mark.parametrize("descriptor", ["bad\ud800.json", "bad\udfff.json"])
def test_final_round3_D01_surrogate_config_basenames_are_lexically_unsafe(
    matrix_repo: RepoFixture, descriptor: str
) -> None:
    """D01: surrogate path components never reach OS path encoding."""
    problems: list[str] = []
    required, optional = catalog_lib._plugin_config_schema_contract(
        matrix_repo.root / "plugins/ericsson-example",
        {"config_schema": descriptor},
        "plugins/ericsson-example",
        problems,
    )
    assert required == optional == set()
    assert problems == ["unsafe plugin config schema: plugins/ericsson-example"]


@pytest.mark.parametrize("relative", [False, True])
def test_final_round3_D01_path_encoding_unicode_errors_are_fixed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, relative: bool
) -> None:
    """D01/B08: defensive OS encoding failures become label-only SourceError."""
    bounded = _bounded_source()

    def fail(*_args, **_kwargs):
        raise UnicodeEncodeError("utf-8", "\ud800", 0, 1, "PRIVATE-SENTINEL")

    seam = "_open_relative_source_descriptor" if relative else "_open_source_descriptor"
    monkeypatch.setattr(bounded, seam, fail)
    with pytest.raises(CatalogError) as exc:
        if relative:
            bounded.load_json_mapping_relative(
                tmp_path, "schema.json", bounded.CONFIG_SCHEMA_CONTRACT
            )
        else:
            bounded.load_yaml_mapping(
                tmp_path / "workflow.yml", bounded.WORKFLOW_METADATA_CONTRACT
            )
    assert exc.value.code == "unsafe_source"
    assert "PRIVATE-SENTINEL" not in str(exc.value)


@pytest.mark.parametrize("command", ["validate", "build", "check"])
def test_final_round3_C02_surrogate_config_callers_fail_fixed(
    matrix_repo: RepoFixture, command: str
) -> None:
    """C02/B08: every real catalog caller rejects surrogate descriptors safely."""
    plugin = matrix_repo.root / "plugins/ericsson-example/plugin.yaml"
    metadata = yaml.safe_load(plugin.read_text(encoding="utf-8"))
    metadata["config_schema"] = "PRIVATE-SENTINEL-\ud800.json"
    plugin.write_text(yaml.safe_dump(metadata, sort_keys=False), encoding="utf-8")
    matrix_repo.write_complete_entry()
    script = {
        "validate": CATALOG_SCRIPTS / "validate_catalog.py",
        "build": CATALOG_SCRIPTS / "build_catalog.py",
        "check": CATALOG_SCRIPTS / "build_catalog.py",
    }[command]
    args = ["--check"] if command == "check" else []
    result = _cli(script, matrix_repo, *args)
    assert result.returncode == 1
    assert result.stderr == ""
    assert "PRIVATE-SENTINEL" not in result.stdout
    assert "Traceback" not in result.stdout


@pytest.mark.parametrize(
    "arguments",
    [
        ["--unknown", "PRIVATE-SENTINEL"],
        ["--repo"],
        ["sets/ericsson.json", "PRIVATE-SENTINEL-extra"],
    ],
    ids=("unknown-option", "missing-repo-value", "extra-positional"),
)
def test_final_round3_B08_every_invalid_lint_argv_is_fixed_json(
    arguments: list[str],
) -> None:
    """B08: argparse never owns observable diagnostics or leaks argv."""
    result = subprocess.run(
        [sys.executable, str(ROOT_SCRIPTS / "lint_manifest.py"), *arguments],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 1
    assert result.stderr == ""
    assert json.loads(result.stdout) == {
        "error": "usage: lint_manifest.py <manifest.json>"
    }
    assert "PRIVATE-SENTINEL" not in result.stdout


@pytest.mark.parametrize("absolute", [False, True], ids=("relative", "absolute"))
def test_final_round3_B08_repo_manifest_resolution_is_explicit(
    matrix_repo: RepoFixture, tmp_path: Path, absolute: bool
) -> None:
    """B08: relative manifests are repo-relative; absolute paths stay absolute."""
    manifest = matrix_repo.root / "sets/ericsson.json"
    argument = str(manifest) if absolute else "sets/ericsson.json"
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT_SCRIPTS / "lint_manifest.py"),
            argument,
            "--repo",
            str(matrix_repo.root),
        ],
        cwd=tmp_path,
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert json.loads(result.stdout) == {"ok": True}


# Final review round 4: close the complete two-review union before changing
# the bounded acquisition or registration analyzer implementation.


@pytest.mark.parametrize(
    "character,count,encoded_bytes,accepted",
    [
        ("x", 32_766, 65_532, True),
        ("x", 32_767, 65_534, False),
        ("\U0001f642", 16_383, 65_532, True),
        ("\U0001f642", 16_384, 65_536, False),
    ],
    ids=("bmp-exact", "bmp-adjacent", "non-bmp-exact", "non-bmp-adjacent"),
)
def test_final_round4_C02_D01_config_component_utf16_bound_is_exact(
    character: str, count: int, encoded_bytes: int, accepted: bool
) -> None:
    """C02/D01: portable components fit both UNICODE_STRING ushort fields."""
    name = character * count
    assert len(name.encode("utf-16-le")) == encoded_bytes
    assert (catalog_lib._portable_config_basename(name) == name) is accepted


@pytest.mark.parametrize(
    "name,accepted",
    [
        ("x" * 32_766, True),
        ("x" * 32_767, False),
        ("\U0001f642" * 16_383, True),
        ("\U0001f642" * 16_384, False),
    ],
    ids=("bmp-exact", "bmp-adjacent", "non-bmp-exact", "non-bmp-adjacent"),
)
def test_final_round4_D01_win32_relative_open_defends_utf16_bound(
    name: str, accepted: bool
) -> None:
    """D01: the Win32 API itself rejects length overflow before NtCreateFile."""
    api, _ntdll, captured = _round3_win32_api()
    if accepted:
        assert api.open_relative(111, name, directory=False) == 222
        assert captured
    else:
        with pytest.raises(CatalogError) as exc:
            api.open_relative(111, name, directory=False)
        assert exc.value.code == "unsafe_source"
        assert captured == {}


def _assert_example_registration_rejected(
    matrix_repo: RepoFixture, source: str
) -> None:
    matrix_repo._write_text("plugins/ericsson-example/__init__.py", source)
    problems = _catalog_problems(matrix_repo)
    assert (
        "plugin tool missing handler: plugins/ericsson-example: example_tool"
        in problems
    )
    assert (
        "plugin tool not runtime-registered: plugins/ericsson-example: example_tool"
        in problems
    )


# Final review round 5: freeze the complete closed grammar and both-reviewer
# adversarial union before the final analyzer replacement.


# Final review round 6: freeze a total module/register grammar. Every executable
# statement and eagerly evaluated expression must be consumed by one production;
# sufficient-looking registration evidence cannot excuse unknown Python.


# Final review round 7: every imported local module, import binding, eagerly
# evaluated value, and host registration keyword is part of the closed proof.


# Final review round 8: no syntax marker or stale lexical authority can bypass
# the one total proof, and accepted loops match the real host call signature.


# Final review round 9: every eager surface uses the active Python binding,
# local import/class construction is executable, and host arguments have their
# public per-keyword types.


# Final review round 10: close every remaining eager-execution gap while
# retaining the real plugin forms and harmless module-only imports.


@pytest.mark.skipif(os.name != "posix", reason="A07 relative acquisition is POSIX")
@pytest.mark.parametrize("stage", ["first", "intermediate", "final"])
def test_final_round11_A07_relative_syscall_has_one_total_eintr_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, stage: str
) -> None:
    """A07: no nested retry layer can multiply a syscall's three attempts."""
    bounded = _bounded_source()
    directory = tmp_path / "parent" / "child"
    directory.mkdir(parents=True)
    basename = "schema.json"
    (directory / basename).write_text("{}", encoding="utf-8")
    original = bounded._posix_open_component
    target = {
        "first": directory.anchor,
        "intermediate": directory.name,
        "final": basename,
    }[stage]
    attempts = 0

    def interrupted(parent: int | None, name: str, flags: int) -> int:
        nonlocal attempts
        if name == target:
            attempts += 1
            if attempts <= 4:
                raise InterruptedError(errno.EINTR, "PRIVATE-SENTINEL")
        return original(parent, name, flags)

    monkeypatch.setattr(bounded, "_posix_open_component", interrupted)
    with pytest.raises(CatalogError) as exc:
        bounded.load_json_mapping_relative(
            directory,
            basename,
            bounded.CONFIG_SCHEMA_CONTRACT,
        )
    assert exc.value.code == "io_error"
    assert attempts == 3
    assert "PRIVATE-SENTINEL" not in str(exc.value)


def _round11_support_module(matrix_repo: RepoFixture, helper_source: str) -> list[str]:
    matrix_repo._write_text("plugins/ericsson-example/helper.py", helper_source)
    matrix_repo._write_text(
        "plugins/ericsson-example/__init__.py",
        "import example_tools, helper\n"
        "def register(ctx):\n"
        "    handlers = {'example_tool': lambda args: args}\n"
        "    for name, schema in example_tools.SCHEMAS.items():\n"
        "        ctx.register_tool(name=name, toolset='ericsson-example', "
        "schema=schema, handler=handlers[name])\n",
    )
    return _catalog_problems(matrix_repo)


@pytest.mark.skipif(os.name != "posix", reason="D01 flag assertion is POSIX")
def test_D01_posix_open_uses_nonblocking_cloexec_nofollow_flags(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D01: exact POSIX safe-open flags precede every byte read."""
    bounded = _bounded_source()
    path = tmp_path / "source.yaml"
    path.write_text("x: y\n", encoding="utf-8")
    original = os.open
    seen: list[int] = []

    def tracked(source, flags, mode=0o777):
        seen.append(flags)
        return original(source, flags, mode)

    monkeypatch.setattr(os, "open", tracked)
    fd = bounded._posix_open_regular(path)
    os.close(fd)
    required = os.O_RDONLY | os.O_NONBLOCK
    required |= getattr(os, "O_CLOEXEC", 0)
    required |= getattr(os, "O_NOFOLLOW", 0)
    assert seen == [required]


@pytest.mark.skipif(os.name != "posix", reason="A07 open EINTR assertion is POSIX")
@pytest.mark.parametrize("interrupts", [1, 4], ids=("then-success", "exhausted"))
def test_A07_posix_open_syscall_eintr_uses_bounded_retry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, interrupts: int
) -> None:
    """A07: the real POSIX open syscall reaches the shared retry authority."""
    bounded = _bounded_source()
    path = tmp_path / "source.yaml"
    path.write_text("x: y\n", encoding="utf-8")
    original = os.open
    attempts = 0

    def interrupted(source, flags, mode=0o777):
        nonlocal attempts
        attempts += 1
        if attempts <= interrupts:
            raise InterruptedError(errno.EINTR, "PRIVATE-SENTINEL")
        return original(source, flags, mode)

    monkeypatch.setattr(os, "open", interrupted)
    if interrupts == 1:
        assert bounded.load_yaml_mapping(path, bounded.WORKFLOW_METADATA_CONTRACT) == {
            "x": "y"
        }
        assert attempts == 2
    else:
        with pytest.raises(CatalogError) as exc:
            bounded.load_yaml_mapping(path, bounded.WORKFLOW_METADATA_CONTRACT)
        assert exc.value.code == "io_error"
        assert "PRIVATE-SENTINEL" not in str(exc.value)
        assert attempts == 3


def test_D01_posix_without_nofollow_fails_closed_without_open(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D01: lack of a race-safe no-follow primitive never falls back to follow."""
    bounded = _bounded_source()
    path = tmp_path / "source.yaml"
    path.write_text("x: y\n", encoding="utf-8")
    opens: list[Path] = []
    monkeypatch.setattr(bounded, "_POSIX_O_NOFOLLOW", None)
    monkeypatch.setattr(
        os, "open", lambda source, *_args: opens.append(Path(source)) or 7
    )
    with pytest.raises(CatalogError) as exc:
        bounded._posix_open_regular(path)
    assert exc.value.code == "safe_open_unavailable"
    assert opens == []


@pytest.mark.skipif(os.name != "posix", reason="D01 inheritable-fd fallback is POSIX")
def test_D01_posix_without_cloexec_forces_noninheritable_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """D01: PEP-446 is verified/forced when O_CLOEXEC is unavailable."""
    bounded = _bounded_source()
    path = tmp_path / "source.yaml"
    path.write_text("x: y\n", encoding="utf-8")
    original_open = os.open
    forced: list[tuple[int, bool]] = []
    original_set = os.set_inheritable

    def opened(source, flags, mode=0o777):
        fd = original_open(source, flags, mode)
        original_set(fd, True)
        return fd

    def set_inheritable(fd: int, inheritable: bool) -> None:
        forced.append((fd, inheritable))
        original_set(fd, inheritable)

    monkeypatch.setattr(bounded, "_POSIX_O_CLOEXEC", 0)
    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "set_inheritable", set_inheritable)
    fd = bounded._posix_open_regular(path)
    try:
        assert os.get_inheritable(fd) is False
        assert forced == [(fd, False)]
    finally:
        os.close(fd)


@pytest.mark.skipif(os.name != "posix", reason="D01 inheritable-fd failures are POSIX")
@pytest.mark.parametrize("operation", ["get", "set"])
def test_D01_posix_inheritable_fallback_failures_close_descriptor_once(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    operation: str,
) -> None:
    """D01: inheritable inspection/enforcement errors retain no owned fd."""
    bounded = _bounded_source()
    path = tmp_path / "source.yaml"
    path.write_text("x: y\n", encoding="utf-8")
    original_open = os.open
    original_close = os.close
    acquired: list[int] = []
    close_attempts: list[int] = []

    def opened(source, flags, mode=0o777):
        descriptor = original_open(source, flags, mode)
        acquired.append(descriptor)
        return descriptor

    def closed(descriptor: int) -> None:
        close_attempts.append(descriptor)
        original_close(descriptor)

    def get_inheritable(_descriptor: int) -> bool:
        if operation == "get":
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")
        return True

    def set_inheritable(_descriptor: int, _inheritable: bool) -> None:
        raise OSError(errno.EIO, "PRIVATE-SENTINEL")

    monkeypatch.setattr(bounded, "_POSIX_O_CLOEXEC", 0)
    monkeypatch.setattr(os, "open", opened)
    monkeypatch.setattr(os, "close", closed)
    monkeypatch.setattr(os, "get_inheritable", get_inheritable)
    monkeypatch.setattr(os, "set_inheritable", set_inheritable)
    with pytest.raises(CatalogError) as exc:
        bounded._posix_open_regular(path)
    assert exc.value.code == "io_error"
    assert "PRIVATE-SENTINEL" not in str(exc.value)
    assert len(acquired) == 1
    assert close_attempts == acquired
    with pytest.raises(OSError):
        os.fstat(acquired[0])


class _FakeWin32:
    def __init__(self, *, status: str, descriptor: int) -> None:
        self.status = status
        self.descriptor = descriptor
        self.opened: list[Path] = []
        self.inspected: list[int] = []
        self.converted: list[int] = []
        self.produced_fds: list[int] = []
        self.closed_handles: list[int] = []

    def open_reparse(self, path: Path) -> int:
        self.opened.append(path)
        if self.status == "missing":
            raise FileNotFoundError(errno.ENOENT, "PRIVATE-SENTINEL")
        if self.status == "open-error":
            raise PermissionError(errno.EACCES, "PRIVATE-SENTINEL")
        return 101

    def inspect(self, handle: int):
        self.inspected.append(handle)
        if self.status.startswith("inspect-error"):
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")
        attributes = 0
        file_type = 1
        if self.status in {"broken-reparse", "internal-reparse", "external-reparse"}:
            attributes |= 0x400
        if self.status.startswith("directory"):
            attributes |= 0x10
        if self.status == "non-disk":
            file_type = 3
        return SimpleNamespace(file_type=file_type, attributes=attributes)

    def descriptor_from_handle(self, handle: int) -> int:
        self.converted.append(handle)
        if self.status.startswith("conversion-error"):
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")
        descriptor = os.dup(self.descriptor)
        self.produced_fds.append(descriptor)
        return descriptor

    def close_handle(self, handle: int) -> None:
        self.closed_handles.append(handle)
        if self.status.endswith("close-error"):
            raise OSError(errno.EIO, "PRIVATE-SENTINEL")


class _FakeCFunction:
    def __init__(self, callback) -> None:
        self.callback = callback
        self.calls: list[tuple[object, ...]] = []
        self.argtypes = None
        self.restype = None

    def __call__(self, *args):
        self.calls.append(args)
        return self.callback(*args)


def test_D01_concrete_win32_ctypes_wiring_and_flags(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """D01: freeze CreateFileW/GetFileType/info/open_osfhandle ABI wiring."""
    bounded = _bounded_source()
    # Constants and ctypes signatures come from the documented Win32 ABI,
    # independently of the implementation's names.
    generic_read = 0x80000000
    share_read, share_write, share_delete = 0x1, 0x2, 0x4
    open_existing = 3
    open_reparse_point, backup_semantics = 0x00200000, 0x02000000
    file_attribute_normal = 0x80
    file_type_disk = 0x1
    binary = 0x8000
    assert bounded._WIN_GENERIC_READ == generic_read
    assert bounded._WIN_FILE_SHARE_READ == share_read
    assert bounded._WIN_FILE_SHARE_WRITE == share_write
    assert bounded._WIN_FILE_SHARE_DELETE == share_delete
    assert bounded._WIN_OPEN_EXISTING == open_existing
    assert bounded._WIN_FILE_FLAG_OPEN_REPARSE_POINT == open_reparse_point
    assert bounded._WIN_FILE_FLAG_BACKUP_SEMANTICS == backup_semantics
    assert bounded._WIN_FILE_ATTRIBUTE_NORMAL == file_attribute_normal
    assert bounded._WIN_FILE_ATTRIBUTE_DIRECTORY == 0x10
    assert bounded._WIN_FILE_ATTRIBUTE_REPARSE_POINT == 0x400
    assert bounded._WIN_FILE_TYPE_DISK == file_type_disk
    assert bounded._WIN_INVALID_HANDLE_VALUE == ctypes.c_void_p(-1).value
    assert bounded._O_BINARY == binary

    information_fields = bounded._BY_HANDLE_FILE_INFORMATION._fields_
    assert tuple(name for name, _field_type in information_fields) == (
        "dwFileAttributes",
        "ftCreationTime",
        "ftLastAccessTime",
        "ftLastWriteTime",
        "dwVolumeSerialNumber",
        "nFileSizeHigh",
        "nFileSizeLow",
        "nNumberOfLinks",
        "nFileIndexHigh",
        "nFileIndexLow",
    )
    assert information_fields[0][1] is ctypes.c_uint32
    filetime_type = information_fields[1][1]
    assert issubclass(filetime_type, ctypes.Structure)
    assert filetime_type._fields_ == [
        ("dwLowDateTime", ctypes.c_uint32),
        ("dwHighDateTime", ctypes.c_uint32),
    ]
    assert all(information_fields[index][1] is filetime_type for index in (1, 2, 3))
    assert all(
        information_fields[index][1] is ctypes.c_uint32
        for index in range(4, len(information_fields))
    )
    assert ctypes.sizeof(filetime_type) == 8
    assert ctypes.alignment(filetime_type) == 4
    assert ctypes.sizeof(bounded._BY_HANDLE_FILE_INFORMATION) == 52
    assert ctypes.alignment(bounded._BY_HANDLE_FILE_INFORMATION) == 4
    assert {
        name: getattr(bounded._BY_HANDLE_FILE_INFORMATION, name).offset
        for name, _field_type in information_fields
    } == {
        "dwFileAttributes": 0,
        "ftCreationTime": 4,
        "ftLastAccessTime": 12,
        "ftLastWriteTime": 20,
        "dwVolumeSerialNumber": 28,
        "nFileSizeHigh": 32,
        "nFileSizeLow": 36,
        "nNumberOfLinks": 40,
        "nFileIndexHigh": 44,
        "nFileIndexLow": 48,
    }

    create = _FakeCFunction(lambda *_args: 101)
    file_type = _FakeCFunction(lambda _handle: file_type_disk)

    def fill_info(_handle, pointer):
        pointer._obj.dwFileAttributes = file_attribute_normal
        return 1

    info = _FakeCFunction(fill_info)
    close = _FakeCFunction(lambda _handle: 1)
    last_error = _FakeCFunction(lambda: 0)
    kernel32 = SimpleNamespace(
        CreateFileW=create,
        GetFileType=file_type,
        GetFileInformationByHandle=info,
        CloseHandle=close,
        GetLastError=last_error,
    )
    converted: list[tuple[int, int]] = []
    msvcrt = SimpleNamespace(
        open_osfhandle=lambda handle, flags: converted.append((handle, flags)) or 77
    )
    api = bounded._Win32Api(kernel32=kernel32, msvcrt=msvcrt)

    handle = api.open_reparse(Path("C:/repo/workflows/example.hermes.yaml"))
    assert handle == 101
    assert create.calls == [
        (
            "C:\\repo\\workflows\\example.hermes.yaml",
            generic_read,
            share_read | share_write | share_delete,
            None,
            open_existing,
            open_reparse_point | backup_semantics,
            None,
        )
    ]
    identity = api.inspect(handle)
    assert identity.file_type == file_type_disk
    assert identity.attributes == file_attribute_normal
    assert api.descriptor_from_handle(handle) == 77
    assert converted == [(101, os.O_RDONLY | binary)]
    assert create.argtypes == [
        wintypes.LPCWSTR,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        wintypes.HANDLE,
    ]
    assert create.restype is wintypes.HANDLE
    assert file_type.argtypes == [wintypes.HANDLE]
    assert file_type.restype is wintypes.DWORD
    assert info.argtypes == [
        wintypes.HANDLE,
        ctypes.POINTER(bounded._BY_HANDLE_FILE_INFORMATION),
    ]
    assert info.restype is wintypes.BOOL
    assert close.argtypes == [wintypes.HANDLE]
    assert close.restype is wintypes.BOOL
    assert last_error.argtypes == []
    assert last_error.restype is wintypes.DWORD


@pytest.mark.parametrize(
    "last_error,code",
    [
        (2, "missing_source"),
        (3, "missing_source"),
        (5, "unsafe_source"),
        (12_345, "io_error"),
    ],
)
def test_D01_win32_invalid_handle_error_mapping(last_error: int, code: str) -> None:
    """D01: INVALID_HANDLE_VALUE maps GetLastError without path leakage."""
    bounded = _bounded_source()
    create = _FakeCFunction(lambda *_args: ctypes.c_void_p(-1).value)
    kernel32 = SimpleNamespace(
        CreateFileW=create,
        GetFileType=_FakeCFunction(lambda _handle: 0),
        GetFileInformationByHandle=_FakeCFunction(lambda *_args: 0),
        CloseHandle=_FakeCFunction(lambda _handle: 1),
        GetLastError=_FakeCFunction(lambda: last_error),
    )
    api = bounded._Win32Api(
        kernel32=kernel32,
        msvcrt=SimpleNamespace(open_osfhandle=lambda *_args: 7),
    )
    with pytest.raises(CatalogError) as exc:
        api.open_reparse(Path("C:/PRIVATE-SENTINEL.yaml"))
    assert exc.value.code == code
    assert "PRIVATE-SENTINEL" not in str(exc.value)


@pytest.mark.parametrize("last_error", [2, 3])
@pytest.mark.parametrize(
    "contract_name,kind,optional",
    [
        ("WORKFLOW_SIDECAR_CONTRACT", "yaml", True),
        ("WORKFLOW_METADATA_CONTRACT", "yaml", False),
        ("CONFIG_SCHEMA_CONTRACT", "json", False),
    ],
)
def test_A02_D01_concrete_win32_missing_errors_follow_contract_optionality(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    last_error: int,
    contract_name: str,
    kind: str,
    optional: bool,
) -> None:
    """A02/D01: Win32 errors 2/3 are typed absence only for sidecars."""
    bounded = _bounded_source()
    kernel32 = SimpleNamespace(
        CreateFileW=_FakeCFunction(lambda *_args: ctypes.c_void_p(-1).value),
        GetFileType=_FakeCFunction(lambda _handle: 0),
        GetFileInformationByHandle=_FakeCFunction(lambda *_args: 0),
        CloseHandle=_FakeCFunction(lambda _handle: 1),
        GetLastError=_FakeCFunction(lambda: last_error),
    )
    api = bounded._Win32Api(
        kernel32=kernel32,
        msvcrt=SimpleNamespace(open_osfhandle=lambda *_args: 7),
    )
    monkeypatch.setattr(bounded, "_platform_name", lambda: "nt")
    monkeypatch.setattr(bounded, "_win32_api", lambda: api)
    contract = getattr(bounded, contract_name)
    loader = bounded.load_yaml_mapping if kind == "yaml" else bounded.load_json_mapping
    source = tmp_path / "PRIVATE-SENTINEL-source"
    if optional:
        assert loader(source, contract) is None
    else:
        with pytest.raises(CatalogError) as exc:
            loader(source, contract)
        assert exc.value.code == "missing_source"
        assert "PRIVATE-SENTINEL" not in str(exc.value)


def test_D01_win32_closehandle_failure_is_observable_and_redacted() -> None:
    """D01: a failed pre-transfer CloseHandle has one owned-handle error."""
    bounded = _bounded_source()
    close = _FakeCFunction(lambda _handle: 0)
    kernel32 = SimpleNamespace(
        CreateFileW=_FakeCFunction(lambda *_args: 101),
        GetFileType=_FakeCFunction(lambda _handle: 1),
        GetFileInformationByHandle=_FakeCFunction(lambda *_args: 1),
        CloseHandle=close,
        GetLastError=_FakeCFunction(lambda: 12_345),
    )
    api = bounded._Win32Api(
        kernel32=kernel32,
        msvcrt=SimpleNamespace(open_osfhandle=lambda *_args: 7),
    )
    with pytest.raises(OSError) as exc:
        api.close_handle(101)
    assert len(close.calls) == 1
    assert "PRIVATE-SENTINEL" not in str(exc.value)


@pytest.mark.parametrize("stage", ["file-type", "attributes"])
def test_D01_win32_handle_inspection_error_mapping(stage: str) -> None:
    """D01: GetFileType/info errors are fixed before handle conversion."""
    bounded = _bounded_source()
    kernel32 = SimpleNamespace(
        CreateFileW=_FakeCFunction(lambda *_args: 101),
        GetFileType=_FakeCFunction(
            lambda _handle: 0 if stage == "file-type" else bounded._WIN_FILE_TYPE_DISK
        ),
        GetFileInformationByHandle=_FakeCFunction(
            lambda *_args: 0 if stage == "attributes" else 1
        ),
        CloseHandle=_FakeCFunction(lambda _handle: 1),
        GetLastError=_FakeCFunction(lambda: 5),
    )
    api = bounded._Win32Api(
        kernel32=kernel32,
        msvcrt=SimpleNamespace(open_osfhandle=lambda *_args: 7),
    )
    with pytest.raises(CatalogError) as exc:
        api.inspect(101)
    assert exc.value.code == "io_error"


@pytest.mark.parametrize(
    "status,accepted,absent,code",
    [
        ("regular", True, False, None),
        ("missing", False, True, None),
        ("directory", False, False, "unsafe_source"),
        ("non-disk", False, False, "unsafe_source"),
        ("broken-reparse", False, False, "unsafe_source"),
        ("internal-reparse", False, False, "unsafe_source"),
        ("external-reparse", False, False, "unsafe_source"),
        ("open-error", False, False, "unsafe_source"),
        ("inspect-error", False, False, "io_error"),
        ("conversion-error", False, False, "io_error"),
        ("directory-close-error", False, False, "unsafe_source"),
        ("conversion-error-close-error", False, False, "io_error"),
    ],
)
def test_D01_win32_open_reparse_handle_policy(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    status: str,
    accepted: bool,
    absent: bool,
    code: str | None,
) -> None:
    """D01: concrete Win32 handle acquisition rejects every unsafe class."""
    bounded = _bounded_source()
    source = tmp_path / "source.hermes.yaml"
    source.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
    original = os.open(source, os.O_RDONLY)
    fake = _FakeWin32(status=status, descriptor=original)
    monkeypatch.setattr(bounded, "_platform_name", lambda: "nt")
    monkeypatch.setattr(bounded, "_win32_api", lambda: fake)
    try:
        if accepted:
            loaded = bounded.load_yaml_mapping(
                source, bounded.WORKFLOW_SIDECAR_CONTRACT
            )
            assert loaded["language_compatibility"] == "archon-2026-07"
        elif absent:
            assert (
                bounded.load_yaml_mapping(source, bounded.WORKFLOW_SIDECAR_CONTRACT)
                is None
            )
        else:
            with pytest.raises(CatalogError) as exc:
                bounded.load_yaml_mapping(source, bounded.WORKFLOW_SIDECAR_CONTRACT)
            assert exc.value.code == code
            assert "PRIVATE-SENTINEL" not in str(exc.value)
    finally:
        os.close(original)
    if status in {
        "directory",
        "non-disk",
        "broken-reparse",
        "internal-reparse",
        "external-reparse",
        "inspect-error",
        "conversion-error",
        "directory-close-error",
        "conversion-error-close-error",
    }:
        assert fake.closed_handles == [101]
    if status == "regular":
        assert fake.converted == [101]
        assert fake.closed_handles == []  # descriptor conversion transfers ownership


@pytest.mark.parametrize("operation", ["fstat", "read", "close"])
def test_D01_win32_post_conversion_errors_close_descriptor(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, operation: str
) -> None:
    """D01: Win32 descriptor ownership follows the shared error/close path."""
    bounded = _bounded_source()
    source = tmp_path / "source.hermes.yaml"
    source.write_text("language_compatibility: archon-2026-07\n", encoding="utf-8")
    original_fd = os.open(source, os.O_RDONLY)
    fake = _FakeWin32(status="regular", descriptor=original_fd)
    monkeypatch.setattr(bounded, "_platform_name", lambda: "nt")
    monkeypatch.setattr(bounded, "_win32_api", lambda: fake)
    seam = {
        "fstat": "_fstat_descriptor",
        "read": "_read_descriptor",
        "close": "_close_descriptor",
    }[operation]
    original = getattr(bounded, seam)
    attempts: list[int] = []

    def fail(*args):
        attempts.append(args[0])
        if operation == "close":
            original(*args)
        raise OSError(errno.EIO, "PRIVATE-SENTINEL")

    monkeypatch.setattr(bounded, seam, fail)
    try:
        with pytest.raises(CatalogError) as exc:
            bounded.load_yaml_mapping(source, bounded.WORKFLOW_SIDECAR_CONTRACT)
        assert exc.value.code == "io_error"
    finally:
        os.close(original_fd)
    assert len(fake.produced_fds) == 1
    assert len(attempts) == 1
    with pytest.raises(OSError):
        os.fstat(fake.produced_fds[0])


def test_D02_current_task11_and_connector_contract_surfaces_remain_present() -> None:
    """D02: execute Task8-11/reference gates, including 11 scheduler lanes."""
    selection = [
        "tests/test_gitlab_reads.py",
        "tests/test_gitlab_ci.py",
        "tests/test_gitlab_writes.py",
        "tests/test_gitlab_skills.py",
        "tests/test_gitlab_workflows.py",
        "tests/test_onboarding_catalog.py",
        "tests/test_manifest.py",
        "tests/test_reference_workflows.py",
    ]
    result = subprocess.run(
        [sys.executable, "-m", "pytest", *selection],
        cwd=REPO,
        text=True,
        capture_output=True,
        timeout=900,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    assert "passed" in result.stdout


def test_matrix_constants_are_frozen() -> None:
    """D03: closure limits are explicit constants, never caller magic values."""
    bounded = importlib.import_module("bounded_source")
    signature = inspect.signature(bounded.SourceContract)
    assert tuple(signature.parameters) == (
        "label",
        "max_bytes",
        "max_graph_entries",
        "max_depth",
        "max_aliases",
        "optional",
    )
    assert all(
        parameter.kind is inspect.Parameter.KEYWORD_ONLY
        for parameter in signature.parameters.values()
    )
    contract = bounded.SourceContract(label="test source", max_bytes=17)
    assert not hasattr(contract, "__dict__")
    assert contract.max_graph_entries == SIDE_CAR_ENTRY_LIMIT
    assert contract.max_depth == SIDE_CAR_DEPTH_LIMIT
    assert contract.max_aliases is None
    assert contract.optional is False
    with pytest.raises(FrozenInstanceError):
        contract.max_bytes = 18

    assert issubclass(bounded.SourceErrorCode, StrEnum)
    assert tuple((item.name, item.value) for item in bounded.SourceErrorCode) == (
        ("VALIDATION", "validation"),
        ("MISSING_SOURCE", "missing_source"),
        ("UNSAFE_SOURCE", "unsafe_source"),
        ("SAFE_OPEN_UNAVAILABLE", "safe_open_unavailable"),
        ("IO_ERROR", "io_error"),
        ("BYTE_LIMIT", "byte_limit"),
        ("INVALID_YAML", "invalid_yaml"),
        ("INVALID_JSON", "invalid_json"),
        ("DUPLICATE_KEY", "duplicate_key"),
        ("MERGE_KEY", "merge_key"),
        ("PARSER_LIMIT", "parser_limit"),
        ("KEY_TYPE", "key_type"),
        ("CYCLE", "cycle"),
        ("STRUCTURE_LIMIT", "structure_limit"),
    )
    assert bounded.WORKFLOW_SIDECAR_CONTRACT.max_bytes == SIDE_CAR_LIMIT
    assert bounded.WORKFLOW_SIDECAR_CONTRACT.max_depth == SIDE_CAR_DEPTH_LIMIT
    assert bounded.WORKFLOW_SIDECAR_CONTRACT.max_graph_entries == SIDE_CAR_ENTRY_LIMIT
    assert bounded.WORKFLOW_SIDECAR_CONTRACT.max_aliases == 128
    assert bounded.CONFIG_SCHEMA_CONTRACT.max_bytes == CONFIG_SCHEMA_LIMIT
    assert bounded.CONFIG_SCHEMA_CONTRACT.max_graph_entries == SIDE_CAR_ENTRY_LIMIT
    assert bounded.CONFIG_SCHEMA_CONTRACT.max_aliases is None
    assert bounded.WORKFLOW_METADATA_CONTRACT.max_bytes == WORKFLOW_METADATA_LIMIT
    assert bounded.WORKFLOW_METADATA_CONTRACT.max_graph_entries == SIDE_CAR_ENTRY_LIMIT
    assert bounded.WORKFLOW_METADATA_CONTRACT.max_aliases == 128


def test_D03_source_errors_are_structured_and_catalog_compatible(
    tmp_path: Path,
) -> None:
    """A02/B08/D03: callers branch on codes/optionality, never rendered text."""
    bounded = _bounded_source()
    assert catalog_lib.CatalogError is bounded.SourceError
    directory = tmp_path / "source.yaml"
    directory.mkdir()
    with pytest.raises(bounded.SourceError) as exc:
        bounded.load_yaml_mapping(directory, bounded.WORKFLOW_SIDECAR_CONTRACT)
    assert isinstance(exc.value.code, bounded.SourceErrorCode)
    assert exc.value.code == "unsafe_source"
    assert exc.value.label == "workflow sidecar"
    assert str(exc.value) == FIXED_INVALID_SOURCE
    assert not hasattr(exc.value, "source_value")

    legacy = catalog_lib.CatalogError("legacy validation detail")
    assert isinstance(legacy.code, bounded.SourceErrorCode)
    assert legacy.code == "validation"
    assert legacy.label is None
    assert legacy.args == ("legacy validation detail",)
    assert str(legacy) == "legacy validation detail"


@pytest.mark.parametrize(
    "contract_name,kind",
    [
        ("WORKFLOW_SIDECAR_CONTRACT", "yaml"),
        ("WORKFLOW_METADATA_CONTRACT", "yaml"),
        ("CONFIG_SCHEMA_CONTRACT", "json"),
    ],
)
def test_D03_adjacent_parser_capacity_stops_construction(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    contract_name: str,
    kind: str,
) -> None:
    """D03: exact graph entry 2,049 stops before excess construction."""
    bounded = _bounded_source()
    contract = getattr(bounded, contract_name)
    path = tmp_path / ("source.yaml" if kind == "yaml" else "source.json")
    # root=1, mapping value array=1, and 2,047 array elements => 2,049.
    items = contract.max_graph_entries - 1
    assert 1 + 1 + items == contract.max_graph_entries + 1
    if kind == "yaml":
        path.write_text("items: [" + ",".join("{}" for _ in range(items)) + "]\n")
        constructions = 0
        original = bounded._BoundedSafeLoader.construct_object

        def counted(loader, node, deep=False):
            nonlocal constructions
            constructions += 1
            return original(loader, node, deep=deep)

        monkeypatch.setattr(bounded._BoundedSafeLoader, "construct_object", counted)
        with pytest.raises(CatalogError) as exc:
            bounded.load_yaml_mapping(path, contract)
        assert exc.value.code == "parser_limit"
        assert constructions == 0
    else:
        path.write_text('{"items":[' + ",".join("{}" for _ in range(items)) + "]}")
        appended = 0
        original_append = bounded._BoundedJsonParser._append_value

        def counted(parser, *args):
            nonlocal appended
            appended += 1
            return original_append(parser, *args)

        monkeypatch.setattr(bounded._BoundedJsonParser, "_append_value", counted)
        with pytest.raises(CatalogError) as exc:
            bounded.load_json_mapping(path, contract)
        assert exc.value.code == "parser_limit"
        assert 0 < appended <= contract.max_graph_entries
