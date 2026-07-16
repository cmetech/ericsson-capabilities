from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


SCRIPTS_DIR = (
    Path(__file__).resolve().parents[1]
    / "skills/ericsson/onboard-ericsson-capabilities/scripts"
)
sys.path.insert(0, str(SCRIPTS_DIR))

from catalog_lib import (  # noqa: E402
    CatalogError,
    build_catalog,
    load_entries,
    read_frontmatter,
    serialize_catalog,
    validate_repository,
)


COMPACT_KEYS = {
    "id",
    "displayName",
    "aliases",
    "goals",
    "maturity",
    "recommendationEligible",
    "entry",
}

EXPECTED_IDS = {
    "ericsson-capability-onboarding",
    "opportunity-visuals",
    "jira-assigned-ticket-summary",
    "jira-tools",
    "teams-tools",
    "outlook-tools",
    "outlook-inbox-digest",
    "glean-search",
    "workflow-orchestrator",
    "workflow-builder",
    "ci-file-auditor",
    "tol-generation",
    "jira-to-gitlab",
    "jira-defect-loop",
    "third-party-support-lcm-tracker",
    "pseudonymization",
    "re-identification",
    "windows-laptop-diagnostic",
}

EMPTY_IMPLEMENTATION = {
    "skills": [],
    "plugins": [],
    "mcp_servers": [],
    "workflows": [],
    "tools": [],
}

EXPECTED_REAL_ENTRY_CONTRACT = {
    "ericsson-capability-onboarding": (
        "available",
        False,
        EMPTY_IMPLEMENTATION
        | {"skills": ["skills/ericsson/onboard-ericsson-capabilities"]},
    ),
    "opportunity-visuals": (
        "available",
        True,
        EMPTY_IMPLEMENTATION
        | {"skills": ["skills/ericsson/opportunity-visuals"]},
    ),
    "jira-assigned-ticket-summary": (
        "available",
        True,
        EMPTY_IMPLEMENTATION
        | {
            "plugins": ["plugins/ericsson-jira"],
            "workflows": ["workflows/my-tickets-summary.yml"],
            "tools": ["jira_my_tickets"],
        },
    ),
    "jira-tools": (
        "available",
        True,
        EMPTY_IMPLEMENTATION
        | {
            "plugins": ["plugins/ericsson-jira"],
            "tools": ["jira_my_tickets", "jira_get_issue", "jira_add_comment"],
        },
    ),
    "teams-tools": (
        "available",
        True,
        EMPTY_IMPLEMENTATION
        | {
            "plugins": ["plugins/ericsson-teams"],
            "tools": [
                "teams_auth",
                "teams_list",
                "teams_channels",
                "teams_read",
                "teams_send",
                "teams_reply",
            ],
        },
    ),
    "outlook-tools": (
        "available",
        True,
        EMPTY_IMPLEMENTATION | {"mcp_servers": ["outlook"]},
    ),
    "outlook-inbox-digest": (
        "available",
        True,
        EMPTY_IMPLEMENTATION
        | {
            "mcp_servers": ["outlook"],
            "workflows": ["workflows/inbox-digest.yml"],
        },
    ),
    "glean-search": (
        "available",
        True,
        EMPTY_IMPLEMENTATION | {"mcp_servers": ["glean"]},
    ),
    "workflow-orchestrator": (
        "available",
        True,
        EMPTY_IMPLEMENTATION
        | {"skills": ["skills/ericsson/workflow-orchestrator"]},
    ),
    "workflow-builder": (
        "available",
        True,
        EMPTY_IMPLEMENTATION | {"skills": ["skills/ericsson/workflow-builder"]},
    ),
    "ci-file-auditor": (
        "planned-not-implemented",
        False,
        EMPTY_IMPLEMENTATION,
    ),
    "tol-generation": ("planned-not-implemented", False, EMPTY_IMPLEMENTATION),
    "jira-to-gitlab": ("partially-ported", False, EMPTY_IMPLEMENTATION),
    "jira-defect-loop": ("partially-ported", False, EMPTY_IMPLEMENTATION),
    "third-party-support-lcm-tracker": (
        "planned-not-implemented",
        False,
        EMPTY_IMPLEMENTATION,
    ),
    "pseudonymization": (
        "not-supported-no-port-planned",
        False,
        EMPTY_IMPLEMENTATION,
    ),
    "re-identification": (
        "planned-not-implemented",
        False,
        EMPTY_IMPLEMENTATION,
    ),
    "windows-laptop-diagnostic": (
        "planned-not-implemented",
        False,
        EMPTY_IMPLEMENTATION,
    ),
}

EXPECTED_CRITICAL_CONFIGURATION = {
    "opportunity-visuals": {
        ("openpyxl", "local-software", False),
        ("Playwright", "local-software", False),
        ("Chromium", "local-software", False),
    },
    "jira-assigned-ticket-summary": {
        ("JIRA_BASE_URL", "static-setting", True),
        ("JIRA_PAT", "static-secret", True),
        ("deliver_to", "workflow-input", False),
        ("Windows", "local-software", False),
        ("Classic Outlook desktop", "local-software", False),
        ("PowerShell and Outlook COM", "local-software", False),
        ("Outlook mailbox access", "permission", False),
        ("Outlook MCP", "local-software", False),
    },
    "jira-tools": {
        ("JIRA_BASE_URL", "static-setting", True),
        ("JIRA_PAT", "static-secret", True),
    },
    "teams-tools": {
        ("ERICSSON_GRAPH_CLIENT_ID", "static-setting", False),
        ("msal", "local-software", True),
        ("Microsoft device code", "interactive-sign-in", True),
        ("Microsoft Graph permissions", "permission", True),
    },
    "outlook-tools": {
        ("Windows", "local-software", True),
        ("Classic Outlook desktop", "local-software", True),
        ("PowerShell and Outlook COM", "local-software", True),
        ("Outlook mailbox access", "permission", True),
    },
    "outlook-inbox-digest": {
        ("Windows", "local-software", True),
        ("Classic Outlook desktop", "local-software", True),
        ("PowerShell and Outlook COM", "local-software", True),
        ("Outlook mailbox access", "permission", True),
        ("since", "workflow-input", False),
        ("limit", "workflow-input", False),
    },
    "glean-search": {
        ("GLEAN_API_TOKEN", "static-secret", True),
    },
}

