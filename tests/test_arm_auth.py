"""Configuration must resolve to one validated identity, header and TLS context."""

import ssl
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from auth import (  # noqa: E402
    API_ROOT,
    authentication_from_configuration,
    certificate_not_after,
)
from models import ArmError  # noqa: E402


def _write_certificate(directory: Path, *, days: int) -> tuple[Path, Path]:
    """Generate a throwaway self-signed cert/key pair with openssl.

    Real files rather than fixtures: the code under test reads a PEM from
    disk and builds a real SSLContext, and a fake would test neither.
    """
    cert = directory / "client.pem"
    key = directory / "client-key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert),
            "-days", str(days), "-subj", "/CN=test-endpoint",
        ],
        check=True, capture_output=True,
    )
    return cert, key


@pytest.fixture
def certificate(tmp_path):
    return _write_certificate(tmp_path, days=30)


@pytest.fixture
def expired_certificate(tmp_path):
    """Expiry is tested by moving the clock, not by minting a past-dated
    certificate: openssl cannot backdate notAfter portably, and
    authentication_from_configuration takes `now` precisely so the
    expiry branch is reachable without one."""
    return _write_certificate(tmp_path, days=1)


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
    settings = {"base_url": "https://artifactory.test", "auth_mode": "bearer"}
    settings.update(overrides.pop("settings", {}))
    secrets = {"token": "token-value"}
    secrets.update(overrides.pop("secrets", {}))
    return FakeConfig(settings, secrets)


class TestAuthHeader:
    def test_bearer_mode_builds_an_authorization_header(self):
        auth = authentication_from_configuration(_config())
        assert auth.auth_header_name == "Authorization"
        assert auth.auth_header_value == "Bearer token-value"
        assert auth.token == "token-value"

    def test_api_key_mode_builds_the_legacy_jfrog_header(self):
        """The OSCAR shell scripts use this header. The token value is the
        same either way -- a JFrog reference token satisfies both."""
        auth = authentication_from_configuration(
            _config(settings={"auth_mode": "api_key"})
        )
        assert auth.auth_header_name == "X-JFrog-Art-Api"
        assert auth.auth_header_value == "token-value"

    def test_unknown_auth_mode_is_rejected(self):
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={"auth_mode": "basic"})
            )
        assert excinfo.value.category == "invalid_configuration"

    def test_missing_token_is_rejected(self):
        with pytest.raises(ArmError):
            authentication_from_configuration(_config(secrets={"token": ""}))


class TestOrigin:
    def test_scheme_is_added_when_missing(self):
        auth = authentication_from_configuration(
            _config(settings={"base_url": "artifactory.test"})
        )
        assert auth.origin == "https://artifactory.test"

    def test_api_root_is_the_artifactory_mount(self):
        """Xray would add a second root. Leaving it out is what keeps the
        transport allow-list a single exact prefix."""
        assert API_ROOT == "/artifactory/"
        assert authentication_from_configuration(_config()).api_root == "/artifactory/"

    @pytest.mark.parametrize(
        "bad",
        [
            "https://user:pw@artifactory.test",
            "https://artifactory.test?q=1",
            "https://artifactory.test#frag",
            "ftp://artifactory.test",
            "https://artifactory .test",
            "https://artifactory.test\\evil",
            "https://artifactory.test/artifactory",
        ],
    )
    def test_hostile_base_urls_are_rejected(self, bad):
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(_config(settings={"base_url": bad}))
        assert excinfo.value.category == "invalid_configuration"

    def test_a_path_segment_is_rejected(self):
        """Unlike Confluence, no path is ever legitimate here: the REST mount
        is always /artifactory on the origin."""
        with pytest.raises(ArmError):
            authentication_from_configuration(
                _config(settings={"base_url": "https://artifactory.test/foo"})
            )


class TestClientCertificate:
    def test_no_certificate_configured_means_no_tls_context(self):
        auth = authentication_from_configuration(_config())
        assert auth.tls_context is None
        assert auth.certificate_not_after is None

    def test_certificate_builds_a_tls_context(self, certificate):
        cert, key = certificate
        auth = authentication_from_configuration(
            _config(settings={
                "client_cert_path": str(cert), "client_key_path": str(key),
            })
        )
        assert isinstance(auth.tls_context, ssl.SSLContext)
        assert auth.certificate_not_after is not None

    def test_certificate_without_a_key_is_rejected(self, certificate):
        cert, _key = certificate
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={"client_cert_path": str(cert)})
            )
        assert excinfo.value.category == "invalid_configuration"

    def test_missing_certificate_file_is_certificate_invalid(self, tmp_path):
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(tmp_path / "absent.pem"),
                    "client_key_path": str(tmp_path / "absent-key.pem"),
                })
            )
        assert excinfo.value.category == "certificate_invalid"

    def test_expired_certificate_is_refused_before_any_request(self, expired_certificate):
        """This is the whole point of the task. The live failure mode was a
        302 to cloudflareaccess.com carrying 'certificate has expired'; the
        shell scripts reported it as 'No files found'."""
        cert, key = expired_certificate
        not_after = certificate_not_after(str(cert))
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(cert), "client_key_path": str(key),
                }),
                now=not_after + 1.0,
            )
        assert excinfo.value.category == "certificate_invalid"
        assert "expired" in (excinfo.value.remediation or "")

    def test_expiry_remediation_names_the_actual_date(self, expired_certificate):
        """The date is the whole point: 'your certificate expired' sends an
        operator looking, 'expired on 2026-03-21' ends the investigation."""
        import time

        cert, key = expired_certificate
        not_after = certificate_not_after(str(cert))
        expected = time.strftime("%Y-%m-%d", time.gmtime(not_after))
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(cert), "client_key_path": str(key),
                }),
                now=not_after + 1.0,
            )
        assert expected in (excinfo.value.remediation or "")

    def test_a_certificate_expiring_soon_is_still_accepted(self, certificate):
        """Warn-vs-fail matters: refusing a still-valid certificate would
        break a working build the day before renewal was due."""
        cert, key = certificate
        auth = authentication_from_configuration(
            _config(settings={
                "client_cert_path": str(cert), "client_key_path": str(key),
            }),
            now=certificate_not_after(str(cert)) - 60.0,
        )
        assert auth.tls_context is not None

    def test_unreadable_certificate_is_certificate_invalid(self, tmp_path):
        junk = tmp_path / "junk.pem"
        junk.write_text("not a certificate")
        key = tmp_path / "junk-key.pem"
        key.write_text("not a key")
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(junk), "client_key_path": str(key),
                })
            )
        assert excinfo.value.category == "certificate_invalid"


class TestBounds:
    def test_defaults_apply_when_settings_absent(self):
        auth = authentication_from_configuration(_config())
        assert auth.request_timeout_seconds == 60
        assert auth.default_max_results == 25
        assert auth.max_deploy_bytes == 2048 * 1024 * 1024
        assert auth.deploy_root is None

    def test_bool_is_not_accepted_as_an_integer(self):
        with pytest.raises(ArmError):
            authentication_from_configuration(
                _config(settings={"default_max_results": True})
            )

    def test_deploy_megabytes_convert_to_bytes(self):
        auth = authentication_from_configuration(
            _config(settings={"max_deploy_megabytes": 10})
        )
        assert auth.max_deploy_bytes == 10 * 1024 * 1024

    def test_deploy_root_is_normalised(self, tmp_path):
        auth = authentication_from_configuration(
            _config(settings={"deploy_root": str(tmp_path) + "/"})
        )
        assert auth.deploy_root == str(tmp_path.resolve())
