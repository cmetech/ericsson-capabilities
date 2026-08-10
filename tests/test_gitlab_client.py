from __future__ import annotations

import importlib
import sys
from pathlib import Path

import httpx
import pytest
import respx


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
ORIGIN = "https://gitlab.example.test"
TOKEN = "pat-secret-sentinel"


def _modules():
    assert PLUGIN.is_dir(), "Task 8 GitLab plugin production surface is missing"
    if str(PLUGIN) not in sys.path:
        sys.path.insert(0, str(PLUGIN))
    return (
        importlib.import_module("auth"),
        importlib.import_module("client"),
        importlib.import_module("models"),
    )


class RuntimeConfiguration:
    def __init__(self, *, settings=None, secrets=None):
        self._settings = dict(settings or {})
        self._secrets = dict(secrets or {})

    def setting(self, field_id):
        if field_id not in self._settings:
            raise ValueError("unavailable")
        return self._settings[field_id]

    def secret(self, field_id):
        if field_id not in self._secrets:
            raise ValueError("unavailable")
        return self._secrets[field_id]


def _auth(tmp_path=None, **overrides):
    auth, _client, _models = _modules()
    settings = {
        "origin": ORIGIN,
        "client_certificate_path": "~/.config/edpctl/auth/client.pem",
        "client_key_path": "~/.config/edpctl/auth/client-key.pem",
    }
    settings.update(overrides)
    return auth.GitLabAuth.from_configuration(
        RuntimeConfiguration(settings=settings, secrets={"pat": TOKEN}),
        home=tmp_path,
    )


def test_auth_uses_private_token_json_headers_and_exact_origin(tmp_path):
    # GL-AUTH-01 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    _auth_module, client, _models = _modules()
    gitlab = client.GitLabClient(_auth(tmp_path))
    seen = {}

    def response(request):
        seen["request"] = request
        return httpx.Response(200, json={"ok": True})

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(side_effect=response)
        assert gitlab.get_json("/api/v4/projects/42") == {"ok": True}

    request = seen["request"]
    assert str(request.url) == f"{ORIGIN}/api/v4/projects/42"
    assert request.headers["PRIVATE-TOKEN"] == TOKEN
    assert request.headers["Accept"] == "application/json"
    assert TOKEN not in repr(gitlab)


def test_auth_accepts_complete_edpctl_defaults_and_bounded_overrides(tmp_path):
    # GL-AUTH-02 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    cert = tmp_path / ".config/edpctl/auth/client.pem"
    key = tmp_path / ".config/edpctl/auth/client-key.pem"
    cert.parent.mkdir(parents=True)
    cert.write_text("certificate", encoding="utf-8")
    key.write_text("key", encoding="utf-8")
    assert _auth(tmp_path).certificate_pair == (cert, key)

    override_cert = tmp_path / "override-cert.pem"
    override_key = tmp_path / "override-key.pem"
    override_cert.write_text("certificate", encoding="utf-8")
    override_key.write_text("key", encoding="utf-8")
    configured = _auth(
        tmp_path,
        client_certificate_path=str(override_cert),
        client_key_path=str(override_key),
    )
    assert configured.certificate_pair == (override_cert, override_key)


@pytest.mark.parametrize("missing", ["certificate", "key"])
def test_auth_rejects_partial_or_unusable_mtls_without_disclosing_paths(tmp_path, missing):
    # GL-AUTH-02 legacy: gitlab_file_reader.py:GitLabLinkReader._get_session
    auth, _client, models = _modules()
    cert = tmp_path / "sensitive-cert-name.pem"
    key = tmp_path / "sensitive-key-name.pem"
    if missing != "certificate":
        cert.write_text("certificate", encoding="utf-8")
    if missing != "key":
        key.write_text("key", encoding="utf-8")
    configuration = RuntimeConfiguration(
        settings={
            "origin": ORIGIN,
            "client_certificate_path": str(cert),
            "client_key_path": str(key),
        },
        secrets={"pat": TOKEN},
    )
    with pytest.raises(models.GitLabError) as caught:
        auth.GitLabAuth.from_configuration(configuration, home=tmp_path)
    assert caught.value.category == "invalid_configuration"
    assert "sensitive-" not in str(caught.value)


def test_auth_rejects_explicit_mtls_pair_when_both_files_are_unusable(tmp_path):
    # GL-AUTH-02 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    auth, _client, models = _modules()
    configuration = RuntimeConfiguration(
        settings={
            "origin": ORIGIN,
            "client_certificate_path": str(tmp_path / "missing-cert.pem"),
            "client_key_path": str(tmp_path / "missing-key.pem"),
        },
        secrets={"pat": TOKEN},
    )
    with pytest.raises(models.GitLabError) as caught:
        auth.GitLabAuth.from_configuration(configuration, home=tmp_path)
    assert caught.value.category == "invalid_configuration"
    assert "missing-" not in str(caught.value)


