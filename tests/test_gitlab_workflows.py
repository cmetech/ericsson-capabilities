from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import yaml


REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / "workflows/jira-to-gitlab.yml"

READ_TOOLS = {
    "jira_get_issue",
    "gitlab_resolve_project",
    "gitlab_list_repository_tree",
    "gitlab_read_file",
    "gitlab_read_merge_request",
}
WRITE_TOOLS = {
    "gitlab_create_branch",
    "gitlab_commit_changes",
    "gitlab_create_merge_request",
    "jira_add_comment",
}
OUTWARD_NODES = {
    "create-branch",
    "commit-changes",
    "create-merge-request",
    "update-jira",
}


def _document() -> dict:
    assert WORKFLOW.is_file(), "missing Task 11 Jira-to-GitLab workflow"
    document = yaml.safe_load(WORKFLOW.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _node_map(document: dict) -> dict[str, dict]:
    nodes = document.get("nodes")
    assert isinstance(nodes, list) and nodes
    assert all(
        isinstance(node, dict) and isinstance(node.get("id"), str) for node in nodes
    )
    mapped = {node["id"]: node for node in nodes}
    assert len(mapped) == len(nodes)
    return mapped


def _hermes_checkout() -> Path:
    override = os.environ.get("HERMES_AGENT_DIR")
    candidates = []
    if override:
        candidates.append(Path(override))
    workspace = REPO.parents[2]
    candidates.extend(
        [
            workspace / "hermes-agent/.worktrees/ericsson-gitlab-connector",
            workspace / "hermes-agent",
        ]
    )
    for candidate in candidates:
        if (candidate / "plugins/workflow/schema.py").is_file():
            return candidate
    raise AssertionError(
        "paired Hermes checkout with the real workflow compiler is missing"
    )


def test_jira_to_gitlab_is_flat_archon_source_with_exact_dependencies() -> None:
    # GL-JIRA-04/05/11/13: explicit ticket flow replaces Langflow aggregation/fallback.
    document = _document()
    assert document["name"] == "jira-to-gitlab"
    assert document["requires"] == ["ericsson-gitlab", "ericsson-jira"]
    assert "loop_group" not in WORKFLOW.read_text(encoding="utf-8")
    nodes = _node_map(document)
    assert set(nodes) == {
        "read-ticket",
        "resolve-project",
        "research-repository",
        "reason-about-fix",
        "approve-code-writes",
        "create-branch",
        "commit-changes",
        "create-merge-request",
        "review-merge-request",
        "approve-jira-update",
        "update-jira",
        "report-status",
    }
    assert nodes["resolve-project"]["depends_on"] == ["read-ticket"]
    assert nodes["research-repository"]["depends_on"] == ["resolve-project"]
    assert nodes["reason-about-fix"]["depends_on"] == ["research-repository"]
    assert nodes["approve-code-writes"]["depends_on"] == ["reason-about-fix"]
    assert nodes["create-branch"]["depends_on"] == ["approve-code-writes"]
    assert nodes["commit-changes"]["depends_on"] == ["create-branch"]
    assert nodes["create-merge-request"]["depends_on"] == ["commit-changes"]
    assert nodes["review-merge-request"]["depends_on"] == ["create-merge-request"]
    assert nodes["approve-jira-update"]["depends_on"] == ["review-merge-request"]
    assert nodes["update-jira"]["depends_on"] == ["approve-jira-update"]
    assert nodes["report-status"]["depends_on"] == ["update-jira"]


def test_each_reasoning_node_has_an_exact_least_privilege_tool_contract() -> None:
    # GL-WRITE-04/08 and GL-JIRA-06/07/09/10: the active agent reasons inside
    # bounded nodes; deterministic tools remain explicit and least-privilege.
    nodes = _node_map(_document())
    expected = {
        "read-ticket": ["jira_get_issue"],
        "resolve-project": ["gitlab_resolve_project"],
        "research-repository": [
            "gitlab_list_repository_tree",
            "gitlab_read_file",
        ],
        "reason-about-fix": [],
        "create-branch": ["gitlab_create_branch"],
        "commit-changes": ["gitlab_commit_changes"],
        "create-merge-request": ["gitlab_create_merge_request"],
        "review-merge-request": [
            "gitlab_read_merge_request",
            "gitlab_read_file",
        ],
        "update-jira": ["jira_add_comment"],
        "report-status": [],
    }
    for node_id, tools in expected.items():
        assert nodes[node_id]["allowed_tools"] == tools
    assert {
        tool for tools in expected.values() for tool in tools if tool in READ_TOOLS
    } == READ_TOOLS
    assert {
        tool for tools in expected.values() for tool in tools if tool in WRITE_TOOLS
    } == WRITE_TOOLS


def test_every_write_is_downstream_of_visible_approval_and_uses_preview_semantics() -> (
    None
):
    # GL-WRITE-03/05/06/08/10 and GL-JIRA-08/09: workflow approval is visible;
    # each tool still consumes the host's current-invocation admission.
    nodes = _node_map(_document())
    assert "approval" in nodes["approve-code-writes"]
    assert "approval" in nodes["approve-jira-update"]
    for node_id in OUTWARD_NODES - {"update-jira"}:
        prompt = nodes[node_id]["prompt"].lower()
        assert "dry_run" in prompt
        assert "host approval" in prompt
    jira_prompt = nodes["update-jira"]["prompt"].lower()
    assert "host approval" in jira_prompt
    assert "exact approved" in jira_prompt


def test_workflow_preserves_truthful_per_ticket_status_and_uncertain_write_stop() -> (
    None
):
    # GL-JIRA-05/08/09/10/13: not_found and every failure stay visible; exact
    # multi-ticket loop parity remains deferred rather than silently claimed.
    text = WORKFLOW.read_text(encoding="utf-8").lower()
    for phrase in (
        "not_found",
        "per-ticket",
        "uncertain",
        "do not retry",
        "merge request",
        "attention needed",
        "zero-ticket",
    ):
        assert phrase in text


def test_real_archon_compiler_and_admission_accept_exact_ready_authorities() -> None:
    # Task 7 public contract: flat requires and allowed_tools compile under the
    # pinned Archon profile, then admit only with exact ready services/tools.
    _document()
    hermes = _hermes_checkout()
    python = hermes / ".venv/bin/python"
    assert python.is_file()
    script = r"""
import json
from pathlib import Path
import sys
from plugins.workflow.compilation import WorkflowCatalogSnapshot, compile_workflow
from plugins.workflow.schema import parse_workflow_source_bytes
from plugins.workflow.admission_service import assess_workflow_admission
from tests.plugins.workflow.test_phase5_admission_parity import _context

path = Path(sys.argv[1]).resolve()
workflow_bytes = path.read_bytes()
sidecar_bytes = b'''language_compatibility: archon-2026-07
outward_action_nodes:
  - create-branch
  - commit-changes
  - create-merge-request
  - update-jira
outward_action_policy: approval_required
'''
source = parse_workflow_source_bytes(
    path,
    workflow_bytes=workflow_bytes,
    sidecar_bytes=sidecar_bytes,
    source="ericsson",
    precedence=1,
)
compilation = compile_workflow(
    source,
    WorkflowCatalogSnapshot.capture((source,)),
    normalizer_version=5,
)
package = compilation.package
tools = {
    tool
    for node in package.definition.nodes
    for tool in node.options.get("allowed_tools", ())
}
assessment = assess_workflow_admission(
    compilation,
    _context(),
    available_services=frozenset({"ericsson-gitlab", "ericsson-jira"}),
    available_tools=frozenset(tools),
)
print(json.dumps({
    "profile": package.language.effective_profile.value,
    "requires": list(package.definition.options["requires"]),
    "outward": list(package.sidecar["outward_action_nodes"]),
    "policy": package.sidecar["outward_action_policy"],
    "runnable": assessment.compatibility.runnable,
    "next_actions": list(assessment.next_actions),
}))
"""
    result = subprocess.run(
        [str(python), "-c", script, str(WORKFLOW)],
        cwd=hermes,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    payload = json.loads(result.stdout)
    assert payload == {
        "profile": "archon-2026-07",
        "requires": ["ericsson-gitlab", "ericsson-jira"],
        "outward": [
            "create-branch",
            "commit-changes",
            "create-merge-request",
            "update-jira",
        ],
        "policy": "approval_required",
        "runnable": True,
        "next_actions": ["run"],
    }


def test_workflow_contains_no_secret_transport_or_hidden_model_authority() -> None:
    text = WORKFLOW.read_text(encoding="utf-8").lower() if WORKFLOW.is_file() else ""
    assert WORKFLOW.is_file(), "missing Task 11 Jira-to-GitLab workflow"
    forbidden = {
        "loop_group",
        "private-token",
        "authorization:",
        "jira_pat",
        "gitlab_pat",
        ".env",
        "curl ",
        "subprocess",
        "ollama",
        "openai",
        "anthropic",
        "codereviewrunner",
        "model:",
    }
    assert not {token for token in forbidden if token in text}
