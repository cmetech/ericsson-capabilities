"""Static SharePoint connector configuration contract."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-sharepoint"


def _load_models():
    path = PLUGIN / "models.py"
    spec = importlib.util.spec_from_file_location("sharepoint_models", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_descriptor_declares_standalone_disabled_connector_and_safe_actions():
    manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))
    descriptor = json.loads((PLUGIN / "config.schema.json").read_text(encoding="utf-8"))
    capability_set = json.loads((REPO / "sets" / "ericsson.json").read_text())

    assert manifest["name"] == "ericsson-sharepoint"
    assert manifest["kind"] == "standalone"
    assert manifest["config_schema"] == "config.schema.json"
    assert "ericsson-sharepoint" in capability_set["disabledByDefault"]["toolsets"]

    fields = {field["id"]: field for field in descriptor["fields"]}
    assert {
        "tenant_host", "auth_mode", "tenant_id", "client_id", "client_secret",
        "scopes", "authority_url", "account_id", "azure_cli_enabled",
        "max_pages", "max_items", "max_bytes", "timeout_seconds",
        "download_root", "upload_root", "browser_profile",
    } <= fields.keys()
    assert fields["client_secret"]["storage"] == "secret"
    assert "default" not in fields["client_secret"]
    assert fields["browser_profile"]["storage"] == "setting"
    assert not {"cdp_port", "browser_user_data_dir", "token_cache_path"} & fields.keys()

    actions = {action["id"]: action for action in descriptor["setup_actions"]}
    assert set(actions) == {
        "authenticate", "test_connection", "enroll_browser", "clear_session"
    }
    assert actions["authenticate"]["interactive"] is True
    assert actions["enroll_browser"]["interactive"] is True
    assert actions["test_connection"].get("interactive", False) is False
    assert actions["clear_session"].get("interactive", False) is False


def test_configuration_normalizes_identity_limits_roots_and_private_cache(tmp_path):
    models = _load_models()
    config = models.SharePointConfiguration.from_mapping(
        {
            "tenant_host": " Tenant.SharePoint.com ",
            "auth_mode": "delegated_msal",
            "tenant_id": " tenant-id ",
            "client_id": " client-id ",
            "client_secret": " do-not-echo ",
            "scopes": "Sites.Read.All, User.Read Group.Read.All",
            "authority_url": "https://login.microsoftonline.com/",
            "account_id": " user@example.com ",
            "max_pages": 7,
            "max_items": 40,
            "max_bytes": 4096,
            "timeout_seconds": 9,
            "download_root": "artifacts/downloads",
            "upload_root": "artifacts/uploads",
            "browser_profile": " corp-sharepoint ",
        },
        profile_home=tmp_path,
    )

    assert config.tenant_host == "tenant.sharepoint.com"
    assert config.tenant_origin == "https://tenant.sharepoint.com"
    assert config.scopes == ("Sites.Read.All", "User.Read", "Group.Read.All")
    assert config.authority_url == "https://login.microsoftonline.com"
    assert config.browser_profile == "corp-sharepoint"
    assert config.cache_path == tmp_path / "auth" / "ericsson-sharepoint" / "msal-cache.json"
    assert config.download_root == tmp_path / "artifacts" / "downloads"
    assert config.upload_root == tmp_path / "artifacts" / "uploads"
    assert config.public_status()["delegated_cache"] == "not_configured"
    assert "do-not-echo" not in repr(config.public_status())
    assert str(tmp_path) not in repr(config.public_status())


@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_host": "https://tenant.sharepoint.com/path"},
        {"tenant_host": "user@tenant.sharepoint.com"},
        {"tenant_host": "tenant.example.com"},
        {"browser_profile": ""},
        {"max_pages": 0},
        {"max_items": 100_001},
        {"max_bytes": 2**41},
    ],
)
def test_configuration_rejects_unsafe_or_unbounded_values(tmp_path, overrides):
    models = _load_models()
    values = {
        "tenant_host": "tenant.sharepoint.com",
        "auth_mode": "azure_cli",
        "scopes": "https://graph.microsoft.com/.default",
        "browser_profile": "corp-sharepoint",
    }
    values.update(overrides)

    with pytest.raises(models.SharePointConfigurationError):
        models.SharePointConfiguration.from_mapping(values, profile_home=tmp_path)
