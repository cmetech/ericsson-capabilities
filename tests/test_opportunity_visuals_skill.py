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
        "expected-run-summary.json",
        "analyze",
        "PNG if available",
        "$Python =",
        "$RunRoot =",
        "Python 3.11+",
        "bootstrap.sh` does not enforce",
        ".venv/bin/python --version",
        "reuses an existing `.venv`",
        "selected Python 3.11+ interpreter",
        "minimal stage labels and diagnostics",
    ):
        assert phrase in showcase
    assert "Do not paste confidential rows into chat unless" in showcase
    assert "no opportunity data is sent to a hosted model" not in showcase
    assert "No API key is required" in config
    assert "openpyxl>=3.1.5" in config
    assert "playwright>=1.52" in config
    assert "status: intent-ported" in flow
    assert "opportunity-visuals" in flow
    assert "model-backed coworker" in config
    assert "local helpers" in config


def test_opportunity_visuals_interview_documents_read_only_analysis():
    skill = (SKILL_DIR / "SKILL.md").read_text()
    contract = (SKILL_DIR / "references/data-contract.md").read_text()
    normalized_contract = " ".join(contract.split())
    interview = (SKILL_DIR / "references/interview-guide.md").read_text()

    assert "prepare_opportunities.py analyze" in skill
    assert "prepare_opportunities.py analyze SOURCE --view VIEW" in contract
    assert "unresolved_transitions" in contract
    assert "unresolved_terminal_stages" in contract
    assert '"non_terminal_stages": ["Discovery"]' in contract
    assert "terminal_status_resolved" in contract
    assert "affects_truncation" in contract
    assert "terminal metadata, and first-terminal cutoff" in contract
    assert "pre-range stage history" in contract
    assert (
        "terminal-before-range exclusion is evaluated before filters"
        in normalized_contract
    )
    assert "uncached formula" in contract
    assert "mixed_transitions" in contract
    assert "add it to `non_terminal_stages`" in interview
    assert "terminal status" in interview
    assert "rerun" in interview
    assert "before preparing artifacts" in interview
    assert "forward, backward, or neutral" in interview
