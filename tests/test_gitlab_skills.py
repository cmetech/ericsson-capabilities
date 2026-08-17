from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins/ericsson-gitlab"

PLUGIN_SKILLS = {
    "repository-research": {
        "read": {
            "gitlab_resolve_project",
            "gitlab_list_group_projects",
            "gitlab_list_repository_tree",
            "gitlab_read_file",
            "gitlab_list_commits",
            "gitlab_read_commit",
            "gitlab_list_commit_comments",
            "gitlab_list_commit_discussions",
        },
        "write": set(),
    },
    "merge-request-review": {
        "read": {
            "gitlab_resolve_project",
            "gitlab_list_repository_tree",
            "gitlab_read_file",
            "gitlab_read_merge_request",
            "gitlab_list_merge_requests",
            "gitlab_list_merge_request_commits",
            "gitlab_list_merge_request_discussions",
            "gitlab_merge_request_approvals",
            "gitlab_list_pipelines",
        },
        "write": {
            "gitlab_create_mr_note",
            "gitlab_reply_to_discussion",
            "gitlab_resolve_discussion",
            "gitlab_approve_merge_request",
            "gitlab_merge_merge_request",
            "gitlab_update_merge_request",
        },
    },
    "gitlab-activity-digest": {
        "read": {
            "gitlab_resolve_project",
            "gitlab_list_commits",
            "gitlab_list_merge_requests",
        },
        "write": {"cronjob"},
    },
    "ci-investigation": {
        "read": {
            "gitlab_resolve_project",
            "gitlab_read_file",
            "gitlab_list_pipelines",
            "gitlab_inspect_ci",
        },
        "write": set(),
    },
}

SOURCE_SKILLS = {
    "gitlab": REPO / "skills/ericsson/gitlab/SKILL.md",
    "jira-to-gitlab": REPO / "skills/ericsson/jira-to-gitlab/SKILL.md",
}

GITLAB_READS = {
    "gitlab_resolve_project",
    "gitlab_list_repository_tree",
    "gitlab_read_file",
    "gitlab_read_merge_request",
    "gitlab_list_pipelines",
    "gitlab_inspect_ci",
}
GITLAB_WRITES = {
    "gitlab_create_branch",
    "gitlab_commit_changes",
    "gitlab_create_merge_request",
}


def _skill_contract(path: Path) -> tuple[dict, ET.Element, str]:
    assert path.is_file(), f"missing Task 11 skill: {path.relative_to(REPO)}"
    text = path.read_text(encoding="utf-8")
    assert text.startswith("---\n")
    _open, frontmatter, body = text.split("---", 2)
    metadata = yaml.safe_load(frontmatter)
    assert isinstance(metadata, dict)
    assert len(body.splitlines()) < 500
    assert not any(re.match(r"^\s*#{1,6}\s", line) for line in body.splitlines())
    root = ET.fromstring(f"<skill>{body}</skill>")
    for required in ("objective", "quick_start", "success_criteria"):
        assert root.find(required) is not None, f"{path}: missing <{required}>"
    assert metadata["name"] == path.parent.name
    description = metadata.get("description")
    assert isinstance(description, str) and "Use when" in description
    return metadata, root, body


def _declared_tools(root: ET.Element, mode: str) -> set[str]:
    return {
        item.attrib["name"]
        for item in root.findall(".//tool")
        if item.attrib.get("mode") == mode
    }


@pytest.mark.parametrize("skill_name", sorted(PLUGIN_SKILLS))
def test_plugin_skills_are_trigger_valid_semantic_and_bounded(skill_name: str) -> None:
    # GL-READ-07/08, GL-REVIEW-02, and GL-CI-11: active-agent guidance replaces
    # legacy prompt aggregation and hidden model clients with bounded tool use.
    path = PLUGIN / "skills" / skill_name / "SKILL.md"
    metadata, _root, _body = _skill_contract(path)
    assert metadata["name"] == skill_name


