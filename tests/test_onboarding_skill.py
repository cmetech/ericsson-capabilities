from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skills/ericsson/onboard-ericsson-capabilities"
SKILL_PATH = SKILL_DIR / "SKILL.md"

WORKFLOW_LOADS = {
    "discover-and-recommend.md": {"../references/catalog.json"},
    "explain-capability.md": {
        "../references/capabilities/{selected-capability-id}.md"
    },
    "configure-and-check-readiness.md": {
        "../references/capabilities/{selected-capability-id}.md",
        "../references/configuration-and-authentication.md",
        "../references/safety-and-approvals.md",
    },
    "run-synthetic-demonstration.md": {
        "../references/capabilities/{selected-capability-id}.md",
        "../references/demonstration-policy.md",
        "../references/artifact-interpretation.md",
    },
    "guide-first-real-run.md": {
        "../references/capabilities/{selected-capability-id}.md",
        "../references/safety-and-approvals.md",
    },
    "interpret-artifacts.md": {
        "../references/capabilities/{selected-capability-id}.md",
        "../references/artifact-interpretation.md",
    },
    "troubleshoot-capability.md": {
        "../references/capabilities/{selected-capability-id}.md",
        "../references/troubleshooting-taxonomy.md",
    },
    "resume-or-summarize.md": {
        "../references/catalog.json",
        "../references/capabilities/{selected-capability-id}.md",
        "../references/configuration-and-authentication.md",
        "../references/safety-and-approvals.md",
    },
}

SHARED_REFERENCES = {
    "configuration-and-authentication.md",
    "safety-and-approvals.md",
    "demonstration-policy.md",
    "artifact-interpretation.md",
    "troubleshooting-taxonomy.md",
}

TEMPLATES = {
    "onboarding-summary.md",
    "readiness-checklist.md",
    "first-run-checklist.md",
    "session-handoff.md",
}


def _frontmatter(text: str) -> dict[str, object]:
    assert text.startswith("---\n")
    return yaml.safe_load(text.split("---\n", 2)[1])


def _load_block(text: str) -> str:
    match = re.search(r"^## Load\n(?P<body>.*?)(?=^## )", text, re.MULTILINE | re.DOTALL)
    assert match, "workflow is missing a bounded Load section"
    return match.group("body")


def _referenced_paths(text: str) -> set[str]:
    return set(re.findall(r"`(\.\./references/[^`]+|references/[^`]+|workflows/[^`]+)`", text))


def test_router_has_exact_metadata_and_is_thin() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    fm = _frontmatter(text)

    assert fm["name"] == "onboard-ericsson-capabilities"
    assert fm["description"] == "Onboard users to Ericsson Co-Worker capabilities."
    assert len(fm["description"]) <= 60
    assert len(text) <= 12_000
    assert "JIRA_PAT" not in text
    assert "GLEAN_API_TOKEN" not in text


def test_router_preserves_required_section_order() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    headings = [
        "# Ericsson Capability Onboarding",
        "## When to Use",
        "## Prerequisites",
        "## How to Run",
        "## Quick Reference",
        "## Procedure",
        "## Pitfalls",
    ]
    positions = [text.index(heading) for heading in headings]
    assert positions == sorted(positions)


def test_router_encodes_adaptive_progressive_routing() -> None:
    text = SKILL_PATH.read_text(encoding="utf-8")
    for phrase in (
        "one question at a time",
        "at most two",
        "references/catalog.json",
        "maturity before readiness",
        "Quick overview",
        "Configuration/readiness check",
        "Synthetic demonstration",
        "Guided first real run",
        "Artifact walkthrough",
        "Troubleshooting",
        "resume-or-summarize.md",
        "consent",
    ):
        assert phrase in text

    assert "`hermes-agent` skill" in text
    assert "underlying Ericsson capability" in text
    assert "already clear domain request" in text
    assert "persisting an onboarding summary" in text
    for onboarding_verb in (
        "learn",
        "configure",
        "validate",
        "demonstrate",
        "interpret",
        "troubleshoot",
        "resume",
    ):
        assert onboarding_verb in text.lower()


