"""B-01 through B-05 and B-15: core browser authority and readiness."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys
import types

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-sharepoint"


def _load():
    name = "sharepoint_browser_test"
    for key in list(sys.modules):
        if key == name or key.startswith(name + "."):
            sys.modules.pop(key)
    spec = importlib.util.spec_from_file_location(name, PLUGIN / "__init__.py", submodule_search_locations=[str(PLUGIN)])
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module, sys.modules[name + ".operations"], sys.modules[name + ".models"]


def _config(models, tmp_path):
    return models.SharePointConfiguration.from_mapping({
        "tenant_host": "tenant.sharepoint.com", "auth_mode": "azure_cli",
        "scopes": "https://graph.microsoft.com/.default", "browser_profile": "corp"
    }, profile_home=tmp_path)


@pytest.mark.anyio
async def test_b01_b05_operation_uses_named_core_session_and_releases_without_killing(tmp_path):
    _, operations, models = _load()
    config = _config(models, tmp_path)
    events = []
    profile = types.SimpleNamespace(name="corp", is_enrolled=True)

    class Session:
        def __init__(self): self.profile = profile
        def release(self): events.append("release")

    profiles = types.SimpleNamespace(
        get_profile=lambda name: profile if name == "corp" else None,
        is_origin_trusted=lambda candidate, url: candidate is profile and url == "https://tenant.sharepoint.com",
    )
    manager = types.SimpleNamespace(acquire=lambda **kwargs: (events.append(kwargs) or Session()))

    async def runner(session, **kwargs):
        assert isinstance(session, Session)
        return {"status": "complete", "sites": [], "warnings": [], "truncated": False, "truncation_reasons": []}

    result = await operations.audit_permissions_with_browser(
        config, sites=[], selected=(), browser_profiles=profiles,
        browser_manager=manager, audit_runner=runner,
    )

    assert result["status"] == "complete"
    assert events[0] == {"profile": "corp", "headless": True, "session_key": "ericsson-sharepoint::corp::audit", "attach_global": False}
    assert events[1] == "release"
    assert not hasattr(manager, "close")


@pytest.mark.anyio
async def test_b01_browser_profile_must_be_enrolled_and_origin_trusted(tmp_path):
    _, operations, models = _load()
    config = _config(models, tmp_path)
    profile = types.SimpleNamespace(name="corp", is_enrolled=True)
    manager = types.SimpleNamespace(acquire=lambda **_kwargs: pytest.fail("must not acquire"))
    profiles = types.SimpleNamespace(get_profile=lambda _name: profile, is_origin_trusted=lambda *_args: False)
    with pytest.raises(models.SharePointAuditError, match="trusted"):
        await operations.audit_permissions_with_browser(config, sites=[], selected=(), browser_profiles=profiles, browser_manager=manager)


def test_b15_audit_readiness_is_independent_from_graph_tools(tmp_path):
    package, _, models = _load()
    tools = sys.modules["sharepoint_browser_test.tools"]

    class Context:
        def __init__(self):
            self.tools = []
            self.actions = []
            self.hooks = []
        def configuration(self): return {"invalid": True}
        def register_setup_action(self, *args, **kwargs): self.actions.append((args, kwargs))
        def register_hook(self, name, handler): self.hooks.append((name, handler))
        def register_tool(self, **kwargs): self.tools.append(kwargs)

    ctx = Context()
    package.register(ctx)
    by_name = {item["name"]: item for item in ctx.tools}
    assert "sharepoint_audit_permissions" in by_name
    assert "sharepoint_list_owned_sites" in by_name
    assert by_name["sharepoint_audit_permissions"]["check_fn"] is not by_name["sharepoint_list_owned_sites"]["check_fn"]
    assert {"sharepoint_audit_permissions", "sharepoint_list_owned_sites"} <= tools.SCHEMAS.keys()
