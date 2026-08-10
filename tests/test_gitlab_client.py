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

CERTIFICATE_PEM = """-----BEGIN CERTIFICATE-----
MIIDGTCCAgGgAwIBAgIUeKjwPwIJaz0PPgJgjujBFRUOwh8wDQYJKoZIhvcNAQEL
BQAwHDEaMBgGA1UEAwwRZ2l0bGFiLXRhc2s4LXRlc3QwHhcNMjYwODEwMTA0MDE3
WhcNMjYwODExMTA0MDE3WjAcMRowGAYDVQQDDBFnaXRsYWItdGFzazgtdGVzdDCC
ASIwDQYJKoZIhvcNAQEBBQADggEPADCCAQoCggEBAK+RiOS2FpjEIM1pKvuA/W7l
WPUJYVPpceo3hQuTFwCZMURK+nGMZiKATmysTjgyl7YKOCh9atHX15Z5az58+eoD
HgQ51P4kFpfQtdWICXcCQ3X3aTEXSURV9DjXO0diVUmbG3nYOzR/r4zhfVYOJjRf
rAmtiRcDPXer3SEggGZuSgSHs+qzkst7QCVECSFGJDtoTKEIwk3Xc2hzztMZ0dXY
dCnY+zqN5PzF74OGS0ehzafZh4/GZ6riFZ6kHQq1R7gNpoYQH3szQi8cB0vPz5Ge
J9PoQsgAJYMmrPt+s1vsRAD+YvD/d8oEaiXdW0p+yYZCqwu9q57U8KCVOlAaTOEC
AwEAAaNTMFEwHQYDVR0OBBYEFKKXSIstSiFcN5YVY8LNqZpL4yYPMB8GA1UdIwQY
MBaAFKKXSIstSiFcN5YVY8LNqZpL4yYPMA8GA1UdEwEB/wQFMAMBAf8wDQYJKoZI
hvcNAQELBQADggEBAHcuJrrPK/M5iSnp4bw3PhRWn2MIGxc2r/Vnkh5wL+s2Bt9o
3Ed+hRNACuGDLD32evFeZAilhguqrb8SVOD5BoaDF7h5LHUKrYTvThVWD/Xnffsn
mN6AcofC5mChNt9HZY7frg3JJCeBAMcN2InYnYEgKlIqrSfnoZmXH3fShpN4zcE/
e0t803sXZma4kVOZ0y/EEPenKIHgv69ttjZzVeDQQ8zqtGF4GD4ag9pEPrgfI/y6
JWcBXG1W4HR8EZiPIfnTP00qWFguuiwOhFbViJNcl79aEZqy/9I7lioE1FOFy+0e
SnX42oQTIrKbovpO5/YMDfZ4wL1/6mJ+JmMwTcg=
-----END CERTIFICATE-----
"""

_TEST_PRIVATE_KEY_BEGIN = "-----BEGIN " + "PRIVATE KEY-----\n"
_TEST_PRIVATE_KEY_END = "-----END " + "PRIVATE KEY-----\n"

