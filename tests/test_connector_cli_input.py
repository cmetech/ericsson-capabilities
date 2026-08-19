from __future__ import annotations

import importlib.util
import io
import os
import sys
import threading
import uuid
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-connector-cli"


def _load_io():
    name = f"connector_cli_io_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "io.py")
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def local_io():
    return _load_io()


def test_regular_utf8_files_and_stdin_are_bounded(local_io, tmp_path):
    source = tmp_path / "body.md"
    source.write_text("café", encoding="utf-8")
    reader = local_io.BoundedInputReader(stdin=io.BytesIO("stdin".encode()))
    assert reader.read_text(str(source), reject_symlink=True) == "café"
    assert reader.read_text("-", reject_symlink=True) == "stdin"
    with pytest.raises(local_io.CliInputError, match="stdin.*once"):
        reader.read_text("-", reject_symlink=True)


def test_text_input_rejects_symlink_non_regular_invalid_utf8_and_oversize(
    local_io, tmp_path
):
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    link = tmp_path / "link.txt"
    link.symlink_to(source)
    directory = tmp_path / "directory"
    directory.mkdir()
    invalid = tmp_path / "invalid.txt"
    invalid.write_bytes(b"\xff")
    oversize = tmp_path / "oversize.txt"
    oversize.write_bytes(b"x" * (local_io.MAX_INPUT_BYTES + 1))
    reader = local_io.BoundedInputReader(stdin=io.BytesIO())

    for path, message in (
        (link, "symbolic link"),
        (directory, "regular file"),
        (invalid, "UTF-8"),
        (oversize, "256 KiB"),
    ):
        with pytest.raises(local_io.CliInputError, match=message):
            reader.read_text(str(path), reject_symlink=True)


def test_stdin_is_read_at_most_limit_plus_one_and_invalid_utf8_is_safe(local_io):
    class RecordingBytesIO(io.BytesIO):
        def __init__(self, value):
            super().__init__(value)
            self.requested = []

        def read(self, size=-1):
            self.requested.append(size)
            return super().read(size)

    stream = RecordingBytesIO(b"x" * (local_io.MAX_INPUT_BYTES + 1))
    reader = local_io.BoundedInputReader(stdin=stream)
    with pytest.raises(local_io.CliInputError, match="256 KiB"):
        reader.read_text("-", reject_symlink=True)
    assert stream.requested == [local_io.MAX_INPUT_BYTES + 1]

    with pytest.raises(local_io.CliInputError, match="UTF-8"):
        local_io.BoundedInputReader(stdin=io.BytesIO(b"\xff")).read_text(
            "-", reject_symlink=True
        )


def test_local_upload_path_is_resolved_but_never_read(local_io, tmp_path, monkeypatch):
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"payload")
    touched = []
    monkeypatch.setattr(Path, "read_bytes", lambda self: touched.append(self))
    resolved = local_io.resolve_local_path(str(source))
    assert resolved == str(source.resolve())
    assert touched == []


def test_local_upload_path_leaves_existence_and_symlink_authority_to_connector(
    local_io, tmp_path
):
    source = tmp_path / "artifact.bin"
    source.write_bytes(b"payload")
    link = tmp_path / "artifact-link.bin"
    link.symlink_to(source)
    assert local_io.resolve_local_path(str(tmp_path / "missing.bin")) == str(
        (tmp_path / "missing.bin").resolve()
    )
    assert local_io.resolve_local_path(str(link)) == str(source.resolve())


def test_name_value_decoder_bounds_and_duplicate_policy(local_io):
    values = local_io.decode_name_values(
        ['summary="hello"', "count=3", "enabled=true", "nothing=null"]
    )
    assert values == {
        "summary": "hello",
        "count": 3,
        "enabled": True,
        "nothing": None,
    }

    with pytest.raises(local_io.CliInputError, match="at most 64"):
        local_io.decode_name_values([f"f{i}=1" for i in range(65)])
    with pytest.raises(local_io.CliInputError, match="duplicate"):
        local_io.decode_name_values(["name=1", "name=2"])
    assert local_io.decode_name_values(
        ["name=1", "name=2"], list_valued=True
    ) == {"name": [1, 2]}