@pytest.mark.parametrize("skill_name", sorted(PLUGIN_SKILLS))
def test_plugin_skills_declare_only_their_exact_tool_contract(
    skill_name: str,
) -> None:
    # GL-READ-07/08, GL-REVIEW-01/02, GL-CI-03/06/07/09/11.
    _metadata, root, body = _skill_contract(PLUGIN / "skills" / skill_name / "SKILL.md")
    expected = PLUGIN_SKILLS[skill_name]
    assert _declared_tools(root, "read") == expected["read"]
    assert _declared_tools(root, "write") == expected["write"]
    lowered = body.lower()
    assert "bounded" in lowered
    assert "warning" in lowered or "truncat" in lowered
    if skill_name == "merge-request-review":
        assert "host approval" in lowered
    else:
        assert "read-only" in lowered


def test_repository_research_requires_identity_before_bounded_evidence_reads() -> None:
    # GL-ID-02, GL-READ-04/07/08: project/ref identity precedes bounded tree/file reads.
    _metadata, _root, body = _skill_contract(
        PLUGIN / "skills/repository-research/SKILL.md"
    )
    lowered = body.lower()
    assert lowered.index("gitlab_resolve_project") < lowered.index(
        "gitlab_list_repository_tree"
    )
    assert "default branch" in lowered
    assert "binary" in lowered
    assert "group" in lowered and "subgroup" in lowered
    assert "commit" in lowered and "discussion" in lowered
    assert "pipelines are not commit history" in lowered


def test_merge_request_review_uses_active_agent_and_closes_the_approved_loop() -> (
    None
):
    # GL-REVIEW-01/02/03: replace CodeReviewRunner with one active-agent review.
    _metadata, _root, body = _skill_contract(
        PLUGIN / "skills/merge-request-review/SKILL.md"
    )
    lowered = body.lower()
    assert "active agent" in lowered
    assert "explicitly asks" in lowered
    assert "host approval" in lowered
    assert "confidence score" not in lowered
    assert "created" in lowered and "updated" in lowered
    assert "new" in lowered and "active" in lowered
    assert "discussion" in lowered and "commit" in lowered
    assert "dry_run=true" in body and "confirm=true" in body
    assert "write_ambiguous" in body and "blindly retry" in lowered
    ordered_loop = (
        "gitlab_list_merge_request_discussions",
        "gitlab_reply_to_discussion",
        "gitlab_resolve_discussion",
        "gitlab_merge_request_approvals",
        "gitlab_approve_merge_request",
        "gitlab_list_pipelines",
        "gitlab_merge_merge_request",
    )
    positions = [body.index(tool) for tool in ordered_loop]
    assert positions == sorted(positions)
    assert "exact reviewed head SHA" in body
    assert "source_branch" in body


def test_activity_digest_supports_natural_language_one_time_and_recurring_runs() -> None:
    metadata, _root, body = _skill_contract(
        PLUGIN / "skills/gitlab-activity-digest/SKILL.md"
    )
    description = metadata["description"].lower()
    assert "one-time" in description or "one time" in description
    assert "recurring" in description or "daily" in description
    assert "commit" in description and "merge request" in description
    lowered = body.lower()
    for phrase in (
        "last 24 hours",
        "ericsson-gitlab:gitlab-activity-digest",
        "ericsson-gitlab",
        "origin delivery",
        "[silent]",
        "do not call",
    ):
        assert phrase in lowered
    assert "cronjob" in lowered
    assert "reschedul" in lowered


def test_ci_investigation_preserves_metadata_only_and_unsupported_include_facts() -> (
    None
):
    # GL-CI-03/06/07/09/11/12: bounded evidence, no values/evaluation, explicit deferral.
    _metadata, _root, body = _skill_contract(
        PLUGIN / "skills/ci-investigation/SKILL.md"
    )
    lowered = body.lower()
    assert "gitlab_inspect_ci" in lowered
    assert "variable values" in lowered and "never" in lowered
    assert "remote" in lowered and "template" in lowered
    assert "unsupported" in lowered


