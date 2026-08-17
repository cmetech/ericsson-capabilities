"""Configuration must resolve to one validated bearer identity and API base."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-confluence"
sys.path.insert(0, str(PLUGIN))

from auth import authentication_from_configuration, derive_api_base  # noqa: E402
from models import ConfluenceError  # noqa: E402


class FakeConfig:
    def __init__(self, settings, secrets):
        self._settings = settings
        self._secrets = secrets

    def setting(self, field_id):
        if field_id not in self._settings:
            raise KeyError(field_id)
        return self._settings[field_id]

    def secret(self, field_id):
        if field_id not in self._secrets:
            raise KeyError(field_id)
        return self._secrets[field_id]


def _config(**overrides):
    settings = {"base_url": "https://wiki.test"}
    settings.update(overrides.pop("settings", {}))
    secrets = {"pat": "token-value"}
    secrets.update(overrides.pop("secrets", {}))
    return FakeConfig(settings, secrets)


class TestDeriveApiBase:
    def test_data_center_base(self):
        assert derive_api_base("https://wiki.test") == "https://wiki.test/rest/api"

    def test_cloud_base_when_path_contains_wiki(self):
        """Confluence Cloud serves the REST API under /wiki. super-cli is
        Data-Center-only and would 404 here."""
        assert derive_api_base("https://x.atlassian.net/wiki") == (
            "https://x.atlassian.net/wiki/rest/api"
        )

    def test_cloud_base_with_trailing_segments(self):
        assert derive_api_base("https://x.atlassian.net/wiki/spaces/OPS") == (
            "https://x.atlassian.net/wiki/rest/api"
        )

    def test_override_wins(self):
        assert derive_api_base(
            "https://wiki.test", "https://wiki.test/custom/api/"
        ) == "https://wiki.test/custom/api"


class TestAuthentication:
    def test_builds_a_bearer_header(self):
        auth = authentication_from_configuration(_config())
        assert auth.authorization == "Bearer token-value"
        assert auth.origin == "https://wiki.test"
        assert auth.api_base == "https://wiki.test/rest/api"

    def test_cloud_url_yields_a_cloud_api_base(self):
        auth = authentication_from_configuration(
            _config(settings={"base_url": "https://x.atlassian.net/wiki"})
        )
        assert auth.api_base == "https://x.atlassian.net/wiki/rest/api"

    def test_scheme_is_added_when_missing(self):
        auth = authentication_from_configuration(
            _config(settings={"base_url": "wiki.test"})
        )
        assert auth.origin == "https://wiki.test"

    @pytest.mark.parametrize(
        "bad",
        [
            "https://user:pw@wiki.test",
            "https://wiki.test?q=1",
            "https://wiki.test#frag",
            "ftp://wiki.test",
            "https://wiki .test",
            "https://wiki.test\\evil",
        ],
    )
    def test_hostile_base_urls_are_rejected(self, bad):
        with pytest.raises(ConfluenceError) as excinfo:
            authentication_from_configuration(_config(settings={"base_url": bad}))
        assert excinfo.value.category == "invalid_configuration"

    def test_a_wiki_path_is_allowed_because_cloud_needs_it(self):
        """Unlike the Jira connector, a path segment is legitimate here."""
        auth = authentication_from_configuration(
            _config(settings={"base_url": "https://x.atlassian.net/wiki"})
        )
        assert auth.origin == "https://x.atlassian.net/wiki"

    def test_missing_token_is_rejected(self):
        with pytest.raises(ConfluenceError):
            authentication_from_configuration(_config(secrets={"pat": ""}))

    def test_bool_is_not_accepted_as_an_integer(self):
        with pytest.raises(ConfluenceError):
            authentication_from_configuration(
                _config(settings={"default_max_results": True})
            )

    def test_defaults_apply_when_settings_absent(self):
        auth = authentication_from_configuration(_config())
        assert auth.request_timeout_seconds == 30
        assert auth.default_max_results == 25