ALLOWED_DEMONSTRATION_MODES = {
    "synthetic-offline",
    "simulated",
    "read-only-live",
    "approved-live",
}

REQUIRED_ENTRY_HEADINGS = {
    "#",
    "## What it solves",
    "## Try saying",
    "## Questions",
    "## Reads and writes",
    "## Readiness",
    "## Demonstration",
    "## Artifacts",
    "## Troubleshooting",
}


class RepoFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.entry_dir = (
            root
            / "skills/ericsson/onboard-ericsson-capabilities/references/capabilities"
        )
        self.entry_dir.mkdir(parents=True)

        self._write_json(
            "sets/ericsson.json",
            {
                "name": "ericsson",
                "version": "1.2.3",
                "skills": ["skills/ericsson/example"],
                "plugins": ["plugins/ericsson-example"],
                "mcpServers": "mcp/mcp-servers.yaml",
                "mcpLocal": ["mcp/example-mcp"],
                "workflows": ["workflows/example.yml"],
                "env": [],
            },
        )
        self._write_markdown(
            "skills/ericsson/example/SKILL.md",
            {
                "name": "example",
                "description": "Example skill.",
                "platforms": ["linux", "macos", "windows"],
            },
            "# Example\n",
        )
        self._write_yaml(
            "plugins/ericsson-example/plugin.yaml",
            {
                "name": "ericsson-example",
                "kind": "backend",
                "provides_tools": ["example_tool"],
                "requires_env": [],
                "optional_env": [],
            },
        )
        self._write_text(
            "plugins/ericsson-example/example_tools.py",
            "SCHEMAS = {\n"
            "    'example_tool': {\n"
            "        'name': 'example_tool',\n"
            "        'description': 'Example tool.',\n"
            "        'parameters': {'type': 'object', 'properties': {}},\n"
            "    },\n"
            "}\n",
        )
        self._write_text(
            "plugins/ericsson-example/__init__.py",
            "import example_tools\n\n"
            "def register(ctx):\n"
            "    handlers = {'example_tool': lambda args: args}\n"
            "    for name, schema in example_tools.SCHEMAS.items():\n"
            "        ctx.register_tool(name=name, schema=schema, handler=handlers[name])\n",
        )
        self._write_text("mcp/example-mcp/run_server.py", "")
        self._write_yaml(
            "mcp/mcp-servers.yaml",
            {
                "mcp_servers": {
                    "example-mcp": {
                        "command": "python",
                        "args": ["${CAPABILITY_DIR}/example-mcp/run_server.py"],
                    }
                }
            },
        )
        self._write_yaml(
            "workflows/example.yml",
            {
                "name": "example",
                "requires": {"env": []},
                "nodes": [],
            },
        )
        self._write_markdown(
            "docs/flows/example.md",
            {
                "status": "intent-ported",
                "target_artifacts": [
                    "example",
                    "ericsson-example",
                    "example-mcp",
                ],
                "platforms": ["linux", "macos", "windows"],
            },
            "# Example flow\n",
        )
        self._write_markdown(
            "docs/flows/_template.md",
            {
                "status": "not-ported",
                "target_artifacts": [],
                "platforms": ["linux", "macos", "windows"],
            },
            "# Template\n",
        )

    def _write_text(self, relative: str, text: str) -> None:
        path = self.root / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")

    def _write_json(self, relative: str, value: object) -> None:
        self._write_text(relative, json.dumps(value, indent=2) + "\n")

    def _write_yaml(self, relative: str, value: object) -> None:
        self._write_text(relative, yaml.safe_dump(value, sort_keys=False))

    def _write_markdown(
        self, relative: str, frontmatter: object, body: str = "# Entry\n"
    ) -> None:
        self._write_text(
            relative,
            "---\n"
            + yaml.safe_dump(frontmatter, sort_keys=False)
            + "---\n\n"
            + body,
        )

    def write_entry(self, frontmatter: object, filename: str = "example.md") -> Path:
        path = self.entry_dir / filename
        self._write_markdown(str(path.relative_to(self.root)), frontmatter)
        return path

    def complete_entry_metadata(self, **overrides: object) -> dict[str, object]:
        entry = {
            "id": "example",
            "display_name": "Example",
            "aliases": ["example capability"],
            "goals": ["Explain the example capability."],
            "maturity": "available",
            "recommendation_eligible": True,
            "source_flows": ["docs/flows/example.md"],
            "implementation": {
                "skills": ["skills/ericsson/example"],
                "plugins": ["plugins/ericsson-example"],
                "mcp_servers": ["example-mcp"],
                "workflows": ["workflows/example.yml"],
                "tools": ["example_tool"],
            },
            "platforms": ["linux", "macos", "windows"],
            "configuration": [],
            "reads": ["synthetic input"],
            "writes": [],
            "artifacts": [],
            "demonstrations": ["synthetic-offline"],
            "troubleshooting": ["missing dependency"],
        }
        entry.update(overrides)
        return entry

    def write_complete_entry(self, **overrides: object) -> Path:
        return self.write_entry(self.complete_entry_metadata(**overrides))


