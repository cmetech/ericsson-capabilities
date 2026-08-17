"""Artifactory client rides the shared transport policy and classifies the edge."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))


def _is_arm_module(module: object) -> bool:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, (str, Path)):
        return False
    try:
        return Path(module_file).resolve().is_relative_to(PLUGIN.resolve())
    except (OSError, ValueError):
        return False


def _displace_foreign_standalone_modules() -> dict[str, object]:
    """Let this ARM test import its own generic modules without cache reuse."""
    displaced = {}
    for name in ("aql", "auth", "client", "models", "operations", "tools"):
        module = sys.modules.get(name)
        if module is not None and not _is_arm_module(module):
            displaced[name] = sys.modules.pop(name)
    for name in tuple(sys.modules):
        module = sys.modules[name]
        if (
            (name == "_common" or name.startswith("_common."))
            and not _is_arm_module(module)
        ):
            displaced[name] = sys.modules.pop(name)
    return displaced


def _restore_foreign_standalone_modules(displaced: dict[str, object]) -> None:
    """Remove only ARM imports, then put displaced foreign modules back."""
    for name in ("aql", "auth", "client", "models", "operations", "tools"):
        module = sys.modules.get(name)
        if _is_arm_module(module):
            sys.modules.pop(name, None)
    for name in tuple(sys.modules):
        if (
            (name == "_common" or name.startswith("_common."))
            and _is_arm_module(sys.modules[name])
        ):
            sys.modules.pop(name, None)
    for name, module in displaced.items():
        current = sys.modules.get(name)
        if current is None or _is_arm_module(current):
            sys.modules[name] = module


_DISPLACED_FOREIGN_MODULES = _displace_foreign_standalone_modules()
try:
    from _common.errors import ConnectorError  # noqa: E402
    from _common.transport import Response  # noqa: E402
    from client import ArmClient  # noqa: E402
    from models import ArmAuth, ArmError  # noqa: E402
finally:
    _restore_foreign_standalone_modules(_DISPLACED_FOREIGN_MODULES)


# The repository's standalone plugins intentionally share top-level module
# names. Keep the imported ARM classes, but do not make later connector tests
# resolve their own ``auth``, ``client``, or ``models`` imports to this plugin.
for _module_name in ("auth", "client", "models"):
    _module = sys.modules.get(_module_name)
    if _is_arm_module(_module):
        sys.modules.pop(_module_name, None)
for _module_name in tuple(sys.modules):
    if (
        (_module_name == "_common" or _module_name.startswith("_common."))
        and _is_arm_module(sys.modules[_module_name])
    ):
        sys.modules.pop(_module_name, None)
while str(PLUGIN) in sys.path:
    sys.path.remove(str(PLUGIN))

ACCESS_REDIRECT = Response(
    302,
    {
        "location": (
            "https://ericssondevops.cloudflareaccess.com/cdn-cgi/access/login/"
            "artifactory.test?kid=abc"
        ),
        "www-authenticate": 'Cloudflare-Access resource_metadata="https://x/.well-known"',
    },
    b"<html>redirecting</html>",
)


class FakeTransport:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, path, *, params, json_body, timeout_seconds,
                content=None, extra_headers=None):
        self.calls.append({
            "method": method, "path": path, "params": params,
            "json_body": json_body, "content": content,
            "extra_headers": extra_headers,
        })
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _auth(**overrides):
    values = dict(
        origin="https://artifactory.test",
        api_root="/artifactory/",
        auth_header_name="Authorization",
        auth_header_value="Bearer secret-token-value",
        token="secret-token-value",
        tls_context=None,
        certificate_not_after=None,
        request_timeout_seconds=60,
        default_max_results=25,
        max_deploy_bytes=1024,
        deploy_root=None,
    )
    values.update(overrides)
    return ArmAuth(**values)


def _client(script, **overrides):
    clock = FakeClock()
    return (
        ArmClient(_auth(**overrides), transport=FakeTransport(script),
                  clock=clock, sleep=clock.sleep),
        clock,
    )


class TestClient:
    @pytest.mark.parametrize(
        ("auth_overrides", "client_overrides"),
        [
            ({"request_timeout_seconds": 0}, {}),
            ({}, {"max_retries": 5}),
        ],
    )
    def test_constructor_translates_shared_configuration_errors(
        self, auth_overrides, client_overrides
    ):
        with pytest.raises(ArmError) as excinfo:
            ArmClient(
                _auth(**auth_overrides),
                transport=FakeTransport([]),
                **client_overrides,
            )
        assert excinfo.value.category == "invalid_configuration"
        assert not isinstance(excinfo.value, ConnectorError)

    def test_decodes_json(self):
        client, _clock = _client([Response(200, {}, b'{"repo":"generic"}')])
        assert client.get_json("/artifactory/api/repositories") == {"repo": "generic"}

    def test_retry_after_is_honoured(self):
        client, clock = _client(
            [Response(429, {"Retry-After": "2"}, b""), Response(200, {}, b"{}")]
        )
        client.get_json("/artifactory/api/repositories")
        assert clock.slept == [2.0]

    def test_writes_are_not_retried(self):
        client, _clock = _client([Response(503, {}, b"")])
        with pytest.raises(ArmError) as excinfo:
            client.request_json("PUT", "/artifactory/generic/a.tgz", json_body={})
        assert excinfo.value.category == "write_ambiguous"

    @pytest.mark.parametrize("status", [302, 503])
    def test_checksum_probe_returns_each_received_status_once(self, status):
        client, _clock = _client([Response(status, {}, b"")])
        response = client.checksum_probe("/artifactory/generic/a.tgz")
        assert response.status == status
        assert len(client._transport.calls) == 1

    def test_checksum_probe_keeps_cloudflare_edge_classification(self):
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError) as excinfo:
            client.checksum_probe("/artifactory/generic/a.tgz")
        assert excinfo.value.category == "edge_authentication"
        assert len(client._transport.calls) == 1

    def test_checksum_probe_transport_failure_is_ambiguous_and_not_retried(self):
        client, _clock = _client([RuntimeError("network lost")])
        with pytest.raises(ArmError) as excinfo:
            client.checksum_probe("/artifactory/generic/a.tgz")
        assert excinfo.value.category == "write_ambiguous"
        assert len(client._transport.calls) == 1

    def test_checksum_probe_cancelled_after_response_is_ambiguous(self):
        cancelled = False
        transport = FakeTransport([Response(404, {}, b"")])
        original_request = transport.request

        def cancel_after_response(*args, **kwargs):
            nonlocal cancelled
            response = original_request(*args, **kwargs)
            cancelled = True
            return response

        transport.request = cancel_after_response
        clock = FakeClock()
        client = ArmClient(
            _auth(),
            transport=transport,
            cancel_check=lambda: cancelled,
            clock=clock,
            sleep=clock.sleep,
        )
        with pytest.raises(ArmError) as excinfo:
            client.checksum_probe("/artifactory/generic/a.tgz")
        assert excinfo.value.category == "write_ambiguous"
        assert len(transport.calls) == 1

    def test_shared_error_type_never_escapes(self):
        client, _clock = _client([Response(401, {}, b"")])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert not isinstance(excinfo.value, ConnectorError)
        assert excinfo.value.remediation

    def test_empty_body_is_none_not_an_error(self):
        """DELETE returns 204 with no body."""
        client, _clock = _client([Response(204, {}, b"")])
        assert client.request_json("DELETE", "/artifactory/generic/a.tgz") is None

    def test_path_outside_the_api_root_is_rejected(self):
        client, _clock = _client([])
        with pytest.raises(ArmError):
            client.get_json("/xray/api/v1/violations")

    def test_the_auth_header_is_whatever_auth_resolved(self):
        client, _clock = _client(
            [Response(200, {}, b"{}")],
            auth_header_name="X-JFrog-Art-Api",
            auth_header_value="raw-token",
        )
        assert client.headers["X-JFrog-Art-Api"] == "raw-token"
        assert "Authorization" not in client.headers


class TestCloudflareAccess:
    def test_access_redirect_is_its_own_category(self):
        """The live failure mode. Classifying this as `authentication` would
        send an operator to rotate the Artifactory token, when the credential
        that actually failed is the mTLS client certificate."""
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/system/ping")
        assert excinfo.value.category == "edge_authentication"

    def test_access_remediation_points_at_the_certificate(self):
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/system/ping")
        assert "certificate" in (excinfo.value.remediation or "").lower()

    def test_detected_by_www_authenticate_alone(self):
        client, _clock = _client([
            Response(302, {"www-authenticate": "Cloudflare-Access"}, b"")
        ])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "edge_authentication"

    def test_detected_by_location_alone(self):
        client, _clock = _client([
            Response(302, {"location": "https://x.cloudflareaccess.com/login"}, b"")
        ])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "edge_authentication"

    def test_an_unrelated_redirect_is_not_an_access_failure(self):
        client, _clock = _client([
            Response(302, {"location": "https://artifactory.test/elsewhere"}, b"")
        ])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "invalid_remote_data"

    def test_access_failure_is_not_retried(self):
        """An expired certificate will not fix itself. Retrying wastes the
        deadline and hides the cause behind a timeout."""
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError):
            client.get_json("/artifactory/api/repositories")
        assert len(client._transport.calls) == 1

    def test_access_redirect_on_post_is_not_write_ambiguous_or_retryable(self):
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError) as excinfo:
            client.post_text("/artifactory/api/search/aql", "items.find({})")
        assert excinfo.value.category == "edge_authentication"
        assert len(client._transport.calls) == 1
        assert not client._client._failures

    def test_access_redirect_on_put_is_not_write_ambiguous_or_retryable(self):
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError) as excinfo:
            client.send("PUT", "/artifactory/generic/a.tgz", content=b"archive")
        assert excinfo.value.category == "edge_authentication"
        assert len(client._transport.calls) == 1
        assert not client._client._failures

    def test_unrelated_write_redirect_remains_write_ambiguous(self):
        client, _clock = _client([
            Response(302, {"location": "https://artifactory.test/elsewhere"}, b"")
        ])
        with pytest.raises(ArmError) as excinfo:
            client.send("PUT", "/artifactory/generic/a.tgz", content=b"archive")
        assert excinfo.value.category == "write_ambiguous"


class TestBodies:
    def test_post_text_sends_text_plain(self):
        """AQL is a DSL, not JSON. Sending application/json here is a 400,
        and it is the classic Artifactory integration mistake."""
        client, _clock = _client([Response(200, {}, b'{"results":[]}')])
        client.post_text("/artifactory/api/search/aql", 'items.find({})')
        call = client._transport.calls[0]
        assert call["content"] == b'items.find({})'
        assert call["extra_headers"]["Content-Type"] == "text/plain"
        assert call["json_body"] is None

    def test_html_body_raises_invalid_remote_data(self):
        """An HTML body where JSON was expected means an interstitial --
        the same signal super-cli detects for Jira."""
        client, _clock = _client([Response(200, {}, b"<html>login</html>")])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "invalid_remote_data"

    def test_send_can_return_a_non_2xx_without_raising(self):
        """Deploy needs this: a failed checksum-deploy probe is a normal,
        expected outcome that must fall through to a full upload."""
        client, _clock = _client([Response(404, {}, b"")])
        response = client.send(
            "PUT", "/artifactory/generic/a.tgz", content=b"", classify=False
        )
        assert response.status == 404