def test_required_workflows_references_and_templates_exist() -> None:
    assert {path.name for path in (SKILL_DIR / "workflows").glob("*.md")} == set(
        WORKFLOW_LOADS
    )
    assert SHARED_REFERENCES <= {
        path.name for path in (SKILL_DIR / "references").glob("*.md")
    }
    assert {path.name for path in (SKILL_DIR / "templates").glob("*.md")} == TEMPLATES


def test_all_literal_relative_links_resolve() -> None:
    markdown_files = [SKILL_PATH]
    markdown_files.extend((SKILL_DIR / "workflows").glob("*.md"))
    markdown_files.extend((SKILL_DIR / "references").glob("*.md"))
    markdown_files.extend((SKILL_DIR / "templates").glob("*.md"))

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        for target in re.findall(r"\[[^\]]+\]\(([^)]+)\)", text):
            if "://" in target or "{" in target:
                continue
            resolved = (path.parent / target.split("#", 1)[0]).resolve()
            assert resolved.exists(), f"{path}: broken relative link {target}"


def test_all_literal_routing_paths_resolve_and_templates_are_used() -> None:
    markdown_files = [SKILL_PATH]
    markdown_files.extend((SKILL_DIR / "workflows").glob("*.md"))

    for path in markdown_files:
        text = path.read_text(encoding="utf-8")
        targets = re.findall(
            r"`((?:\.\./)?(?:references|workflows|templates)/[^`]+)`", text
        )
        for target in targets:
            if "{" in target:
                continue
            resolved = (path.parent / target).resolve()
            assert resolved.exists(), f"{path}: broken routing path {target}"

    assert "templates/onboarding-summary.md" in SKILL_PATH.read_text(
        encoding="utf-8"
    )
    expected_usage = {
        "configure-and-check-readiness.md": "../templates/readiness-checklist.md",
        "guide-first-real-run.md": "../templates/first-run-checklist.md",
        "resume-or-summarize.md": "../templates/session-handoff.md",
    }
    for workflow, template in expected_usage.items():
        text = (SKILL_DIR / "workflows" / workflow).read_text(encoding="utf-8")
        assert template in text, f"{workflow}: must render {template}"


def test_each_workflow_has_contract_sections_and_exact_load_boundary() -> None:
    for filename, expected in WORKFLOW_LOADS.items():
        path = SKILL_DIR / "workflows" / filename
        text = path.read_text(encoding="utf-8")
        positions = [
            text.index(f"## {heading}")
            for heading in ("Entry", "Load", "Procedure", "Checkpoint", "Exit")
        ]
        assert positions == sorted(positions), filename
        assert _referenced_paths(_load_block(text)) == expected, filename


def test_discovery_loads_no_capability_entry_until_selection() -> None:
    text = (SKILL_DIR / "workflows/discover-and-recommend.md").read_text(
        encoding="utf-8"
    )
    before_selection, after_selection = text.split("After selection", 1)
    assert "references/capabilities" not in before_selection
    assert "references/capabilities/{selected-capability-id}.md" in after_selection


def test_resume_loads_detail_only_when_reconciling_or_rechecking() -> None:
    load = _load_block(
        (SKILL_DIR / "workflows/resume-or-summarize.md").read_text(encoding="utf-8")
    )
    assert "Load `../references/catalog.json` first" in load
    assert "Only when resuming selected capability work" in load
    assert "only when rechecking volatile readiness" in load


def test_unavailable_capabilities_are_never_executed_or_presented_as_ready() -> None:
    router = SKILL_PATH.read_text(encoding="utf-8")
    first_run = (SKILL_DIR / "workflows/guide-first-real-run.md").read_text(
        encoding="utf-8"
    )
    combined = router + first_run
    for maturity in (
        "partially-ported",
        "planned-not-implemented",
        "not-supported-no-port-planned",
    ):
        assert maturity in combined
    assert "refuse execution" in first_run.lower()
    assert "maturity is `available`" in first_run


def test_safety_reference_preserves_the_exact_readiness_ladder() -> None:
    text = (SKILL_DIR / "references/safety-and-approvals.md").read_text(
        encoding="utf-8"
    )
    steps = [
        "1. Packaged and discoverable.",
        "2. Enabled and supported on the current platform.",
        "3. Dependency or server startup.",
        "4. Authentication.",
        "5. Read-only list or retrieval.",
        "6. Draft, preview, or synthetic execution.",
        "7. Explicit authorization to execute the previewed write through the underlying capability.",
    ]
    positions = [text.index(step) for step in steps]
    assert positions == sorted(positions)
    assert "environment-variable name" in text
    assert "never sufficient evidence for `ready`" in text