@pytest.fixture
def repo_fixture(tmp_path: Path) -> RepoFixture:
    return RepoFixture(tmp_path)


def test_real_catalog_has_complete_unique_product_inventory() -> None:
    repo = Path(__file__).resolve().parents[1]
    entries = load_entries(repo)
    ids = [entry["id"] for entry in entries]
    assert len(ids) == len(set(ids))
    assert set(ids) == EXPECTED_IDS


def test_real_repository_runtime_and_onboarding_contracts_are_reconciled() -> None:
    repo = Path(__file__).resolve().parents[1]
    assert validate_repository(repo, load_entries(repo)) == []


def test_real_catalog_maturity_is_honest() -> None:
    repo = Path(__file__).resolve().parents[1]
    entries = {entry["id"]: entry for entry in load_entries(repo)}

    assert entries["pseudonymization"]["maturity"] == (
        "not-supported-no-port-planned"
    )
    assert entries["pseudonymization"]["recommendation_eligible"] is False
    assert entries["jira-to-gitlab"]["maturity"] == "partially-ported"
    assert entries["jira-defect-loop"]["maturity"] == "partially-ported"

    planned = {
        "ci-file-auditor",
        "tol-generation",
        "third-party-support-lcm-tracker",
        "re-identification",
        "windows-laptop-diagnostic",
    }
    assert {
        entry_id
        for entry_id in planned
        if entries[entry_id]["maturity"] != "planned-not-implemented"
    } == set()


@pytest.mark.parametrize(
    ("entry_id", "expected"),
    sorted(EXPECTED_REAL_ENTRY_CONTRACT.items()),
)
def test_real_entry_contract_pins_status_and_implementation(
    entry_id: str,
    expected: tuple[str, bool, dict[str, list[str]]],
) -> None:
    repo = Path(__file__).resolve().parents[1]
    entries = {entry["id"]: entry for entry in load_entries(repo)}
    maturity, eligible, implementation = expected
    assert entries[entry_id]["maturity"] == maturity
    assert entries[entry_id]["recommendation_eligible"] is eligible
    assert entries[entry_id]["implementation"] == implementation


@pytest.mark.parametrize(
    ("entry_id", "expected"),
    sorted(EXPECTED_CRITICAL_CONFIGURATION.items()),
)
def test_real_entry_contract_pins_critical_configuration(
    entry_id: str, expected: set[tuple[str, str, bool]]
) -> None:
    repo = Path(__file__).resolve().parents[1]
    entries = {entry["id"]: entry for entry in load_entries(repo)}
    actual = {
        (item["name"], item["kind"], item["required"])
        for item in entries[entry_id]["configuration"]
    }
    assert actual == expected


def test_real_entry_demonstration_modes_use_approved_vocabulary() -> None:
    repo = Path(__file__).resolve().parents[1]
    for entry in load_entries(repo):
        assert set(entry["demonstrations"]) <= ALLOWED_DEMONSTRATION_MODES, entry[
            "id"
        ]


def test_assigned_ticket_entry_separates_fixed_workflow_from_optional_email() -> None:
    repo = Path(__file__).resolve().parents[1]
    body = (
        repo
        / "skills/ericsson/onboard-ericsson-capabilities/references/capabilities"
        / "jira-assigned-ticket-summary.md"
    ).read_text(encoding="utf-8")
    assert "bundled workflow is fixed at 25" in body
    assert "direct `jira_my_tickets(max_results=...)`" in body
    assert "Email readiness additionally requires Windows" in body
    assert "whether the default 25-ticket limit is suitable" not in body


def test_jira_and_teams_entries_teach_only_supported_narrowing() -> None:
    repo = Path(__file__).resolve().parents[1]
    entry_dir = (
        repo
        / "skills/ericsson/onboard-ericsson-capabilities/references/capabilities"
    )
    jira = (entry_dir / "jira-tools.md").read_text(encoding="utf-8")
    teams = (entry_dir / "teams-tools.md").read_text(encoding="utf-8")
    assert "supported result limit" in jira
    assert "status or project filter" not in jira
    assert "supported team, channel, and message count" in teams
    assert "date filter" not in teams


def test_real_capability_entries_have_the_education_contract() -> None:
    repo = Path(__file__).resolve().parents[1]
    entries = load_entries(repo)

    for entry in entries:
        body = Path(entry["_path"]).read_text(encoding="utf-8")
        assert len(entry["goals"]) >= 3, entry["id"]
        for heading in REQUIRED_ENTRY_HEADINGS:
            assert heading in body, f"{entry['id']}: missing {heading}"
        for topic in (
            "filter",
            "preview",
            "format",
            "destination",
            "exclusion",
            "warning",
            "rerun",
        ):
            assert topic in body.lower(), f"{entry['id']}: missing {topic} guidance"


