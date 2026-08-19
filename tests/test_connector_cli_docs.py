"""User-facing connector CLI documentation and onboarding contracts."""

from __future__ import annotations

import json
from pathlib import Path


REPO = Path(__file__).resolve().parents[1]
ONBOARDING = (
    REPO
    / "skills"
    / "ericsson"
    / "onboard-ericsson-capabilities"
    / "references"
)


def _read(relative: str) -> str:
    return (REPO / relative).read_text(encoding="utf-8")


def _normalized(value: str) -> str:
    return " ".join(value.lower().split())


def test_handbook_explains_both_connector_interfaces_and_complete_surface() -> None:
    handbook = _read("docs/README.md")
    normalized = _normalized(handbook)

    assert "direct shell commands" in normalized
    assert "natural-language cli and tui" in normalized
    assert "Jira 15, GitLab 30, Confluence 9, and ARM 6" in handbook
    assert "[SuperCLI 0.14.1 migration guide](cli-migration/supercli-0.14.1.md)" in handbook
    assert "<brand> jira" in handbook
    assert "<brand> gitlab" in handbook
    assert "<brand> confluence" in handbook
    assert "<brand> arm" in handbook


def test_handbook_describes_the_remaining_jira_defect_loop_gap_accurately() -> None:
    handbook = _normalized(_read("docs/README.md"))

    assert (
        "jira and gitlab tools, triage guidance, and single-ticket orchestration "
        "exist; multi-ticket iteration, aggregation, and safe batch recovery remain"
    ) in handbook
    assert "triage, gitlab tools, loop, reviews, and summary remain" not in handbook


def test_configuration_documents_visibility_enablement_and_cli_security() -> None:
    configuration = _read("docs/configuration.md")
    normalized = _normalized(configuration)

    assert "`ericsson-connector-cli` is an always-loaded backend string entry" in configuration
    assert "help remains available while a standalone connector is disabled" in normalized
    assert "Do not enable `ericsson-connector-cli`" in configuration
    assert "exactly one of `--dry-run` and `--confirm`" in normalized
    assert "credentials, origins, certificate paths, or profile selection on argv" in configuration
    assert "`ericsson.connector-cli/v1`" in configuration
    assert "Exit code `5`" in configuration
    assert "`write_ambiguous`" in configuration
    assert "docs/cli-migration/supercli-0.14.1.md" in configuration


def test_domain_onboarding_entries_represent_facade_and_all_60_operations() -> None:
    expected = {
        "jira-tools.md": ("ericsson-jira", "jira", 15),
        "gitlab-tools.md": ("ericsson-gitlab", "gitlab", 30),
        "confluence-tools.md": ("ericsson-confluence", "confluence", 9),
        "artifactory-arm-tools.md": ("ericsson-arm", "arm", 6),
    }
    facade = "plugins/ericsson-connector-cli"

    for filename, (connector_id, domain, operation_count) in expected.items():
        source = (ONBOARDING / "capabilities" / filename).read_text(encoding="utf-8")
        assert f"plugins: [plugins/{connector_id}, {facade}]" in source
        assert f"<brand> {domain}" in source
        assert "always-loaded facade" in source
        assert "natural-language" in source
        tool_lines = [line for line in source.split("---", 2)[1].splitlines() if line.startswith("    - ")]
        assert len(tool_lines) == operation_count


def test_generated_catalog_indexes_each_domain_cli_without_a_facade_lifecycle() -> None:
    catalog = json.loads((ONBOARDING / "catalog.json").read_text(encoding="utf-8"))
    by_id = {item["id"]: item for item in catalog["capabilities"]}
    expected = {
        "jira-tools": "<brand> jira",
        "gitlab-tools": "<brand> gitlab",
        "confluence-tools": "<brand> confluence",
        "artifactory-arm-tools": "<brand> arm",
    }

    assert "ericsson-connector-cli" not in by_id
    for entry_id, command_prefix in expected.items():
        indexed_text = json.dumps(by_id[entry_id], sort_keys=True)
        assert command_prefix in indexed_text


def test_generic_facade_discovery_has_one_non_recommendation_entry_owner() -> None:
    catalog = json.loads((ONBOARDING / "catalog.json").read_text(encoding="utf-8"))
    owners = [
        item
        for item in catalog["capabilities"]
        if "Ericsson connector CLI" in item["aliases"]
    ]

    assert [(item["id"], item["recommendationEligible"]) for item in owners] == [
        ("ericsson-capability-onboarding", False)
    ]

    by_id = {item["id"]: item for item in catalog["capabilities"]}
    assert "Ericsson Jira connector CLI" in by_id["jira-tools"]["aliases"]
    assert "Ericsson GitLab connector CLI" in by_id["gitlab-tools"]["aliases"]
    assert "Ericsson Confluence connector CLI" in by_id["confluence-tools"]["aliases"]
    assert "Ericsson ARM connector CLI" in by_id["artifactory-arm-tools"]["aliases"]


def test_related_flow_docs_keep_orchestration_status_distinct_from_cli_leaves() -> None:
    expected = {
        "docs/flows/jira-assigned-tickets-summary.md": "<brand> jira",
        "docs/flows/jira-to-gitlab.md": "<brand> gitlab",
        "docs/flows/jira-defect-loop.md": "<brand> jira",
        "docs/flows/ci-file-auditor.md": "<brand> gitlab",
    }

    for relative, command_prefix in expected.items():
        source = _read(relative)
        assert command_prefix in source
        assert "natural-language" in source.lower()
        assert "does not change this flow's status" in _normalized(source)