def test_readiness_template_keeps_independent_non_sensitive_facts() -> None:
    text = (SKILL_DIR / "templates/readiness-checklist.md").read_text(
        encoding="utf-8"
    )
    independent_facts = (
        "Enabled",
        "Platform supported",
        "Required protected settings configured (values never shown)",
        "Required permission adequate",
    )
    for fact in independent_facts:
        assert f"- {fact}: [true/false/unchecked]" in text
    assert "Enabled and platform-supported" not in text
    assert "Profile-scoped persistence must keep these facts distinct" in text
    assert "Boolean/null" in text


def test_readiness_contract_pins_persisted_setting_and_permission_field_names() -> None:
    template = (SKILL_DIR / "templates/readiness-checklist.md").read_text(
        encoding="utf-8"
    )
    reference = (
        SKILL_DIR / "references/configuration-and-authentication.md"
    ).read_text(encoding="utf-8")
    plan = (
        REPO
        / "docs/superpowers/plans/2026-07-15-ericsson-capability-onboarding.md"
    ).read_text(encoding="utf-8")

    for field in ("requiredSettingsConfigured", "permissionAdequate"):
        assert f"`{field}`" in template
        assert f"`{field}`" in reference
        assert f"`{field}`" in plan
    assert "the eight fact fields are Boolean or null" in plan


def test_demo_mode_slugs_map_one_to_one_and_workflow_uses_display_label() -> None:
    policy = (SKILL_DIR / "references/demonstration-policy.md").read_text(
        encoding="utf-8"
    )
    mappings = dict(
        re.findall(r"^- `([^`]+)` maps to `([^`]+)`\.$", policy, re.MULTILINE)
    )
    assert mappings == {
        "synthetic-offline": "synthetic/offline",
        "simulated": "simulated",
        "read-only-live": "read-only live",
        "approved-live": "approved live",
    }
    assert len(set(mappings.values())) == 4

    workflow = (SKILL_DIR / "workflows/run-synthetic-demonstration.md").read_text(
        encoding="utf-8"
    )
    assert "Translate the entry's machine mode slug through the one-to-one mapping" in workflow
    assert "show only its user-facing label" in workflow


def test_write_requires_authorization_to_execute_not_preview_acknowledgment() -> None:
    safety = (SKILL_DIR / "references/safety-and-approvals.md").read_text(
        encoding="utf-8"
    )
    workflow = (SKILL_DIR / "workflows/guide-first-real-run.md").read_text(
        encoding="utf-8"
    )
    template = (SKILL_DIR / "templates/first-run-checklist.md").read_text(
        encoding="utf-8"
    )
    combined = safety + workflow + template

    assert "explicitly authorized to execute this previewed action" in template
    assert "explicit authorization to execute the previewed action" in workflow
    exact_boundary = (
        "Acknowledging the preview, approving its content, or approving a draft "
        "alone is not write authorization."
    )
    assert exact_boundary in safety
    assert exact_boundary in workflow
    assert exact_boundary in template
    for ambiguous in (
        "explicit approval of that preview",
        "explicitly approved for this preview",
        "approval of a draft does not authorize execution",
    ):
        assert ambiguous not in combined


def test_offered_token_contract_refuses_already_pasted_secret_use() -> None:
    scenarios = yaml.safe_load(
        (REPO / "tests/fixtures/ericsson_onboarding/pressure-scenarios.yaml").read_text(
            encoding="utf-8"
        )
    )["scenarios"]
    offered = next(item for item in scenarios if item["id"] == "offered-token")
    assert any("Refuse to accept or persist" in item for item in offered["required_behaviors"])

    router = SKILL_PATH.read_text(encoding="utf-8")
    safety = (SKILL_DIR / "references/safety-and-approvals.md").read_text(
        encoding="utf-8"
    )
    for text in (router, safety):
        assert "do not repeat, use, validate, or persist the value" in text
        assert "protected Tools & Keys" in text
        assert "documented rotation or revocation" in text
        assert "do not invent" in text.lower()


