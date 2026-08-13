from __future__ import annotations

import json
import os
import subprocess
import textwrap
from pathlib import Path

import httpx
import pytest

from jira_test_support import models, transport

JiraAuth = models.JiraAuth
JiraError = models.JiraError
TransportResponse = models.TransportResponse
CurlTransport = transport.CurlTransport
NativeTransport = transport.NativeTransport


def auth(executable: Path, *, transport="curl") -> JiraAuth:
    return JiraAuth(
        origin="https://jira.example.test",
        authorization="Bearer request-secret-token",
        auth_mode="bearer",
        rest_api_version="3",
        transport=transport,
        curl_executable=str(executable),
        request_timeout_seconds=2,
        default_max_results=25,
    )


@pytest.fixture
def fake_curl(tmp_path, monkeypatch):
    executable = tmp_path / "curl"
    executable.write_text(
        textwrap.dedent(
            """\
            #!/usr/bin/env python3
            import json
            import os
            import signal
            import stat
            import sys
            import time
            from pathlib import Path

            config_path = Path(sys.argv[sys.argv.index("--config") + 1])
            options = {}
            headers = []
            for line in config_path.read_text().splitlines():
                key, _, raw = line.partition(" = ")
                value = json.loads(raw) if raw else True
                if key == "header":
                    headers.append(value)
                else:
                    options[key] = value
            body_path = options.get("data-binary", "")
            if body_path.startswith("@"):
                body_path = body_path[1:]
            record = {
                "argv": sys.argv,
                "config_mode": stat.S_IMODE(config_path.stat().st_mode),
                "directory_mode": stat.S_IMODE(config_path.parent.stat().st_mode),
                "body_mode": stat.S_IMODE(Path(body_path).stat().st_mode) if body_path else None,
                "header_mode": stat.S_IMODE(Path(options["dump-header"]).stat().st_mode),
                "output_mode": stat.S_IMODE(Path(options["output"]).stat().st_mode),
                "headers": headers,
                "method": options["request"],
                "url": options["url"],
                "proxy": options["proxy"],
                "proto": options["proto"],
                "proto_redir": options["proto-redir"],
                "request_body": Path(body_path).read_text() if body_path else "",
                "pid": os.getpid(),
            }
            Path(os.environ["FAKE_CURL_RECORD"]).write_text(json.dumps(record))
            delay = float(os.environ.get("FAKE_CURL_DELAY", "0"))
            if delay:
                signal.signal(signal.SIGTERM, lambda *_: sys.exit(143))
                time.sleep(delay)
            if os.environ.get("FAKE_CURL_EXIT"):
                print("request-secret-token unsafe stderr", file=sys.stderr)
                sys.exit(int(os.environ["FAKE_CURL_EXIT"]))
            Path(options["dump-header"]).write_bytes(
                os.environ.get("FAKE_CURL_HEADERS", "HTTP/1.1 200 OK\\r\\nContent-Type: application/json\\r\\n\\r\\n").encode()
            )
            response_size = int(os.environ.get("FAKE_CURL_BODY_SIZE", "0"))
            Path(options["output"]).write_bytes(
                b"x" * response_size if response_size else os.environ.get("FAKE_CURL_BODY", '{"ok":true}').encode()
            )
            print(os.environ.get("FAKE_CURL_STATUS", "200"), end="")
            """
        ),
        encoding="utf-8",
    )
    executable.chmod(0o700)
    record = tmp_path / "record.json"
    monkeypatch.setenv("FAKE_CURL_RECORD", str(record))
    return executable, record


def test_private_config_keeps_secret_and_body_out_of_argv_and_cleans_up(fake_curl):
    executable, record_path = fake_curl
    spawns = []

    def spawn(argv, **kwargs):
        spawns.append((argv, kwargs))
        return subprocess.Popen(argv, **kwargs)

    transport = CurlTransport(
        auth(executable), approved_executables={executable}, popen=spawn
    )
    request_body = {"body": "private request body"}

    result = transport.request(
        "POST",
        "/rest/api/3/issue/ABC-1/comment",
        params={"notifyUsers": "false"},
        json_body=request_body,
        timeout_seconds=2,
    )

    record = json.loads(record_path.read_text())
    argv = repr(record["argv"])
    assert "request-secret-token" not in argv
    assert "private request body" not in argv
    assert record["argv"] == [str(executable), "-q", "--config", record["argv"][3]]
    assert record["config_mode"] == 0o600
    assert record["body_mode"] == 0o600
    assert record["header_mode"] == 0o600
    assert record["output_mode"] == 0o600
    assert record["directory_mode"] == 0o700
    assert record["headers"] == [
        "Authorization: Bearer request-secret-token",
        "Accept: application/json",
        "Content-Type: application/json",
    ]
    assert record["method"] == "POST"
    assert record["proxy"] == ""
    assert record["proto"] == "=http,https"
    assert record["proto_redir"] == "-all"
    assert record["url"] == "https://jira.example.test/rest/api/3/issue/ABC-1/comment?notifyUsers=false"
    assert json.loads(record["request_body"]) == request_body
    assert result == TransportResponse(
        status=200,
        headers={"content-type": "application/json"},
        body=b'{"ok":true}',
    )
    assert spawns[0][0] == record["argv"]
    assert spawns[0][1]["shell"] is False
    assert isinstance(spawns[0][0], list)
    assert not Path(record["argv"][3]).parent.exists()


