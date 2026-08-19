from __future__ import annotations

import hashlib
import importlib.util
import shlex
import subprocess
import sys
import types
import uuid
from collections import Counter
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-connector-cli"
MAPPING = PLUGIN / "mappings" / "supercli-0.14.1.yaml"
GENERATOR = PLUGIN / "scripts" / "build_migration_docs.py"
GUIDE = REPO / "docs" / "cli-migration" / "supercli-0.14.1.md"
DISPOSITIONS = {
    "equivalent",
    "renamed",
    "safer-different",
    "not-yet-supported",
    "no-equivalent",
}
SUPPORTED = {"equivalent", "renamed", "safer-different"}
WRITE_MARKERS = ("--dry-run", "--confirm", "write_ambiguous")
PINNED_INVENTORY_SHA256 = (
    "2c09aab7b8a84a3fc6cff2e98b8cfd40e37290fd6c05ca1ac212584cf548664c"
)


def _load_module(path: Path, label: str):
    name = f"connector_cli_migration_{label}_{uuid.uuid4().hex}"
    module = types.ModuleType(name)
    module.__file__ = str(path)
    sys.modules[name] = module
    exec(compile(path.read_bytes(), str(path), "exec"), module.__dict__)
    return module


def _load_facade():
    name = f"connector_cli_migration_facade_{uuid.uuid4().hex}"
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


_PLACEHOLDER_VALUES = {
    "<assignee>": "jsmith",
    "<branch>": "feature/test",
    "<content-id>": "12345",
    "<count>": "10",
    "<cql>": "type = page",
    "<discussion-id>": "discussion-1",
    "<group>": "group",
    "<iid>": "42",
    "<inward-key>": "ABC-1",
    "<issue-type>": "Bug",
    "<job-id>": "17",
    "<jql>": "project = ABC",
    "<key>": "ABC-1",
    "<label>": "triage",
    "<link-type>": "Blocks",
    "<name=value>": "summary=updated",
    "<outward-key>": "ABC-2",
    "<path>": "bounded.txt",
    "<pipeline-id>": "918",
    "<project>": "group/project",
    "<ref>": "main",
    "<repo>": "release-local",
    "<sha>": "a" * 40,
    "<source-branch>": "feature/test",
    "<space-key>": "ENG",
    "<target-branch>": "main",
    "<text>": "bounded text",
    "<ticket-key>": "ABC-1",
    "<transition-id>": "31",
}


def _template_argv(template: str, descriptor, *, intent: str | None) -> list[str]:
    tokens = shlex.split(template)
    assert tokens.pop(0) == "{brand}"
    argv = []
    for token in tokens:
        if token == "--dry-run|--confirm":
            assert intent in {"dry_run", "confirm"}
            argv.append("--dry-run" if intent == "dry_run" else "--confirm")
            continue
        assert "|" not in token, f"unsupported choice notation: {token}"
        if token == "<project>" and descriptor.connector_id == "ericsson-jira":
            argv.append("ABC")
        else:
            argv.append(_PLACEHOLDER_VALUES.get(token, token))
    assert not any(token.startswith("<") and token.endswith(">") for token in argv)
    return argv