def test_secret_and_side_effect_policy_requires_protected_entry_and_authorization() -> None:
    configuration = (
        SKILL_DIR / "references/configuration-and-authentication.md"
    ).read_text(encoding="utf-8")
    safety = (SKILL_DIR / "references/safety-and-approvals.md").read_text(
        encoding="utf-8"
    )
    first_run = (SKILL_DIR / "workflows/guide-first-real-run.md").read_text(
        encoding="utf-8"
    )

    for category in (
        "Static secrets and settings",
        "Interactive sign-in",
        "Permissions",
        "Software and platform",
        "Workflow inputs",
    ):
        assert category in configuration
    assert "protected Tools & Keys" in configuration
    assert "paste" in configuration.lower()
    assert "print" in configuration.lower()
    assert "target" in first_run.lower()
    assert "intended effect" in first_run.lower()
    assert "explicit authorization to execute" in first_run.lower()
    assert "never used merely to test configuration" in safety
    for side_effect in (
        "email",
        "Teams message",
        "Jira comment",
        "commit",
        "branch",
        "merge request",
    ):
        assert side_effect in safety


def test_demonstration_and_artifact_policies_are_honest_and_non_destructive() -> None:
    demonstration = (SKILL_DIR / "references/demonstration-policy.md").read_text(
        encoding="utf-8"
    )
    artifacts = (SKILL_DIR / "references/artifact-interpretation.md").read_text(
        encoding="utf-8"
    )
    for label in (
        "synthetic/offline",
        "simulated",
        "read-only live",
        "approved live",
    ):
        assert label in demonstration
    assert "fictional" in demonstration
    assert "expected-versus-actual" in demonstration
    assert "never present a simulation as successful live integration" in demonstration.lower()
    assert "never overwrite" in demonstration.lower()
    assert "ambiguous" in artifacts.lower()
    assert "before writing" in artifacts.lower()


def test_troubleshooting_taxonomy_is_exact() -> None:
    text = (SKILL_DIR / "references/troubleshooting-taxonomy.md").read_text(
        encoding="utf-8"
    )
    expected = [
        "missing configuration",
        "rejected/expired authentication",
        "insufficient permission",
        "network/TLS",
        "missing local dependency/application",
        "invalid input",
        "source-system failure",
        "workflow-state failure",
        "partial side effect",
        "ambiguous artifact destination",
    ]
    bullets = re.findall(r"^- `([^`]+)`:", text, re.MULTILINE)
    assert bullets == expected


def test_templates_have_stable_fields_unknown_defaults_and_no_secret_examples() -> None:
    required_by_template = {
        "onboarding-summary.md": {
            "Selected capabilities",
            "Product maturity",
            "Current readiness",
            "Supporting facts",
            "Completed learning or demonstration",
            "Missing user actions",
            "Safe artifact locations and inspection guidance",
            "Suggested next prompt",
        },
        "readiness-checklist.md": {
            "Capability",
            "Product maturity",
            "Readiness state",
            "Supporting facts",
            "Missing user actions",
            "Next safe check",
        },
        "first-run-checklist.md": {
            "Capability",
            "Readiness state",
            "Target",
            "Intended effect",
            "Reads",
            "Writes or changes",
            "Approval",
            "Output format and destination",
            "Expected result and artifacts",
            "Inspection plan",
        },
        "session-handoff.md": {
            "Schema version",
            "Catalog version",
            "Selected capabilities",
            "Product maturity",
            "Readiness facts",
            "Completed steps",
            "Pending actions",
            "Safe artifact pointers",
            "Suggested next prompt",
            "Created at",
            "Updated at",
        },
    }
    forbidden_examples = ("sk-", "Bearer ", "password=", "token=", "BEGIN PRIVATE KEY")

    for filename, fields in required_by_template.items():
        text = (SKILL_DIR / "templates" / filename).read_text(encoding="utf-8")
        assert "unknown-needs-check" in text, filename
        for field in fields:
            assert field in text, f"{filename}: missing {field}"
        for value in forbidden_examples:
            assert value not in text, f"{filename}: contains example secret value"