@pytest.mark.parametrize("method", ["PATCH", "HEAD", "OPTIONS", "get", ""])
def test_curl_rejects_non_allowlisted_methods_before_spawn(fake_curl, method):
    executable, record = fake_curl
    transport = CurlTransport(auth(executable), approved_executables={executable})

    with pytest.raises(JiraError) as caught:
        transport.request(method, "/rest/api/3/search", timeout_seconds=1)
    assert caught.value.category == "invalid_input"
    assert not record.exists()


@pytest.mark.parametrize(
    "path",
    [
        "https://other.example.test/rest/api/3/search",
        "//other.example.test/search",
        "/rest/api/3/../admin",
        "/rest/api/3/search?token=request-secret-token",
        "/plugins/servlet/search",
    ],
)
def test_curl_is_pinned_to_configured_jira_rest_origin(fake_curl, path):
    executable, record = fake_curl
    transport = CurlTransport(auth(executable), approved_executables={executable})
    with pytest.raises(JiraError) as caught:
        transport.request("GET", path, timeout_seconds=1)
    assert caught.value.category == "invalid_input"
    assert not record.exists()


def test_curl_executable_must_be_exact_absolute_regular_executable(tmp_path):
    candidates = [
        Path("curl"),
        tmp_path / "not-curl",
        tmp_path / "curl",
        tmp_path / "curl.exe",
    ]
    candidates[1].write_text("x")
    candidates[1].chmod(0o700)
    candidates[2].mkdir()
    candidates[3].write_text("x")
    candidates[3].chmod(0o600)

    for candidate in candidates:
        with pytest.raises(JiraError) as caught:
            CurlTransport(auth(candidate), approved_executables=set(candidates))
        assert caught.value.category == "invalid_configuration"

    unapproved = tmp_path / "approved-looking" / "curl"
    unapproved.parent.mkdir()
    unapproved.write_text("#!/bin/sh\nexit 0\n")
    unapproved.chmod(0o700)
    with pytest.raises(JiraError) as caught:
        CurlTransport(auth(unapproved), approved_executables=set())
    assert caught.value.category == "invalid_configuration"


@pytest.mark.parametrize(
    ("env", "category"),
    [
        ({"FAKE_CURL_EXIT": "7"}, "transient"),
        ({"FAKE_CURL_STATUS": "not-a-status"}, "invalid_remote_data"),
        ({"FAKE_CURL_STATUS": "999"}, "invalid_remote_data"),
        ({"FAKE_CURL_HEADERS": "malformed headers"}, "invalid_remote_data"),
    ],
)
def test_failure_strings_are_redacted_and_private_directory_is_cleaned(
    fake_curl, monkeypatch, env, category
):
    executable, record_path = fake_curl
    for key, value in env.items():
        monkeypatch.setenv(key, value)
    transport = CurlTransport(auth(executable), approved_executables={executable})

    with pytest.raises(JiraError) as caught:
        transport.request("GET", "/rest/api/3/search", timeout_seconds=1)

    assert caught.value.category == category
    assert "request-secret-token" not in str(caught.value)
    record = json.loads(record_path.read_text())
    assert not Path(record["argv"][3]).parent.exists()


def test_spawn_failure_cleans_up_without_echoing_executable(tmp_path):
    executable = tmp_path / "curl"
    executable.write_text("#!/bin/sh\nexit 0\n")
    executable.chmod(0o700)
    transport = CurlTransport(auth(executable), approved_executables={executable})
    executable.unlink()

    with pytest.raises(JiraError) as caught:
        transport.request("GET", "/rest/api/3/search", timeout_seconds=1)
    assert caught.value.category == "transient"
    assert str(executable) not in str(caught.value)


