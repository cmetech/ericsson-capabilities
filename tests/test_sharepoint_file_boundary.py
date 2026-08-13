"""R-02 through R-05: download boundary, cleanup, and evidence behavior."""

from __future__ import annotations

import hashlib
import importlib.util
import os
from pathlib import Path
import sys
import time

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-sharepoint"
CONTENT = b"bounded sharepoint content"


def _load_package():
    name = "ericsson_sharepoint_boundary_test"
    for loaded in list(sys.modules):
        if loaded == name or loaded.startswith(f"{name}."):
            sys.modules.pop(loaded)
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
    )
    assert spec is not None and spec.loader is not None
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return sys.modules[f"{name}.operations"], sys.modules[f"{name}.models"]


def _config(models, tmp_path):
    return models.SharePointConfiguration.from_mapping(
        {
            "tenant_host": "tenant.sharepoint.com",
            "auth_mode": "azure_cli",
            "scopes": "https://graph.microsoft.com/.default",
            "browser_profile": "corp",
            "download_root": str(tmp_path / "downloads"),
            "upload_root": str(tmp_path / "uploads"),
            "max_bytes": 1024,
        },
        profile_home=tmp_path,
    )


class Graph:
    def __init__(self, *, fail=False):
        self.fail = fail
        self.calls = []

    async def download_to_file(self, path, destination, **kwargs):
        destination = Path(destination)
        self.calls.append((path, destination, kwargs))
        if self.fail:
            destination.with_suffix(destination.suffix + ".part").write_bytes(b"partial")
            raise RuntimeError("download failed with secret body")
        destination.write_bytes(CONTENT)
        return {"path": str(destination), "size": len(CONTENT)}


class Client:
    def __init__(self, graph=None, *, item_name="Report?.docx", kind="file"):
        self.graph = graph or Graph()
        self.item_name = item_name
        self.kind = kind

    async def get_item(self, **_identity):
        return {
            "tenant_host": "tenant.sharepoint.com",
            "site": {"id": "site", "name": "", "web_url": ""},
            "drive": {"id": "drive", "name": "Documents"},
            "item": {
                "id": "item", "name": self.item_name, "path": "", "kind": self.kind,
                "size": len(CONTENT), "web_url": "", "parent_id": "", "mime_type": "",
            },
        }


@pytest.mark.anyio
async def test_streamed_download_returns_digest_size_and_relative_only_evidence(tmp_path):
    operations, models = _load_package()
    config = _config(models, tmp_path)
    client = Client()

    result = await operations.download_with_client(
        client, config, url="https://tenant.sharepoint.com/Documents/Report.docx"
    )

    assert result == {
        "item_id": "item",
        "drive_id": "drive",
        "name": "Report_.docx",
        "path": "Report_.docx",
        "boundary": "configured_download_root",
        "size": len(CONTENT),
        "sha256": hashlib.sha256(CONTENT).hexdigest(),
    }
    assert (config.download_root / "Report_.docx").read_bytes() == CONTENT
    assert str(tmp_path) not in repr(result)
    path, temporary, kwargs = client.graph.calls[0]
    assert path == "/drives/drive/items/item/content"
    assert temporary.parent != config.download_root
    assert kwargs["max_bytes"] == config.max_bytes


@pytest.mark.anyio
@pytest.mark.parametrize(
    "destination",
    ["../escape.docx", "nested/../../escape.docx", "/tmp/not-authorized.docx"],
)
async def test_download_rejects_traversal_and_outside_absolute_paths(tmp_path, destination):
    operations, models = _load_package()
    config = _config(models, tmp_path)

    with pytest.raises(models.SharePointFileBoundaryError):
        await operations.download_with_client(
            Client(), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
            destination=destination,
        )

    assert not (tmp_path / "escape.docx").exists()


@pytest.mark.anyio
async def test_download_rejects_symlink_escape_and_existing_special_file(tmp_path):
    operations, models = _load_package()
    config = _config(models, tmp_path)
    config.download_root.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    (config.download_root / "linked").symlink_to(outside, target_is_directory=True)

    with pytest.raises(models.SharePointFileBoundaryError):
        await operations.download_with_client(
            Client(), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
            destination="linked/escape.docx",
        )

    if hasattr(os, "mkfifo"):
        fifo = config.download_root / "existing.pipe"
        os.mkfifo(fifo)
        try:
            with pytest.raises(models.SharePointFileBoundaryError):
                await operations.download_with_client(
                    Client(), config,
                    url="https://tenant.sharepoint.com/Documents/Report.docx",
                    destination="existing.pipe",
                )
        finally:
            fifo.unlink()


