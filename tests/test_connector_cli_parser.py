from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import uuid
from pathlib import Path

import pytest


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-connector-cli"


def _load_facade():
    name = f"connector_cli_parser_{uuid.uuid4().hex}"
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


class RecordingContext:
    def __init__(self):
        self.calls = []

    def invoke_application_command(
        self, provider_id, operation, arguments, *, mode, invocation_id
    ):
        self.calls.append(
            (provider_id, operation, arguments, mode, invocation_id)
        )
        return {"success": True, "result": arguments}


def _value(binding):
    if binding.choices:
        return str(binding.choices[0])
    if binding.value_type == "integer":
        return str(binding.minimum if binding.minimum is not None else 1)
    if binding.value_type == "string_or_integer":
        return "group/project"
    if binding.value_type == "nullable_string":
        return "user@example.com"
    if binding.value_type == "field_assignment":
        return 'summary="updated"'
    if binding.value_type in {
        "continuation",
        "group_continuation",
        "project_continuation",
    }:
        return "page=1"
    if binding.pattern:
        if "0-9a-f" in binding.pattern:
            return "a" * 7
        if "0-9" in binding.pattern:
            return "1"
    size = max(binding.min_length or 1, 5)
    return "v" * size


def _minimum_argv(descriptor, tmp_path, *, intent="dry_run"):
    argv = list(descriptor.path_tokens)
    for binding in descriptor.positional_bindings:
        argv.append(_value(binding))
    chosen_groups = set()
    for binding in descriptor.option_bindings:
        if binding.mutually_exclusive_group:
            if binding.mutually_exclusive_group in chosen_groups:
                continue
            if binding.mutually_exclusive_group_required:
                chosen_groups.add(binding.mutually_exclusive_group)
            else:
                continue
        elif not binding.required:
            continue
        argv.append(binding.public_name)
        if binding.value_type != "boolean":
            argv.append(_value(binding))
    for binding in descriptor.file_bindings:
        if binding.mutually_exclusive_group:
            if binding.mutually_exclusive_group in chosen_groups:
                continue
            if not binding.mutually_exclusive_group_required:
                continue
            chosen_groups.add(binding.mutually_exclusive_group)
        elif not binding.required:
            continue
        if binding.value_type == "change_object_file":
            content = '{"action":"delete","file_path":"old.txt"}'
        else:
            content = "bounded input"
        path = tmp_path / f"{descriptor.operation}-{binding.target_schema_property}.txt"
        path.write_text(content, encoding="utf-8")
        argv.extend((binding.public_name, str(path)))
    if descriptor.access == "write":
        argv.append("--dry-run" if intent == "dry_run" else "--confirm")
    return argv


def _normal_help(text, brand):
    return " ".join(text.replace(brand, "{brand}").split())


def test_all_60_descriptors_have_help_and_a_minimum_valid_parse(
    facade, tmp_path, capsys
):
    context = RecordingContext()
    for brand in ("otto", "loop24"):
        parser = facade.build_parser(prog=brand, ctx=context)
        for descriptor in facade.DESCRIPTORS:
            argv = _minimum_argv(descriptor, tmp_path)
            namespace = parser.parse_args(argv)
            assert namespace._connector_cli_descriptor is descriptor
            assert callable(namespace.func)
            with pytest.raises(SystemExit) as stopped:
                parser.parse_args([*descriptor.path_tokens, "--help"])
            assert stopped.value.code == 0
            assert descriptor.operation in capsys.readouterr().out


