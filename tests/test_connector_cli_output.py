"""Stable human and JSON output contracts for the connector facade."""

from __future__ import annotations

import importlib.util
import json
import sys
import uuid
from collections.abc import Mapping
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-connector-cli"


def _load_facade():
    name = f"connector_cli_output_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        name,
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def facade():
    return _load_facade()


class Context:
    def __init__(self, result):
        self.result = result

    def invoke_application_command(self, *args, **kwargs):
        return self.result


class HostileMapping(Mapping):
    """Malformed provider object whose access must never escape the facade."""

    def __getitem__(self, key):
        raise RuntimeError("RAW-MAPPING-EXCEPTION")

    def __iter__(self):
        raise RuntimeError("RAW-MAPPING-EXCEPTION")

    def __len__(self):
        raise RuntimeError("RAW-MAPPING-EXCEPTION")

    def get(self, key, default=None):
        raise RuntimeError("RAW-MAPPING-EXCEPTION")


def _run(facade, result, *, brand="otto", json_mode=True):
    parser = facade.build_parser(prog=brand, ctx=Context(result))
    argv = ["jira", "issue", "get", "ABC-1"]
    if json_mode:
        argv.append("--json")
    parsed = parser.parse_args(argv)
    return parsed.func(parsed)


def _run_gitlab_ci(facade, result, *, json_mode=True):
    parser = facade.build_parser(prog="otto", ctx=Context(result))
    argv = ["gitlab", "ci", "inspect", "group/project"]
    if json_mode:
        argv.append("--json")
    parsed = parser.parse_args(argv)
    return parsed.func(parsed)


def test_json_success_is_one_exact_sorted_compact_utf8_envelope(
    facade, capsys
):
    result = {
        "success": True,
        "result": {"z": "café", "a": 1},
        "warnings": ["bounded warning"],
        "meta": {"truncated": False},
        "configuration": "must-not-leak",
        "invocation": "must-not-leak",
    }

    assert _run(facade, result) == 0
    captured = capsys.readouterr()
    expected = {
        "schema_version": "ericsson.connector-cli/v1",
        "ok": True,
        "connector": "jira",
        "operation": "jira_get_issue",
        "mode": "read",
        "data": {"z": "café", "a": 1},
        "warnings": ["bounded warning"],
        "meta": {"truncated": False},
    }
    assert captured.out == json.dumps(
        expected,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ) + "\n"
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert "must-not-leak" not in captured.out


def test_real_shaped_gitlab_ci_warnings_and_meta_lift_out_of_result_data(
    facade, capsys
):
    result = {
        "success": True,
        "result": {
            "project": {"id": 7, "path": "group/project"},
            "root": ".gitlab-ci.yml",
            "jobs": [{"name": "test", "status": "bounded"}],
            "warnings": ["include_limit_reached"],
            "meta": {"truncated": True, "sources": 25},
        },
    }

    assert _run_gitlab_ci(facade, result) == 0
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    assert envelope["operation"] == "gitlab_inspect_ci"
    assert envelope["warnings"] == ["include_limit_reached"]
    assert envelope["meta"] == {"truncated": True, "sources": 25}
    assert envelope["data"] == {
        "project": {"id": 7, "path": "group/project"},
        "root": ".gitlab-ci.yml",
        "jobs": [{"name": "test", "status": "bounded"}],
    }

    assert _run_gitlab_ci(facade, result, json_mode=False) == 0
    captured = capsys.readouterr()
    assert "include_limit_reached" not in captured.out
    assert "include_limit_reached" in captured.err
    assert "truncated" in captured.err


def test_matching_explicit_and_legacy_diagnostics_are_emitted_once(
    facade, capsys
):
    result = {
        "success": True,
        "result": {
            "project": "group/project",
            "warnings": ["bounded"],
            "meta": {"truncated": False},
        },
        "warnings": ["bounded"],
        "meta": {"truncated": False},
    }

    assert _run_gitlab_ci(facade, result) == 0
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["data"] == {"project": "group/project"}
    assert envelope["warnings"] == ["bounded"]
    assert envelope["meta"] == {"truncated": False}


@pytest.mark.parametrize(
    "result",
    [
        {
            "success": True,
            "result": {"warnings": ["legacy"]},
            "warnings": ["explicit"],
        },
        {
            "success": True,
            "result": {"meta": {"truncated": True}},
            "meta": {"truncated": False},
        },
        {"success": True, "result": {"warnings": "not-a-list"}},
        {"success": True, "result": {"meta": ["not-a-map"]}},
    ],
)
def test_conflicting_or_malformed_legacy_diagnostics_fail_closed(
    facade, capsys, result
):
    assert _run_gitlab_ci(facade, result) == 4
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["error"]["category"] == "transient"
    assert envelope["error"]["message"] == "Connector returned an invalid response."