@pytest.mark.anyio
async def test_configured_root_itself_may_not_be_a_symlink(tmp_path):
    operations, models = _load_package()
    outside = tmp_path / "outside-root"
    outside.mkdir()
    linked_root = tmp_path / "linked-downloads"
    linked_root.symlink_to(outside, target_is_directory=True)
    config = models.SharePointConfiguration.from_mapping(
        {
            "tenant_host": "tenant.sharepoint.com",
            "auth_mode": "azure_cli",
            "scopes": "https://graph.microsoft.com/.default",
            "browser_profile": "corp",
            "download_root": str(linked_root),
            "upload_root": str(tmp_path / "uploads"),
        },
        profile_home=tmp_path,
    )

    with pytest.raises(models.SharePointFileBoundaryError, match="symbolic link"):
        await operations.download_with_client(
            Client(), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
        )
    assert list(outside.iterdir()) == []


@pytest.mark.anyio
async def test_external_root_requires_single_use_interactive_authorization(tmp_path):
    operations, models = _load_package()
    config = _config(models, tmp_path)
    external = tmp_path / "approved-external"
    authorization = operations.OneOperationFileAuthorization(
        tool_name="sharepoint_download", root=external, interactive=True
    )

    result = await operations.download_with_client(
        Client(), config,
        url="https://tenant.sharepoint.com/Documents/Report.docx",
        destination=str(external / "approved.docx"),
        file_authorization=authorization,
        unattended=False,
    )

    assert result["path"] == "approved.docx"
    assert result["boundary"] == "interactive_authorization"
    assert external.joinpath("approved.docx").read_bytes() == CONTENT
    with pytest.raises(models.SharePointFileBoundaryError, match="consumed"):
        await operations.download_with_client(
            Client(), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
            destination=str(external / "second.docx"),
            file_authorization=authorization,
            unattended=False,
        )


@pytest.mark.anyio
async def test_unattended_caller_cannot_expand_file_boundary(tmp_path):
    operations, models = _load_package()
    config = _config(models, tmp_path)
    external = tmp_path / "external"
    authorization = operations.OneOperationFileAuthorization(
        tool_name="sharepoint_download", root=external, interactive=True
    )

    with pytest.raises(models.SharePointFileBoundaryError, match="unattended"):
        await operations.download_with_client(
            Client(), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
            destination=str(external / "blocked.docx"),
            file_authorization=authorization,
            unattended=True,
        )


@pytest.mark.anyio
async def test_failure_cleans_every_private_partial_and_does_not_publish_target(tmp_path):
    operations, models = _load_package()
    config = _config(models, tmp_path)
    graph = Graph(fail=True)

    with pytest.raises(RuntimeError, match="secret body"):
        await operations.download_with_client(
            Client(graph), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
            destination="failed.docx",
        )

    assert not (config.download_root / "failed.docx").exists()
    assert list(config.download_root.glob("**/*.part")) == []
    assert list(config.download_root.glob(".sharepoint-*")) == []


@pytest.mark.anyio
async def test_download_rejects_folder_and_propagates_deadline_cancellation_controls(tmp_path):
    operations, models = _load_package()
    config = _config(models, tmp_path)
    with pytest.raises(models.SharePointFileBoundaryError, match="folder"):
        await operations.download_with_client(
            Client(kind="folder"), config,
            url="https://tenant.sharepoint.com/Documents/Folder",
        )

    graph = Graph()
    deadline = time.monotonic() + 123.0
    await operations.download_with_client(
        Client(graph), config,
        url="https://tenant.sharepoint.com/Documents/Report.docx",
        destination="controlled.docx",
        deadline=deadline,
        cancel_check=lambda: False,
    )
    assert graph.calls[0][2]["deadline"] == deadline
    assert graph.calls[0][2]["cancel_check"]() is False

    cancelled_graph = Graph()
    with pytest.raises(models.SharePointCancelledError):
        await operations.download_with_client(
            Client(cancelled_graph), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
            destination="cancelled.docx",
            cancel_check=lambda: True,
        )
    assert cancelled_graph.calls == []


@pytest.mark.anyio
async def test_download_rejects_expired_deadline_before_remote_stream(tmp_path):
    operations, models = _load_package()
    config = _config(models, tmp_path)
    graph = Graph()

    with pytest.raises(models.SharePointDeadlineError):
        await operations.download_with_client(
            Client(graph), config,
            url="https://tenant.sharepoint.com/Documents/Report.docx",
            destination="expired.docx",
            deadline=0,
        )

    assert graph.calls == []