def test_all_60_minimum_parses_map_to_one_canonical_host_call(facade, tmp_path):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    for descriptor in facade.DESCRIPTORS:
        parsed = parser.parse_args(_minimum_argv(descriptor, tmp_path))
        before = len(context.calls)
        assert parsed.func(parsed) == 0, descriptor.operation
        assert len(context.calls) == before + 1
        provider, operation, arguments, mode, invocation_id = context.calls[-1]
        assert provider == descriptor.connector_id
        assert operation == descriptor.operation
        assert mode == ("read" if descriptor.access == "read" else "dry_run")
        assert set(arguments) == {
            binding.target_schema_property
            for binding in (
                descriptor.positional_bindings
                + descriptor.option_bindings
                + descriptor.file_bindings
            )
            if binding.required or binding.mutually_exclusive_group_required
        }
        assert uuid.UUID(invocation_id)


def test_brands_have_identical_grammar_and_help_below_executable(
    facade, tmp_path, capsys
):
    context = RecordingContext()
    argv = _minimum_argv(
        next(d for d in facade.DESCRIPTORS if d.operation == "gitlab_read_pipeline"),
        tmp_path,
    )
    parsed = []
    helps = []
    for brand in ("otto", "loop24"):
        parser = facade.build_parser(prog=brand, ctx=context)
        parsed.append(vars(parser.parse_args(argv)))
        with pytest.raises(SystemExit):
            parser.parse_args(["gitlab", "pipeline", "view", "--help"])
        helps.append(_normal_help(capsys.readouterr().out, brand))
    for internal in ("func", "_connector_cli_ctx"):
        parsed[0].pop(internal)
        parsed[1].pop(internal)
    assert parsed[0] == parsed[1]
    assert helps[0] == helps[1]


def test_every_write_requires_exactly_one_intent_before_any_local_or_host_work(
    facade, tmp_path, monkeypatch
):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    touched = []
    monkeypatch.setattr(
        facade.local_io.BoundedInputReader,
        "read_text",
        lambda *args, **kwargs: touched.append("file") or "unexpected",
    )

    for descriptor in (d for d in facade.DESCRIPTORS if d.access == "write"):
        argv = _minimum_argv(descriptor, tmp_path)
        with pytest.raises(SystemExit) as missing:
            parser.parse_args(argv[:-1])
        assert missing.value.code == 2
        with pytest.raises(SystemExit) as both:
            parser.parse_args([*argv, "--confirm"])
        assert both.value.code == 2
        assert touched == []
        assert context.calls == []

        for intent in ("dry_run", "confirm"):
            parsed = parser.parse_args(
                _minimum_argv(descriptor, tmp_path, intent=intent)
            )
            assert getattr(parsed, intent) is True


def test_unknown_commands_flags_missing_values_enums_and_integer_bounds_fail(
    facade,
):
    parser = facade.build_parser(prog="otto", ctx=RecordingContext())
    bad_argv = (
        ["unknown"],
        ["jira", "issue", "get", "ABC-1", "--unknown"],
        ["jira", "issue", "get"],
        ["jira", "issue", "label", "ABC-1", "replace", "x", "--dry-run"],
        ["gitlab", "pipeline", "view", "group/project", "0"],
        ["jira", "issue", "mine", "--max-results", "101"],
    )
    for argv in bad_argv:
        with pytest.raises(SystemExit) as stopped:
            parser.parse_args(argv)
        assert stopped.value.code == 2