@pytest.fixture(scope="module")
def document():
    assert MAPPING.is_file()
    value = yaml.safe_load(MAPPING.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


@pytest.fixture(scope="module")
def descriptors():
    return _load_module(PLUGIN / "descriptors.py", "descriptors").DESCRIPTORS


@pytest.fixture(scope="module")
def generator():
    assert GENERATOR.is_file()
    return _load_module(GENERATOR, "generator")


@pytest.fixture(scope="module")
def facade():
    return _load_facade()


def test_mapping_is_pinned_to_the_reviewed_supercli_binary(document):
    assert document["schema_version"] == "ericsson.supercli-migration/v1"
    assert document["source"] == {
        "product": "SuperCLI",
        "version": "0.14.1",
        "commit": "6645cd0bb56cc54aa4f1d49095490832c9528dbb",
        "binary_sha256": (
            "72ce9d9ad14b451b53a7f0f06786d75336a302562a8ed6d0dbafc2cb7657cc6a"
        ),
        "inventory_sha256": PINNED_INVENTORY_SHA256,
        "evidence": [
            "SUPER-CLI-ARCHITECTURE.md",
            "PLUGIN-GAP-ANALYSIS.md",
            "out/func-strings.txt",
        ],
    }


def test_inventory_is_the_exact_unique_quoted_service_command_set(document):
    rows = document["rows"]
    commands = [row["source_command"] for row in rows]
    assert len(commands) == len(set(commands)) == 108
    assert Counter(row["service"] for row in rows) == {
        "jira": 24,
        "gitlab": 46,
        "confluence": 19,
        "arm": 19,
    }
    inventory = "".join(f"{command}\n" for command in sorted(commands)).encode()
    assert hashlib.sha256(inventory).hexdigest() == PINNED_INVENTORY_SHA256
    for row in rows:
        assert row["source_command"].startswith(f"super-cli {row['service']} ")


def test_extractor_accepts_only_exact_single_quoted_commands(generator, tmp_path):
    evidence = tmp_path / "func-strings.txt"
    evidence.write_text(
        "    'super-cli jira issue view'\n"
        "    'super-cli gitlab pipeline view' | 'description'\n"
        "    'super-cli arm artifact deploysuper-cli arm artifact delete'\n"
        "    'super-cli confluence page moveList fused'\n"
        '    "super-cli jira issue list"\n'
        "    'super-cli jira issue view'\n",
        encoding="utf-8",
    )
    assert generator.extract_commands(evidence) == (
        "super-cli gitlab pipeline view",
        "super-cli jira issue view",
    )


def test_every_row_has_the_complete_review_contract(document):
    required = {
        "service",
        "source_command",
        "disposition",
        "replacement",
        "operation",
        "flag_mapping",
        "output_difference",
        "write_behavior",
        "earliest_wave",
        "rationale",
        "evidence_ref",
    }
    for row in document["rows"]:
        assert set(row) == required
        assert row["disposition"] in DISPOSITIONS
        assert isinstance(row["flag_mapping"], list)
        assert row["output_difference"]
        assert row["write_behavior"]
        assert row["earliest_wave"]
        assert row["rationale"]
        assert row["evidence_ref"]
        if row["disposition"] in SUPPORTED:
            assert row["replacement"].startswith("{brand} ")
            assert row["replacement"].count("{") == 1
            assert row["replacement"].count("}") == 1
            assert row["operation"]
        else:
            assert row["replacement"] is None
            assert row["operation"] is None


def test_supported_replacements_resolve_to_real_descriptors(document, descriptors):
    by_operation = {descriptor.operation: descriptor for descriptor in descriptors}
    supported_operations = set()
    for row in document["rows"]:
        if row["disposition"] not in SUPPORTED:
            continue
        descriptor = by_operation[row["operation"]]
        prefix = "{brand} " + " ".join(descriptor.path_tokens)
        assert row["replacement"] == prefix or row["replacement"].startswith(
            prefix + " "
        )
        supported_operations.add(row["operation"])

    new_capabilities = document["new_capabilities"]
    assert all(note["status"] == "new-capability" for note in new_capabilities)
    assert all(note["operation"] in by_operation for note in new_capabilities)
    assert all(note["replacement"].startswith("{brand} ") for note in new_capabilities)
    assert all(note["rationale"] and note["evidence_ref"] for note in new_capabilities)
    assert supported_operations | {
        note["operation"] for note in new_capabilities
    } == set(by_operation)


def test_every_supported_template_is_accepted_by_the_real_parser(
    document, descriptors, facade
):
    by_operation = {descriptor.operation: descriptor for descriptor in descriptors}
    records = [
        row for row in document["rows"] if row["disposition"] in SUPPORTED
    ] + document["new_capabilities"]
    parser = facade.build_parser(prog="otto", ctx=object())

    for record in records:
        descriptor = by_operation[record["operation"]]
        intents = ("dry_run", "confirm") if descriptor.access == "write" else (None,)
        for intent in intents:
            argv = _template_argv(
                record["replacement"], descriptor, intent=intent
            )
            parsed = parser.parse_args(argv)
            assert parsed._connector_cli_descriptor.operation == record["operation"]


def test_safety_differences_and_deliberate_gaps_are_explicit(document, descriptors):
    rows = {row["source_command"]: row for row in document["rows"]}
    writes = {descriptor.operation for descriptor in descriptors if descriptor.access == "write"}
    for row in document["rows"]:
        combined = " ".join(
            [
                str(row["flag_mapping"]),
                row["output_difference"],
                row["write_behavior"],
                row["rationale"],
            ]
        )
        if row["operation"] in writes:
            assert row["disposition"] == "safer-different"
            assert all(marker in combined for marker in WRITE_MARKERS)

    for note in document["new_capabilities"]:
        assert note["access"] == (
            "write" if note["operation"] in writes else "read"
        )
        if note["access"] == "write":
            assert all(marker in note["write_behavior"] for marker in WRITE_MARKERS)
        else:
            assert note["write_behavior"].startswith("Read-only")

    assert rows["super-cli gitlab pipeline view"]["operation"] == "gitlab_read_pipeline"
    assert rows["super-cli gitlab pipeline view"]["replacement"] == (
        "{brand} gitlab pipeline view <project> <pipeline-id>"
    )
    assert rows["super-cli arm artifact download"]["disposition"] == "no-equivalent"
    assert "checksum" in rows["super-cli arm artifact download"]["rationale"]

    unsupported_prefixes = (
        "super-cli jira board ",
        "super-cli jira sprint ",
        "super-cli gitlab release ",
        "super-cli gitlab tag ",
        "super-cli gitlab webhook ",
        "super-cli gitlab variable ",
        "super-cli gitlab todo ",
        "super-cli gitlab search code",
        "super-cli confluence page label ",
        "super-cli confluence page attachment ",
        "super-cli confluence page version ",
        "super-cli confluence page move",
        "super-cli confluence page delete",
        "super-cli confluence page append",
        "super-cli arm artifact copy",
        "super-cli arm artifact move",
        "super-cli arm artifact properties set",
        "super-cli arm artifact properties delete",
        "super-cli arm xray ",
        "super-cli arm storage ",
        "super-cli arm permission ",
    )
    for command, row in rows.items():
        if command.startswith(unsupported_prefixes):
            assert row["disposition"] in {"not-yet-supported", "no-equivalent"}

    named_branch = next(
        note
        for note in document["new_capabilities"]
        if note["operation"] == "gitlab_create_named_branch"
    )
    assert named_branch["replacement"] == (
        "{brand} gitlab branch create <project> <branch> <ref> "
        "--dry-run|--confirm"
    )
    assert "No exact pinned source command" in named_branch["rationale"]


def test_source_only_escape_hatches_are_never_claimed_as_equivalent(document):
    forbidden = ("--url", "credential", "--raw", "--no-throttle", "raw JSON")
    for row in document["rows"]:
        if row["disposition"] != "equivalent":
            continue
        claims = " ".join(
            [row["replacement"], str(row["flag_mapping"]), row["rationale"]]
        )
        assert not any(token in claims for token in forbidden)


def test_generator_is_byte_stable_and_check_detects_drift(
    document, generator, tmp_path
):
    rendered_once = generator.render_guide(document)
    rendered_twice = generator.render_guide(document)
    assert rendered_once == rendered_twice
    assert rendered_once.encode("utf-8") == GUIDE.read_bytes()

    candidate = tmp_path / "guide.md"
    candidate.write_text(rendered_once, encoding="utf-8")
    assert generator.check_document(candidate, rendered_once) is True
    candidate.write_text(rendered_once + "drift\n", encoding="utf-8")
    assert generator.check_document(candidate, rendered_once) is False

    completed = subprocess.run(
        [sys.executable, str(GENERATOR), "--check"],
        cwd=REPO,
        check=False,
        capture_output=True,
        text=True,
    )
    assert completed.returncode == 0, completed.stderr


def test_generated_guide_contains_the_required_migration_contract(document):
    guide = GUIDE.read_text(encoding="utf-8")
    assert "not drop-in compatible" in guide
    assert "## Quick start" in guide
    assert "otto jira issue get" in guide
    assert "loop24 gitlab pipeline retry" in guide
    assert "ericsson.connector-cli/v1" in guide
    assert "Exit code 5" in guide
    assert "active profile" in guide
    assert "enable" in guide
    for service in ("Jira", "GitLab", "Confluence", "ARM"):
        assert f"## {service}" in guide
    for disposition in sorted(DISPOSITIONS):
        assert disposition in guide
