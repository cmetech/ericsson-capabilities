from __future__ import annotations

import re
from pathlib import Path

import yaml


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-jira"
ROUTER = REPO / "skills" / "ericsson" / "jira" / "SKILL.md"
PLUGIN_SKILLS = {
    "ticket-research": PLUGIN / "skills" / "ticket-research" / "SKILL.md",
    "defect-triage": PLUGIN / "skills" / "defect-triage" / "SKILL.md",
}
REGISTERED_TOOLS = {
    "jira_my_tickets",
    "jira_search_issues",
    "jira_get_issue",
    "jira_add_comment",
}


def _body(path: Path) -> str:
    assert path.is_file(), f"missing Jira skill: {path}"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _start, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert isinstance(metadata, dict)
    expected_name = path.parent.name if "plugins" in path.parts else "jira"
    assert metadata["name"] == expected_name
    assert isinstance(metadata["description"], str) and metadata["description"]
    return body


def test_plugin_skills_own_ticket_research_triage_and_fix_summary_reasoning():
    research = _body(PLUGIN_SKILLS["ticket-research"])
    triage = _body(PLUGIN_SKILLS["defect-triage"])

    assert "one explicit ticket" in research.lower()
    assert "fix summary" in research.lower()
    assert "jira_get_issue" in research
    assert "jira_search_issues" in research
    assert "auto-fix" in triage
    assert "manual-review" in triage
    assert "needs-info" in triage
    assert "not-a-code-fix" in triage
    assert "70" in triage and "40" in triage
    assert "does not grant" in triage.lower()
    assert "jira_add_comment" in triage


def test_jira_skills_reference_only_registered_tools_and_no_transport_or_secret_recipe():
    for path in [*PLUGIN_SKILLS.values(), ROUTER]:
        body = _body(path)
        referenced = set(re.findall(r"jira_[a-z_]+", body))
        assert referenced <= REGISTERED_TOOLS, (path, referenced - REGISTERED_TOOLS)
        lowered = body.lower()
        assert "curl " not in lowered
        assert "authorization:" not in lowered
        assert "jira_pat" not in lowered
        assert "jira_api_token" not in lowered
        assert "hidden prompt" not in lowered
        assert "system prompt" not in lowered


def test_source_router_remains_indexed_while_connector_is_disabled_and_names_plugin_skills():
    manifest = yaml.safe_load((REPO / "sets" / "ericsson.json").read_text())
    assert "skills/ericsson/jira" in manifest["skills"]
    jira = next(entry for entry in manifest["plugins"] if isinstance(entry, dict) and entry.get("id") == "ericsson-jira")
    assert jira["enabled"] is False

    router = _body(ROUTER)
    assert "ericsson-jira:ticket-research" in router
    assert "ericsson-jira:defect-triage" in router
    assert "disabled" in router.lower()
    assert "hermes tools" in router.lower()
    assert "read-only" in router.lower()


def test_plugin_registers_both_qualified_skill_sources_without_embedding_content():
    source = (PLUGIN / "__init__.py").read_text(encoding="utf-8")
    assert '"ticket-research"' in source
    assert '"defect-triage"' in source
    assert "register_skill" in source
    assert "SKILL.md" in source


def test_multi_ticket_exact_parity_is_explicitly_deferred_to_phase6_loop_group():
    defect = (REPO / "docs" / "flows" / "jira-defect-loop.md").read_text(encoding="utf-8")
    showcase = (REPO / "docs" / "flows" / "jira-single-ticket-showcase.md").read_text(encoding="utf-8")
    assert "Phase 6" in defect and "loop_group" in defect
    assert "exact multi-ticket parity" in defect.lower()
    assert "exactly one" in showcase.lower()
    assert "processes multiple tickets" not in showcase.lower()
