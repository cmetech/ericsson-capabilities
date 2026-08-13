"""W-03 through W-08: approved SharePoint mutation semantics."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import types

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-sharepoint"
WRITE_TOOLS = {
    "sharepoint_upload",
    "sharepoint_create_folder",
    "sharepoint_move_item",
    "sharepoint_copy_item",
    "sharepoint_recycle_item",
}


def _load(name="sharepoint_writes_test"):
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            sys.modules.pop(key)
    spec = importlib.util.spec_from_file_location(
        name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)]
    )
    package = importlib.util.module_from_spec(spec)
    sys.modules[name] = package
    spec.loader.exec_module(package)
    return package, sys.modules[name + ".operations"], sys.modules[name + ".models"]


class Graph:
    def __init__(self):
        self.calls = []
        self.controls = []
        self.monitor_validators = []

    async def post_json(
        self,
        path,
        *,
        json_body=None,
        headers=None,
        retry_ambiguous=True,
        deadline=None,
        cancel_check=None,
    ):
        self.controls.append((deadline, cancel_check))
        self.calls.append(("post", path, json_body, headers, retry_ambiguous))
        return {"id": "created", "name": json_body.get("name", "")}

    async def patch_json(
        self,
        path,
        *,
        json_body=None,
        headers=None,
        retry_ambiguous=True,
        deadline=None,
        cancel_check=None,
    ):
        self.controls.append((deadline, cancel_check))
        self.calls.append(("patch", path, json_body, headers, retry_ambiguous))
        return {"id": "source", "name": json_body.get("name", "Moved")}

    async def delete(
        self,
        path,
        *,
        headers=None,
        retry_ambiguous=True,
        deadline=None,
        cancel_check=None,
    ):
        self.controls.append((deadline, cancel_check))
        self.calls.append(("delete", path, headers, retry_ambiguous))
        return {"deleted": True, "status_code": 204}

    async def start_async_operation(
        self,
        path,
        *,
        json_body,
        max_polls,
        deadline=None,
        cancel_check=None,
        monitor_url_validator=None,
    ):
        self.monitor_validators.append(monitor_url_validator)
        self.controls.append((deadline, cancel_check))
        self.calls.append(("async", path, json_body, max_polls, deadline, cancel_check))
        return {"status": "completed"}


class Client:
    def __init__(self, graph=None, *, destination_drive="drive"):
        self.graph = graph or Graph()
        self.destination_drive = destination_drive
        self.controls = []

    async def get_item(
        self,
        *,
        url=None,
        drive_id=None,
        item_id=None,
        deadline=None,
        cancel_check=None,
    ):
        self.controls.append((deadline, cancel_check))
        if url and "Destination" in url:
            drive_id, item_id = self.destination_drive, "dest"
        else:
            drive_id, item_id = drive_id or "drive", item_id or "source"
        return {
            "tenant_host": "tenant.sharepoint.com",
            "site": {"id": "site", "name": "", "web_url": ""},
            "drive": {"id": drive_id, "name": "Documents"},
            "item": {
                "id": item_id,
                "name": "Source.docx",
                "path": "",
                "kind": "folder" if item_id == "dest" else "file",
                "size": 10,
                "web_url": "",
                "parent_id": "",
                "mime_type": "",
            },
        }


@pytest.mark.anyio
async def test_w04_create_folder_conflict_policy_and_optimistic_header():
    _, operations, _ = _load()
    graph = Graph()
    client = Client(graph)
    cancel_check = lambda: False
    result = await operations.create_folder_with_client(
        client,
        parent_url="https://tenant.sharepoint.com/Destination",
        name="New Folder",
        exist_ok=True,
        etag='"etag"',
        deadline=99.0,
        cancel_check=cancel_check,
    )
    assert result == {"id": "created", "name": "New Folder", "kind": "folder"}
    assert graph.calls == [
        (
            "post",
            "/drives/drive/items/dest/children",
            {
                "name": "New Folder",
                "folder": {},
                "@microsoft.graph.conflictBehavior": "replace",
            },
            {"If-Match": '"etag"'},
            False,
        )
    ]
    assert client.controls == [(99.0, cancel_check)]
    assert graph.controls == [(99.0, cancel_check)]


@pytest.mark.anyio
async def test_w05_move_requires_same_tenant_and_validates_cross_drive_parent():
    _, operations, models = _load()
    graph = Graph()
    client = Client(graph, destination_drive="other-drive")
    cancel_check = lambda: False
    result = await operations.move_item_with_client(
        client,
        source_url="https://tenant.sharepoint.com/Source.docx",
        destination_url="https://tenant.sharepoint.com/Destination",
        name="Renamed.docx",
        etag='"etag"',
        deadline=99.0,
        cancel_check=cancel_check,
    )
    assert result["id"] == "source"
    assert graph.calls[0] == (
        "patch",
        "/drives/drive/items/source",
        {
            "name": "Renamed.docx",
            "parentReference": {"driveId": "other-drive", "id": "dest"},
        },
        {"If-Match": '"etag"'},
        False,
    )
    assert client.controls == [(99.0, cancel_check), (99.0, cancel_check)]
    assert graph.controls == [(99.0, cancel_check)]
    bad = Client()

    async def foreign(**kwargs):
        value = await Client.get_item(bad, **kwargs)
        if kwargs.get("url") and "Destination" in kwargs["url"]:
            value["tenant_host"] = "other.sharepoint.com"
        return value

    bad.get_item = foreign
    with pytest.raises(models.SharePointWriteError, match="tenant"):
        await operations.move_item_with_client(
            bad,
            source_url="https://tenant.sharepoint.com/Source",
            destination_url="https://other.sharepoint.com/Destination",
        )


@pytest.mark.anyio
async def test_w06_copy_polls_async_completion_once_without_duplicate_create():
    _, operations, models = _load()
    graph = Graph()
    client = Client(graph, destination_drive="other")
    cancel_check = lambda: False
    result = await operations.copy_item_with_client(
        client,
        source_url="https://tenant.sharepoint.com/Source",
        destination_url="https://tenant.sharepoint.com/Destination",
        name="Copy.docx",
        max_polls=8,
        deadline=99,
        cancel_check=cancel_check,
    )
    assert result == {"status": "completed"}
    assert len(graph.calls) == 1
    assert graph.calls[0][:4] == (
        "async",
        "/drives/drive/items/source/copy",
        {"parentReference": {"driveId": "other", "id": "dest"}, "name": "Copy.docx"},
        8,
    )
    assert client.controls == [(99, cancel_check), (99, cancel_check)]
    assert graph.controls == [(99, cancel_check)]
    validator = graph.monitor_validators[0]
    validator(
        "https://tenant.sharepoint.com/sites/Governance/"
        "_api/v2.1/monitor/4A7547A801E905B3E06BD113D18C4D48"
    )
    validator(
        "https://tenant.sharepoint.com/_api/v2.0/monitor/"
        "4A7547A801E905B3E06BD113D18C4D48?token=opaque"
    )
    for unsafe in (
        "https://other.sharepoint.com/_api/v2.0/monitor/copy-1",
        "https://tenant.sharepoint.com/download/copy-1",
        "https://tenant.sharepoint.com/_api/v2.0/monitor/copy-1#fragment",
        "https://user@tenant.sharepoint.com/_api/v2.0/monitor/copy-1",
    ):
        with pytest.raises(models.SharePointWriteError, match="monitor"):
            validator(unsafe)


@pytest.mark.anyio
async def test_w07_recycle_uses_driveitem_delete_not_permanent_delete():
    _, operations, _ = _load()
    graph = Graph()
    client = Client(graph)
    cancel_check = lambda: False
    result = await operations.recycle_item_with_client(
        client,
        url="https://tenant.sharepoint.com/Source",
        etag='"etag"',
        deadline=99.0,
        cancel_check=cancel_check,
    )
    assert result == {"recycled": True, "item_id": "source", "drive_id": "drive"}
    assert graph.calls == [
        ("delete", "/drives/drive/items/source", {"If-Match": '"etag"'}, False)
    ]
    assert client.controls == [(99.0, cancel_check)]
    assert graph.controls == [(99.0, cancel_check)]
    assert "permanent" not in repr(result).lower()


def test_w08_all_writes_require_exact_backend_admission_and_reject_argument_claims():
    package, _, _ = _load("sharepoint_write_admission_test")

    class Context:
        def __init__(self):
            self.tools = []
            self.hooks = []

        def register_setup_action(self, *_a, **_k):
            pass

        def register_hook(self, name, handler):
            self.hooks.append((name, handler))

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

        def configuration(self):
            return {}

    ctx = Context()
    package.register(ctx)
    by_name = {tool["name"]: tool for tool in ctx.tools}
    assert WRITE_TOOLS <= by_name.keys()
    hook = ctx.hooks[0][1]
    for name in WRITE_TOOLS:
        assert hook(name, {})["action"] == "approve"
        denied = json.loads(
            __import__("asyncio").run(by_name[name]["handler"]({"approved": True}))
        )
        assert denied["error"]["category"] == "approval_required"
        wrong = types.SimpleNamespace(
            approved=True, policy="plugin_approve", tool_name="other"
        )
        denied = json.loads(
            __import__("asyncio").run(
                by_name[name]["handler"]({}, tool_admission=wrong)
            )
        )
        assert denied["error"]["category"] == "approval_required"


def test_write_approval_binds_cache_identity_and_prompt_to_exact_target():
    package, _, _ = _load("sharepoint_write_approval_binding_test")

    class Context:
        def __init__(self):
            self.hook = None

        def register_setup_action(self, *_args, **_kwargs):
            pass

        def register_hook(self, name, handler):
            assert name == "pre_tool_call"
            self.hook = handler

        def register_tool(self, **_kwargs):
            pass

        def configuration(self):
            return {}

    context = Context()
    package.register(context)

    first_args = {"url": "https://tenant.sharepoint.com/Documents/First.docx"}
    reordered_first_args = dict(reversed(list(first_args.items())))
    second_args = {"url": "https://tenant.sharepoint.com/Documents/Second.docx"}
    first = context.hook("sharepoint_recycle_item", first_args)
    same = context.hook("sharepoint_recycle_item", reordered_first_args)
    second = context.hook("sharepoint_recycle_item", second_args)

    assert first["action"] == same["action"] == second["action"] == "approve"
    assert first["rule_key"].startswith("sharepoint_recycle_item:")
    assert first["rule_key"] == same["rule_key"]
    assert first["rule_key"] != second["rule_key"]
    assert first_args["url"] in first["message"]
    assert second_args["url"] in second["message"]


def test_write_schemas_have_no_permanent_delete_or_approval_claims():
    _load()
    tools = sys.modules["sharepoint_writes_test.tools"]
    assert WRITE_TOOLS <= tools.SCHEMAS.keys()
    for name in WRITE_TOOLS:
        props = tools.SCHEMAS[name]["parameters"]["properties"]
        assert not {"approved", "approval", "permanent", "hard_delete"} & props.keys()


def test_ambiguous_write_result_requires_reconciliation_before_retry(monkeypatch):
    package, _, models = _load("sharepoint_ambiguous_write_test")

    class Context:
        def __init__(self):
            self.tools = []

        def register_setup_action(self, *_args, **_kwargs):
            pass

        def register_hook(self, *_args, **_kwargs):
            pass

        def register_tool(self, **kwargs):
            self.tools.append(kwargs)

        def configuration(self):
            return {}

    async def ambiguous(*_args, **_kwargs):
        raise models.SharePointAmbiguousWriteError("private remote detail")

    monkeypatch.setattr(package.tools, "invoke", ambiguous)
    context = Context()
    package.register(context)
    handler = next(
        tool["handler"]
        for tool in context.tools
        if tool["name"] == "sharepoint_upload"
    )
    admission = types.SimpleNamespace(
        approved=True,
        policy="plugin_approve",
        tool_name="sharepoint_upload",
    )

    result = json.loads(
        __import__("asyncio").run(handler({}, tool_admission=admission))
    )

    assert result["error"]["category"] == "ambiguous_write"
    assert "inspect" in result["error"]["message"].lower()
    assert "retry" in result["error"]["message"].lower()
    assert "private remote detail" not in repr(result)


@pytest.mark.anyio
async def test_generic_graph_ambiguity_is_translated_to_connector_error(monkeypatch):
    _, operations, models = _load("sharepoint_ambiguity_translation_test")

    class GenericAmbiguousWriteError(RuntimeError):
        pass

    async def ambiguous(*_args, **_kwargs):
        raise GenericAmbiguousWriteError("private graph detail")

    tools_package = types.ModuleType("tools")
    graph_module = types.ModuleType("tools.microsoft_graph_client")
    graph_module.MicrosoftGraphAmbiguousWriteError = GenericAmbiguousWriteError
    monkeypatch.setitem(sys.modules, "tools", tools_package)
    monkeypatch.setitem(sys.modules, "tools.microsoft_graph_client", graph_module)
    monkeypatch.setattr(operations, "_write_operation", ambiguous)

    with pytest.raises(models.SharePointAmbiguousWriteError) as caught:
        await operations.write_operation("sharepoint_upload", {}, {})

    assert "private graph detail" not in str(caught.value)