def test_frontmatter_requires_stable_fields(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_entry({"id": "only-an-id"})
    with pytest.raises(CatalogError, match="missing required fields"):
        load_entries(repo_fixture.root)


def test_compact_catalog_omits_detailed_guidance(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry()
    item = build_catalog(repo_fixture.root)["capabilities"][0]
    assert set(item) == COMPACT_KEYS
    assert "configuration" not in item
    assert "writes" not in item
    assert item["entry"] == "references/capabilities/example.md"


def test_validation_reports_unrepresented_manifest_component(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry(
        implementation={"skills": [], "tools": ["example_tool"]}
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unrepresented manifest skill: skills/ericsson/example" in problems


def test_validation_reports_unrepresented_flow(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry(source_flows=[])
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unrepresented flow: docs/flows/example.md" in problems


def test_validation_rejects_runnable_planned_entry(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry(
        maturity="planned-not-implemented", recommendation_eligible=True
    )
    with pytest.raises(CatalogError, match="cannot be recommendation eligible"):
        load_entries(repo_fixture.root)


def test_catalog_serialization_is_byte_stable(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry()
    catalog = build_catalog(repo_fixture.root)
    first = serialize_catalog(catalog)
    reparsed = json.loads(first)
    assert serialize_catalog(reparsed) == first
    assert first.endswith("\n")


@pytest.mark.parametrize(
    ("frontmatter", "message"),
    [
        ([], "frontmatter must be a mapping"),
        ({"id": "example", "unexpected": True}, "unknown fields"),
    ],
)
def test_entry_frontmatter_is_a_strict_mapping(
    repo_fixture: RepoFixture, frontmatter: object, message: str
) -> None:
    repo_fixture.write_entry(frontmatter)
    with pytest.raises(CatalogError, match=message):
        load_entries(repo_fixture.root)


def test_read_frontmatter_requires_delimiters(repo_fixture: RepoFixture) -> None:
    path = repo_fixture.entry_dir / "plain.md"
    path.write_text("# Plain markdown\n", encoding="utf-8")
    with pytest.raises(CatalogError, match="missing YAML frontmatter"):
        read_frontmatter(path)


def test_read_frontmatter_rejects_unsafe_yaml(repo_fixture: RepoFixture) -> None:
    path = repo_fixture.entry_dir / "unsafe.md"
    path.write_text(
        "---\nvalue: !!python/object/apply:os.system ['false']\n---\n",
        encoding="utf-8",
    )
    with pytest.raises(CatalogError, match="invalid YAML frontmatter"):
        read_frontmatter(path)


def test_read_frontmatter_rejects_attached_closing_marker(
    repo_fixture: RepoFixture,
) -> None:
    path = repo_fixture.entry_dir / "attached.md"
    path.write_text("---\nid: accepted---\n# body\n", encoding="utf-8")
    with pytest.raises(CatalogError, match="missing YAML frontmatter closing delimiter"):
        read_frontmatter(path)


def test_read_frontmatter_rejects_missing_closing_marker(
    repo_fixture: RepoFixture,
) -> None:
    path = repo_fixture.entry_dir / "unclosed.md"
    path.write_text("---\nid: unclosed\n# body\n", encoding="utf-8")
    with pytest.raises(CatalogError, match="missing YAML frontmatter closing delimiter"):
        read_frontmatter(path)


def test_read_frontmatter_ignores_body_horizontal_rule(
    repo_fixture: RepoFixture,
) -> None:
    path = repo_fixture.entry_dir / "horizontal-rule.md"
    path.write_text(
        "---\nid: horizontal-rule\n---\n# Body\n\n---\n\nMore body.\n",
        encoding="utf-8",
    )
    assert read_frontmatter(path) == {"id": "horizontal-rule"}


def test_entry_validation_rejects_duplicate_ids(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry()
    entry = yaml.safe_load(
        repo_fixture.write_complete_entry().read_text(encoding="utf-8").split("---\n")[1]
    )
    repo_fixture.write_entry(entry, "second.md")
    with pytest.raises(CatalogError, match="duplicate entry id: example"):
        load_entries(repo_fixture.root)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"maturity": "experimental"}, "unknown maturity"),
        ({"recommendation_eligible": "yes"}, "must be a boolean"),
        ({"aliases": "example"}, "aliases must be a list of strings"),
        ({"implementation": []}, "implementation must be a mapping"),
        (
            {"implementation": {"mcp_local": ["mcp/example-mcp"]}},
            "unknown implementation fields",
        ),
        ({"platforms": ["amiga"]}, "unknown platform"),
    ],
)
def test_entry_validation_rejects_invalid_shapes(
    repo_fixture: RepoFixture, overrides: dict[str, object], message: str
) -> None:
    repo_fixture.write_complete_entry(**overrides)
    with pytest.raises(CatalogError, match=message):
        load_entries(repo_fixture.root)


@pytest.mark.parametrize(
    ("configuration", "message"),
    [
        ([{"name": "TOKEN"}], "configuration item missing required fields"),
        (
            [
                {
                    "name": "TOKEN",
                    "kind": "mystery",
                    "required": True,
                    "guidance": "Use protected settings.",
                }
            ],
            "unknown configuration kind",
        ),
        (
            [
                {
                    "name": "TOKEN",
                    "kind": "static-secret",
                    "required": "yes",
                    "guidance": "Use protected settings.",
                }
            ],
            "required must be a boolean",
        ),
        (
            [
                {
                    "name": "TOKEN",
                    "kind": "static-secret",
                    "required": True,
                    "guidance": "Set value: hunter2",
                }
            ],
            "secret guidance must not contain a value",
        ),
    ],
)
def test_configuration_validation_is_strict(
    repo_fixture: RepoFixture,
    configuration: list[dict[str, object]],
    message: str,
) -> None:
    repo_fixture.write_complete_entry(configuration=configuration)
    with pytest.raises(CatalogError, match=message):
        load_entries(repo_fixture.root)


@pytest.mark.parametrize(
    "reference",
    ["/absolute/path", "docs/../secrets.md", "..\\secrets.md"],
)
def test_entry_references_must_be_safe(
    repo_fixture: RepoFixture, reference: str
) -> None:
    repo_fixture.write_complete_entry(source_flows=[reference])
    with pytest.raises(CatalogError, match="unsafe reference"):
        load_entries(repo_fixture.root)


def test_named_implementation_references_must_be_safe(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry(implementation={"tools": ["../unsafe"]})
    with pytest.raises(CatalogError, match="unsafe reference"):
        load_entries(repo_fixture.root)


@pytest.mark.parametrize(
    "artifact",
    ["../escape", "..\\escape", "C:\\escape", "\\\\server\\share\\escape"],
)
def test_artifact_references_must_be_safe(
    repo_fixture: RepoFixture, artifact: str
) -> None:
    repo_fixture.write_complete_entry(artifacts=[artifact])
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert f"unsafe entry path: example: {artifact}" in problems


def test_validation_reconciles_all_repository_inventory(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry()
    assert validate_repository(
        repo_fixture.root, load_entries(repo_fixture.root)
    ) == []


@pytest.mark.parametrize(
    ("implementation", "expected"),
    [
        (
            {"skills": ["skills/ericsson/example"], "plugins": []},
            "unrepresented manifest plugin: plugins/ericsson-example",
        ),
        (
            {"skills": ["skills/ericsson/example"], "mcp_servers": []},
            "unrepresented manifest local MCP: mcp/example-mcp",
        ),
        (
            {"skills": ["skills/ericsson/example"], "mcp_servers": []},
            "unrepresented MCP server: example-mcp",
        ),
        (
            {"skills": ["skills/ericsson/example"], "workflows": []},
            "unrepresented manifest workflow: workflows/example.yml",
        ),
        (
            {"skills": ["skills/ericsson/example"], "tools": []},
            "unrepresented plugin tool: example_tool",
        ),
    ],
)
def test_validation_reports_each_unrepresented_runtime_component(
    repo_fixture: RepoFixture,
    implementation: dict[str, list[str]],
    expected: str,
) -> None:
    repo_fixture.write_complete_entry(implementation=implementation)
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert expected in problems


def test_validation_reports_unknown_entry_reference(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry(
        implementation={
            "skills": ["skills/ericsson/missing"],
            "plugins": [],
            "mcp_servers": [],
            "workflows": [],
            "tools": [],
        }
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unknown entry skill: skills/ericsson/missing" in problems


def test_validation_reconciles_flow_metadata(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry(
        maturity="partially-ported",
        recommendation_eligible=False,
        platforms=["windows"],
    )
    repo_fixture._write_markdown(
        "docs/flows/example.md",
        {
            "status": "intent-ported",
            "target_artifacts": ["missing-artifact"],
            "platforms": ["linux", "macos", "windows"],
        },
        "# Example flow\n",
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "flow maturity mismatch: docs/flows/example.md: intent-ported requires available, entry example has partially-ported" in problems
    assert "unrepresented flow target artifact: docs/flows/example.md: missing-artifact" in problems
    assert "flow platform mismatch: docs/flows/example.md: entry example does not cover linux, macos" in problems


def test_validation_uses_union_for_outlook_style_split(
    repo_fixture: RepoFixture,
) -> None:
    manifest = json.loads(
        (repo_fixture.root / "sets/ericsson.json").read_text(encoding="utf-8")
    )
    manifest["mcpLocal"] = ["mcp/outlook-mcp"]
    manifest["workflows"] = ["workflows/inbox-digest.yml"]
    repo_fixture._write_json("sets/ericsson.json", manifest)

    (repo_fixture.root / "mcp/example-mcp").rename(
        repo_fixture.root / "mcp/outlook-mcp"
    )
    repo_fixture._write_yaml(
        "mcp/mcp-servers.yaml",
        {
            "mcp_servers": {
                "outlook": {
                    "command": "python",
                    "args": ["${CAPABILITY_DIR}/outlook-mcp/run_server.py"],
                }
            }
        },
    )
    (repo_fixture.root / "workflows/example.yml").rename(
        repo_fixture.root / "workflows/inbox-digest.yml"
    )
    repo_fixture._write_yaml(
        "workflows/inbox-digest.yml",
        {"name": "inbox-digest", "requires": {"env": []}, "nodes": []},
    )
    repo_fixture._write_markdown(
        "docs/flows/example.md",
        {
            "status": "intent-ported",
            "target_artifacts": ["outlook-mcp", "inbox-digest-workflow"],
            "platforms": ["windows"],
        },
        "# Search and Read E-Mails\n",
    )

    repo_fixture.write_entry(
        repo_fixture.complete_entry_metadata(
            id="outlook-tools",
            display_name="Outlook tools",
            platforms=["windows"],
            implementation={
                "skills": ["skills/ericsson/example"],
                "plugins": ["plugins/ericsson-example"],
                "mcp_servers": ["outlook"],
                "tools": ["example_tool"],
            },
        ),
        "outlook-tools.md",
    )
    repo_fixture.write_entry(
        repo_fixture.complete_entry_metadata(
            id="outlook-inbox-digest",
            display_name="Outlook inbox digest",
            platforms=["windows"],
            implementation={"workflows": ["workflows/inbox-digest.yml"]},
        ),
        "outlook-inbox-digest.md",
    )

    assert validate_repository(
        repo_fixture.root, load_entries(repo_fixture.root)
    ) == []


def test_validation_parses_malformed_unrepresented_flow(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry(source_flows=[])
    repo_fixture._write_markdown(
        "docs/flows/example.md",
        {"status": [], "target_artifacts": "bad", "platforms": "windows"},
        "# Malformed flow\n",
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unrepresented flow: docs/flows/example.md" in problems
    assert "unknown flow status: docs/flows/example.md: []" in problems
    assert "invalid flow target_artifacts: docs/flows/example.md" in problems
    assert "invalid flow platforms: docs/flows/example.md" in problems


def test_validation_accepts_documented_target_artifact_suffixes(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry()
    repo_fixture._write_markdown(
        "docs/flows/example.md",
        {
            "status": "intent-ported",
            "target_artifacts": [
                "example-skill",
                "ericsson-example-plugin",
                "example-workflow",
            ],
            "platforms": ["linux", "macos", "windows"],
        },
        "# Example flow\n",
    )
    assert validate_repository(
        repo_fixture.root, load_entries(repo_fixture.root)
    ) == []


def test_validation_reports_runtime_component_missing_from_manifest(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry()
    repo_fixture._write_markdown(
        "skills/ericsson/unpackaged/SKILL.md",
        {"name": "unpackaged", "description": "Not packaged."},
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unpackaged repository skill: skills/ericsson/unpackaged" in problems


def test_entry_id_must_match_filename(repo_fixture: RepoFixture) -> None:
    entry_path = repo_fixture.write_complete_entry()
    entry_path.rename(entry_path.with_name("different.md"))
    with pytest.raises(CatalogError, match="entry id must match filename"):
        load_entries(repo_fixture.root)


def test_available_entry_requires_nonempty_implementation(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry()
    repo_fixture.write_entry(
        repo_fixture.complete_entry_metadata(
            id="ghost",
            display_name="Ghost",
            source_flows=[],
            implementation={},
        ),
        "ghost.md",
    )
    with pytest.raises(CatalogError, match="available entry must reference an implementation"):
        load_entries(repo_fixture.root)


def test_available_entry_allows_omitted_implementation_subkeys(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry(
        source_flows=[],
        implementation={"skills": ["skills/ericsson/example"]},
    )
    assert load_entries(repo_fixture.root)[0]["implementation"] == {
        "skills": ["skills/ericsson/example"]
    }


def test_local_mcp_binding_ignores_remote_url_collision(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture._write_yaml(
        "mcp/mcp-servers.yaml",
        {
            "mcp_servers": {
                "local": {"command": "python", "args": ["run_server.py"]},
                "remote": {"url": "https://host.example/example-mcp/api"},
            }
        },
    )
    repo_fixture.write_complete_entry(
        implementation={"mcp_servers": ["remote"]}
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unrepresented manifest local MCP: mcp/example-mcp" in problems


def test_local_mcp_binding_rejects_overlapping_basename(
    repo_fixture: RepoFixture,
) -> None:
    manifest = json.loads(
        (repo_fixture.root / "sets/ericsson.json").read_text(encoding="utf-8")
    )
    manifest["mcpLocal"] = ["mcp/outlook"]
    repo_fixture._write_json("sets/ericsson.json", manifest)
    (repo_fixture.root / "mcp/example-mcp").rename(repo_fixture.root / "mcp/outlook")
    repo_fixture._write_yaml(
        "mcp/mcp-servers.yaml",
        {
            "mcp_servers": {
                "wrong": {
                    "command": "python",
                    "args": ["${CAPABILITY_DIR}/outlook-mcp/run_server.py"],
                }
            }
        },
    )
    repo_fixture.write_complete_entry(implementation={"mcp_servers": ["wrong"]})
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unrepresented manifest local MCP: mcp/outlook" in problems


def test_local_mcp_binding_supports_outlook_path_and_server_name_mismatch(
    repo_fixture: RepoFixture,
) -> None:
    manifest = json.loads(
        (repo_fixture.root / "sets/ericsson.json").read_text(encoding="utf-8")
    )
    manifest["mcpLocal"] = ["mcp/outlook-mcp"]
    repo_fixture._write_json("sets/ericsson.json", manifest)
    (repo_fixture.root / "mcp/example-mcp").rename(
        repo_fixture.root / "mcp/outlook-mcp"
    )
    repo_fixture._write_yaml(
        "mcp/mcp-servers.yaml",
        {
            "mcp_servers": {
                "outlook": {
                    "command": "python",
                    "args": ["${CAPABILITY_DIR}/outlook-mcp/run_server.py"],
                }
            }
        },
    )
    repo_fixture._write_markdown(
        "docs/flows/example.md",
        {
            "status": "intent-ported",
            "target_artifacts": ["outlook-mcp"],
            "platforms": ["linux", "macos", "windows"],
        },
    )
    repo_fixture.write_complete_entry(
        implementation={
            "skills": ["skills/ericsson/example"],
            "plugins": ["plugins/ericsson-example"],
            "mcp_servers": ["outlook"],
            "workflows": ["workflows/example.yml"],
            "tools": ["example_tool"],
        }
    )
    assert validate_repository(
        repo_fixture.root, load_entries(repo_fixture.root)
    ) == []


def test_validation_reconciles_configuration_names(repo_fixture: RepoFixture) -> None:
    manifest = json.loads(
        (repo_fixture.root / "sets/ericsson.json").read_text(encoding="utf-8")
    )
    manifest["env"] = [{"key": "MANIFEST_TOKEN"}]
    repo_fixture._write_json("sets/ericsson.json", manifest)
    plugin = yaml.safe_load(
        (repo_fixture.root / "plugins/ericsson-example/plugin.yaml").read_text(
            encoding="utf-8"
        )
    )
    plugin["requires_env"] = ["PLUGIN_REQUIRED"]
    plugin["optional_env"] = ["PLUGIN_OPTIONAL"]
    repo_fixture._write_yaml("plugins/ericsson-example/plugin.yaml", plugin)
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["requires"]["env"] = ["WORKFLOW_ENV"]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "MANIFEST_TOKEN",
                "kind": "static-secret",
                "required": True,
                "guidance": "Configure this in Tools & Keys.",
            }
        ]
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "unrepresented configuration: PLUGIN_OPTIONAL" in problems
    assert "unrepresented configuration: PLUGIN_REQUIRED" in problems
    assert "unrepresented configuration: WORKFLOW_ENV" in problems


def test_validation_rejects_required_configuration_marked_optional(
    repo_fixture: RepoFixture,
) -> None:
    plugin = yaml.safe_load(
        (repo_fixture.root / "plugins/ericsson-example/plugin.yaml").read_text(
            encoding="utf-8"
        )
    )
    plugin["requires_env"] = ["REQUIRED_TOKEN"]
    repo_fixture._write_yaml("plugins/ericsson-example/plugin.yaml", plugin)
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["requires"]["env"] = ["REQUIRED_TOKEN"]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "REQUIRED_TOKEN",
                "kind": "static-secret",
                "required": False,
                "guidance": "Configure this in Tools & Keys.",
            }
        ]
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "configuration requiredness mismatch: entry example: REQUIRED_TOKEN must set required: true" in problems


def test_validation_rejects_optional_configuration_marked_required(
    repo_fixture: RepoFixture,
) -> None:
    plugin = yaml.safe_load(
        (repo_fixture.root / "plugins/ericsson-example/plugin.yaml").read_text(
            encoding="utf-8"
        )
    )
    plugin["optional_env"] = ["OPTIONAL_OVERRIDE"]
    repo_fixture._write_yaml("plugins/ericsson-example/plugin.yaml", plugin)
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "OPTIONAL_OVERRIDE",
                "kind": "static-setting",
                "required": True,
                "guidance": "Configure this in Tools & Keys when needed.",
            }
        ]
    )
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "configuration requiredness mismatch: entry example: OPTIONAL_OVERRIDE must set required: false" in problems


def test_validation_rejects_plugin_tool_missing_from_runtime_schemas(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture._write_text(
        "plugins/ericsson-example/example_tools.py", "SCHEMAS = {}\n"
    )
    repo_fixture.write_complete_entry()

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert (
        "plugin tool declaration not registered: plugins/ericsson-example: example_tool"
        in problems
    )


def test_validation_rejects_renamed_implementation_environment_variable(
    repo_fixture: RepoFixture,
) -> None:
    plugin = yaml.safe_load(
        (repo_fixture.root / "plugins/ericsson-example/plugin.yaml").read_text(
            encoding="utf-8"
        )
    )
    plugin["optional_env"] = ["ERICSSON_GRAPH_CLIENT_ID"]
    repo_fixture._write_yaml("plugins/ericsson-example/plugin.yaml", plugin)
    repo_fixture._write_text(
        "plugins/ericsson-example/example_tools.py",
        "import os\n"
        "CLIENT_ID = os.environ.get('ERICSSON_GRAPH_CLIENT_ID_RENAMED')\n"
        "SCHEMAS = {'example_tool': {'name': 'example_tool'}}\n",
    )
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "ERICSSON_GRAPH_CLIENT_ID",
                "kind": "static-setting",
                "required": False,
                "guidance": "Configure the supported optional override.",
            }
        ]
    )

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert (
        "undeclared implementation configuration: plugins/ericsson-example: "
        "ERICSSON_GRAPH_CLIENT_ID_RENAMED" in problems
    )
    assert (
        "unused plugin configuration declaration: plugins/ericsson-example: "
        "ERICSSON_GRAPH_CLIENT_ID" in problems
    )


def test_validation_rejects_deleted_workflow_input_still_advertised(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "scope",
                "kind": "workflow-input",
                "required": False,
                "guidance": "Choose the optional workflow scope.",
            }
        ]
    )

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert "unknown workflow input: entry example: scope" in problems


def test_validation_rejects_unknown_onboarding_static_configuration(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "FICTIONAL_TOKEN",
                "kind": "static-secret",
                "required": True,
                "guidance": "Configure it only through protected entry.",
            }
        ]
    )

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert "unknown onboarding configuration: entry example: FICTIONAL_TOKEN" in problems


def test_validation_reconciles_workflow_input_requiredness(
    repo_fixture: RepoFixture,
) -> None:
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["inputs"] = [{"name": "scope"}]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "scope",
                "kind": "workflow-input",
                "required": False,
                "guidance": "Choose the workflow scope.",
            }
        ]
    )

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert (
        "workflow input requiredness mismatch: entry example: scope must set required: true"
        in problems
    )


def test_validation_rejects_workflow_tool_removed_from_runtime(
    repo_fixture: RepoFixture,
) -> None:
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["requires"]["toolsets"] = ["ericsson-example"]
    workflow["nodes"] = [
        {
            "id": "fetch",
            "kind": "tool",
            "tools": ["removed_runtime_tool"],
            "prompt": "Fetch with the removed_runtime_tool tool.",
        }
    ]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry()

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert (
        "unknown workflow tool: workflows/example.yml: fetch: removed_runtime_tool"
        in problems
    )


def test_validation_rejects_removed_runtime_tool_named_only_in_workflow_prompt(
    repo_fixture: RepoFixture,
) -> None:
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["requires"]["toolsets"] = ["ericsson-example"]
    workflow["nodes"] = [
        {
            "id": "fetch",
            "kind": "tool",
            "tools": ["example_tool"],
            "prompt": "Fetch with the removed_runtime_tool tool.",
        }
    ]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry()

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert (
        "undeclared workflow prompt tool: workflows/example.yml: fetch: "
        "removed_runtime_tool" in problems
    )


def test_validation_rejects_invoked_prompt_tool_without_literal_tool_suffix(
    repo_fixture: RepoFixture,
) -> None:
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["requires"]["toolsets"] = ["ericsson-example"]
    workflow["nodes"] = [
        {
            "id": "fetch",
            "kind": "tool",
            "tools": ["example_tool"],
            "prompt": "Use example_tool, then call removed_runtime_tool now.",
        }
    ]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry()

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert (
        "undeclared workflow prompt tool: workflows/example.yml: fetch: "
        "removed_runtime_tool" in problems
    )


def test_validation_rejects_backticked_invoked_prompt_tool(
    repo_fixture: RepoFixture,
) -> None:
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["requires"]["toolsets"] = ["ericsson-example"]
    workflow["nodes"] = [
        {
            "id": "fetch",
            "kind": "tool",
            "tools": ["example_tool"],
            "prompt": "Run example_tool; then invoke `removed_runtime_tool`, now.",
        }
    ]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry()

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert (
        "undeclared workflow prompt tool: workflows/example.yml: fetch: "
        "removed_runtime_tool" in problems
    )


def test_validation_does_not_treat_workflow_input_as_invoked_tool(
    repo_fixture: RepoFixture,
) -> None:
    workflow = yaml.safe_load(
        (repo_fixture.root / "workflows/example.yml").read_text(encoding="utf-8")
    )
    workflow["requires"]["toolsets"] = ["ericsson-example"]
    workflow["inputs"] = [{"name": "deliver_to", "default": "chat"}]
    workflow["nodes"] = [
        {
            "id": "fetch",
            "kind": "tool",
            "tools": ["example_tool"],
            "prompt": "Use example_tool and use deliver_to input.",
        }
    ]
    repo_fixture._write_yaml("workflows/example.yml", workflow)
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "deliver_to",
                "kind": "workflow-input",
                "required": False,
                "guidance": "Choose the optional destination.",
            }
        ]
    )

    assert validate_repository(
        repo_fixture.root, load_entries(repo_fixture.root)
    ) == []


