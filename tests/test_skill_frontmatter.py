from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]


def _frontmatter(path):
    text = path.read_text()
    assert text.startswith("---\n"), f"{path}: missing frontmatter"
    fm = text.split("---\n", 2)[1]
    return yaml.safe_load(fm)


def all_skill_mds():
    return sorted((REPO / "skills").rglob("SKILL.md"))


def test_skills_exist():
    names = {p.parent.name for p in all_skill_mds()}
    assert "workflow-orchestrator" in names


def test_frontmatter_required_fields():
    for p in all_skill_mds():
        fm = _frontmatter(p)
        assert fm.get("name") == p.parent.name, f"{p}: name must match dir"
        assert isinstance(fm.get("description"), str) and len(fm["description"]) <= 1024
        hermes = (fm.get("metadata") or {}).get("hermes") or {}
        assert "ericsson" in [t.lower() for t in hermes.get("tags", [])], f"{p}: needs ericsson tag"
        assert fm.get("requires_toolsets"), f"{p}: must gate on an Ericsson toolset"


def test_orchestrator_mentions_all_commands():
    body = (REPO / "skills/ericsson/workflow-orchestrator/SKILL.md").read_text()
    for cmd in ("validate", "start", "next", "record", "approve", "reject",
                "status", "list", "resume", "skip", "cancel", "clean", "set-kanban"):
        assert cmd in body, f"SKILL.md must document workflow_ctl {cmd}"