def test_source_gitlab_skill_is_a_thin_always_indexed_enablement_router() -> None:
    _metadata, root, body = _skill_contract(SOURCE_SKILLS["gitlab"])
    manifest = json.loads((REPO / "sets/ericsson.json").read_text(encoding="utf-8"))
    lowered = body.lower()
    assert "skills/ericsson/gitlab" in manifest["skills"]
    assert not any(
        path.startswith("plugins/ericsson-gitlab/skills") for path in manifest["skills"]
    )
    assert _declared_tools(root, "read") == set()
    assert _declared_tools(root, "write") == set()
    assert "disabled" in lowered and "fresh conversation" in lowered
    assert "configured" in lowered and "ready" in lowered
    assert {
        "ericsson-gitlab:repository-research",
        "ericsson-gitlab:merge-request-review",
        "ericsson-gitlab:ci-investigation",
        "ericsson-gitlab:gitlab-activity-digest",
    } <= set(re.findall(r"ericsson-gitlab:[a-z-]+", body))
    for intent in ("subgroup", "latest commit", "recent merge request", "daily digest"):
        assert intent in lowered
    assert "do not claim" in lowered or "never claim" in lowered


def test_jira_to_gitlab_skill_owns_visible_active_agent_reasoning_and_approved_writes() -> (
    None
):
    # GL-WRITE-04/08, GL-REVIEW-02, GL-JIRA-01..11/13 replacement and deferral.
    _metadata, root, body = _skill_contract(SOURCE_SKILLS["jira-to-gitlab"])
    assert _declared_tools(root, "read") == GITLAB_READS | {
        "jira_my_tickets",
        "jira_get_issue",
    }
    assert _declared_tools(root, "write") == GITLAB_WRITES | {"jira_add_comment"}
    lowered = body.lower()
    for phrase in (
        "active agent",
        "host approval",
        "dry-run",
        "ticket key",
        "not_found",
        "default branch",
        "per-ticket status",
        "uncertain",
    ):
        assert phrase in lowered
    assert "loop_group" in body and "deferred" in lowered


def test_new_skills_embed_no_transport_credentials_or_hidden_model_client() -> None:
    forbidden = {
        "codereviewrunner",
        "_call_llm",
        "ollama",
        "openai_api_key",
        "anthropic_api_key",
        "private-token",
        "authorization:",
        "requests.session",
        "httpx",
        "subprocess",
        "curl ",
    }
    paths = [PLUGIN / "skills" / name / "SKILL.md" for name in PLUGIN_SKILLS]
    paths.extend(SOURCE_SKILLS.values())
    for path in paths:
        _metadata, _root, body = _skill_contract(path)
        lowered = body.lower()
        assert forbidden.isdisjoint(
            {token for token in forbidden if token in lowered}
        ), path


def test_enabled_plugin_registers_explicit_qualified_skills_from_contract() -> None:
    # Hermes PluginContext.register_skill is the sole qualified plugin-skill authority.
    module_name = "_task11_ericsson_gitlab"
    init_path = PLUGIN / "__init__.py"
    spec = importlib.util.spec_from_file_location(
        module_name,
        init_path,
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    try:
        spec.loader.exec_module(module)

        class Context:
            def __init__(self) -> None:
                self.skills: list[tuple[str, Path, str]] = []

            def register_hook(self, *_args, **_kwargs) -> None:
                pass

            def register_tool(self, **_kwargs) -> None:
                pass

            def register_skill(self, name, path, description="") -> None:
                self.skills.append((name, Path(path), description))

        context = Context()
        module.register(context)
        assert {name for name, _path, _description in context.skills} == set(
            PLUGIN_SKILLS
        )
        assert all(path.is_file() for _name, path, _description in context.skills)
        assert all(description for _name, _path, description in context.skills)
    finally:
        for key in list(sys.modules):
            if key == module_name or key.startswith(f"{module_name}."):
                sys.modules.pop(key, None)


def test_every_skill_tool_reference_resolves_to_plugin_or_local_scheduler() -> None:
    module_name = "_task_read_exploration_tools"
    tools_path = PLUGIN / "tools.py"
    spec = importlib.util.spec_from_file_location(module_name, tools_path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.path.insert(0, str(PLUGIN))
    try:
        spec.loader.exec_module(module)
        available = set(module.SCHEMAS) | {"cronjob"}
        declared = set()
        for skill_name in PLUGIN_SKILLS:
            _metadata, root, _body = _skill_contract(
                PLUGIN / "skills" / skill_name / "SKILL.md"
            )
            declared |= _declared_tools(root, "read")
            declared |= _declared_tools(root, "write")
        assert declared <= available
    finally:
        sys.modules.pop(module_name, None)
