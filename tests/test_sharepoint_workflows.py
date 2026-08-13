from pathlib import Path
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows/sharepoint-document-intake.yml"
SCRIPTS = ROOT / "skills/ericsson/workflow-orchestrator/scripts"
sys.path.insert(0, str(SCRIPTS))

import workflow_ctl as wc  # noqa: E402


def test_document_intake_has_flat_toolset_requirement_and_exact_tool_node():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow["requires"] == ["ericsson-sharepoint"]
    assert len(workflow["nodes"]) == 1
    node = workflow["nodes"][0]
    assert node["kind"] == "tool"
    assert node["allowed_tools"] == [
        "sharepoint_resolve_url",
        "sharepoint_list_items",
        "sharepoint_download",
    ]
    assert node["output"] == "sharepoint-intake-manifest.json"
    assert "parse" not in node["prompt"].lower()
    assert "generate" not in node["prompt"].lower()


def test_document_intake_compiles_with_real_workflow_controller():
    errors, _warnings = wc.validate_workflow(wc.load_workflow(WORKFLOW))
    assert errors == []


def test_workflow_stops_at_artifact_acquisition_and_docs_state_handoff():
    workflow = WORKFLOW.read_text().lower()
    docs = (ROOT / "docs/flows/sharepoint-document-intake.md").read_text().lower()
    assert "document processing" in docs
    assert "separate" in docs
    assert "ocr" in docs
    assert "sharepoint_audit_permissions" not in workflow
    assert "sharepoint_upload" not in workflow


def test_audit_example_preserves_independent_browser_readiness():
    docs = (ROOT / "docs/flows/sharepoint-document-intake.md").read_text().lower()
    assert "browser_enrollment_required" in docs
    assert "graph file tools remain available" in docs
    assert "sharepoint_audit_permissions" in docs