def test_validation_rejects_manifest_environment_unused_by_implementation(
    repo_fixture: RepoFixture,
) -> None:
    manifest = json.loads(
        (repo_fixture.root / "sets/ericsson.json").read_text(encoding="utf-8")
    )
    manifest["env"] = [{"key": "UNUSED_MANIFEST_TOKEN"}]
    repo_fixture._write_json("sets/ericsson.json", manifest)
    repo_fixture.write_complete_entry(
        configuration=[
            {
                "name": "UNUSED_MANIFEST_TOKEN",
                "kind": "static-secret",
                "required": True,
                "guidance": "Configure it only through protected entry.",
            }
        ]
    )

    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))

    assert "unused manifest environment: UNUSED_MANIFEST_TOKEN" in problems


def test_validation_rejects_missing_referenced_path(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry(artifacts=["docs/missing.md"])
    problems = validate_repository(repo_fixture.root, load_entries(repo_fixture.root))
    assert "missing entry path: example: docs/missing.md" in problems


def test_build_catalog_cli_writes_atomically_and_checks_freshness(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry()
    script = SCRIPTS_DIR / "build_catalog.py"
    target = (
        repo_fixture.root
        / "skills/ericsson/onboard-ericsson-capabilities/references/catalog.json"
    )

    written = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo_fixture.root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert written.returncode == 0, written.stderr
    assert target.read_text(encoding="utf-8") == serialize_catalog(
        build_catalog(repo_fixture.root)
    )
    assert not list(target.parent.glob(".catalog.json.*"))

    target.write_text("{}\n", encoding="utf-8")
    checked = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo_fixture.root), "--check"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 1
    assert checked.stdout == "catalog is stale\n"
    assert target.read_text(encoding="utf-8") == "{}\n"


def test_build_catalog_check_compares_physical_crlf_bytes(
    repo_fixture: RepoFixture,
) -> None:
    repo_fixture.write_complete_entry()
    script = SCRIPTS_DIR / "build_catalog.py"
    target = (
        repo_fixture.root
        / "skills/ericsson/onboard-ericsson-capabilities/references/catalog.json"
    )
    expected = serialize_catalog(build_catalog(repo_fixture.root)).encode("utf-8")
    crlf = expected.replace(b"\n", b"\r\n")
    target.write_bytes(crlf)

    checked = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo_fixture.root), "--check"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert checked.returncode == 1
    assert checked.stdout == "catalog is stale\n"
    assert target.read_bytes() == crlf


def test_validate_catalog_cli_emits_stable_json(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry()
    script = SCRIPTS_DIR / "validate_catalog.py"

    result = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo_fixture.root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == '{"ok": true, "problems": []}\n'


def test_validate_catalog_cli_sorts_problems(repo_fixture: RepoFixture) -> None:
    repo_fixture.write_complete_entry(source_flows=[], implementation={})
    script = SCRIPTS_DIR / "validate_catalog.py"

    result = subprocess.run(
        [sys.executable, str(script), "--repo", str(repo_fixture.root)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["problems"] == sorted(payload["problems"])
