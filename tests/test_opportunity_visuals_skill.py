from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skills/ericsson/opportunity-visuals"


def test_opportunity_visuals_frontmatter_contract():
    text = (SKILL_DIR / "SKILL.md").read_text()
    fm = yaml.safe_load(text.split("---\n", 2)[1])
    assert fm["name"] == "opportunity-visuals"
    assert fm["description"] == "Create Ericsson opportunity progression visuals."
    assert len(fm["description"]) <= 60
    assert fm["platforms"] == ["macos", "linux", "windows"]
    assert "Ericsson" in fm["metadata"]["hermes"]["tags"]


def test_opportunity_visuals_interview_and_trigger_contract():
    body = (SKILL_DIR / "SKILL.md").read_text()
    required = (
        "one question at a time",
        "wins",
        "losses",
        "all-stage progression",
        "positive progression",
        "play back",
        "confirm",
        "prepare_opportunities.py",
        "render_opportunity_visual.py",
        "image_generate",
        "generic image",
        "exclusions.json",
        "render-manifest.json",
    )
    for phrase in required:
        assert phrase in body


def test_opportunity_visuals_references_and_requirements_exist():
    for rel in (
        "references/data-contract.md",
        "references/interview-guide.md",
        "references/visual-rules.md",
        "requirements.txt",
    ):
        assert (SKILL_DIR / rel).is_file()
    requirements = (SKILL_DIR / "requirements.txt").read_text().splitlines()
    assert "openpyxl>=3.1.5" in requirements
    assert "playwright>=1.52" in requirements