def test_origin_validation_rejects_credentials_paths_and_foreign_urls(tmp_path):
    # GL-ID-01 legacy: gitlab_project_resolver.py:GitLabProjectResolver._parse_gitlab_url
    auth, _client, models = _modules()
    for origin in (
        "ftp://gitlab.example.test",
        "https://user:pass@gitlab.example.test",
        "https://gitlab.example.test/subpath",
        "https://gitlab.example.test?query=yes",
    ):
        configuration = RuntimeConfiguration(
            settings={
                "origin": origin,
                "client_certificate_path": "",
                "client_key_path": "",
            },
            secrets={"pat": TOKEN},
        )
        with pytest.raises(models.GitLabError) as caught:
            auth.GitLabAuth.from_configuration(configuration, home=tmp_path)
        assert caught.value.category == "invalid_configuration"
        assert TOKEN not in str(caught.value)


@pytest.mark.parametrize(
    ("status", "category"),
    [
        (400, "invalid_input"),
        (401, "authentication"),
        (403, "permission"),
        (404, "not_found"),
        (409, "conflict"),
        (429, "rate_limited"),
        (502, "transient"),
    ],
)
def test_client_maps_http_failures_without_raw_body_or_credentials(tmp_path, status, category):
    # GL-AUTH-01 legacy: sibling GitLab component _get_session/_check call sites
    _auth_module, client, models = _modules()
    gitlab = client.GitLabClient(_auth(tmp_path), max_retries=0)
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(status, text=f"remote-body-{TOKEN}")
        )
        with pytest.raises(models.GitLabError) as caught:
            gitlab.get_json("/api/v4/projects/42")
    assert caught.value.category == category
    assert "remote-body" not in str(caught.value)
    assert TOKEN not in str(caught.value)


def test_safe_reads_retry_only_bounded_transient_cases_and_stop_after_success(tmp_path):
    # GL-CI-10 legacy: gitlab_cicd_collector.py:_fetch_pipeline_branches
    _auth_module, client, _models = _modules()
    attempts = 0

    def response(_request):
        nonlocal attempts
        attempts += 1
        if attempts < 3:
            return httpx.Response(503, text="do-not-project")
        return httpx.Response(200, json={"ok": True})

    gitlab = client.GitLabClient(_auth(tmp_path), max_retries=2)
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(side_effect=response)
        assert gitlab.get_json("/api/v4/projects/42") == {"ok": True}
    assert attempts == 3


def test_invalid_requests_and_redirects_are_never_retried(tmp_path):
    # GL-AUTH-03 legacy: ericsson_gitlab/README.md:Requirements
    _auth_module, client, models = _modules()
    for status, headers in (
        (400, {}),
        (302, {"Location": "https://foreign.example.test/steal"}),
    ):
        route_calls = 0

        def response(_request):
            nonlocal route_calls
            route_calls += 1
            return httpx.Response(status, headers=headers, text="unsafe-body")

        gitlab = client.GitLabClient(_auth(tmp_path), max_retries=4)
        with respx.mock:
            respx.get(f"{ORIGIN}/api/v4/projects/42").mock(side_effect=response)
            with pytest.raises(models.GitLabError) as caught:
                gitlab.get_json("/api/v4/projects/42")
        assert route_calls == 1
        assert caught.value.category in {"invalid_input", "invalid_remote_data"}
        assert "foreign.example" not in str(caught.value)


def test_cancellation_is_checked_before_request_and_before_retry(tmp_path):
    # GL-AUTH-01 legacy: gitlab_project_resolver.py:GitLabProjectResolver.resolve_project
    _auth_module, client, models = _modules()
    cancelled = False
    attempts = 0

    def cancel_check():
        return cancelled

    def response(_request):
        nonlocal attempts, cancelled
        attempts += 1
        cancelled = True
        return httpx.Response(503)

    gitlab = client.GitLabClient(
        _auth(tmp_path), cancel_check=cancel_check, max_retries=3
    )
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(side_effect=response)
        with pytest.raises(models.GitLabError) as caught:
            gitlab.get_json("/api/v4/projects/42")
    assert caught.value.category == "cancelled"
    assert attempts == 1

    with pytest.raises(models.GitLabError) as pre_cancelled:
        gitlab.get_json("/api/v4/projects/42")
    assert pre_cancelled.value.category == "cancelled"
    assert attempts == 1


def test_response_body_json_and_total_deadline_are_bounded(tmp_path):
    # GL-READ-03 legacy: gitlab_file_fetcher.py:GitLabFileFetcher._get_file
    _auth_module, client, models = _modules()
    gitlab = client.GitLabClient(
        _auth(tmp_path), max_response_bytes=64, total_timeout_seconds=1.0
    )
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, content=b'{' + b'"x":"' + b'a' * 100 + b'"}')
        )
        with pytest.raises(models.GitLabError) as too_large:
            gitlab.get_json("/api/v4/projects/42")
    assert too_large.value.category == "capacity"

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, content=b"not-json")
        )
        with pytest.raises(models.GitLabError) as malformed:
            gitlab.get_json("/api/v4/projects/42")
    assert malformed.value.category == "invalid_remote_data"
    assert "not-json" not in str(malformed.value)
