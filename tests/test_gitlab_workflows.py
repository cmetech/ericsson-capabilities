from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

from jsonschema import Draft202012Validator
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

COMMON_OUTPUT = {
    "status": "success",
    "warnings": [],
    "attention_needed": False,
}
SUCCESS_OUTPUTS = {
    "read-ticket": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "ticket_summary": "Fix the issue",
        "project_path": "group/project",
    },
    "resolve-project": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "ticket_summary": "Fix the issue",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "main",
    },
    "research-repository": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "ticket_summary": "Fix the issue",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "main",
        "evidence_summary": "bounded evidence",
    },
    "reason-about-fix": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "ticket_summary": "Fix the issue",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "main",
        "branch_prefix": "fix",
        "proposed_branch": "fix/ERIC-123-fix-the-issue",
        "branch_summary": "bounded proposal",
        "commit_message": "Fix ERIC-123",
        "actions": [{"action": "update", "file_path": "a.py", "content": "fixed"}],
        "actions_digest": "sha256:abcd",
        "mr_title": "ERIC-123: Fix the issue",
        "mr_description": "bounded description",
        "mr_target_branch": "main",
        "remove_source_branch": True,
        "squash": False,
    },
    "create-branch": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "project_id": 42,
        "project_path": "group/project",
        "branch_name": "fix/ERIC-123-fix-the-issue",
        "source_branch": "main",
        "web_url": "https://gitlab.example/group/project/-/tree/fix",
    },
    "commit-changes": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "project_id": 42,
        "branch_name": "fix/ERIC-123-fix-the-issue",
        "commit_id": "a" * 40,
        "web_url": "https://gitlab.example/group/project/-/commit/a",
    },
    "create-merge-request": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "project_id": 42,
        "iid": 7,
        "source_branch": "fix/ERIC-123-fix-the-issue",
        "target_branch": "main",
        "title": "ERIC-123: Fix the issue",
        "state": "opened",
        "web_url": "https://gitlab.example/group/project/-/merge_requests/7",
    },
    "review-merge-request": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "project_id": 42,
        "iid": 7,
        "merge_request_url": "https://gitlab.example/group/project/-/merge_requests/7",
        "verdict": "approved",
        "review_summary": "bounded review",
        "jira_comment": "MR 7 reviewed and ready",
    },
    "update-jira": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "project_id": 42,
        "iid": 7,
        "merge_request_url": "https://gitlab.example/group/project/-/merge_requests/7",
        "comment_status": "created",
    },
    "report-completion-status": COMMON_OUTPUT
    | {
        "ticket_key": "ERIC-123",
        "project_id": 42,
        "iid": 7,
        "merge_request_url": "https://gitlab.example/group/project/-/merge_requests/7",
        "jira_status": "created",
        "review_status": "approved",
    },
}
ALL_FAILURE_STATUSES = {
    "not_found",
    "permission",
    "incomplete",
    "failed",
    "skipped",
    "zero_ticket",
}
FAILURE_STATUSES = {node_id: ALL_FAILURE_STATUSES for node_id in SUCCESS_OUTPUTS}

