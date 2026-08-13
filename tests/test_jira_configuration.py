from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
SCHEMA = REPO / "plugins" / "ericsson-jira" / "config.schema.json"


def _fields() -> dict[str, dict[str, object]]:
    descriptor = json.loads(SCHEMA.read_text(encoding="utf-8"))
    assert descriptor["version"] == 1
    assert "enabled" not in descriptor
    return {field["id"]: field for field in descriptor["fields"]}


def test_configuration_separates_settings_from_write_only_secrets():
    fields = _fields()

    assert fields["base_url"]["storage"] == "setting"
    assert fields["auth_mode"]["storage"] == "setting"
    assert fields["email"]["storage"] == "setting"
    assert fields["pat"]["storage"] == "secret"
    assert fields["api_token"]["storage"] == "secret"
    assert "default" not in fields["pat"]
    assert "default" not in fields["api_token"]
    assert fields["pat"]["visible_when"] == {
        "field": "auth_mode",
        "equals": "bearer",
    }
    assert fields["email"]["visible_when"] == {
        "field": "auth_mode",
        "equals": "basic",
    }
    assert fields["api_token"]["visible_when"] == {
        "field": "auth_mode",
        "equals": "basic",
    }


def test_configuration_declares_only_supported_auth_rest_and_transport_modes():
    fields = _fields()

    assert fields["auth_mode"]["validation"]["enum"] == ["bearer", "basic"]
    assert fields["rest_api_version"]["validation"]["enum"] == ["auto", "3", "2"]
    assert fields["transport"]["validation"]["enum"] == [
        "auto",
        "native",
        "curl",
    ]
    assert fields["curl_executable"]["visible_when"] == {
        "field": "transport",
        "equals": "curl",
    }


def test_configuration_defaults_are_finite_and_bounded():
    fields = _fields()

    timeout = fields["request_timeout_seconds"]
    assert timeout["default"] == 30
    assert timeout["validation"] == {"minimum": 1, "maximum": 120}

    maximum = fields["default_max_results"]
    assert maximum["default"] == 25
    assert maximum["validation"] == {"minimum": 1, "maximum": 100}

    assert fields["base_url"]["validation"]["format"] == "url"
    assert fields["base_url"]["readiness"] is True
    assert fields["pat"]["readiness"] is True
    assert fields["api_token"]["readiness"] is True
    assert fields["curl_executable"]["validation"]["format"] == "path"
