"""SharePoint auth actions consume generic Graph and browser authority."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import threading
import types

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-sharepoint"


def _load_package():
    name = "ericsson_sharepoint_test"
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
    return module, sys.modules[f"{name}.auth"]


class _Run:
    def __init__(self, configuration):
        self.configuration = configuration
        self._cancel = threading.Event()

    @property
    def cancelled(self):
        return self._cancel.is_set()


def _configuration(tmp_path, **overrides):
    values = {
        "tenant_host": "tenant.sharepoint.com",
        "auth_mode": "delegated_msal",
        "tenant_id": "tenant-id",
        "client_id": "client-id",
        "client_secret": "app-secret-must-not-leak",
        "scopes": "Sites.Read.All User.Read",
        "browser_profile": "corp-sharepoint",
        "profile_home": str(tmp_path),
    }
    values.update(overrides)
    return values


class _GraphIdentityConfig:
    def __init__(self, **kwargs):
        self.values = kwargs


def test_identity_config_is_delegated_to_generic_graph_without_secret_projection(tmp_path):
    _, auth = _load_package()
    captured = {}

    class GraphIdentityConfig:
        def __init__(self, **kwargs):
            captured.update(kwargs)

    config = auth.build_identity_config(
        auth.SharePointConfiguration.from_mapping(
            _configuration(tmp_path), profile_home=tmp_path
        ),
        identity_config_type=GraphIdentityConfig,
    )

    assert isinstance(config, GraphIdentityConfig)
    assert captured["mode"] == "delegated_msal"
    assert captured["cache_path"].name == "msal-cache.json"
    assert captured["scopes"] == ("Sites.Read.All", "User.Read")
    assert "app-secret-must-not-leak" not in repr(auth.identity_status(
        auth.SharePointConfiguration.from_mapping(_configuration(tmp_path), profile_home=tmp_path),
        readiness_probe=lambda _config: types.SimpleNamespace(
            status="ready", mode="delegated_msal", missing_fields=()
        ),
        delegated_cache_has_account=True,
        browser_enrolled=False,
        identity_config_type=_GraphIdentityConfig,
    ))


def test_readiness_keeps_graph_ready_when_audit_browser_needs_enrollment(tmp_path):
    _, auth = _load_package()
    config = auth.SharePointConfiguration.from_mapping(
        _configuration(tmp_path), profile_home=tmp_path
    )

    status = auth.identity_status(
        config,
        readiness_probe=lambda _config, **_kw: types.SimpleNamespace(
            status="ready", mode="delegated_msal", missing_fields=()
        ),
        delegated_cache_has_account=True,
        browser_enrolled=False,
        identity_config_type=_GraphIdentityConfig,
    )

    assert status == {
        "graph": {"status": "ready", "mode": "delegated_msal", "missing_fields": []},
        "audit": {"status": "browser_enrollment_required", "browser_profile": "corp-sharepoint"},
        "delegated_cache": "configured",
    }


def test_graph_readiness_accepts_explicit_azure_cli_identity(tmp_path):
    _, auth = _load_package()
    seen = []

    def readiness_probe(_config, **facts):
        seen.append(facts)
        return types.SimpleNamespace(
            status=(
                "ready"
                if facts["azure_cli_authenticated"]
                else "authentication_required"
            ),
            mode="azure_cli",
            missing_fields=(),
        )

    assert auth.graph_ready(
        _configuration(
            tmp_path,
            auth_mode="azure_cli",
            tenant_id="",
            client_id="",
            client_secret="",
            scopes="https://graph.microsoft.com/.default",
        ),
        readiness_probe=readiness_probe,
        identity_config_type=_GraphIdentityConfig,
    )
    assert seen == [
        {
            "delegated_cache_has_account": False,
            "azure_cli_authenticated": True,
        }
    ]


def test_authenticate_is_explicit_interactive_and_never_returns_a_token(tmp_path):
    _, auth = _load_package()
    calls = []

    class Provider:
        async def authenticate_interactively(self):
            calls.append("interactive")
            return {
                "authenticated": True,
                "account": "user@example.com",
                "access_token": "must-not-return",
            }

    result = auth.authenticate(
        _Run(_configuration(tmp_path)),
        provider_factory=lambda _config, *, interactive_allowed: (
            calls.append(interactive_allowed) or Provider()
        ),
        identity_config_type=_GraphIdentityConfig,
    )

    assert calls == [True, "interactive"]
    assert result == {"authenticated": True, "account": "user@example.com"}
    assert "must-not-return" not in json.dumps(result)


def test_test_connection_is_silent_and_returns_no_token_or_remote_body(tmp_path):
    _, auth = _load_package()
    calls = []

    class Provider:
        async def get_access_token(self, *, force_refresh=False):
            calls.append(("token", force_refresh))
            return "connection-token-must-not-return"

    class Client:
        async def get_json(self, path, **_kwargs):
            calls.append(("get", path))
            return {"id": "tenant.sharepoint.com,secret-remote-id", "body": "private"}

    result = auth.test_connection(
        _Run(_configuration(tmp_path)),
        provider_factory=lambda _config, *, interactive_allowed: (
            calls.append(("interactive_allowed", interactive_allowed)) or Provider()
        ),
        client_factory=lambda provider, **_kwargs: Client(),
        identity_config_type=_GraphIdentityConfig,
    )

    assert calls[0] == ("interactive_allowed", False)
    assert calls[1] == ("get", "/sites/tenant.sharepoint.com")
    assert result == {"connected": True, "tenant_host": "tenant.sharepoint.com"}
    assert "connection-token" not in json.dumps(result)
    assert "private" not in json.dumps(result)


def test_browser_actions_use_core_profile_registry_and_manager_authority(tmp_path):
    _, auth = _load_package()
    events = []

    profile = types.SimpleNamespace(
        name="corp-sharepoint",
        is_enrolled=True,
        trusted_origins=("https://tenant.sharepoint.com",),
    )

    class Session:
        def __init__(self):
            self.profile = profile

        def signin(self, url, probe_js, **kwargs):
            events.append(("signin", url, probe_js, kwargs))
            return True

        def release(self):
            events.append(("release", self.profile.name))

    profiles = types.SimpleNamespace(
        get_profile=lambda name: profile if name == profile.name else None,
        is_origin_trusted=lambda candidate, url: candidate is profile and url.startswith(
            "https://tenant.sharepoint.com"
        ),
    )
    registry = types.SimpleNamespace(
        profile_for=lambda key: profile.name if key == "ericsson-sharepoint::corp-sharepoint" else None,
    )
    manager = types.SimpleNamespace(
        acquire=lambda **kwargs: (events.append(("acquire", kwargs)) or Session())
    )

    enrolled = auth.enroll_browser(
        _Run(_configuration(tmp_path)),
        browser_profiles=profiles,
        browser_registry=registry,
        browser_manager=manager,
    )
    cleared = auth.clear_session(
        _Run(_configuration(tmp_path)), browser_registry=registry
    )

    assert enrolled == {"enrolled": True, "browser_profile": "corp-sharepoint"}
    assert events[0] == (
        "acquire",
        {
            "profile": "corp-sharepoint",
            "headless": False,
            "session_key": "ericsson-sharepoint::corp-sharepoint",
            "attach_global": False,
        },
    )
    assert events[1][0:2] == ("signin", "https://tenant.sharepoint.com")
    assert cleared == {"cleared": True, "browser_profile": "corp-sharepoint"}
    assert events[-1] == ("release", "corp-sharepoint")


def test_clear_session_refuses_foreign_profile_binding(tmp_path):
    _, auth = _load_package()
    registry = types.SimpleNamespace(profile_for=lambda _key: "other-profile")

    result = auth.clear_session(
        _Run(_configuration(tmp_path)), browser_registry=registry
    )

    assert result == {"cleared": False, "reason": "session_not_owned"}