PRIVATE_KEY_PEM = _TEST_PRIVATE_KEY_BEGIN + """MIIEuwIBADANBgkqhkiG9w0BAQEFAASCBKUwggShAgEAAoIBAQCvkYjkthaYxCDN
aSr7gP1u5Vj1CWFT6XHqN4ULkxcAmTFESvpxjGYigE5srE44Mpe2CjgofWrR19eW
eWs+fPnqAx4EOdT+JBaX0LXViAl3AkN192kxF0lEVfQ41ztHYlVJmxt52Ds0f6+M
4X1WDiY0X6wJrYkXAz13q90hIIBmbkoEh7Pqs5LLe0AlRAkhRiQ7aEyhCMJN13No
c87TGdHV2HQp2Ps6jeT8xe+DhktHoc2n2YePxmeq4hWepB0KtUe4DaaGEB97M0Iv
HAdLz8+RnifT6ELIACWDJqz7frNb7EQA/mLw/3fKBGol3VtKfsmGQqsLvaue1PCg
lTpQGkzhAgMBAAECggEACHgVYc4AU0xztiDuej0fzI2K7+AM1jzGulkFBZjJ9WUO
ZbhVsixHAX9NuSuLJuYW4CjISni5UkfOjiNLh3NFJXMSy7qj8gH45ogie1tRdJCT
A0Hk7MGuLroUOrk0MnZ1fYRaTBOAkKDfraSzdHcgg+qBDKL2v9nPyWHsm/RayUYQ
eAaiLwHUEMGIixMnbBII67azCC9cEf7/KAhOi4uYR6BZgMmivM5idGA0ZcV1eyZu
v1C/UpQ4C/Tiw2jNU9sXWLW+5iBCRPqzYxHQRnHJmnO2lKNRqHdmR+lqxeXxAm5C
xLTIJ1ZcAh/nsrMMz1kQuVUp123dA3nZhrCmvDuzCQKBgQDfVRKRiY68bvtPxl/A
/c0jiK1Z8/50eNgGNKV9/GzKzBLpw8vujs12lUZ3nhYaPMyfV9GaRPqcechZSwV+
F9z6k4F6aqJqs0bJZ9v83T2HaAPqqSrSvGAdE3VqeGUg7N1AfXvw0ypfk8BSgU9Y
V/BTG1ykqK4cmpXGS6LMfeLKGQKBgQDJP+SK0Z7dTF38NHGOqW7ca59TK37KJOBm
XhbYU2ZwgOOaZptIx/ZhsKNUTwECZo6JUj+G6Qhf+T3fz7O8n8n2SlN/4OjZ1tYK
sBg4+Rk05p5gUr2oGWL55/AfslfM7hxO6p6/pIwi5GULVfyOGF94N6tP9SM4dvjy
mIx8BZUCCQJ/Ab6oZnqsosw7KmRiWx+geqaWtB0z37UR+vpuUI2oS+1MOIdPEI4N
DOAdrNGPWqUe9B+7g3kGfDJ3Xjs3z8Rf9ZUxbcNngW3lH62wCkmwMV6eqTapHvxZ
w+BjCnHmWFuBXv+b+EWuDxEYb4yTEh2dwwhzsNWghpiukt4EZ5SUMQKBgQCFgVFH
lg/hlsuyh8fdcCEPMIYdUnll+Fi1EC3vjEQk1hwnTXIuMhkMbXWsdEyjHw3noxxp
jyXzJREa7Fq8AvSj4mLKLpXKDW8o3/Dxuq4yHdtq4vjWDyFNz8PIAzOjy0IUSCjP
0YT1kLZHct98FEchJS0Mef7HcoVryi9IBxv2oQKBgH0ipKm4OwXgx8MzVKPLfLug
mJpcT7XrO50KPILXXLJJX8TRUe/cHyaBGQ7ERtFuLKr17URyDBw1jwvzkQ8aTfO5
Ru3OlIyDqsg4th9K0yseOojdTiQWXkKfU2JUw2yFSh1QXJC4kDYA+AzAdLMMdSRd
BUM7oDrhol+3xzu6cbHd
""" + _TEST_PRIVATE_KEY_END

MISMATCHED_PRIVATE_KEY_PEM = _TEST_PRIVATE_KEY_BEGIN + """MIIEvgIBADANBgkqhkiG9w0BAQEFAASCBKgwggSkAgEAAoIBAQDCs/lx7taKhJUS
8Iz/qNLzhvjGoK6aGt+SGd4tUiXNn8AnAGqBlQkGVNaae+BMoYGVJotvuAlYrtfs
XaECI9pP6c+EBaegdCzNILyZ12R8u/Byy5K9Owbvx5DvoaKgwF1VQPeXKgxPIKvn
5ljNaDLqrwraDPv3gqEnhiCnZPiW5Dgmyek4HyYMJYz1+krMc0SBaSkZHyJo+/BP
j9MffA0mFDlkucfHVeUIgnNGrid5pVvAxykDWVSC9GeM8Q45/76LrGJSo63Iiomg
QfQgz/2cBCic204yGNFUe6uZuRF0QszF4WFQdKiyazapPvhO5u3ONgmsMacUu4xL
57EYORIpAgMBAAECggEABzFhKyB60Ev42mXk3ZqJ7Yl8VhEwVhzdSs9WFghJgXzP
+1jgdmhQOKnIclVWelpCmGUfxFkxDjPKYg7s8HBs46QkgJD5afv0vkDB+vB6Q8Hp
LoJ/CardNR1DKVkoMgZdRFWlt/HLmd4//42S1QbPD7y2+sp9Qf3zUGub9/cq2F8m
MAbjlehmp41IjfhT1rUZ3by+8/E/C7nQNpIASRyBbnRrNQ2+RhW/8NWDD5Toy00J
Ip0beW4rh47+7N/VI4OIScr/RJnSfTM2GFw7CXGSEo14V8zVo9U9W4ALKnklN8Ss
+x0V4KucX+0NPgxikP8+cxZ0Os5s+nGZSUOibtO0sQKBgQD27FQr9QUWriSFmP9v
9XpHN/KEieyYiLgkT9YjGfzn8Ifp3ZoF3obORDz/fJBvJBbCzoySRK5Ny0ZPaK20
vSMGmmF86UsSmcHQxS2l3qzOZk01JT+rm8oNURc8hk0fDRmXqQTiAxn2xZYuFYua
2BwsYsmsDT2h9eVOkA2RvHq8mQKBgQDJ3DpUifWj/0+Q7OLEa4ZZwcd1NZrSafKt
afRBDYqc+PoqmjpUIkzmF8Sfx2xII6rqPcqNYhgcQBBFmG0qsHue97m6OKHHeHX6
mk7ayho/fkxC4tGUeuiJ3ArlygVtyvKEADaLrDNepBSThENP/sMYZ772/WYNdgIO
v6dZL9JsEQKBgQDPRaB+aaYE3NdxgfXiIHitccxU74Y4oIOaj53cR0Nh2ynr6YYS
KTKV0Pg3KnP/p5annkSnv5llWh5CKEewMRhGwa7V8OuAyKrGOc5QrzP16jAjTYo9
3n9kYE6WEtKIHzH9efbMVfgkisW/F3zh1UkJBT/u+gpjewsqwIdzb3jD+QKBgQCE
eyk9Op4g1/tcXlwmFXvDhM5nOps15ZsD/Tn1R/HlO/LT6wzFEw3tJURCqRuD7QTL
X2qEiBDS2ajUREnBbrpzhpo6gdiLlZ+4rXV7WpEHgtiCPWLXVCMx91yfm4scl8m6
oHksCgRc5MssVe3nnohkiBJo/73ur7iB/X7TpfMwQQKBgEJ0vUnMFGgGBTTGnKOf
qVpuowtB76i9wE2I+4P1l6RgZmp5VRmwcT+Z9Q6Aq8nt37gflxjY5qDUt9IMcXqs
sxuKhCzERG878UefvhRvVuG3UII8XrHy5TyGK6NMUcUTDPauq+o+tzV11BLlMdEW
+w0ZdbxLMl5RpksqAdbg4Xww
""" + _TEST_PRIVATE_KEY_END


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


