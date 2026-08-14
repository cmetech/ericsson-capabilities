"""L-01 through L-05: bounded SharePoint listing behavior."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-sharepoint"


def _load_package():
    name = "ericsson_sharepoint_reads_test"
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


def _item(item_id, name, *, folder=False, size=10, web_url=None):
    result = {
        "id": item_id,
        "name": name,
        "size": size,
        "webUrl": web_url or f"https://tenant.sharepoint.com/docs/{name}",
        "lastModifiedDateTime": "2026-08-09T12:00:00Z",
        "parentReference": {"id": "parent"},
    }
    result["folder" if folder else "file"] = (
        {"childCount": 1} if folder else {"mimeType": "text/plain"}
    )
    return result


class Graph:
    def __init__(self, pages):
        self.pages = pages
        self.calls = []
        self.yielded = 0

    async def iterate_pages(
        self, path, *, params=None, headers=None, deadline=None, cancel_check=None
    ):
        self.calls.append((path, params, headers, deadline, cancel_check))
        for page in self.pages.get(path, []):
            self.yielded += 1
            yield page


class Client:
    def __init__(self, pages):
        self.graph = Graph(pages)
        self.tenant_hosts = {"tenant.sharepoint.com"}

    async def get_item(self, **_identity):
        return {
            "tenant_host": "tenant.sharepoint.com",
            "site": {"id": "site", "name": "Site", "web_url": ""},
            "drive": {"id": "drive", "name": "Documents"},
            "item": {
                "id": "root", "name": "Root", "path": "Base", "kind": "folder",
                "size": 0, "web_url": "", "parent_id": "", "mime_type": "",
            },
        }


@pytest.mark.anyio
async def test_l01_l03_paginated_listing_has_stable_relative_metadata():
    operations, _ = _load_package()
    client = Client(
        {
            "/drives/drive/items/root/children": [
                {"value": [_item("a", "A.txt")]},
                {"value": [_item("folder", "Folder", folder=True, size=0)]},
            ]
        }
    )

    result = await operations.list_items_with_client(
        client, url="https://tenant.sharepoint.com/Documents", recursive=False,
        max_pages=3, max_items=10, max_depth=2, max_metadata_bytes=10_000,
    )

    assert result["status"] == "complete"
    assert result["truncated"] is False
    assert result["warnings"] == []
    assert result["items"] == [
        {
            "id": "a", "drive_id": "drive", "name": "A.txt",
            "relative_path": "A.txt", "kind": "file", "size": 10,
            "mime_type": "text/plain",
            "web_url": "https://tenant.sharepoint.com/docs/A.txt",
            "modified": "2026-08-09T12:00:00Z",
        },
        {
            "id": "folder", "drive_id": "drive", "name": "Folder",
            "relative_path": "Folder", "kind": "folder", "size": 0,
            "mime_type": "",
            "web_url": "https://tenant.sharepoint.com/docs/Folder",
            "modified": "2026-08-09T12:00:00Z",
        },
    ]
    assert result["counts"] == {"items": 2, "pages": 2, "metadata_bytes": result["counts"]["metadata_bytes"]}


@pytest.mark.anyio
async def test_listing_propagates_operation_controls_to_resolution_and_pagination():
    operations, _ = _load_package()
    client = Client({"/drives/drive/items/root/children": [{"value": []}]})
    resolved_controls = []
    original_get_item = client.get_item

    async def get_item(**identity):
        resolved_controls.append((identity.pop("deadline"), identity.pop("cancel_check")))
        return await original_get_item(**identity)

    client.get_item = get_item
    cancel_check = lambda: False

    await operations.list_items_with_client(
        client,
        url="https://tenant.sharepoint.com/Documents",
        recursive=False,
        max_pages=1,
        max_items=1,
        max_depth=1,
        max_metadata_bytes=1000,
        deadline=99.0,
        cancel_check=cancel_check,
        clock=lambda: 1.0,
    )

    assert resolved_controls == [(99.0, cancel_check)]
    assert client.graph.calls[0][-2:] == (99.0, cancel_check)


@pytest.mark.anyio
async def test_l02_recursive_listing_is_depth_and_cycle_bounded():
    operations, _ = _load_package()
    client = Client(
        {
            "/drives/drive/items/root/children": [
                {"value": [_item("folder", "Folder", folder=True, size=0)]}
            ],
            "/drives/drive/items/folder/children": [
                {"value": [
                    _item("nested", "Nested.txt"),
                    _item("folder", "Cycle", folder=True, size=0),
                    _item("deep", "Deep", folder=True, size=0),
                ]}
            ],
        }
    )

    result = await operations.list_items_with_client(
        client, url="https://tenant.sharepoint.com/Documents", recursive=True,
        max_pages=10, max_items=10, max_depth=1, max_metadata_bytes=20_000,
    )

    assert [item["relative_path"] for item in result["items"]] == [
        "Folder", "Folder/Nested.txt", "Folder/Cycle", "Folder/Deep"
    ]
    assert result["status"] == "truncated"
    assert "maximum recursion depth reached" in result["warnings"]
    assert "cycle skipped" in result["warnings"]
    assert all("/items/deep/children" not in call[0] for call in client.graph.calls)


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("bounds", "warning"),
    [
        ({"max_pages": 1, "max_items": 10, "max_metadata_bytes": 20_000}, "page limit"),
        ({"max_pages": 10, "max_items": 1, "max_metadata_bytes": 20_000}, "item limit"),
        ({"max_pages": 10, "max_items": 10, "max_metadata_bytes": 80}, "metadata byte limit"),
    ],
)
async def test_l02_listing_returns_explicit_truncation(bounds, warning):
    operations, _ = _load_package()
    client = Client(
        {
            "/drives/drive/items/root/children": [
                {"value": [_item("a", "A.txt")], "@odata.nextLink": "https://graph.microsoft.com/v1.0/next"},
                {"value": [_item("b", "B.txt")]},
            ]
        }
    )

    result = await operations.list_items_with_client(
        client, url="https://tenant.sharepoint.com/Documents", recursive=False,
        max_depth=1, **bounds,
    )

    assert result["status"] == "truncated"
    assert result["truncated"] is True
    assert any(warning in value for value in result["warnings"])
    if warning == "page limit":
        assert client.graph.yielded == 1


@pytest.mark.anyio
async def test_listing_honors_cancellation_and_deadline_without_false_completion():
    operations, models = _load_package()
    client = Client({"/drives/drive/items/root/children": [{"value": []}]})

    with pytest.raises(models.SharePointCancelledError):
        await operations.list_items_with_client(
            client, url="https://tenant.sharepoint.com/Documents", recursive=False,
            max_pages=1, max_items=1, max_depth=1, max_metadata_bytes=1000,
            cancel_check=lambda: True,
        )
    with pytest.raises(models.SharePointDeadlineError):
        await operations.list_items_with_client(
            client, url="https://tenant.sharepoint.com/Documents", recursive=False,
            max_pages=1, max_items=1, max_depth=1, max_metadata_bytes=1000,
            deadline=0,
            clock=lambda: 1,
        )


@pytest.mark.anyio
async def test_l04_l05_filters_are_case_insensitive_and_never_expand_fetch_scope():
    operations, _ = _load_package()
    client = Client(
        {
            "/drives/drive/items/root/children": [
                {"value": [
                    _item("folder", "Folder", folder=True, size=0),
                    _item("root-pdf", "ROOT.PDF"),
                ]}
            ],
            "/drives/drive/items/folder/children": [
                {"value": [
                    _item("docx", "Plan.DOCX"),
                    _item("pdf", "Notes.pdf"),
                    _item("txt", "skip.txt"),
                ]}
            ],
        }
    )

    by_extension = await operations.list_items_with_client(
        client, url="https://tenant.sharepoint.com/Documents", recursive=True,
        max_pages=10, max_items=10, max_depth=2, max_metadata_bytes=20_000,
        extensions=("pdf",),
    )
    by_path_pattern = await operations.list_items_with_client(
        client, url="https://tenant.sharepoint.com/Documents", recursive=True,
        max_pages=10, max_items=10, max_depth=2, max_metadata_bytes=20_000,
        extensions=("txt",), name_patterns=("folder/*.docx",),
    )

    assert [row["relative_path"] for row in by_extension["items"]] == [
        "ROOT.PDF", "Folder/Notes.pdf"
    ]
    assert [row["relative_path"] for row in by_path_pattern["items"]] == [
        "Folder/Plan.DOCX"
    ]
    assert len(client.graph.calls) == 4


def test_read_tool_schemas_expose_limits_but_not_authority_claims():
    _load_package()
    tools = sys.modules["ericsson_sharepoint_reads_test.tools"]

    assert {"sharepoint_list_items", "sharepoint_download"} <= tools.SCHEMAS.keys()
    download_properties = tools.SCHEMAS["sharepoint_download"]["parameters"]["properties"]
    list_properties = tools.SCHEMAS["sharepoint_list_items"]["parameters"]["properties"]
    assert {"name_patterns", "extensions"} <= list_properties.keys()
    assert "destination" in download_properties
    assert not {"approved", "interactive", "authorized_root", "unattended"} & download_properties.keys()