@pytest.mark.parametrize(
    "result",
    [
        {},
        {"success": True},
        {"success": 1, "result": {}},
        {"success": True, "result": float("nan")},
        {"success": True, "result": object()},
        HostileMapping(),
        {"success": True, "result": {}, "warnings": "not-a-list"},
        {"success": False, "error": {"category": "conflict"}},
        {
            "success": True,
            "result": {"credentials": "TOP-SECRET-SENTINEL"},
        },
        {
            "success": True,
            "result": {"invocationId": "INTERNAL-AUTHORITY-SENTINEL"},
        },
    ],
)
def test_malformed_or_sensitive_provider_results_become_stable_transient(
    facade, capsys, result
):
    assert _run(facade, result) == 4
    captured = capsys.readouterr()
    envelope = json.loads(captured.out)
    assert envelope["error"] == {
        "category": "transient",
        "message": "Connector returned an invalid response.",
        "remediation": "Retry the command after the connector is available.",
    }
    assert "object at" not in captured.out
    assert "TOP-SECRET-SENTINEL" not in captured.out
    assert "INTERNAL-AUTHORITY-SENTINEL" not in captured.out
    assert "RAW-MAPPING-EXCEPTION" not in captured.out
    assert "nan" not in captured.out.lower()
    assert captured.err == ""


@pytest.mark.parametrize(
    "sensitive_key",
    [
        "token",
        "access_token",
        "access-token",
        "accessToken",
        "accesstoken",
        "password",
        "userPassword",
        "userpassword",
        "secret",
        "client_secret",
        "client-secret",
        "clientSecret",
        "clientsecret",
        "api_key",
        "api-key",
        "apiKey",
        "apikey",
        "x-api-key",
        "apiKeyValue",
        "aws_access_key_id",
        "pat",
        "authorization",
        "authorizationHeader",
        "authorizationheader",
        "certificate",
        "client_certificate",
        "client-certificate",
        "clientCertificate",
        "clientcertificate",
        "private_key",
        "private-key",
        "privateKey",
        "privatekey",
        "bearer",
        "bearerToken",
        "bearertoken",
        "cookie",
        "sessionCookie",
        "sessioncookie",
    ],
)
@pytest.mark.parametrize("json_mode", [True, False])
def test_credential_bearing_key_variants_fail_closed_in_json_and_human_output(
    facade, capsys, sensitive_key, json_mode
):
    sentinel = f"SECRET-SENTINEL-{sensitive_key}"
    result = {"success": True, "result": {sensitive_key: sentinel}}

    assert _run(facade, result, json_mode=json_mode) == 4
    captured = capsys.readouterr()
    assert sentinel not in captured.out + captured.err
    if json_mode:
        assert captured.err == ""
        assert json.loads(captured.out)["error"]["category"] == "transient"
    else:
        assert captured.out == ""
        assert "Connector returned an invalid response." in captured.err


def test_legitimate_resource_keys_are_not_sensitive_substring_false_positives(
    facade, capsys
):
    result = {
        "success": True,
        "result": {
            "path": "repository/path",
            "key": "ABC-1",
            "project_key": "ABC",
            "monkey": "bounded",
        },
    }

    assert _run(facade, result) == 0
    assert json.loads(capsys.readouterr().out)["data"] == result["result"]


def test_every_json_error_is_one_envelope_without_ansi_or_diagnostics(
    facade, capsys
):
    result = {
        "success": False,
        "error": {
            "category": "conflict",
            "message": (
                "\x1b[31mConflict\x1b[0m\n"
                "\x1b]0;secret-title\x07requires review"
            ),
            "remediation": "Inspect\x00 remote state.",
            "raw": object(),
        },
        "admission": "never",
    }

    assert _run(facade, result) == 4
    captured = capsys.readouterr()
    assert captured.out.count("\n") == 1
    envelope = json.loads(captured.out)
    assert envelope["error"] == {
        "category": "conflict",
        "message": "Conflict requires review",
        "remediation": "Inspect remote state.",
    }
    assert "\x1b" not in captured.out
    assert "secret-title" not in captured.out
    assert "admission" not in captured.out
    assert captured.err == ""


def test_human_output_is_bounded_sanitized_and_routes_warnings_to_stderr(
    facade, capsys
):
    result = {
        "success": True,
        "result": [
            {"row": index, "text": "x" * 2000 + "\x1b[31mred\x1b[0m"}
            for index in range(200)
        ],
        "warnings": ["\x1b]0;hidden\x07Review bounded output."],
        "meta": {"truncated": True},
    }

    assert _run(facade, result, json_mode=False) == 0
    captured = capsys.readouterr()
    assert "\x1b" not in captured.out + captured.err
    assert "hidden" not in captured.err
    assert "Review bounded output." in captured.err
    assert len(captured.out.encode("utf-8")) <= 32 * 1024
    assert captured.out.count("\n") <= 51
    assert "banner" not in captured.out.lower()
    assert "spinner" not in captured.out.lower()


def test_human_failure_uses_stderr_only_with_remediation(facade, capsys):
    result = {
        "success": False,
        "error": {
            "category": "write_ambiguous",
            "message": "Outcome unknown.",
            "remediation": "Reconcile before retrying.",
        },
    }

    assert _run(facade, result, json_mode=False) == 5
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Outcome unknown." in captured.err
    assert "Reconcile before retrying." in captured.err


def test_both_brands_preserve_identical_normalized_success_payloads(
    facade, capsys
):
    result = {
        "success": True,
        "result": {"key": "ABC-1"},
        "warnings": ["bounded"],
        "meta": {"page": 1},
    }
    normalized = []
    for brand in ("otto", "loop24"):
        assert _run(facade, result, brand=brand) == 0
        envelope = json.loads(capsys.readouterr().out)
        normalized.append(
            (envelope["data"], envelope["warnings"], envelope["meta"])
        )
    assert normalized[0] == normalized[1]
