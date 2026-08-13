from __future__ import annotations

import base64
import sys
from pathlib import Path

import pytest


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
sys.path.insert(0, str(PLUGIN))

from auth import authentication_from_configuration  # noqa: E402
from models import JiraError  # noqa: E402


class Configuration:
    def __init__(self, *, settings=None, secrets=None):
        self.settings = {
            "base_url": "jira.example.test/",
            "auth_mode": "bearer",
            "rest_api_version": "auto",
            "transport": "auto",
            "curl_executable": "/usr/bin/curl",
            "request_timeout_seconds": 30,
            "default_max_results": 25,
            **(settings or {}),
        }
        self.secrets = {"pat": "bearer-secret", "api_token": "", **(secrets or {})}

    def setting(self, field_id):
        return self.settings[field_id]

    def secret(self, field_id):
        return self.secrets[field_id]


def test_bearer_auth_normalizes_origin_and_redacts_secret():
    auth = authentication_from_configuration(Configuration())

    assert auth.origin == "https://jira.example.test"
    assert auth.headers == {"Authorization": "Bearer bearer-secret"}
    assert auth.rest_api_version == "auto"
    assert auth.transport == "auto"
    assert auth.request_timeout_seconds == 30
    assert auth.default_max_results == 25
    assert "bearer-secret" not in repr(auth)
    assert "<redacted>" in repr(auth)


def test_basic_auth_requires_email_and_api_token_and_redacts_both():
    configuration = Configuration(
        settings={"auth_mode": "basic", "email": "person@example.test"},
        secrets={"pat": "", "api_token": "basic-secret"},
    )

    auth = authentication_from_configuration(configuration)

    expected = base64.b64encode(b"person@example.test:basic-secret").decode("ascii")
    assert auth.headers == {"Authorization": f"Basic {expected}"}
    assert "person@example.test" not in repr(auth)
    assert "basic-secret" not in repr(auth)


@pytest.mark.parametrize(
    ("settings", "secrets"),
    [
        ({"auth_mode": "bearer"}, {"pat": ""}),
        ({"auth_mode": "bearer"}, {"api_token": "also-set"}),
        ({"auth_mode": "basic", "email": ""}, {"pat": "", "api_token": "x"}),
        ({"auth_mode": "basic", "email": "a@b.test"}, {"pat": "also-set", "api_token": "x"}),
        ({"auth_mode": "basic", "email": "a@b.test"}, {"pat": "", "api_token": ""}),
        ({"auth_mode": "unknown"}, {}),
        ({"transport": "ssh"}, {}),
        ({"rest_api_version": "4"}, {}),
        ({"request_timeout_seconds": 0}, {}),
        ({"request_timeout_seconds": 121}, {}),
        ({"default_max_results": 0}, {}),
        ({"default_max_results": 101}, {}),
        ({"transport": "curl", "curl_executable": "curl"}, {}),
    ],
)
def test_missing_ambiguous_or_out_of_contract_configuration_is_rejected(
    settings, secrets
):
    with pytest.raises(JiraError) as caught:
        authentication_from_configuration(
            Configuration(settings=settings, secrets=secrets)
        )

    assert caught.value.category == "invalid_configuration"
    assert "bearer-secret" not in str(caught.value)
    assert "basic-secret" not in str(caught.value)


@pytest.mark.parametrize(
    "base_url",
    [
        "ftp://jira.example.test",
        "https://user:password@jira.example.test",
        "https://jira.example.test/rest/api/3",
        "https://jira.example.test?token=x",
        "https://jira.example.test/#fragment",
        "https://jira.example.test\\evil",
        "",
    ],
)
def test_base_url_is_one_http_origin_without_credentials_or_api_path(base_url):
    with pytest.raises(JiraError, match="configuration"):
        authentication_from_configuration(Configuration(settings={"base_url": base_url}))


def test_configuration_lookup_failure_is_safe_and_does_not_echo_exception():
    class BrokenConfiguration:
        def setting(self, field_id):
            raise RuntimeError("filesystem secret sentinel")

        def secret(self, field_id):
            raise RuntimeError("credential secret sentinel")

    with pytest.raises(JiraError) as caught:
        authentication_from_configuration(BrokenConfiguration())

    assert caught.value.category == "invalid_configuration"
    assert "sentinel" not in str(caught.value)
