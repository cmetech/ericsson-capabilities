import json
import os
from pathlib import Path
import subprocess
import sys

import yaml


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / "workflows/sharepoint-document-intake.yml"
SIDECAR = ROOT / "workflows/sharepoint-document-intake.hermes.yaml"


def test_document_intake_has_flat_toolset_requirement_and_exact_tool_node():
    workflow = yaml.safe_load(WORKFLOW.read_text())
    assert workflow["requires"] == ["ericsson-sharepoint"]
    assert len(workflow["nodes"]) == 1
    node = workflow["nodes"][0]
    assert "kind" not in node
    assert node["allowed_tools"] == [
        "sharepoint_resolve_url",
        "sharepoint_list_items",
        "sharepoint_download",
    ]
    assert "output" not in node
    assert "sharepoint-intake-manifest.json" in node["prompt"]
    assert "parse" not in node["prompt"].lower()
    assert "generate" not in node["prompt"].lower()
    sidecar = yaml.safe_load(SIDECAR.read_text())
    assert sidecar["language_compatibility"] == "archon-2026-07"
    assert sidecar["delivery_defaults"]["inputs"]["arguments"] == {
        "kind": "text",
        "required": True,
        "max_bytes": 8192,
    }
    assert sidecar["overlap_policy"] == "forbid"


def test_document_intake_compiles_with_real_archon_authority():
    override = os.environ.get("HERMES_AGENT_DIR")
    candidates = [Path(override)] if override else []
    if not candidates:
        source_root = next(
            path
            for path in (ROOT, *ROOT.parents)
            if path.name == "ericsson-capabilities"
        )
        candidates.append(source_root.parent / "hermes-agent")
    hermes = next(
        path for path in candidates if (path / "plugins/workflow/schema.py").is_file()
    )
    python = Path(os.environ.get("HERMES_PYTHON") or sys.executable)
    script = r"""
import json
from pathlib import Path
import sys
from plugins.workflow.compilation import WorkflowCatalogSnapshot, compile_workflow
from plugins.workflow.schema import parse_workflow_source_bytes

path = Path(sys.argv[1])
sidecar = path.with_name(f"{path.stem}.hermes.yaml")
source = parse_workflow_source_bytes(
    path,
    workflow_bytes=path.read_bytes(),
    sidecar_bytes=sidecar.read_bytes(),
    source="ericsson",
    precedence=1,
)
compilation = compile_workflow(source, WorkflowCatalogSnapshot.capture((source,)))
package = compilation.package
print(json.dumps({
    "requires": list(package.definition.options["requires"]),
    "nodes": [node.id for node in package.definition.nodes],
    "allowed_tools": sorted({
        tool
        for node in package.definition.nodes
        for tool in node.options.get("allowed_tools", ())
    }),
}))
"""
    result = subprocess.run(
        [
            str(python),
            "-c",
            script,
            str(WORKFLOW),
        ],
        cwd=hermes,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout) == {
        "requires": ["ericsson-sharepoint"],
        "nodes": ["acquire"],
        "allowed_tools": [
            "sharepoint_download",
            "sharepoint_list_items",
            "sharepoint_resolve_url",
        ],
    }


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
