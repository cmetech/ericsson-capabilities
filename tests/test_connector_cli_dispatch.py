"""Facade dispatch through the public Wave 4A application-command port."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import uuid
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-connector-cli"


def _hermes_root() -> Path:
    configured = os.environ.get("HERMES_AGENT_DIR")
    candidates = ([Path(configured)] if configured else []) + [
        ancestor / "hermes-agent" for ancestor in REPO.parents
    ]
    return next(
        candidate
        for candidate in candidates
        if (candidate / "hermes_cli" / "plugin_application_commands.py").is_file()
    )


sys.path.insert(0, str(_hermes_root()))

from hermes_cli.plugin_application_commands import (  # noqa: E402
    PluginApplicationCommandDenied,
    PluginApplicationCommandExecutionError,
    PluginApplicationCommandInvalid,
    PluginApplicationCommandUnavailable,
)


def _load_facade():
    name = f"connector_cli_dispatch_{uuid.uuid4().hex}"
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
    def __init__(self, result=None, failure=None):
        self.result = result or {"success": True, "result": {"bounded": "value"}}
        self.failure = failure
        self.calls = []

    def invoke_application_command(
        self, provider_id, operation, arguments, *, mode, invocation_id
    ):
        self.calls.append(
            (provider_id, operation, arguments, mode, invocation_id)
        )
        if self.failure is not None:
            raise self.failure
        return self.result


@pytest.mark.parametrize(
    ("argv", "expected"),
    [
        (
            ["jira", "issue", "get", "ABC-1", "--json"],
            ("ericsson-jira", "jira_get_issue", {"key": "ABC-1"}, "read"),
        ),
        (
            [
                "jira", "issue", "comment", "ABC-1", "--body-file", "-",
                "--dry-run", "--json",
            ],
            (
                "ericsson-jira",
                "jira_add_comment",
                {"key": "ABC-1", "body": "bounded body"},
                "dry_run",
            ),
        ),
        (
            [
                "jira", "issue", "comment", "ABC-1", "--body-file", "-",
                "--confirm", "--json",
            ],
            (
                "ericsson-jira",
                "jira_add_comment",
                {"key": "ABC-1", "body": "bounded body"},
                "confirm",
            ),
        ),
    ],
)
def test_read_dry_run_and_confirm_use_one_public_host_call(
    facade, argv, expected, monkeypatch, capsys
):
    context = Context()
    parser = facade.build_parser(prog="otto", ctx=context)
    monkeypatch.setattr(
        facade.local_io.BoundedInputReader,
        "read_text",
        lambda *args, **kwargs: "bounded body",
    )

    parsed = parser.parse_args(argv)
    assert parsed.func(parsed) == 0

    assert len(context.calls) == 1
    provider, operation, arguments, mode, invocation_id = context.calls[0]
    assert (provider, operation, arguments, mode) == expected
    assert uuid.UUID(invocation_id)
    assert json.loads(capsys.readouterr().out)["ok"] is True


def test_disabled_provider_has_current_brand_enablement_remediation(
    facade, capsys
):
    context = Context(failure=PluginApplicationCommandUnavailable())
    parser = facade.build_parser(prog="loop24", ctx=context)

    parsed = parser.parse_args(["jira", "issue", "get", "ABC-1", "--json"])
    assert parsed.func(parsed) == 3

    envelope = json.loads(capsys.readouterr().out)
    assert envelope["error"] == {
        "category": "unavailable",
        "message": "Jira connector is unavailable.",
        "remediation": (
            "Enable the connector for the active profile with: "
            "loop24 plugins enable ericsson-jira"
        ),
    }
    assert "otto" not in envelope["error"]["remediation"]


@pytest.mark.parametrize(
    ("failure", "category"),
    [
        (PluginApplicationCommandInvalid(), "invalid_input"),
        (PluginApplicationCommandDenied(), "permission"),
    ],
)
def test_host_invalid_and_denied_are_usage_failures_without_provider_details(
    facade, capsys, failure, category
):
    context = Context(failure=failure)
    parser = facade.build_parser(prog="otto", ctx=context)
    parsed = parser.parse_args(["jira", "issue", "get", "ABC-1", "--json"])

    assert parsed.func(parsed) == 2
    output = capsys.readouterr().out
    envelope = json.loads(output)
    assert envelope["error"]["category"] == category
    assert "provider" not in output.lower()
    assert "ericsson-jira" not in output


def test_public_host_execution_failure_is_stable_transient(facade, capsys):
    context = Context(failure=PluginApplicationCommandExecutionError())
    parsed = facade.build_parser(prog="otto", ctx=context).parse_args(
        ["jira", "issue", "get", "ABC-1", "--json"]
    )

    assert parsed.func(parsed) == 4
    envelope = json.loads(capsys.readouterr().out)
    assert envelope["error"] == {
        "category": "transient",
        "message": "Connector command execution failed.",
        "remediation": "Retry the command after the connector is available.",
    }


@pytest.mark.parametrize("category", ["invalid_configuration", "authentication", "readiness"])
def test_connector_readiness_categories_use_exit_three(facade, capsys, category):
    context = Context(
        result={
            "success": False,
            "error": {
                "category": category,
                "message": "Safe connector-owned message.",
                "remediation": "Safe connector-owned remediation.",
            },
        }
    )
    parsed = facade.build_parser(prog="otto", ctx=context).parse_args(
        ["jira", "issue", "get", "ABC-1", "--json"]
    )

    assert parsed.func(parsed) == 3
    assert json.loads(capsys.readouterr().out)["error"] == context.result["error"]


@pytest.mark.parametrize("category", ["conflict", "permission"])
def test_ordinary_connector_error_uses_exit_four(facade, capsys, category):
    result = {
        "success": False,
        "error": {"category": category, "message": "Safe connector error."},
    }
    parsed = facade.build_parser(prog="otto", ctx=Context(result=result)).parse_args(
        ["jira", "issue", "get", "ABC-1", "--json"]
    )

    assert parsed.func(parsed) == 4
    assert json.loads(capsys.readouterr().out)["error"] == result["error"]


def test_write_ambiguous_uses_exit_five_and_preserves_remediation(facade, capsys):
    result = {
        "success": False,
        "error": {
            "category": "write_ambiguous",
            "message": "The write outcome is unknown.",
            "remediation": "Reconcile the remote state before retrying.",
        },
    }
    parsed = facade.build_parser(prog="otto", ctx=Context(result=result)).parse_args(
        ["jira", "issue", "get", "ABC-1", "--json"]
    )

    assert parsed.func(parsed) == 5
    assert json.loads(capsys.readouterr().out)["error"] == result["error"]