@pytest.mark.parametrize(
    ("argv", "connector", "operation", "mode"),
    [
        (["unknown", "--json"], "connector", "invalid_command", "invalid"),
        (["jira", "unknown", "--json"], "jira", "invalid_command", "invalid"),
        (
            ["jira", "issue", "get", "ABC-1", "--unknown", "--json"],
            "jira",
            "jira_get_issue",
            "read",
        ),
        (
            ["jira", "issue", "get", "--json"],
            "jira",
            "jira_get_issue",
            "read",
        ),
        (
            [
                "jira", "issue", "label", "ABC-1", "replace", "x",
                "--dry-run", "--json",
            ],
            "jira",
            "jira_manage_labels",
            "dry_run",
        ),
        (
            ["gitlab", "pipeline", "view", "group/project", "0", "--json"],
            "gitlab",
            "gitlab_read_pipeline",
            "read",
        ),
        (
            ["jira", "issue", "mine", "--max-results", "--json"],
            "jira",
            "jira_my_tickets",
            "read",
        ),
        (
            [
                "jira", "issue", "comment", "ABC-1", "--body-file", "body.md",
                "--json",
            ],
            "jira",
            "jira_add_comment",
            "invalid",
        ),
        (
            [
                "jira", "issue", "comment", "ABC-1", "--body-file", "body.md",
                "--dry-run", "--confirm", "--json",
            ],
            "jira",
            "jira_add_comment",
            "invalid",
        ),
    ],
)
def test_json_parse_failures_emit_one_stable_envelope_before_any_work(
    facade, capsys, monkeypatch, argv, connector, operation, mode
):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    touched = []
    monkeypatch.setattr(
        facade.local_io.BoundedInputReader,
        "read_text",
        lambda *args, **kwargs: touched.append("file") or "unexpected",
    )
    monkeypatch.setattr(
        facade.parser.uuid,
        "uuid4",
        lambda: touched.append("uuid") or uuid.UUID(int=1),
    )

    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(argv)

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "schema_version": "ericsson.connector-cli/v1",
        "ok": False,
        "connector": connector,
        "operation": operation,
        "mode": mode,
        "error": {
            "category": "invalid_input",
            "message": "Connector command usage is invalid.",
            "remediation": "Review the command help and try again.",
        },
    }
    assert "\x1b" not in captured.out
    assert "object at" not in captured.out
    assert touched == []
    assert context.calls == []


def test_human_parse_failures_keep_normal_argparse_usage(facade, capsys):
    parser = facade.build_parser(prog="otto", ctx=RecordingContext())

    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(["jira", "issue", "get"])

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "usage:" in captured.err
    assert "required" in captured.err
    assert "ericsson.connector-cli/v1" not in captured.err


def test_host_owned_domain_parser_uses_same_json_error_contract(facade, capsys):
    context = RecordingContext()
    host = argparse.ArgumentParser(prog="loop24")
    domains = host.add_subparsers(dest="command", required=True)
    jira = domains.add_parser("jira")
    facade.parser.add_domain_commands(jira, "jira", context)

    with pytest.raises(SystemExit) as stopped:
        host.parse_args(["jira", "unknown", "--json"])

    assert stopped.value.code == 2
    captured = capsys.readouterr()
    assert captured.err == ""
    envelope = json.loads(captured.out)
    assert envelope["connector"] == "jira"
    assert envelope["operation"] == "invalid_command"
    assert envelope["mode"] == "invalid"
    assert envelope["error"]["category"] == "invalid_input"
    assert context.calls == []


def test_canonical_mapping_decodes_structured_values_and_strips_cli_objects(
    facade, tmp_path
):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    parsed = parser.parse_args(
        [
            "jira",
            "issue",
            "update",
            "ABC-1",
            "--field",
            'summary="new title"',
            "--field",
            "labels=[\"safe\"]",
            "--confirm",
            "--json",
        ]
    )
    assert parsed.func(parsed) == 0
    provider, operation, arguments, mode, invocation_id = context.calls[-1]
    assert (provider, operation, mode) == (
        "ericsson-jira",
        "jira_update_fields",
        "confirm",
    )
    assert arguments == {
        "key": "ABC-1",
        "fields": {"summary": "new title", "labels": ["safe"]},
    }
    assert uuid.UUID(invocation_id)
    assert not {
        "dry_run",
        "confirm",
        "json",
        "func",
        "descriptor",
        "handler",
    } & set(arguments)