def _write_certificate_pair(cert, key, *, mismatched=False):
    cert.write_text(CERTIFICATE_PEM, encoding="ascii")
    key.write_text(
        MISMATCHED_PRIVATE_KEY_PEM if mismatched else PRIVATE_KEY_PEM,
        encoding="ascii",
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
    _write_certificate_pair(cert, key)
    assert _auth(tmp_path).certificate_pair == (cert, key)

    override_cert = tmp_path / "override-cert.pem"
    override_key = tmp_path / "override-key.pem"
    _write_certificate_pair(override_cert, override_key)
    configured = _auth(
        tmp_path,
        client_certificate_path=str(override_cert),
        client_key_path=str(override_key),
    )
    assert configured.certificate_pair == (override_cert, override_key)


@pytest.mark.parametrize("pem_case", ["malformed", "mismatched"])
def test_auth_rejects_malformed_or_mismatched_bounded_pem_pairs_without_leakage(
    tmp_path, pem_case
):
    # GL-AUTH-02 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    auth, _client, models = _modules()
    cert = tmp_path / "sensitive-client-cert.pem"
    key = tmp_path / "sensitive-client-key.pem"
    if pem_case == "malformed":
        cert.write_text("not a certificate", encoding="ascii")
        key.write_text("not a private key", encoding="ascii")
    else:
        _write_certificate_pair(cert, key, mismatched=True)
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
    assert "sensitive-client" not in str(caught.value)


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


def test_each_request_timeout_is_clamped_to_remaining_aggregate_deadline(tmp_path):
    # GL-AUTH-01 legacy: gitlab_project_resolver.py:GitLabProjectResolver._get_session
    _auth_module, client, _models = _modules()
    now = [0.0]
    gitlab = client.GitLabClient(
        _auth(tmp_path),
        connect_timeout_seconds=5.0,
        read_timeout_seconds=20.0,
        total_timeout_seconds=10.0,
        clock=lambda: now[0],
    )
    deadline = gitlab.operation_deadline()
    now[0] = 9.25
    seen = {}

    def response(request):
        seen["timeout"] = dict(request.extensions["timeout"])
        return httpx.Response(200, json={"ok": True})

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(side_effect=response)
        assert gitlab.get_json("/api/v4/projects/42", deadline=deadline) == {"ok": True}

    assert set(seen["timeout"]) == {"connect", "read", "write", "pool"}
    assert all(0 < value <= 0.75 for value in seen["timeout"].values())


@pytest.mark.parametrize("stall", ["headers", "body"])
def test_clamped_request_timeout_bounds_header_and_body_stalls(tmp_path, stall):
    # GL-AUTH-01 legacy: sibling GitLab component _get_session request calls
    _auth_module, client, models = _modules()
    now = [0.0]
    gitlab = client.GitLabClient(
        _auth(tmp_path),
        read_timeout_seconds=20.0,
        total_timeout_seconds=3.0,
        max_retries=0,
        clock=lambda: now[0],
    )
    deadline = gitlab.operation_deadline()
    now[0] = 2.5
    seen = {}

    class StallingBody(httpx.SyncByteStream):
        def __iter__(self):
            now[0] += seen["timeout"]["read"]
            raise httpx.ReadTimeout("bounded body stall")
            yield b""  # pragma: no cover - keeps this a generator

    def response(request):
        seen["timeout"] = dict(request.extensions["timeout"])
        if stall == "headers":
            now[0] += seen["timeout"]["read"]
            raise httpx.ReadTimeout("bounded header stall")
        return httpx.Response(200, stream=StallingBody())

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(side_effect=response)
        with pytest.raises(models.GitLabError) as caught:
            gitlab.get_json("/api/v4/projects/42", deadline=deadline)

    assert caught.value.category == "deadline"
    assert set(seen["timeout"]) == {"connect", "read", "write", "pool"}
    assert all(0 < value <= 0.5 for value in seen["timeout"].values())
