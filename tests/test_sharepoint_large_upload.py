"""W-01 through W-03: bounded small and upload-session behavior."""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import sys
import time

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins/ericsson-sharepoint"


def _load():
    name = "sharepoint_large_upload_test"
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            sys.modules.pop(key)
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return sys.modules[name + ".operations"], sys.modules[name + ".models"]


class Graph:
    def __init__(self):
        self.calls = []

    async def upload_small(self, path, data, **kwargs):
        self.calls.append(("small", path, data, kwargs))
        return {"id": "uploaded", "name": "small.bin", "size": len(data)}

    async def upload_via_session(self, path, source, **kwargs):
        self.calls.append(("large", path, Path(source), kwargs))
        return {
            "id": "uploaded",
            "name": "large.bin",
            "size": Path(source).stat().st_size,
        }


class Client:
    def __init__(self, graph):
        self.graph = graph
        self.controls = []

    async def get_item(self, **kwargs):
        self.controls.append((kwargs.get("deadline"), kwargs.get("cancel_check")))
        return {
            "tenant_host": "tenant.sharepoint.com",
            "drive": {"id": "drive", "name": "Documents"},
            "item": {"id": "folder", "kind": "folder", "name": "Folder"},
            "site": {"id": "site"},
        }


def _config(models, tmp_path):
    return models.SharePointConfiguration.from_mapping(
        {
            "tenant_host": "tenant.sharepoint.com",
            "auth_mode": "azure_cli",
            "scopes": "https://graph.microsoft.com/.default",
            "browser_profile": "corp",
            "upload_root": str(tmp_path / "uploads"),
            "download_root": str(tmp_path / "downloads"),
            "max_bytes": 20 * 1024 * 1024,
        },
        profile_home=tmp_path,
    )


@pytest.mark.anyio
async def test_w01_small_upload_exact_path_bytes_and_conflict_policy(tmp_path):
    operations, models = _load()
    config = _config(models, tmp_path)
    config.upload_root.mkdir(parents=True)
    source = config.upload_root / "small.bin"
    source.write_bytes(b"small")
    graph = Graph()
    client = Client(graph)
    cancel_check = lambda: False
    deadline = time.monotonic() + 99
    result = await operations.upload_with_client(
        client,
        config,
        folder_url="https://tenant.sharepoint.com/Destination",
        source=source,
        name="Remote #1.bin",
        conflict_behavior="rename",
        deadline=deadline,
        cancel_check=cancel_check,
    )
    assert result["id"] == "uploaded"
    assert graph.calls == [
        (
            "small",
            "/drives/drive/items/folder:/Remote%20%231.bin:/content?@microsoft.graph.conflictBehavior=rename",
            b"small",
            {
                "max_bytes": 4194304,
                "deadline": deadline,
                "cancel_check": cancel_check,
            },
        )
    ]
    assert client.controls == [(deadline, cancel_check)]


@pytest.mark.anyio
async def test_w02_large_upload_delegates_aligned_bounded_session_without_restart(
    tmp_path,
):
    operations, models = _load()
    config = _config(models, tmp_path)
    config.upload_root.mkdir(parents=True)
    source = config.upload_root / "large.bin"
    source.write_bytes(b"x" * (4 * 1024 * 1024 + 1))
    deadline = time.monotonic() + 123
    graph = Graph()
    result = await operations.upload_with_client(
        Client(graph),
        config,
        folder_url="https://tenant.sharepoint.com/Destination",
        source=source,
        conflict_behavior="replace",
        chunk_size=10 * 1024 * 1024,
        max_chunks=4,
        deadline=deadline,
        cancel_check=lambda: False,
    )
    assert result["id"] == "uploaded" and len(graph.calls) == 1
    call = graph.calls[0]
    assert call[0] == "large"
    assert call[1] == "/drives/drive/items/folder:/large.bin:/createUploadSession"
    assert call[3]["chunk_size"] % (320 * 1024) == 0
    assert call[3]["max_chunks"] == 4


@pytest.mark.anyio
async def test_w03_upload_source_boundary_rejects_traversal_symlink_and_special_file(
    tmp_path,
):
    operations, models = _load()
    config = _config(models, tmp_path)
    config.upload_root.mkdir(parents=True)
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"secret")
    link = config.upload_root / "link.bin"
    link.symlink_to(outside)
    graph = Graph()
    for source in (outside, link):
        with pytest.raises(models.SharePointFileBoundaryError):
            await operations.upload_with_client(
                Client(graph),
                config,
                folder_url="https://tenant.sharepoint.com/Destination",
                source=source,
            )
    if hasattr(os, "mkfifo"):
        fifo = config.upload_root / "pipe"
        os.mkfifo(fifo)
        try:
            with pytest.raises(models.SharePointFileBoundaryError):
                await operations.upload_with_client(
                    Client(graph),
                    config,
                    folder_url="https://tenant.sharepoint.com/Destination",
                    source=fifo,
                )
        finally:
            fifo.unlink()
    assert graph.calls == []


@pytest.mark.anyio
async def test_upload_rejects_symlink_swap_after_boundary_validation(
    tmp_path, monkeypatch
):
    operations, models = _load()
    config = _config(models, tmp_path)
    config.upload_root.mkdir(parents=True)
    source = config.upload_root / "source.bin"
    source.write_bytes(b"authorized")
    outside = tmp_path / "outside.bin"
    outside.write_bytes(b"outside secret")
    original = operations._upload_source

    def swap_after_validation(config, candidate):
        validated = original(config, candidate)
        validated.unlink()
        validated.symlink_to(outside)
        return validated

    monkeypatch.setattr(operations, "_upload_source", swap_after_validation)
    graph = Graph()

    with pytest.raises(models.SharePointFileBoundaryError):
        await operations.upload_with_client(
            Client(graph),
            config,
            folder_url="https://tenant.sharepoint.com/Destination",
            source=source,
        )

    assert graph.calls == []


@pytest.mark.anyio
async def test_upload_rejects_bad_conflict_chunk_and_cancel_before_remote_call(
    tmp_path,
):
    operations, models = _load()
    config = _config(models, tmp_path)
    config.upload_root.mkdir(parents=True)
    source = config.upload_root / "file.bin"
    source.write_bytes(b"ok")
    graph = Graph()
    with pytest.raises(models.SharePointWriteError):
        await operations.upload_with_client(
            Client(graph),
            config,
            folder_url="https://tenant.sharepoint.com/Destination",
            source=source,
            conflict_behavior="invent",
        )
    with pytest.raises(models.SharePointCancelledError):
        await operations.upload_with_client(
            Client(graph),
            config,
            folder_url="https://tenant.sharepoint.com/Destination",
            source=source,
            cancel_check=lambda: True,
        )
    assert graph.calls == []