@pytest.mark.parametrize("cancelled", [False, True])
def test_timeout_and_cancellation_terminate_exact_child_and_clean_up(
    fake_curl, monkeypatch, cancelled
):
    executable, _record_path = fake_curl
    monkeypatch.setenv("FAKE_CURL_DELAY", "10")
    spawned = {}

    def spawn(argv, **kwargs):
        process = subprocess.Popen(argv, **kwargs)
        spawned.update(pid=process.pid, config=argv[3])
        return process

    transport = CurlTransport(
        auth(executable),
        cancel_check=(lambda: bool(spawned)) if cancelled else None,
        approved_executables={executable},
        popen=spawn,
    )

    with pytest.raises(JiraError) as caught:
        transport.request(
            "GET",
            "/rest/api/3/search",
            timeout_seconds=0.15 if not cancelled else 2,
    )

    assert caught.value.category == ("cancelled" if cancelled else "deadline")
    with pytest.raises(ProcessLookupError):
        os.kill(spawned["pid"], 0)
    assert not Path(spawned["config"]).parent.exists()


def test_request_response_header_and_query_bounds_are_enforced(fake_curl, monkeypatch):
    executable, _record = fake_curl
    transport = CurlTransport(auth(executable), approved_executables={executable})
    cases = [
        {"json_body": {"body": "x" * 262_145}},
        {"params": {"q": "x" * 8193}},
    ]
    for kwargs in cases:
        with pytest.raises(JiraError) as caught:
            transport.request("POST", "/rest/api/3/search", timeout_seconds=1, **kwargs)
        assert caught.value.category == "capacity"

    monkeypatch.setenv("FAKE_CURL_BODY_SIZE", "1048577")
    with pytest.raises(JiraError) as caught:
        transport.request("GET", "/rest/api/3/search", timeout_seconds=1)
    assert caught.value.category == "capacity"

    monkeypatch.delenv("FAKE_CURL_BODY_SIZE")
    monkeypatch.setenv("FAKE_CURL_BODY", "{}")
    monkeypatch.setenv("FAKE_CURL_HEADERS", "HTTP/1.1 200 OK\r\nX-Large: " + "x" * 65_537 + "\r\n\r\n")
    with pytest.raises(JiraError) as caught:
        transport.request("GET", "/rest/api/3/search", timeout_seconds=1)
    assert caught.value.category == "capacity"


class FakeCurl:
    def __init__(self, result):
        self.result = result
        self.calls = []

    def request(self, method, path, **kwargs):
        self.calls.append((method, path, kwargs))
        return self.result

    def close(self):
        pass


def test_explicit_curl_bypasses_native_probe(fake_curl):
    executable, _record = fake_curl
    seen = []

    def native_send(request):
        seen.append(request)
        raise AssertionError("native transport must not run")

    curl = FakeCurl(TransportResponse(200, {}, b"{}"))
    transport = NativeTransport(
        auth(executable, transport="curl"),
        http_transport=httpx.MockTransport(native_send),
        curl_transport=curl,
    )

    assert transport.request("GET", "/rest/api/3/search", timeout_seconds=1).status == 200
    assert seen == []
    assert len(curl.calls) == 1


def test_auto_falls_back_only_on_exact_cloudflare_1010_response(fake_curl):
    executable, _record = fake_curl
    curl = FakeCurl(TransportResponse(200, {}, b'{"via":"curl"}'))

    def native_send(_request):
        return httpx.Response(
            403,
            headers={"server": "cloudflare", "cf-ray": "abc", "content-type": "text/html"},
            content=b"Access denied | error 1010",
        )

    transport = NativeTransport(
        auth(executable, transport="auto"),
        http_transport=httpx.MockTransport(native_send),
        curl_transport=curl,
    )
    result = transport.request("GET", "/rest/api/3/search", timeout_seconds=1)

    assert result.body == b'{"via":"curl"}'
    assert len(curl.calls) == 1


@pytest.mark.parametrize(
    "native_outcome",
    [
        httpx.ConnectError("dns failed"),
        httpx.ReadTimeout("timeout"),
        httpx.Response(401),
        httpx.Response(403, content=b"generic forbidden"),
        httpx.Response(500, content=b"error 1010"),
        httpx.Response(403, headers={"server": "cloudflare", "cf-ray": "abc"}, content=b"malformed"),
    ],
)
def test_auto_never_falls_back_for_unclassified_failures(fake_curl, native_outcome):
    executable, _record = fake_curl
    curl = FakeCurl(TransportResponse(200, {}, b"{}"))

    def native_send(request):
        if isinstance(native_outcome, BaseException):
            native_outcome.request = request
            raise native_outcome
        return native_outcome

    transport = NativeTransport(
        auth(executable, transport="auto"),
        http_transport=httpx.MockTransport(native_send),
        curl_transport=curl,
    )
    if isinstance(native_outcome, BaseException):
        with pytest.raises((httpx.TransportError, httpx.TimeoutException)):
            transport.request("GET", "/rest/api/3/search", timeout_seconds=1)
    else:
        transport.request("GET", "/rest/api/3/search", timeout_seconds=1)
    assert curl.calls == []
