from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def test_router_remains_source_owned_and_explains_disabled_plugin_loading():
    path = ROOT / "skills/ericsson/sharepoint/SKILL.md"
    body = path.read_text(encoding="utf-8")
    frontmatter = yaml.safe_load(body.split("---", 2)[1])
    assert frontmatter["name"] == "sharepoint"
    assert "disabled by default" in body.lower()
    assert "fresh conversation" in body.lower()
    assert all(
        name in body
        for name in (
            "ericsson-sharepoint:sharepoint-navigation",
            "ericsson-sharepoint:sharepoint-file-operations",
            "ericsson-sharepoint:sharepoint-permission-audit",
        )
    )


def test_detailed_skills_cover_auth_readiness_bounds_approval_and_handoff():
    roots = ROOT / "plugins/ericsson-sharepoint/skills"
    bodies = {
        path.parent.name: path.read_text(encoding="utf-8")
        for path in roots.glob("*/SKILL.md")
    }
    assert set(bodies) == {
        "sharepoint-navigation",
        "sharepoint-file-operations",
        "sharepoint-permission-audit",
    }
    combined = "\n".join(bodies.values()).lower()
    for phrase in (
        "delegated msal",
        "app-only",
        "azure cli",
        "graph readiness",
        "browser enrollment",
        "configured download root",
        "approval",
        "recycle",
        "bounded",
        "document processing",
    ):
        assert phrase in combined
    assert "permanent delete" in combined
    assert "does not parse" in combined
    for body in bodies.values():
        assert "subprocess" not in body.lower()
        assert "remote-debugging-port" not in body.lower()
        assert "access_token" not in body


def test_plugin_registers_only_detailed_skills_when_enabled():
    init = (ROOT / "plugins/ericsson-sharepoint/__init__.py").read_text()
    assert "register_skill" in init
    assert "sharepoint-navigation" in init
    assert "sharepoint-file-operations" in init
    assert "sharepoint-permission-audit" in init