def test_change_files_are_one_bounded_object_each(local_io, tmp_path):
    first = tmp_path / "one.json"
    first.write_text(
        '{"action":"create","file_path":"one.txt","content":"hello"}',
        encoding="utf-8",
    )
    second = tmp_path / "two.json"
    second.write_text(
        '{"action":"delete","file_path":"two.txt"}', encoding="utf-8"
    )
    reader = local_io.BoundedInputReader(stdin=io.BytesIO())
    assert reader.read_change_objects([str(first), str(second)]) == [
        {"action": "create", "file_path": "one.txt", "content": "hello"},
        {"action": "delete", "file_path": "two.txt"},
    ]

    array = tmp_path / "array.json"
    array.write_text("[]", encoding="utf-8")
    with pytest.raises(local_io.CliInputError, match="one JSON object"):
        reader.read_change_objects([str(array)])

    with pytest.raises(local_io.CliInputError, match="at most 100"):
        reader.read_change_objects([str(first)] * 101)


def test_text_file_open_is_not_vulnerable_to_post_validation_symlink_swap(
    local_io, tmp_path, monkeypatch
):
    if not hasattr(os, "O_NOFOLLOW"):
        pytest.skip("platform has no O_NOFOLLOW")
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    original_open = os.open

    def swapped_open(path, flags, *args, **kwargs):
        source.unlink()
        source.symlink_to(tmp_path / "other.txt")
        return original_open(path, flags, *args, **kwargs)

    (tmp_path / "other.txt").write_text("unsafe", encoding="utf-8")
    monkeypatch.setattr(local_io.os, "open", swapped_open)
    with pytest.raises(local_io.CliInputError):
        local_io.BoundedInputReader(stdin=io.BytesIO()).read_text(
            str(source), reject_symlink=True
        )


def test_regular_file_open_uses_nonblocking_mode(local_io, tmp_path, monkeypatch):
    if not hasattr(os, "O_NONBLOCK"):
        pytest.skip("platform has no O_NONBLOCK")
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    original_open = os.open
    observed = []

    def inspect_open(path, flags, *args, **kwargs):
        observed.append(flags)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(local_io.os, "open", inspect_open)
    assert local_io.BoundedInputReader(stdin=io.BytesIO()).read_text(
        str(source), reject_symlink=True
    ) == "safe"
    assert observed and observed[0] & os.O_NONBLOCK


def test_pre_open_file_identity_must_match_open_descriptor(
    local_io, tmp_path, monkeypatch
):
    source = tmp_path / "source.txt"
    source.write_text("safe", encoding="utf-8")
    replacement = tmp_path / "replacement.txt"
    replacement.write_text("replacement", encoding="utf-8")
    original_open = os.open

    def replace_before_open(path, flags, *args, **kwargs):
        source.unlink()
        replacement.rename(source)
        return original_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(local_io.os, "open", replace_before_open)
    with pytest.raises(local_io.CliInputError, match="changed while opening"):
        local_io.BoundedInputReader(stdin=io.BytesIO()).read_text(
            str(source), reject_symlink=True
        )


def test_fifo_input_is_rejected_without_blocking(local_io, tmp_path):
    if not hasattr(os, "mkfifo"):
        pytest.skip("platform cannot create a FIFO")
    fifo = tmp_path / "input.fifo"
    os.mkfifo(fifo)
    outcomes = []

    def attempt_read():
        try:
            local_io.BoundedInputReader(stdin=io.BytesIO()).read_text(
                str(fifo), reject_symlink=True
            )
        except Exception as exc:  # captured for the main test thread
            outcomes.append(exc)

    worker = threading.Thread(target=attempt_read, daemon=True)
    worker.start()
    worker.join(timeout=0.5)
    blocked = worker.is_alive()
    if blocked:
        writer = os.open(fifo, os.O_WRONLY | getattr(os, "O_NONBLOCK", 0))
        os.close(writer)
        worker.join(timeout=0.5)
    assert not blocked, "FIFO input open blocked waiting for a writer"
    assert len(outcomes) == 1
    assert isinstance(outcomes[0], local_io.CliInputError)
    assert "regular file" in str(outcomes[0])
