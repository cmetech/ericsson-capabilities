"""U-04 through U-07 and R-01: bounded Graph DriveItem resolution."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-sharepoint"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "sharepoint"


def _load_package():
    name = "ericsson_sharepoint_resolution_test"
    for loaded in list(sys.modules):
        if loaded == name or loaded.startswith(f"{name}."):
            sys.modules.pop(loaded)
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return sys.modules[f"{name}.client"], sys.modules[f"{name}.models"]


class FakeGraphClient:
    def __init__(self, responses, pages=()):
        self.responses = dict(responses)
        self.pages = list(pages)
        self.calls = []

    async def get_json(
        self, path, *, params=None, headers=None, deadline=None, cancel_check=None
    ):
        self.calls.append(("get", path, params, headers, deadline, cancel_check))
        response = self.responses.get(path)
        if isinstance(response, Exception):
            raise response
        if response is None:
            raise AssertionError(f"unexpected Graph GET {path}")
        return response

    async def iterate_pages(
        self, path, *, params=None, headers=None, deadline=None, cancel_check=None
    ):
        self.calls.append(("pages", path, params, headers, deadline, cancel_check))
        for page in self.pages:
            yield page


@pytest.mark.anyio
async def test_u04_u05_u06_resolves_site_named_drive_and_encoded_item_path():
    client_module, _ = _load_package()
    graph = FakeGraphClient(
        {
            "/sites/tenant.sharepoint.com:/sites/Governance": json.loads(
                (FIXTURES / "site.json").read_text(encoding="utf-8")
            ),
            "/drives/drive-id/root:/Folder%20A/Plan%20%231.docx:": {
                "id": "item-id",
                "name": "Plan #1.docx",
                "size": 321,
                "file": {"mimeType": "application/vnd.openxmlformats-officedocument.wordprocessingml.document"},
                "webUrl": "https://tenant.sharepoint.com/sites/Governance/Library%20A/Folder%20A/Plan%20%231.docx",
                "parentReference": {"driveId": "drive-id", "id": "parent-id"},
            },
        },
        pages=[
            {"value": [{"id": "other", "name": "Documents", "webUrl": "https://tenant.sharepoint.com/sites/Governance/Documents"}]},
            {"value": [{"id": "drive-id", "name": "Library A", "webUrl": "https://tenant.sharepoint.com/sites/Governance/Library%20A"}]},
        ],
    )
    client = client_module.SharePointClient(
        graph, tenant_hosts={"tenant.sharepoint.com"}, max_pages=3, max_items=5
    )

    resolved = await client.resolve_url(
        "https://tenant.sharepoint.com/sites/Governance/Library%20A/Folder%20A/Plan%20%231.docx"
    )

    assert resolved == {
        "tenant_host": "tenant.sharepoint.com",
        "site": {
            "id": "site-id",
            "name": "Governance",
            "web_url": "https://tenant.sharepoint.com/sites/Governance",
        },
        "drive": {"id": "drive-id", "name": "Library A"},
        "item": {
            "id": "item-id",
            "name": "Plan #1.docx",
            "path": "Folder A/Plan #1.docx",
            "kind": "file",
            "size": 321,
            "web_url": "https://tenant.sharepoint.com/sites/Governance/Library%20A/Folder%20A/Plan%20%231.docx",
            "parent_id": "parent-id",
            "mime_type": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            "is_drive_root": False,
        },
    }
    assert graph.calls[1][0:2] == ("pages", "/sites/site-id/drives")


@pytest.mark.anyio
async def test_u05_default_and_internal_paths_use_site_default_drive():
    client_module, _ = _load_package()
    for library in ("", "Shared Documents", "Documents", "_layouts"):
        suffix = f"/{library.replace(' ', '%20')}" if library else ""
        graph = FakeGraphClient(
            {
                "/sites/tenant.sharepoint.com:/sites/Governance": {
                    "id": "site-id",
                    "displayName": "Governance",
                    "webUrl": "https://tenant.sharepoint.com/sites/Governance",
                },
                "/sites/site-id/drive": {"id": "default-drive", "name": "Documents"},
                "/drives/default-drive/root": {
                    "id": "root-id", "name": "root", "folder": {"childCount": 1}
                },
            }
        )
        client = client_module.SharePointClient(
            graph, tenant_hosts={"tenant.sharepoint.com"}
        )

        resolved = await client.resolve_url(
            f"https://tenant.sharepoint.com/sites/Governance{suffix}"
        )

        assert resolved["drive"] == {"id": "default-drive", "name": "Documents"}
        assert resolved["item"]["id"] == "root-id"
        assert resolved["item"]["is_drive_root"] is True


@pytest.mark.anyio
async def test_u05_rejects_ambiguous_drive_matches():
    client_module, models = _load_package()
    graph = FakeGraphClient(
        {
            "/sites/tenant.sharepoint.com:/sites/Governance": {
                "id": "site-id", "displayName": "Governance"
            }
        },
        pages=[
            {"value": [
                {"id": "one", "name": "Library", "webUrl": "https://tenant.sharepoint.com/a/Library"},
                {"id": "two", "name": "Other", "webUrl": "https://tenant.sharepoint.com/b/Library"},
            ]}
        ],
    )
    client = client_module.SharePointClient(
        graph, tenant_hosts={"tenant.sharepoint.com"}
    )

    with pytest.raises(models.SharePointResolutionError, match="ambiguous"):
        await client.resolve_url(
            "https://tenant.sharepoint.com/sites/Governance/Library"
        )


@pytest.mark.anyio
async def test_u01_u07_resolves_sharing_link_and_explicit_drive_item_identity():
    client_module, _ = _load_package()
    sharing_url = (
        "https://tenant.sharepoint.com/:w:/g/personal/user_tenant_onmicrosoft_com/"
        "EXAMPLE?e=abc"
    )
    share_id = client_module.encode_share_id(sharing_url)
    item = {
        "id": "shared-item",
        "name": "Shared.docx",
        "size": 10,
        "file": {"mimeType": "application/test"},
        "webUrl": "https://tenant.sharepoint.com/sites/Governance/Documents/Shared.docx",
        "parentReference": {"driveId": "shared-drive", "siteId": "shared-site", "id": "parent"},
    }
    graph = FakeGraphClient(
        {
            f"/shares/{share_id}/driveItem": item,
            "/drives/shared-drive/items/shared-item": item,
        }
    )
    client = client_module.SharePointClient(
        graph, tenant_hosts={"tenant.sharepoint.com"}
    )

    shared = await client.resolve_url(sharing_url)
    explicit = await client.get_item(drive_id="shared-drive", item_id="shared-item")

    assert shared["site"]["id"] == "shared-site"
    assert shared["drive"]["id"] == "shared-drive"
    assert shared["item"]["id"] == "shared-item"
    assert shared["item"]["is_drive_root"] is False
    assert explicit["item"]["id"] == "shared-item"
    assert explicit["item"]["is_drive_root"] is False


@pytest.mark.anyio
async def test_resolution_propagates_deadline_and_cancellation_to_every_graph_call():
    client_module, _ = _load_package()
    graph = FakeGraphClient(
        {
            "/sites/tenant.sharepoint.com:/sites/Governance": {
                "id": "site-id",
                "displayName": "Governance",
                "webUrl": "https://tenant.sharepoint.com/sites/Governance",
            },
            "/sites/site-id/drive": {"id": "drive-id", "name": "Documents"},
            "/drives/drive-id/root": {
                "id": "root-id",
                "name": "root",
                "folder": {"childCount": 1},
            },
        }
    )
    client = client_module.SharePointClient(
        graph, tenant_hosts={"tenant.sharepoint.com"}
    )
    cancel_check = lambda: False

    await client.resolve_url(
        "https://tenant.sharepoint.com/sites/Governance/Documents",
        deadline=99.0,
        cancel_check=cancel_check,
    )

    assert len(graph.calls) == 3
    assert all(call[-2:] == (99.0, cancel_check) for call in graph.calls)


@pytest.mark.anyio
async def test_u03_rejects_graph_web_urls_that_escape_configured_tenant():
    client_module, models = _load_package()
    graph = FakeGraphClient(
        {
            "/sites/tenant.sharepoint.com:/sites/Governance": {
                "id": "site-id",
                "displayName": "Governance",
                "webUrl": "https://evil.example/sites/Governance",
            }
        }
    )
    client = client_module.SharePointClient(
        graph, tenant_hosts={"tenant.sharepoint.com"}
    )

    with pytest.raises(models.SharePointResolutionError, match="tenant authority"):
        await client.resolve_url(
            "https://tenant.sharepoint.com/sites/Governance/Documents"
        )


def test_resolution_tool_schemas_are_connector_owned_and_bounded():
    package_name = "ericsson_sharepoint_resolution_test"
    _load_package()
    tools = next(
        module for name, module in sys.modules.items()
        if name.endswith(".tools") and name.startswith("ericsson_sharepoint_resolution_test")
    )

    assert {"sharepoint_resolve_url", "sharepoint_get_item"} <= set(tools.SCHEMAS)
    assert tools.SCHEMAS["sharepoint_resolve_url"]["parameters"]["additionalProperties"] is False
    assert tools.SCHEMAS["sharepoint_get_item"]["parameters"]["additionalProperties"] is False

    package = sys.modules[package_name]

    class Context:
        def __init__(self):
            self.actions = []
            self.hooks = []
            self.tools = []

        def register_setup_action(self, name, handler, **kwargs):
            self.actions.append((name, handler, kwargs))

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

        def register_hook(self, name, handler):
            self.hooks.append((name, handler))

    context = Context()
    package.register(context)

    assert {registered["name"] for registered in context.tools} == set(tools.SCHEMAS)
    assert all(registered["toolset"] == "ericsson-sharepoint" for registered in context.tools)
    assert all(registered["is_async"] is True for registered in context.tools)