TASK10_BOUNDS = {
    "ticket_key": {"maxLength": 128},
    "ticket_summary": {"maxLength": 2048},
    "project_id": {"minimum": 1},
    "project_path": {"maxLength": 2048},
    "default_branch": {"maxLength": 512},
    "branch_prefix": {"maxLength": 512},
    "proposed_branch": {"maxLength": 512},
    "commit_message": {"maxLength": 4096},
    "actions": {"maxItems": 100},
    "mr_title": {"maxLength": 255},
    "mr_description": {"maxLength": 65536},
    "mr_target_branch": {"maxLength": 512},
    "branch_name": {"maxLength": 512},
    "source_branch": {"maxLength": 512},
    "target_branch": {"maxLength": 512},
    "iid": {"minimum": 1, "maximum": 2147483647},
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
        "report-completion-status",
    }
    assert nodes["resolve-project"]["depends_on"] == ["read-ticket"]
    assert nodes["research-repository"]["depends_on"] == ["resolve-project"]
    assert nodes["reason-about-fix"]["depends_on"] == ["research-repository"]
    assert nodes["approve-code-writes"]["depends_on"] == [
        "read-ticket",
        "resolve-project",
        "research-repository",
        "reason-about-fix",
    ]
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
        "reason-about-fix",
    ]
    assert nodes["report-status"]["depends_on"] == ["reason-about-fix"]
    assert nodes["report-completion-status"]["depends_on"] == [
        "update-jira",
        "review-merge-request",
        "reason-about-fix",
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
        "report-completion-status": [],
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
        if node_id == "report-status":
            assert schema["properties"]["status"]["enum"] == sorted(
                ALL_FAILURE_STATUSES
            )
        else:
            assert len(schema.get("oneOf", ())) == 2


def test_every_prompt_output_has_success_identity_and_truthful_failure_variants() -> (
    None
):
    # GL-JIRA-05/08/09/10/13: success facts are exact; failure and zero-ticket
    # facts remain representable without inventing GitLab/Jira identities.
    nodes = _node_map(_document())
    for node_id, success in SUCCESS_OUTPUTS.items():
        schema = nodes[node_id]["output_format"]
        validator = Draft202012Validator(schema)
        assert list(validator.iter_errors(success)) == [], node_id
        for field, value in success.items():
            if field in {"status", "warnings", "attention_needed"}:
                continue
            missing_identity = success | {field: None}
            assert list(validator.iter_errors(missing_identity)), (node_id, field)
        for failure_status in FAILURE_STATUSES[node_id]:
            failure = {field: None for field in schema["properties"]}
            failure.update(
                status=failure_status,
                warnings=[f"{failure_status}: bounded"],
                attention_needed=True,
            )
            assert list(validator.iter_errors(failure)) == [], (
                node_id,
                failure_status,
            )

    failure_schema = nodes["report-status"]["output_format"]
    failure_validator = Draft202012Validator(failure_schema)
    for status in ALL_FAILURE_STATUSES:
        failure = {field: None for field in failure_schema["properties"]}
        failure.update(
            status=status,
            warnings=[f"{status}: bounded"],
            attention_needed=True,
        )
        assert list(failure_validator.iter_errors(failure)) == [], status


def test_workflow_output_contracts_apply_exact_task10_identity_bounds() -> None:
    # GL-WRITE-01/05/08/10: workflow-produced write arguments retain the exact
    # bounded Task 10 scalar/list identities before any approved transport.
    nodes = _node_map(_document())
    for node_id, node in nodes.items():
        schema = node.get("output_format")
        if not isinstance(schema, dict):
            continue
        properties = schema["properties"]
        for field, expected in TASK10_BOUNDS.items():
            if field in properties:
                for keyword, value in expected.items():
                    assert properties[field].get(keyword) == value, (
                        node_id,
                        field,
                        keyword,
                    )

    for node_id, success in SUCCESS_OUTPUTS.items():
        validator = Draft202012Validator(nodes[node_id]["output_format"])
        if "project_id" in success:
            assert list(validator.iter_errors(success | {"project_id": 1})) == []
            for invalid in (0, -1):
                assert list(validator.iter_errors(success | {"project_id": invalid})), (
                    node_id,
                    invalid,
                )
        if "iid" in success:
            assert list(validator.iter_errors(success | {"iid": 1})) == []
            assert list(validator.iter_errors(success | {"iid": 2147483647})) == []
            for invalid in (0, -1, 2147483648):
                assert list(validator.iter_errors(success | {"iid": invalid})), (
                    node_id,
                    invalid,
                )

    actions = nodes["reason-about-fix"]["output_format"]["properties"]["actions"]
    assert actions["maxItems"] == 100
    action_properties = actions["items"]["properties"]
    assert action_properties["file_path"]["maxLength"] == 4096
    assert action_properties["content"]["maxLength"] == 524288
    assert action_properties["last_commit_id"]["maxLength"] == 512


def test_each_node_binds_required_direct_predecessor_provenance() -> None:
    # GL-JIRA-04/05/06/07/08/09/10: fields a node republishes or mutates are
    # named from direct predecessors, including all status and warning facts.
    nodes = _node_map(_document())
    required_references = {
        "resolve-project": {
            "$read-ticket.output.ticket_key",
            "$read-ticket.output.ticket_summary",
            "$read-ticket.output.project_path",
            "$read-ticket.output.status",
            "$read-ticket.output.warnings",
        },
        "research-repository": {
            "$resolve-project.output.ticket_key",
            "$resolve-project.output.ticket_summary",
            "$resolve-project.output.project_id",
            "$resolve-project.output.project_path",
            "$resolve-project.output.default_branch",
            "$resolve-project.output.status",
            "$resolve-project.output.warnings",
        },
        "reason-about-fix": {
            "$research-repository.output.ticket_key",
            "$research-repository.output.ticket_summary",
            "$research-repository.output.project_id",
            "$research-repository.output.project_path",
            "$research-repository.output.default_branch",
            "$research-repository.output.evidence_summary",
            "$research-repository.output.status",
            "$research-repository.output.warnings",
        },
        "create-branch": {
            "$reason-about-fix.output.status",
            "$reason-about-fix.output.project_id",
            "$reason-about-fix.output.project_path",
            "$reason-about-fix.output.default_branch",
            "$reason-about-fix.output.branch_prefix",
            "$reason-about-fix.output.ticket_key",
            "$reason-about-fix.output.ticket_summary",
            "$reason-about-fix.output.proposed_branch",
            "$reason-about-fix.output.branch_summary",
        },
        "commit-changes": {
            "$reason-about-fix.output.status",
            "$reason-about-fix.output.project_id",
            "$reason-about-fix.output.commit_message",
            "$reason-about-fix.output.actions",
            "$reason-about-fix.output.actions_digest",
            "$reason-about-fix.output.proposed_branch",
            "$create-branch.output.status",
            "$create-branch.output.branch_name",
        },
        "create-merge-request": {
            "$reason-about-fix.output.status",
            "$reason-about-fix.output.project_id",
            "$reason-about-fix.output.mr_title",
            "$reason-about-fix.output.mr_description",
            "$reason-about-fix.output.mr_target_branch",
            "$reason-about-fix.output.remove_source_branch",
            "$reason-about-fix.output.squash",
            "$reason-about-fix.output.proposed_branch",
            "$create-branch.output.status",
            "$create-branch.output.branch_name",
            "$commit-changes.output.status",
            "$commit-changes.output.commit_id",
        },
        "review-merge-request": {
            "$create-merge-request.output.ticket_key",
            "$create-merge-request.output.project_id",
            "$create-merge-request.output.iid",
            "$create-merge-request.output.web_url",
            "$create-merge-request.output.status",
            "$commit-changes.output.commit_id",
            "$commit-changes.output.status",
        },
        "update-jira": {
            "$reason-about-fix.output.status",
            "$review-merge-request.output.ticket_key",
            "$review-merge-request.output.project_id",
            "$review-merge-request.output.iid",
            "$review-merge-request.output.merge_request_url",
            "$review-merge-request.output.verdict",
            "$review-merge-request.output.review_summary",
            "$review-merge-request.output.warnings",
            "$review-merge-request.output.jira_comment",
            "$review-merge-request.output.status",
        },
        "report-status": {
            "$reason-about-fix.output.ticket_key",
            "$reason-about-fix.output.ticket_summary",
            "$reason-about-fix.output.project_id",
            "$reason-about-fix.output.project_path",
            "$reason-about-fix.output.status",
            "$reason-about-fix.output.warnings",
            "$reason-about-fix.output.attention_needed",
        },
        "report-completion-status": {
            "$reason-about-fix.output.status",
            "$review-merge-request.output.ticket_key",
            "$review-merge-request.output.project_id",
            "$review-merge-request.output.iid",
            "$review-merge-request.output.merge_request_url",
            "$review-merge-request.output.verdict",
            "$review-merge-request.output.review_summary",
            "$review-merge-request.output.warnings",
            "$review-merge-request.output.status",
            "$update-jira.output.comment_status",
            "$update-jira.output.status",
        },
    }
    for node_id, references in required_references.items():
        prompt = nodes[node_id]["prompt"]
        assert references <= {token for token in references if token in prompt}, node_id


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


def test_application_status_conditions_gate_approvals_writes_and_terminal_lanes() -> (
    None
):
    # GL-JIRA-05/08/09/10/13: application failures do not pause for irrelevant
    # approvals or claim outward writes; exactly one truthful terminal remains.
    nodes = _node_map(_document())
    assert nodes["approve-code-writes"]["when"] == (
        "$read-ticket.output.status == 'success' && "
        "$resolve-project.output.status == 'success' && "
        "$research-repository.output.status == 'success' && "
        "$reason-about-fix.output.status == 'success'"
    )
    assert nodes["approve-jira-update"]["when"] == (
        "$review-merge-request.output.status == 'success' && "
        "$review-merge-request.output.jira_comment != ''"
    )
    assert nodes["update-jira"]["trigger_rule"] == "all_done"
    assert (
        nodes["update-jira"]["when"] == "$reason-about-fix.output.status == 'success'"
    )
    assert nodes["report-status"]["when"] == (
        "$reason-about-fix.output.status != 'success'"
    )
    assert nodes["report-completion-status"]["trigger_rule"] == "all_done"
    assert nodes["report-completion-status"]["when"] == (
        "$reason-about-fix.output.status == 'success'"
    )


def test_real_scheduler_bypasses_failure_approvals_and_outward_write_claims(
    tmp_path: Path,
) -> None:
    # GL-JIRA-05/08/09/10/13: exercise the committed package with Hermes' real
    # v5 compiler, condition evaluator, scheduler, store, and executor boundary.
    hermes = _hermes_checkout()
    python = hermes / ".venv/bin/python"
    script = r"""
import hashlib
import json
from pathlib import Path
import sys

from hermes_cli.plugin_configuration import ConnectorCapabilitySnapshot
from plugins.workflow import scheduler as scheduler_module
from plugins.workflow.admission import RunAdmissionRequest
from plugins.workflow.admission_service import assess_workflow_admission
from plugins.workflow.compilation import WorkflowCatalogSnapshot, compile_workflow
from plugins.workflow.executors.base import NodeExecutionResult
from plugins.workflow.output_resolution import PrimaryOutputCandidate
from plugins.workflow.scheduler import RunScheduler
from plugins.workflow.schema import parse_workflow_source_bytes
from plugins.workflow.store import ArtifactRef, RunStore
from tests.plugins.workflow.test_phase5_admission_parity import _context

path = Path(sys.argv[1]).resolve()
home = Path(sys.argv[2]).resolve()
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
required_services = frozenset(package.definition.options["requires"])
required_tools = frozenset(
    tool
    for node in package.definition.nodes
    for tool in node.options.get("allowed_tools", ())
)
capabilities = ConnectorCapabilitySnapshot(
    ready_services=required_services,
    available_tools=required_tools,
    fingerprint="c" * 64,
    _service_fingerprints=tuple(
        (service, hashlib.sha256(service.encode()).hexdigest())
        for service in sorted(required_services)
    ),
)
execution_context = _context()
assessment = assess_workflow_admission(
    compilation,
    execution_context,
    available_services=required_services,
    available_tools=required_tools,
)
assert assessment.compatibility.runnable
scheduler_module.connector_capability_snapshot = lambda: capabilities
failure_statuses = (
    "not_found",
)
rows = []

for status in failure_statuses:
    calls = []

    class OutputExecutor:
        def execute(self, context):
            calls.append(context.node.id)
            properties = context.node.options["output_format"]["properties"]
            value = {field: None for field in properties}
            value.update(
                status=status,
                warnings=[f"{status}: bounded"],
                attention_needed=True,
            )
            data = json.dumps(
                value,
                sort_keys=True,
                separators=(",", ":"),
            ).encode()
            output = (
                context.run_directory
                / "nodes"
                / context.node.id
                / context.attempt_id
                / "output.json"
            )
            output.parent.mkdir(parents=True, exist_ok=False)
            output.write_bytes(data)
            relative = output.relative_to(context.run_directory).as_posix()
            digest = hashlib.sha256(data).hexdigest()
            structured = context.structured_output
            return NodeExecutionResult(
                "succeeded",
                (ArtifactRef(relative, "application/json", len(data), digest),),
                primary_output=PrimaryOutputCandidate(
                    attempt_relative_path=relative,
                    media_type="application/json",
                    size_bytes=len(data),
                    sha256=digest,
                    structured_value=value,
                    schema_fingerprint=structured.schema_fingerprint,
                    canonicalization_version=structured.canonicalization_version,
                    output_type=context.node.options.get("output_type"),
                ),
            )

    store = RunStore(home / status)
    prepared = store.prepare_run_snapshot(
        package,
        compilation=compilation,
        trusted_package_digest=assessment.package_digest,
        provider_authority=assessment.provider_authority,
        connector_capabilities=capabilities,
    )
    admitted = store.start_run(
        RunAdmissionRequest(
            workflow_name=package.definition.name,
            definition_digest=prepared.definition_digest,
            policy_digest=prepared.policy_digest,
            input_manifest_digest=prepared.input_manifest_digest,
            trigger_source="cli",
            idempotency_key=f"failure-{status}",
            concurrency_key=f"failure-{status}",
            run_metadata=execution_context.structured_output_run_metadata(package),
        ),
        immutable_snapshot=prepared,
    )
    scheduler = RunScheduler(store, max_parallel_nodes=1)
    scheduler.executors["prompt"] = OutputExecutor()
    try:
        result = scheduler.advance(admitted.run_id, max_nodes=64)
    finally:
        scheduler.shutdown(deadline_seconds=2)
    resolved_outputs = scheduler._output_values(
        result,
        store.run_directory(admitted.run_id),
        node_ids=("report-status",),
    )
    if "report-status" not in resolved_outputs:
        raise AssertionError(json.dumps({
            "status": status,
            "run_status": result["status"],
            "last_error": result.get("last_error"),
            "calls": calls,
            "nodes": result["nodes"],
        }, sort_keys=True, default=str))
    resolved = resolved_outputs["report-status"]
    rows.append({
        "status": status,
        "run_status": result["status"],
        "calls": calls,
        "report": json.loads(resolved.text),
        "states": {
            node_id: {
                "state": result["nodes"][node_id]["state"],
                "attempts": len(result["nodes"][node_id]["attempts"]),
            }
            for node_id in result["nodes"]
        },
    })

print(json.dumps(rows, sort_keys=True))
"""
    try:
        result = subprocess.run(
            [str(python), "-c", script, str(WORKFLOW), str(tmp_path / "runs")],
            cwd=hermes,
            text=True,
            capture_output=True,
            check=False,
            timeout=30,
        )
    except subprocess.TimeoutExpired as exc:
        raise AssertionError(exc.stderr) from exc
    assert result.returncode == 0, result.stderr
    rows = json.loads(result.stdout)
    expected_calls = {
        "read-ticket",
        "resolve-project",
        "research-repository",
        "reason-about-fix",
        "report-status",
    }
    skipped_without_claim = {
        "approve-code-writes",
        "create-branch",
        "commit-changes",
        "create-merge-request",
        "review-merge-request",
        "approve-jira-update",
        "update-jira",
        "report-completion-status",
    }
    # Every other bounded failure value follows the same exact `!= success`
    # condition and is covered by the complete schema matrix above.
    assert {row["status"] for row in rows} == {"not_found"}
    for row in rows:
        assert row["run_status"] == "succeeded", row
        assert set(row["calls"]) == expected_calls, row
        assert row["report"]["status"] == row["status"]
        assert row["report"]["attention_needed"] is True
        assert row["states"]["report-status"]["state"] == "succeeded"
        for node_id in skipped_without_claim:
            assert row["states"][node_id] == {"state": "skipped", "attempts": 0}


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
        "status": "success",
        "warnings": [],
        "attention_needed": False,
    },
    "resolve-project": {
        "ticket_key": "ERIC-123",
        "ticket_summary": "READ_SENTINEL",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "RESOLVE_SENTINEL",
        "status": "success",
        "warnings": [],
        "attention_needed": False,
    },
    "research-repository": {
        "ticket_key": "ERIC-123",
        "ticket_summary": "READ_SENTINEL",
        "project_id": 42,
        "project_path": "group/project",
        "default_branch": "RESOLVE_SENTINEL",
        "evidence_summary": "RESEARCH_SENTINEL",
        "status": "success",
        "warnings": [],
        "attention_needed": False,
    },
    "reason-about-fix": {
        "ticket_key": "ERIC-123-TICKET_SENTINEL",
        "ticket_summary": "TICKET_SUMMARY_SENTINEL",
        "project_id": 424242,
        "project_path": "PROJECT_PATH_SENTINEL",
        "default_branch": "DEFAULT_REF_SENTINEL",
        "branch_prefix": "PREFIX_SENTINEL",
        "proposed_branch": "APPROVED_BRANCH_SENTINEL",
        "branch_summary": "BRANCH_SUMMARY_SENTINEL",
        "commit_message": "COMMIT_MESSAGE_SENTINEL",
        "actions": [{"action": "update", "file_path": "ACTION_PATH_SENTINEL", "content": "ACTION_CONTENT_SENTINEL"}],
        "actions_digest": "ACTION_DIGEST_SENTINEL",
        "mr_title": "MR_TITLE_SENTINEL",
        "mr_description": "MR_DESCRIPTION_SENTINEL",
        "mr_target_branch": "MR_TARGET_SENTINEL",
        "remove_source_branch": True,
        "squash": False,
        "status": "success",
        "warnings": ["PROPOSAL_WARNING_SENTINEL"],
        "attention_needed": False,
    },
    "create-branch": {
        "ticket_key": "ERIC-123-TICKET_SENTINEL",
        "project_id": 424242,
        "project_path": "PROJECT_PATH_SENTINEL",
        "branch_name": "RETURNED_BRANCH_MISMATCH_SENTINEL",
        "source_branch": "DEFAULT_REF_SENTINEL",
        "web_url": "https://gitlab.example/branch",
        "status": "success",
        "warnings": [],
        "attention_needed": False,
    },
    "commit-changes": {
        "ticket_key": "ERIC-123-TICKET_SENTINEL",
        "project_id": 424242,
        "branch_name": "RETURNED_BRANCH_MISMATCH_SENTINEL",
        "commit_id": "COMMIT_SENTINEL",
        "web_url": "https://gitlab.example/commit",
        "status": "success",
        "warnings": [],
        "attention_needed": False,
    },
    "create-merge-request": {
        "ticket_key": "ERIC-123-TICKET_SENTINEL",
        "project_id": 424242,
        "iid": 707,
        "source_branch": "RETURNED_BRANCH_MISMATCH_SENTINEL",
        "target_branch": "MR_TARGET_SENTINEL",
        "title": "MR_TITLE_SENTINEL",
        "state": "opened",
        "web_url": "MR_SENTINEL",
        "status": "success",
        "warnings": [],
        "attention_needed": False,
    },
    "review-merge-request": {
        "ticket_key": "ERIC-123-TICKET_SENTINEL",
        "project_id": 424242,
        "iid": 707,
        "merge_request_url": "MR_URL_SENTINEL",
        "verdict": "VERDICT_SENTINEL",
        "review_summary": "REVIEW_SENTINEL",
        "warnings": ["REVIEW_WARNING_SENTINEL"],
        "jira_comment": "JIRA_COMMENT_SENTINEL",
        "status": "success",
        "attention_needed": False,
    },
    "update-jira": {
        "ticket_key": "ERIC-123-TICKET_SENTINEL",
        "project_id": 424242,
        "iid": 707,
        "merge_request_url": "MR_URL_SENTINEL",
        "comment_status": "JIRA_SENTINEL",
        "status": "success",
        "warnings": [],
        "attention_needed": False,
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
        "READ_SENTINEL": {"resolve-project", "research-repository", "reason-about-fix"},
        "RESOLVE_SENTINEL": {"research-repository", "reason-about-fix"},
        "RESEARCH_SENTINEL": {"reason-about-fix"},
        "BRANCH_SUMMARY_SENTINEL": {
            "approve-code-writes",
            "create-branch",
            "commit-changes",
            "create-merge-request",
        },
        "ACTION_CONTENT_SENTINEL": {"approve-code-writes", "commit-changes"},
        "ACTION_DIGEST_SENTINEL": {"approve-code-writes", "commit-changes"},
        "COMMIT_MESSAGE_SENTINEL": {"approve-code-writes", "commit-changes"},
        "MR_DESCRIPTION_SENTINEL": {
            "approve-code-writes",
            "create-merge-request",
        },
        "APPROVED_BRANCH_SENTINEL": {
            "approve-code-writes",
            "create-branch",
            "commit-changes",
            "create-merge-request",
        },
        "RETURNED_BRANCH_MISMATCH_SENTINEL": {
            "commit-changes",
            "create-merge-request",
        },
        "COMMIT_SENTINEL": {"create-merge-request", "review-merge-request"},
        "MR_SENTINEL": {"review-merge-request"},
        "REVIEW_SENTINEL": {
            "approve-jira-update",
            "update-jira",
            "report-completion-status",
        },
        "JIRA_SENTINEL": {"report-completion-status"},
        "JIRA_COMMENT_SENTINEL": {"approve-jira-update", "update-jira"},
    }
    for sentinel, consumers in expected_consumers.items():
        assert {
            node_id for node_id, prompt in rendered.items() if sentinel in prompt
        } == consumers
    assert "ERIC-123" in rendered["read-ticket"]
    assert "not_found" in rendered["report-status"]
    code_approval = rendered["approve-code-writes"]
    for exact_fact in (
        "ERIC-123-TICKET_SENTINEL",
        "TICKET_SUMMARY_SENTINEL",
        "424242",
        "PROJECT_PATH_SENTINEL",
        "DEFAULT_REF_SENTINEL",
        "PREFIX_SENTINEL",
        "APPROVED_BRANCH_SENTINEL",
        "COMMIT_MESSAGE_SENTINEL",
        "ACTION_PATH_SENTINEL",
        "ACTION_CONTENT_SENTINEL",
        "ACTION_DIGEST_SENTINEL",
        "MR_TITLE_SENTINEL",
        "MR_DESCRIPTION_SENTINEL",
        "MR_TARGET_SENTINEL",
        "true",
        "false",
    ):
        assert exact_fact in code_approval
    write_fact_consumers = {
        "ERIC-123-TICKET_SENTINEL": {
            "approve-code-writes",
            "create-branch",
        },
        "TICKET_SUMMARY_SENTINEL": {
            "approve-code-writes",
            "create-branch",
        },
        "424242": {
            "approve-code-writes",
            "create-branch",
            "commit-changes",
            "create-merge-request",
        },
        "PROJECT_PATH_SENTINEL": {"approve-code-writes", "create-branch"},
        "DEFAULT_REF_SENTINEL": {"approve-code-writes", "create-branch"},
        "PREFIX_SENTINEL": {"approve-code-writes", "create-branch"},
        "APPROVED_BRANCH_SENTINEL": {
            "approve-code-writes",
            "create-branch",
            "commit-changes",
            "create-merge-request",
        },
        "COMMIT_MESSAGE_SENTINEL": {"approve-code-writes", "commit-changes"},
        "ACTION_CONTENT_SENTINEL": {"approve-code-writes", "commit-changes"},
        "ACTION_DIGEST_SENTINEL": {"approve-code-writes", "commit-changes"},
        "MR_TITLE_SENTINEL": {"approve-code-writes", "create-merge-request"},
        "MR_DESCRIPTION_SENTINEL": {
            "approve-code-writes",
            "create-merge-request",
        },
        "MR_TARGET_SENTINEL": {"approve-code-writes", "create-merge-request"},
    }
    for fact, consumers in write_fact_consumers.items():
        assert all(fact in rendered[node_id] for node_id in consumers), fact
    for node_id in ("commit-changes", "create-merge-request"):
        mismatch_prompt = rendered[node_id].lower()
        assert "approved_branch_sentinel" in mismatch_prompt
        assert "returned_branch_mismatch_sentinel" in mismatch_prompt
        assert "failed" in mismatch_prompt
        assert "attention" in mismatch_prompt
        assert "do not call" in mismatch_prompt
    jira_approval = rendered["approve-jira-update"]
    for exact_fact in (
        "ERIC-123-TICKET_SENTINEL",
        "424242",
        "707",
        "MR_URL_SENTINEL",
        "VERDICT_SENTINEL",
        "REVIEW_SENTINEL",
        "REVIEW_WARNING_SENTINEL",
        "JIRA_COMMENT_SENTINEL",
    ):
        assert exact_fact in jira_approval
        assert exact_fact in rendered["update-jira"]


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
