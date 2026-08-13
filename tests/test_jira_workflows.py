from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import yaml


REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "scripts"))
from lint_manifest import _lint_archon_workflow  # noqa: E402


WORKFLOWS = {
    "my-tickets-summary": REPO / "workflows" / "my-tickets-summary.yml",
    "jira-single-ticket-showcase": REPO / "workflows" / "jira-single-ticket-showcase.yml",
}
PACKAGED_JIRA_WORKFLOWS = {
    "my-tickets-summary",
    "jira-single-ticket-showcase",
    "jira-to-gitlab",
}


def _document(name):
    path = WORKFLOWS[name]
    assert path.is_file(), f"missing Jira workflow: {path}"
    document = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _sidecar(name):
    path = WORKFLOWS[name].with_name(f"{name}.hermes.yaml")
    assert path.is_file(), f"missing Jira workflow profile: {path}"
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def test_jira_workflows_are_flat_archon_and_statically_valid():
    for name in WORKFLOWS:
        document = _document(name)
        assert document["requires"] == ["ericsson-jira"]
        assert _lint_archon_workflow(document) == []
        assert _sidecar(name)["language_compatibility"] == "archon-2026-07"
        for node in document["nodes"]:
            if "prompt" in node:
                assert isinstance(node.get("allowed_tools"), list)


def test_summary_uses_only_bounded_jira_read_then_tool_free_reasoning():
    nodes = {node["id"]: node for node in _document("my-tickets-summary")["nodes"]}
    assert set(nodes) == {"fetch-tickets", "summarize-tickets"}
    assert nodes["fetch-tickets"]["allowed_tools"] == ["jira_my_tickets"]
    assert nodes["summarize-tickets"]["allowed_tools"] == []
    assert nodes["summarize-tickets"]["depends_on"] == ["fetch-tickets"]


def test_showcase_accepts_one_issue_key_and_has_exact_read_triage_approval_write_path():
    document = _document("jira-single-ticket-showcase")
    nodes = {node["id"]: node for node in document["nodes"]}
    assert set(nodes) == {"read-ticket", "triage-ticket", "approve-comment", "post-comment", "report-status"}
    assert "$ARGUMENTS" in nodes["read-ticket"]["prompt"]
    assert "exactly one" in nodes["read-ticket"]["prompt"].lower()
    assert nodes["read-ticket"]["allowed_tools"] == ["jira_get_issue"]
    assert nodes["triage-ticket"]["allowed_tools"] == []
    assert nodes["post-comment"]["allowed_tools"] == ["jira_add_comment"]
    assert nodes["report-status"]["allowed_tools"] == []
    assert nodes["approve-comment"]["approval"]["capture_response"] is True
    sidecar = _sidecar("jira-single-ticket-showcase")
    assert sidecar["delivery_defaults"]["inputs"] == {
        "arguments": {"kind": "text", "required": True, "max_bytes": 128}
    }
    assert sidecar["outward_action_nodes"] == ["post-comment"]
    assert sidecar["outward_action_policy"] == "approval_required"


def test_showcase_has_no_hidden_loop_or_unregistered_jira_tool():
    text = WORKFLOWS["jira-single-ticket-showcase"].read_text(encoding="utf-8")
    assert "loop_group" not in text
    assert "foreach" not in text.lower()
    allowed = {
        tool
        for node in _document("jira-single-ticket-showcase")["nodes"]
        for tool in node.get("allowed_tools", [])
    }
    assert allowed == {"jira_get_issue", "jira_add_comment"}


def test_real_hermes_compiler_accepts_both_jira_workflows():
    override = os.environ.get("HERMES_AGENT_DIR")
    workspace = REPO.parents[2]
    candidates = [Path(override)] if override else []
    candidates.extend(
        [
            workspace / "hermes-agent/.worktrees/ericsson-jira-connector",
            workspace / "hermes-agent/.worktrees/ericsson-gitlab-connector",
            workspace / "hermes-agent",
        ]
    )
    hermes = next(path for path in candidates if (path / "plugins/workflow/schema.py").is_file())
    script = r"""
import json
from pathlib import Path
import sys
from plugins.workflow.compilation import WorkflowCatalogSnapshot, compile_workflow
from plugins.workflow.schema import parse_workflow_source_bytes

results = {}
for raw in sys.argv[1:]:
    path = Path(raw)
    sidecar = path.with_name(f"{path.stem}.hermes.yaml")
    source = parse_workflow_source_bytes(
        path,
        workflow_bytes=path.read_bytes(),
        sidecar_bytes=sidecar.read_bytes(),
        source="ericsson",
        precedence=1,
    )
    compilation = compile_workflow(source, WorkflowCatalogSnapshot.capture((source,)))
    results[path.stem] = {
        "requires": list(compilation.package.definition.options["requires"]),
        "nodes": [node.id for node in compilation.package.definition.nodes],
    }
print(json.dumps(results, sort_keys=True))
"""
    result = subprocess.run(
        [str(hermes / ".venv/bin/python"), "-c", script, *map(str, WORKFLOWS.values())],
        cwd=hermes,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr
    compiled = json.loads(result.stdout)
    assert set(compiled) == set(WORKFLOWS)
    assert all(value["requires"] == ["ericsson-jira"] for value in compiled.values())


def test_authenticated_distribution_package_verifies_every_jira_workflow():
    override = os.environ.get("HERMES_AGENT_DIR")
    workspace = REPO.parents[2]
    candidates = [Path(override)] if override else []
    candidates.extend(
        [
            workspace / "hermes-agent/.worktrees/ericsson-jira-connector",
            workspace / "hermes-agent",
        ]
    )
    hermes = next(
        path for path in candidates if (path / "hermes_cli/capability_staging.py").is_file()
    )
    package = REPO / "capabilities/workflow-packages/ericsson"
    script = r"""
import json
from pathlib import Path
import sys
from hermes_cli.capability_staging import _verified_workflow_package

package = Path(sys.argv[1])
verified = _verified_workflow_package(package, package / "digests.json")
print(json.dumps(sorted(name for name, _digest, _package, _compilation in verified)))
"""
    result = subprocess.run(
        [str(hermes / ".venv/bin/python"), "-c", script, str(package)],
        cwd=hermes,
        text=True,
        capture_output=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert set(json.loads(result.stdout)) >= PACKAGED_JIRA_WORKFLOWS
