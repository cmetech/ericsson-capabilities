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
        assert fm.get("name") == p.parent.name
        assert isinstance(fm.get("description"), str) and len(fm["description"]) <= 1024
        hermes = (fm.get("metadata") or {}).get("hermes") or {}
        assert "ericsson" in [t.lower() for t in hermes.get("tags", [])]
        assert "requires_toolsets" not in fm, f"{p}: skills must NOT gate on a toolset (no-toggle model)"
        assert "ERICSSON_ENV" not in ((fm.get("prerequisites") or {}).get("env_vars") or [])


def test_orchestrator_mentions_all_commands():
    body = (REPO / "skills/ericsson/workflow-orchestrator/SKILL.md").read_text()
    for cmd in ("validate", "start", "next", "record", "approve", "reject",
                "status", "list", "resume", "skip", "cancel", "clean", "set-kanban"):
        assert cmd in body, f"SKILL.md must document workflow_ctl {cmd}"