def test_structured_duplicates_and_malformed_values_fail_before_dispatch(
    facade,
):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    for values in (
        ["summary=1", "summary=2"],
        ["missing-separator"],
        ["=value"],
        [f"{'n' * 129}=1"],
        [f"summary={repr('x' * 16385)}"],
    ):
        argv = ["jira", "issue", "update", "ABC-1"]
        for value in values:
            argv.extend(("--field", value))
        argv.append("--dry-run")
        parsed = parser.parse_args(argv)
        assert parsed.func(parsed) == 2
    assert context.calls == []


def test_continuation_flags_merge_to_canonical_mapping(facade):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    parsed = parser.parse_args(
        [
            "gitlab",
            "group",
            "project-list",
            "group/path",
            "--group-continuation",
            "page=2",
            "--group-continuation",
            "offset=4",
            "--project-continuation",
            "next_page=3",
        ]
    )
    assert parsed.func(parsed) == 0
    assert context.calls[-1][2] == {
        "group": "group/path",
        "continuation": {
            "groups": {"page": 2, "offset": 4},
            "projects": {"next_page": 3},
        },
    }


@pytest.mark.parametrize(
    ("argv", "field", "expected"),
    [
        (
            [
                "gitlab", "mr", "discussion-resolve", "group/project", "7",
                "discussion-1", "--resolved", "--confirm",
            ],
            "resolved",
            True,
        ),
        (
            [
                "gitlab", "mr", "discussion-resolve", "group/project", "7",
                "discussion-1", "--no-resolved", "--confirm",
            ],
            "resolved",
            False,
        ),
        (
            [
                "gitlab", "mr", "update", "group/project", "7", "--draft",
                "--confirm",
            ],
            "draft",
            True,
        ),
        (
            [
                "gitlab", "mr", "update", "group/project", "7",
                "--no-draft", "--confirm",
            ],
            "draft",
            False,
        ),
    ],
)
def test_boolean_options_preserve_explicit_true_and_false(
    facade, argv, field, expected
):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    parsed = parser.parse_args(argv)
    assert parsed.func(parsed) == 0
    assert context.calls[-1][2][field] is expected


def test_boolean_help_exposes_positive_and_negative_forms(facade, capsys):
    parser = facade.build_parser(prog="otto", ctx=RecordingContext())
    with pytest.raises(SystemExit) as stopped:
        parser.parse_args(["gitlab", "mr", "discussion-resolve", "--help"])
    assert stopped.value.code == 0
    help_text = capsys.readouterr().out
    assert "--resolved" in help_text
    assert "--no-resolved" in help_text


@pytest.mark.parametrize(
    ("assignee", "expected"),
    [
        ("user@example.com", "user@example.com"),
        ("null", None),
        ('"null"', "null"),
    ],
)
def test_nullable_assignee_distinguishes_unassign_from_literal_null(
    facade, assignee, expected
):
    context = RecordingContext()
    parser = facade.build_parser(prog="otto", ctx=context)
    parsed = parser.parse_args(
        ["jira", "issue", "assign", "ABC-1", assignee, "--confirm"]
    )
    assert parsed.func(parsed) == 0
    assert context.calls[-1][2] == {"key": "ABC-1", "assignee": expected}


def test_uuid_is_created_only_after_inputs_are_valid_and_immediately_before_dispatch(
    facade, tmp_path, monkeypatch
):
    events = []

    class Context(RecordingContext):
        def invoke_application_command(self, *args, **kwargs):
            events.append("dispatch")
            return super().invoke_application_command(*args, **kwargs)

    context = Context()
    parser = facade.build_parser(prog="otto", ctx=context)
    body = tmp_path / "body.txt"
    body.write_text("hello", encoding="utf-8")
    monkeypatch.setattr(
        facade.parser.uuid,
        "uuid4",
        lambda: events.append("uuid") or uuid.UUID(int=1),
    )
    parsed = parser.parse_args(
        [
            "jira", "issue", "comment", "ABC-1",
            "--body-file", str(body), "--confirm",
        ]
    )
    assert parsed.func(parsed) == 0
    assert events == ["uuid", "dispatch"]
