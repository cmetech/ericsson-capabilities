from pathlib import Path
import sys

import yaml
import workflow_ctl as wc

REPO = Path(__file__).resolve().parents[1]
REFS = sorted((REPO / "workflows").glob("*.yml"))
LEGACY_V1 = {"inbox-digest"}
FLAT_ARCHON = {
    "jira-to-gitlab",
    "my-tickets-summary",
    "jira-single-ticket-showcase",
    "sharepoint-document-intake",
}
sys.path.insert(0, str(REPO / "scripts"))
from lint_manifest import _lint_archon_workflow  # noqa: E402


def test_reference_workflow_formats_are_explicit_and_complete():
    assert {p.stem for p in REFS} == LEGACY_V1 | FLAT_ARCHON
    for path in REFS:
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        requires = document.get("requires") if isinstance(document, dict) else None
        sidecar_path = path.with_name(f"{path.stem}.hermes.yaml")
        if path.stem in LEGACY_V1:
            assert not sidecar_path.exists(), f"{path.name}: unexpected profile sidecar"
            assert isinstance(requires, dict), f"{path.name}: expected V1 mapping"
        elif path.stem in FLAT_ARCHON:
            sidecar = yaml.safe_load(sidecar_path.read_text(encoding="utf-8"))
            assert sidecar["language_compatibility"] == "archon-2026-07"
            assert isinstance(requires, list), f"{path.name}: expected flat Archon list"
        else:  # pragma: no cover - exact set assertion above guards future drift
            raise AssertionError(f"unknown workflow format: {path.name}")


def test_v1_reference_workflows_validate_cleanly():
    for p in (path for path in REFS if path.stem in LEGACY_V1):
        doc = wc.load_workflow(p)
        errors, _warnings = wc.validate_workflow(doc)
        assert errors == [], f"{p.name}: {errors}"
        assert "ericsson" in doc.get("tags", []), f"{p.name}: missing ericsson tag"
        for n in doc.get("nodes", []):
            assert "$inputs" not in n.get("prompt", ""), (
                f"{p.name} node {n.get('id')}: prompt uses non-interpolated $inputs syntax"
            )


def test_flat_archon_reference_workflows_validate_cleanly():
    # The paired Task 11 gate compiles/admit-checks the same source with the real
    # Hermes compiler; this repository-side check rejects malformed static shape.
    for path in (item for item in REFS if item.stem in FLAT_ARCHON):
        document = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert _lint_archon_workflow(document) == []
        for node in document["nodes"]:
            assert "$inputs" not in node.get("prompt", ""), (
                f"{path.name} node {node.get('id')}: prompt uses non-interpolated $inputs syntax"
            )


def test_reference_workflows_do_not_require_ericsson_toggle():
    for path in (REPO / "workflows").glob("*.yml"):
        assert "ERICSSON_ENV" not in path.read_text()


def test_tickets_summary_is_read_only_and_showcase_comment_has_approval_ancestor():
    summary = yaml.safe_load((REPO / "workflows/my-tickets-summary.yml").read_text())
    assert {
        tool for node in summary["nodes"] for tool in node.get("allowed_tools", [])
    } == {"jira_my_tickets"}
    showcase = yaml.safe_load(
        (REPO / "workflows/jira-single-ticket-showcase.yml").read_text()
    )
    nodes = {node["id"]: node for node in showcase["nodes"]}
    assert "approve-comment" in nodes["post-comment"]["depends_on"]
    assert nodes["post-comment"]["allowed_tools"] == ["jira_add_comment"]
