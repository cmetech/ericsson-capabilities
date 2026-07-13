from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / "skills/ericsson/workflow-builder/SKILL.md"


def test_builder_frontmatter():
    fm = yaml.safe_load(SKILL.read_text().split("---\n", 2)[1])
    hermes = (fm.get("metadata") or {}).get("hermes") or {}
    assert "workflow-orchestrator" in hermes.get("related_skills", [])


def test_builder_body_contract():
    body = SKILL.read_text()
    for needle in ("one question at a time", "workflow_ctl", "validate",
                   "workflows/", "workflow-schema.md", "side_effects",
                   "approval", "schedule"):
        assert needle in body, f"SKILL.md must mention: {needle}"
    assert (REPO / "skills/ericsson/workflow-builder/references/interview-guide.md").exists()
