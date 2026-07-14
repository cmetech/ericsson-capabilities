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


def test_data_contract_uses_canonical_view_identifiers():
    text = (SKILL_DIR / "references/data-contract.md").read_text()
    assert (
        "Canonical `VIEW` argument values and normalized `view` identifiers are "
        "exactly `wins`, `losses`, `all-progression`, and `positive-progression`."
        in text
    )
    for view in ("wins", "losses", "all-progression", "positive-progression"):
        assert f"--view {view}" in text
    assert "--view all-stage progression" not in text
    assert "--view positive progression" not in text
    assert (
        "The normalized `view` key stores the bare identifier without the "
        "`--view` option name." in text
    )
    assert "all-stage progression” maps to `all-progression`" in text
    assert "positive progression” maps to `positive-progression`" in text


def test_data_contract_requires_transition_warnings_in_both_manifests():
    text = (SKILL_DIR / "references/data-contract.md").read_text()
    assert "Every `mixed` transition emits a `mixed_signals` warning." in text
    assert "Every `unknown` transition emits an `unknown_transition` warning." in text
    assert "Both warnings are retained in `normalized-data.json`" in text
    assert "and carried into `render-manifest.json`" in text


def test_opportunity_visuals_docs_match_the_live_port():
    showcase = (REPO / "docs/showcases/opportunity-visuals.md").read_text()
    config = (REPO / "docs/configuration.md").read_text()
    flow = (REPO / "docs/flows/image-generation.md").read_text()
    for phrase in (
        "showcase-opportunities.csv",
        "wins",
        "losses",
        "all-progression",
        "positive-progression",
        "one question at a time",
        "render-manifest.json",
        "visual verification",
    ):
        assert phrase in showcase
    assert "No API key is required" in config
    assert "openpyxl>=3.1.5" in config
    assert "playwright>=1.52" in config
    assert "status: intent-ported" in flow
    assert "opportunity-visuals" in flow
