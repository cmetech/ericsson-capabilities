"""O-01 through O-03: bounded owned-site discovery."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-sharepoint"


def _load():
    name = "sharepoint_owned_sites_test"
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            sys.modules.pop(key)
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return sys.modules[name + ".operations"]


class Graph:
    def __init__(self):
        self.calls = []

    async def get_json(self, path, **_kwargs):
        self.calls.append(path)
        if path == "/me":
            return {"id": "me", "displayName": "User"}
        if path == "/groups/bad/sites/root":
            raise RuntimeError("raw remote failure")
        group = path.split("/")[2]
        return {"id": f"site-{group}", "displayName": f"Site {group}", "webUrl": f"https://tenant.sharepoint.com/sites/{group}", "description": "Desc", "createdDateTime": "2024-01-01"}

    async def iterate_pages(self, path, **_kwargs):
        self.calls.append(path)
        yield {"value": [{"id": "one", "displayName": "One"}, {"id": "bad", "displayName": "Bad"}], "@odata.nextLink": "next"}
        yield {"value": [{"id": "two", "displayName": "Two"}]}


@pytest.mark.anyio
async def test_o01_o02_owned_groups_resolve_sites_with_partial_warnings():
    operations = _load()
    graph = Graph()

    result = await operations.list_owned_sites_with_graph(
        graph, tenant_hosts={"tenant.sharepoint.com"}, max_pages=3, max_sites=5,
        max_metadata_bytes=20_000,
    )

    assert result["status"] == "partial"
    assert [site["group_id"] for site in result["sites"]] == ["one", "two"]
    assert result["warnings"] == [{"group_id": "bad", "category": "remote_unavailable"}]
    assert "raw remote failure" not in repr(result)
    assert result["counts"]["pages"] == 2


@pytest.mark.anyio
async def test_o01_owned_site_enumeration_is_page_site_byte_deadline_and_cancel_bounded():
    operations = _load()
    graph = Graph()
    page = await operations.list_owned_sites_with_graph(graph, tenant_hosts={"tenant.sharepoint.com"}, max_pages=1, max_sites=10, max_metadata_bytes=20_000)
    site = await operations.list_owned_sites_with_graph(graph, tenant_hosts={"tenant.sharepoint.com"}, max_pages=3, max_sites=1, max_metadata_bytes=20_000)
    byte = await operations.list_owned_sites_with_graph(graph, tenant_hosts={"tenant.sharepoint.com"}, max_pages=3, max_sites=10, max_metadata_bytes=20)

    assert page["truncated"] and "page limit reached" in page["truncation_reasons"]
    assert site["truncated"] and "site limit reached" in site["truncation_reasons"]
    assert byte["truncated"] and "metadata byte limit reached" in byte["truncation_reasons"]
    with pytest.raises(operations.SharePointCancelledError):
        await operations.list_owned_sites_with_graph(graph, tenant_hosts={"tenant.sharepoint.com"}, max_pages=1, max_sites=1, max_metadata_bytes=100, cancel_check=lambda: True)
    with pytest.raises(operations.SharePointDeadlineError):
        await operations.list_owned_sites_with_graph(graph, tenant_hosts={"tenant.sharepoint.com"}, max_pages=1, max_sites=1, max_metadata_bytes=100, deadline=0, clock=lambda: 1)


def test_owned_sites_tool_is_declared_without_browser_arguments():
    _load()
    tools = sys.modules["sharepoint_owned_sites_test.tools"]
    assert "sharepoint_list_owned_sites" in tools.SCHEMAS
    props = tools.SCHEMAS["sharepoint_list_owned_sites"]["parameters"]["properties"]
    assert not {"browser_profile", "cdp_url", "session"} & props.keys()
