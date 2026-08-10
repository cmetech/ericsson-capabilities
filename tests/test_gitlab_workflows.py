from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import yaml


REPO = Path(__file__).resolve().parents[1]
WORKFLOW = REPO / "workflows/jira-to-gitlab.yml"
SIDECAR = REPO / "workflows/jira-to-gitlab.hermes.yaml"

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


def _sidecar() -> dict:
    assert SIDECAR.is_file(), "missing Task 11 Jira-to-GitLab workflow sidecar"
    document = yaml.safe_load(SIDECAR.read_text(encoding="utf-8"))
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
    assert _sidecar() == {
        "language_compatibility": "archon-2026-07",
        "delivery_defaults": {
            "inputs": {
                "arguments": {
                    "kind": "text",
                    "required": True,
                    "max_bytes": 4096,
                }
            }
        },
        "overlap_policy": "forbid",
        "outward_action_nodes": [
            "create-branch",
            "commit-changes",
            "create-merge-request",
            "update-jira",
        ],
        "outward_action_policy": "approval_required",
    }
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
    assert nodes["create-branch"]["depends_on"] == [
        "approve-code-writes",
        "reason-about-fix",
    ]
    assert nodes["commit-changes"]["depends_on"] == [
        "create-branch",
        "reason-about-fix",
    ]
    assert nodes["create-merge-request"]["depends_on"] == [
        "commit-changes",
        "create-branch",
        "reason-about-fix",
    ]
    assert nodes["review-merge-request"]["depends_on"] == [
        "create-merge-request",
        "commit-changes",
    ]
    assert nodes["approve-jira-update"]["depends_on"] == ["review-merge-request"]
    assert nodes["update-jira"]["depends_on"] == [
        "approve-jira-update",
        "review-merge-request",
    ]
    assert nodes["report-status"]["depends_on"] == [
        "update-jira",
        "review-merge-request",
    ]


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
    for node_id in expected:
        schema = nodes[node_id].get("output_format")
        assert isinstance(schema, dict), f"{node_id}: missing structured output"
        assert schema.get("type") == "object"
        assert schema.get("additionalProperties") is False
        assert set(schema.get("required", ())) == set(schema.get("properties", {}))


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
sidecar_path = path.with_name(f"{path.stem}.hermes.yaml")
source = parse_workflow_source_bytes(
    path,
    workflow_bytes=workflow_bytes,
    sidecar_bytes=sidecar_path.read_bytes(),
    source="ericsson",
    precedence=1,
)
compilation = compile_workflow(
    source,
    WorkflowCatalogSnapshot.capture((source,)),
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
    "normalizer": package.language.normalizer_version,
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
        "normalizer": 5,
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


def test_real_package_renders_ticket_and_direct_predecessor_context_without_gaps() -> (
    None
):
    # GL-JIRA-04/05/06/07/08/09/10/13: every fresh node receives only its
    # declared direct data authorities through the real normalizer-v5 renderer.
    hermes = _hermes_checkout()
    python = hermes / ".venv/bin/python"
    script = r"""
import hashlib
import json
from pathlib import Path
import re
import sys
from plugins.workflow.compilation import WorkflowCatalogSnapshot, compile_workflow
from plugins.workflow.output_resolution import ResolvedNodeOutput
from plugins.workflow.resources import VariableContext, substitution_renderer
from plugins.workflow.schema import parse_workflow_source_bytes

path = Path(sys.argv[1]).resolve()
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

values = {
    "read-ticket": {
        "ticket_key": "ERIC-123",
        "ticket_summary": "READ_SENTINEL",
        "project_path": "group/project",
    },
    "resolve-project": {
        "ticket_key": "ERIC-123",
        "ticket_summary": "READ_SENTINEL",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "RESOLVE_SENTINEL",
    },
    "research-repository": {
        "ticket_key": "ERIC-123",
        "ticket_summary": "READ_SENTINEL",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "RESOLVE_SENTINEL",
        "evidence_summary": "RESEARCH_SENTINEL",
    },
    "reason-about-fix": {
        "ticket_key": "ERIC-123",
        "ticket_summary": "READ_SENTINEL",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "main",
        "branch_prefix": "fix",
        "branch_summary": "PROPOSAL_SENTINEL",
        "commit_message": "Fix ERIC-123",
        "actions": [{"action": "update", "file_path": "a.py", "content": "ACTION_SENTINEL"}],
        "mr_title": "ERIC-123 fix",
        "mr_description": "PROPOSAL_DESCRIPTION",
    },
    "create-branch": {
        "project_id": 42,
        "project_path": "group/project",
        "branch_name": "BRANCH_SENTINEL",
        "source_branch": "main",
        "web_url": "https://gitlab.example/branch",
        "status": "created",
    },
    "commit-changes": {
        "project_id": 42,
        "branch_name": "BRANCH_SENTINEL",
        "commit_id": "COMMIT_SENTINEL",
        "web_url": "https://gitlab.example/commit",
        "status": "committed",
    },
    "create-merge-request": {
        "project_id": 42,
        "iid": 7,
        "source_branch": "BRANCH_SENTINEL",
        "target_branch": "main",
        "title": "ERIC-123 fix",
        "state": "opened",
        "web_url": "MR_SENTINEL",
        "status": "created",
    },
    "review-merge-request": {
        "ticket_key": "ERIC-123",
        "project_id": 42,
        "iid": 7,
        "merge_request_url": "REVIEW_MR_URL",
        "verdict": "attention_needed",
        "review_summary": "REVIEW_SENTINEL",
        "warnings": ["bounded"],
        "status": "reviewed",
    },
    "update-jira": {
        "ticket_key": "ERIC-123",
        "merge_request_url": "REVIEW_MR_URL",
        "comment_status": "JIRA_SENTINEL",
        "status": "updated",
    },
}

def resolved(node_id, value):
    data = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return ResolvedNodeOutput(
        canonical_bytes=data,
        value=value,
        text=data.decode(),
        media_type="application/json",
        sha256=hashlib.sha256(data).hexdigest(),
        node_id=node_id,
        attempt_id="attempt-winner",
        publication_id="a" * 32,
        schema_fingerprint="b" * 64,
        canonicalization_version=1,
    )

outputs = {node_id: resolved(node_id, value) for node_id, value in values.items()}
variables = VariableContext(
    arguments="ERIC-123 USER_SENTINEL",
    node_outputs=outputs,
    normalizer_version=package.language.normalizer_version,
)
rendered = {}
for node in package.definition.nodes:
    if node.node_type == "prompt":
        template = str(node.value)
    elif node.node_type == "approval":
        template = str(node.value["message"])
    else:
        continue
    prompt = substitution_renderer(
        variables,
        direct_dependencies=node.depends_on,
    ).render_prompt(template)
    if "$ARGUMENTS" in prompt or re.search(r"\$[^ ]+\.output", prompt):
        raise AssertionError(f"unresolved workflow reference in {node.id}: {prompt}")
    rendered[node.id] = prompt
print(json.dumps(rendered, sort_keys=True))
"""
    result = subprocess.run(
        [str(python), "-c", script, str(WORKFLOW)],
        cwd=hermes,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    rendered = json.loads(result.stdout)
    expected_consumers = {
        "USER_SENTINEL": {"read-ticket"},
        "READ_SENTINEL": {"resolve-project"},
        "RESOLVE_SENTINEL": {"research-repository"},
        "RESEARCH_SENTINEL": {"reason-about-fix"},
        "PROPOSAL_SENTINEL": {
            "approve-code-writes",
            "create-branch",
            "commit-changes",
            "create-merge-request",
        },
        "ACTION_SENTINEL": {"commit-changes"},
        "BRANCH_SENTINEL": {"commit-changes", "create-merge-request"},
        "COMMIT_SENTINEL": {"create-merge-request", "review-merge-request"},
        "MR_SENTINEL": {"review-merge-request"},
        "REVIEW_SENTINEL": {
            "approve-jira-update",
            "update-jira",
            "report-status",
        },
        "JIRA_SENTINEL": {"report-status"},
    }
    for sentinel, consumers in expected_consumers.items():
        assert {
            node_id for node_id, prompt in rendered.items() if sentinel in prompt
        } == consumers
    assert "ERIC-123" in rendered["read-ticket"]
    assert "not_found" in rendered["report-status"]


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
