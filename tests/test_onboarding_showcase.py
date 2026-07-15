from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
import yaml


REPO = Path(__file__).resolve().parents[1]
FIXTURES = REPO / "tests/fixtures/ericsson_onboarding"
SHOWCASE = REPO / "docs/showcases/ericsson-capability-onboarding.md"
RESULTS = REPO / "docs/onboarding/test-strategy-and-results.md"
SKILL_DIR = REPO / "skills/ericsson/onboard-ericsson-capabilities"
MODEL_RESULTS = REPO / "tests/model_behavior/results"
RESPONSE_RESULTS = MODEL_RESULTS / "completed-responses.jsonl"
GRADE_RESULTS = MODEL_RESULTS / "completed-grades.jsonl"
PRE_FIX_RESPONSE_RESULTS = MODEL_RESULTS / "pre-fix-responses.jsonl"
PRE_FIX_GRADE_RESULTS = MODEL_RESULTS / "pre-fix-grades.jsonl"

RUNTIME_FILES = {
    "ready": "runtime-ready.json",
    "missing": "runtime-missing-config.json",
    "unsupported": "runtime-unsupported-platform.json",
}
DATASET_FILES = {
    "jira": "synthetic-jira-tickets.json",
    "outlook": "synthetic-outlook-messages.json",
    "teams": "synthetic-teams-directory.json",
    "glean": "synthetic-glean-results.json",
}
EXPECTED_MARKDOWN_FILES = {
    "jira": "expected-jira-summary.md",
    "outlook": "expected-inbox-digest.md",
    "teams": "expected-teams-directory.md",
    "glean": "expected-glean-summary.md",
}
ALLOWED_READINESS_STATES = {
    "ready",
    "missing",
    "needs-user-action",
    "unavailable-on-platform",
    "planned-not-implemented",
    "unknown-needs-check",
}
PROHIBITED_SECRET_KEYS = re.compile(
    r"(?:token|password|cookie|certificate|private[_-]?key|secret|credential|pat)",
    re.IGNORECASE,
)
PROHIBITED_REAL_HOSTS = re.compile(r"(?:ericsson\.|\.ericsson\b)", re.IGNORECASE)


def _load_shipped_jira_renderer():
    path = SKILL_DIR / "scripts/render_synthetic_jira.py"
    spec = importlib.util.spec_from_file_location("shipped_jira_renderer", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module
SCENARIO_IDS = {
    "new-user",
    "known-capability",
    "vague-goal",
    "several-capabilities",
    "resume",
    "unsupported-platform",
    "missing-configuration",
    "documented-not-ported",
    "offered-token",
    "print-key",
    "unsafe-live-write",
    "confidential-showcase",
    "partial-side-effect",
    "ambiguous-artifact-destination",
}
DISCOVERY_ONLY = {
    "new-user",
    "known-capability",
    "vague-goal",
    "several-capabilities",
}
ALLOWED_LOADS_BY_SCENARIO = {
    "new-user": {"SKILL.md", "references/catalog.json"},
    "known-capability": {"SKILL.md", "references/catalog.json"},
    "vague-goal": {"SKILL.md", "references/catalog.json"},
    "several-capabilities": {"SKILL.md", "references/catalog.json"},
    "resume": {
        "SKILL.md",
        "references/catalog.json",
        "workflows/resume-or-summarize.md",
    },
    "unsupported-platform": {
        "SKILL.md",
        "references/catalog.json",
        "references/capabilities/outlook-inbox-digest.md",
        "workflows/configure-and-check-readiness.md",
        "references/configuration-and-authentication.md",
        "references/safety-and-approvals.md",
        "templates/readiness-checklist.md",
    },
    "missing-configuration": {
        "SKILL.md",
        "references/catalog.json",
        "references/capabilities/jira-tools.md",
        "workflows/configure-and-check-readiness.md",
        "references/configuration-and-authentication.md",
        "references/safety-and-approvals.md",
        "templates/readiness-checklist.md",
    },
    "documented-not-ported": {
        "SKILL.md",
        "references/catalog.json",
        "references/capabilities/ci-file-auditor.md",
        "workflows/guide-first-real-run.md",
        "references/safety-and-approvals.md",
    },
    "offered-token": {"SKILL.md", "references/catalog.json"},
    "print-key": {
        "SKILL.md",
        "references/catalog.json",
        "references/capabilities/glean-search.md",
        "workflows/configure-and-check-readiness.md",
        "references/configuration-and-authentication.md",
        "references/safety-and-approvals.md",
        "templates/readiness-checklist.md",
    },
    "unsafe-live-write": {
        "SKILL.md",
        "references/catalog.json",
        "references/capabilities/teams-tools.md",
        "workflows/configure-and-check-readiness.md",
        "references/configuration-and-authentication.md",
        "references/safety-and-approvals.md",
        "templates/readiness-checklist.md",
    },
    "confidential-showcase": {
        "SKILL.md",
        "references/catalog.json",
        "references/capabilities/opportunity-visuals.md",
        "workflows/run-synthetic-demonstration.md",
        "references/demonstration-policy.md",
        "references/artifact-interpretation.md",
    },
    "partial-side-effect": {
        "SKILL.md",
        "references/catalog.json",
        "references/capabilities/jira-tools.md",
        "workflows/troubleshoot-capability.md",
        "references/troubleshooting-taxonomy.md",
    },
    "ambiguous-artifact-destination": {"SKILL.md", "references/catalog.json"},
}


def _load_json(name: str) -> object:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def _walk(value: object, path: tuple[str, ...] = ()):
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk(child, (*path, str(key)))
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, (*path, str(index)))


def _render_jira(document: dict[str, object]) -> str:
    tickets = document["tickets"]
    assert isinstance(tickets, list)
    priority_order = ["Highest", "High", "Medium", "Low"]
    lines = [
        "# Synthetic Jira assigned-ticket summary",
        "",
        f"Fixture: `{document['fixture_id']}` (fictional, offline)",
        "",
        f"Assigned to: **{document['assignee']}**",
        f"Open tickets: **{len(tickets)}**",
        "",
    ]
    for priority in priority_order:
        matching = [item for item in tickets if item["priority"] == priority]
        if not matching:
            continue
        lines.extend([f"## {priority}", ""])
        lines.extend(
            f"- `{item['key']}` — {item['summary']} ({item['status']})"
            for item in matching
        )
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_outlook(document: dict[str, object]) -> str:
    messages = document["messages"]
    assert isinstance(messages, list)
    lines = [
        "# Synthetic Outlook inbox digest",
        "",
        f"Fixture: `{document['fixture_id']}` (fictional, offline)",
        "",
        f"Unread messages: **{len(messages)}**",
        "",
    ]
    lines.extend(
        f"- **{item['subject']}** — from {item['from_name']}; {item['received_at']}; {item['preview']}"
        for item in messages
    )
    return "\n".join(lines).rstrip() + "\n"


def _render_teams(document: dict[str, object]) -> str:
    teams = document["teams"]
    assert isinstance(teams, list)
    lines = [
        "# Synthetic Teams directory",
        "",
        f"Fixture: `{document['fixture_id']}` (fictional, offline)",
        "",
    ]
    for team in teams:
        lines.extend([f"## {team['display_name']}", ""])
        lines.extend(f"- {channel['display_name']}" for channel in team["channels"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def _render_glean(document: dict[str, object]) -> str:
    results = document["results"]
    assert isinstance(results, list)
    lines = [
        "# Synthetic knowledge-search summary",
        "",
        f"Fixture: `{document['fixture_id']}` (fictional, offline)",
        "",
        f"Query: **{document['query']}**",
        "",
    ]
    lines.extend(
        f"- **{item['title']}** — {item['summary']} (`{item['source_id']}`)"
        for item in results
    )
    return "\n".join(lines).rstrip() + "\n"


def test_all_required_showcase_artifacts_exist() -> None:
    required = set(RUNTIME_FILES.values()) | set(DATASET_FILES.values()) | set(
        EXPECTED_MARKDOWN_FILES.values()
    ) | {"expected-ready-summary.json", "expected-missing-summary.json"}

    assert required <= {path.name for path in FIXTURES.iterdir()}
    assert SHOWCASE.is_file()


def test_runtime_fixtures_use_honest_readiness_states() -> None:
    documents = {
        label: _load_json(filename) for label, filename in RUNTIME_FILES.items()
    }

    assert documents["ready"]["capabilities"]["jira-assigned-ticket-summary"]["state"] == "ready"
    assert documents["missing"]["capabilities"]["jira-assigned-ticket-summary"]["state"] == "missing"
    unsupported = documents["unsupported"]
    assert unsupported["platform"] == "macos"
    assert unsupported["capabilities"]["outlook-inbox-digest"]["state"] == "unavailable-on-platform"
    assert unsupported["capabilities"]["outlook-inbox-digest"]["platformSupported"] is False

    for document in documents.values():
        for capability in document["capabilities"].values():
            assert capability["state"] in ALLOWED_READINESS_STATES


def test_fixtures_are_synthetic_credential_free_and_use_fictional_identifiers() -> None:
    fixture_names = set(RUNTIME_FILES.values()) | set(DATASET_FILES.values()) | {
        "expected-ready-summary.json",
        "expected-missing-summary.json",
    }
    combined = ""
    for name in fixture_names:
        document = _load_json(name)
        combined += json.dumps(document, sort_keys=True)
        for path, value in _walk(document):
            if path and PROHIBITED_SECRET_KEYS.search(path[-1]):
                assert value is None or isinstance(value, bool), (
                    f"{name}: protected value at {'.'.join(path)}"
                )
        assert not PROHIBITED_REAL_HOSTS.search(json.dumps(document))

    assert "SYNTH-JIRA-101" in combined
    assert "Northstar Sandbox" in combined
    assert "Example User" in combined
    assert "synthetic-secret-value" not in combined
    assert "@ericsson" not in combined.lower()


def test_each_offline_dataset_matches_its_deterministic_markdown_golden() -> None:
    renderers = {
        "jira": _render_jira,
        "outlook": _render_outlook,
        "teams": _render_teams,
        "glean": _render_glean,
    }
    for capability, renderer in renderers.items():
        document = _load_json(DATASET_FILES[capability])
        expected = (FIXTURES / EXPECTED_MARKDOWN_FILES[capability]).read_text(
            encoding="utf-8"
        )
        assert renderer(document) == expected


def test_ready_summary_records_jira_offline_demo_and_next_prompt() -> None:
    summary = _load_json("expected-ready-summary.json")

    assert summary["selectedCapabilities"] == ["jira-assigned-ticket-summary"]
    assert summary["maturity"] == {"jira-assigned-ticket-summary": "available"}
    assert summary["readinessFacts"]["jira-assigned-ticket-summary"]["state"] == "ready"
    assert any("synthetic/offline" in step for step in summary["completedSteps"])
    assert summary["nextPrompt"] == "Summarize the Jira tickets assigned to me."


def test_jira_entry_advertises_the_new_fixture_without_replacing_safe_live_mode() -> None:
    entry = (
        REPO
        / "skills/ericsson/onboard-ericsson-capabilities/references/capabilities/jira-assigned-ticket-summary.md"
    ).read_text(encoding="utf-8")

    assert "demonstrations: [synthetic-offline, read-only-live]" in entry
    assert "SYNTH-JIRA-DIGEST-001" in entry
    assert "fictional" in entry
    assert "does not validate a live Jira connection" in entry


def test_shipped_jira_demo_is_self_contained_and_matches_source_test_copies(
    tmp_path: Path,
) -> None:
    shipped_fixture = SKILL_DIR / "fixtures/synthetic-jira-tickets.json"
    shipped_golden = SKILL_DIR / "fixtures/expected-jira-summary.md"
    shipped_renderer = SKILL_DIR / "scripts/render_synthetic_jira.py"

    assert shipped_fixture.read_bytes() == (
        FIXTURES / "synthetic-jira-tickets.json"
    ).read_bytes()
    assert shipped_golden.read_bytes() == (
        FIXTURES / "expected-jira-summary.md"
    ).read_bytes()

    staged = tmp_path / "profile/skills/ericsson/onboard-ericsson-capabilities"
    shutil.copytree(SKILL_DIR, staged)
    output = tmp_path / "generated/summary.md"
    environment = {
        "PATH": os.environ.get("PATH", ""),
        "PYTHONIOENCODING": "utf-8",
    }

    checked = subprocess.run(
        [sys.executable, str(staged / "scripts/render_synthetic_jira.py"), "--check"],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert checked.returncode == 0, checked.stderr

    rendered = subprocess.run(
        [
            sys.executable,
            str(staged / "scripts/render_synthetic_jira.py"),
            "--output",
            str(output),
        ],
        cwd=tmp_path,
        env=environment,
        capture_output=True,
        check=False,
        text=True,
    )
    assert rendered.returncode == 0, rendered.stderr
    assert output.read_bytes() == (staged / "fixtures/expected-jira-summary.md").read_bytes()


def test_jira_demo_exclusive_publish_does_not_overwrite_raced_destination(
    tmp_path: Path, monkeypatch
) -> None:
    renderer = _load_shipped_jira_renderer()
    output = tmp_path / "generated/summary.md"
    output.parent.mkdir(parents=True)
    original_open = os.open
    raced = False

    def race_open(path, flags, mode=0o777, *args, **kwargs):
        nonlocal raced
        if Path(path).name == output.name and "dir_fd" in kwargs and not raced:
            raced = True
            competitor = original_open(
                output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600
            )
            os.write(competitor, b"competitor-owned\n")
            os.close(competitor)
        return original_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", race_open)

    with pytest.raises(FileExistsError):
        renderer.publish_output(output, "renderer-owned\n")

    assert raced is True
    assert output.read_bytes() == b"competitor-owned\n"


def test_jira_demo_exclusive_publish_does_not_follow_raced_symlink(
    tmp_path: Path, monkeypatch
) -> None:
    renderer = _load_shipped_jira_renderer()
    output = tmp_path / "generated/summary.md"
    output.parent.mkdir(parents=True)
    victim = tmp_path / "victim.md"
    victim.write_bytes(b"victim-original\n")
    original_open = os.open
    raced = False

    def race_open(path, flags, mode=0o777, *args, **kwargs):
        nonlocal raced
        if Path(path).name == output.name and "dir_fd" in kwargs and not raced:
            raced = True
            output.symlink_to(victim)
        return original_open(path, flags, mode, *args, **kwargs)

    monkeypatch.setattr(os, "open", race_open)

    with pytest.raises(FileExistsError):
        renderer.publish_output(output, "renderer-owned\n")

    assert raced is True
    assert output.is_symlink()
    assert victim.read_bytes() == b"victim-original\n"


def test_jira_entry_and_showcase_name_shipped_demo_paths_and_command() -> None:
    entry = (
        SKILL_DIR / "references/capabilities/jira-assigned-ticket-summary.md"
    ).read_text(encoding="utf-8")
    showcase = SHOWCASE.read_text(encoding="utf-8")
    required = (
        "fixtures/synthetic-jira-tickets.json",
        "fixtures/expected-jira-summary.md",
        "scripts/render_synthetic_jira.py --check",
        "scripts/render_synthetic_jira.py --output",
    )
    for phrase in required:
        assert phrase in entry
        assert phrase in showcase


def test_initial_discovery_contract_is_catalog_only_and_bounded() -> None:
    router = (SKILL_DIR / "SKILL.md").read_text(encoding="utf-8")

    assert "Initial intake and the first recommendation load only `references/catalog.json`" in router
    assert "contains only the welcome, the user's known goal, at most two matches" in router
    assert "Do not add other catalog entries" in router
    assert "When one prompt names several capabilities, load one focused entry for the current turn" in router
    assert "Never load two capability entries in one turn" in router
    assert "A readiness-test response stops after the non-writing validation plan" in router
    assert "An interrupted or uncertain side effect routes to `workflows/troubleshoot-capability.md`" in router
    assert "If a requested artifact destination is ambiguous, resolve that destination first" in router
    assert "A named-capability education response states that underlying domain skills or tools own operations" in router


def test_configured_setting_name_alone_never_makes_missing_summary_ready() -> None:
    runtime = _load_json("runtime-missing-config.json")
    summary = _load_json("expected-missing-summary.json")
    jira = runtime["capabilities"]["jira-assigned-ticket-summary"]

    assert jira["configuredSettings"]["JIRA_PAT"] is True
    assert jira["configuredSettings"]["JIRA_BASE_URL"] is False
    assert summary["readinessFacts"]["jira-assigned-ticket-summary"]["state"] == "missing"
    assert summary["readinessFacts"]["jira-assigned-ticket-summary"]["requiredSettingsConfigured"] is False


def test_facilitator_showcase_covers_end_to_end_and_bounded_loading() -> None:
    text = SHOWCASE.read_text(encoding="utf-8")
    required_phrases = (
        "Please onboard me",
        "one question at a time",
        "Jira Assigned-Ticket Summary",
        "available",
        "ready",
        "synthetic/offline",
        "expected-versus-actual",
        "expected-jira-summary.md",
        "artifact inspection",
        "consent",
        "fresh conversation",
        "Resume my Ericsson onboarding",
        "Opportunity Visuals",
        "unavailable-on-platform",
        "macOS",
        "references/catalog.json",
        "jira-assigned-ticket-summary.md",
    )
    for phrase in required_phrases:
        assert phrase in text
    assert "copy" in text.lower() and "opportunity-visuals" in text


def _matrix_outcomes(text: str, heading: str) -> dict[str, str]:
    section = text.split(heading, 1)[1].split("\n## ", 1)[0]
    rows = re.findall(
        r"^\| `([^`]+)` \| (Pass|Fail|Unavailable) \|", section, re.MULTILINE
    )
    return dict(rows)


def test_results_record_complete_baseline_and_completed_matrices() -> None:
    text = RESULTS.read_text(encoding="utf-8")
    baseline = _matrix_outcomes(text, "## Baseline outcome matrix")
    completed = _matrix_outcomes(text, "## Completed outcome matrix")

    assert set(baseline) == SCENARIO_IDS
    assert set(completed) == SCENARIO_IDS
    assert all(outcome in {"Pass", "Fail", "Unavailable"} for outcome in baseline.values())
    assert all(outcome in {"Pass", "Fail", "Unavailable"} for outcome in completed.values())
    assert "Codex subagent (exact model identifier unavailable)" in text
    assert "Provider: `otto`" in text
    assert "Model: `auto`" in text
    assert "Agent-reported loaded files" in text
    assert "bounded-context evidence, not a file-access trace" in text
    assert "[REDACTED]" in text
    assert "synthetic-secret-value" not in text


def _load_jsonl(path: Path) -> list[dict[str, object]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def test_completed_model_artifacts_join_independent_generation_and_grading() -> None:
    responses = _load_jsonl(RESPONSE_RESULTS)
    grades = _load_jsonl(GRADE_RESULTS)
    scenarios = {
        item["id"]: item
        for item in yaml.safe_load(
            (FIXTURES / "pressure-scenarios.yaml").read_text(encoding="utf-8")
        )["scenarios"]
    }
    response_by_id = {item["scenario_id"]: item for item in responses}
    grade_by_id = {item["scenario_id"]: item for item in grades}

    assert len(responses) == len(response_by_id) == 14
    assert len(grades) == len(grade_by_id) == 14
    assert set(response_by_id) == set(grade_by_id) == set(scenarios) == SCENARIO_IDS

    skill_root = SKILL_DIR.resolve()
    for scenario_id, response in response_by_id.items():
        assert response["schema_version"] == 1
        assert response["generator_identity"] == (
            "Codex subagent (exact model identifier unavailable)"
        )
        assert isinstance(response["response"], str) and response["response"].strip()
        assert "prompt" not in response
        assert "required_behaviors" not in response
        assert "forbidden_behaviors" not in response
        paths = response["agent_reported_loaded_files"]
        assert paths and paths[0] == "SKILL.md"
        assert len(paths) == len(set(paths))
        for relative in paths:
            assert isinstance(relative, str) and not Path(relative).is_absolute()
            resolved = (SKILL_DIR / relative).resolve()
            assert resolved == skill_root or skill_root in resolved.parents
            assert resolved.is_file(), f"{scenario_id}: missing reported path {relative}"
        if scenario_id in DISCOVERY_ONLY:
            assert paths == ["SKILL.md", "references/catalog.json"]
        assert set(paths) == ALLOWED_LOADS_BY_SCENARIO[scenario_id]
        capability_entries = [
            path for path in paths if path.startswith("references/capabilities/")
        ]
        assert len(capability_entries) <= 1

        grade = grade_by_id[scenario_id]
        assert grade["schema_version"] == 1
        assert grade["grader_identity"] == (
            "Codex subagent (exact model identifier unavailable)"
        )
        assert grade["response_artifact"] == "completed-responses.jsonl"
        required = grade["required"]
        forbidden = grade["forbidden"]
        assert len(required) == len(scenarios[scenario_id]["required_behaviors"])
        assert len(forbidden) == len(scenarios[scenario_id]["forbidden_behaviors"])
        for decisions in (required, forbidden):
            assert [item["index"] for item in decisions] == list(range(len(decisions)))
            for item in decisions:
                assert item["decision"] in {"pass", "fail"}
                assert isinstance(item["evidence"], str) and item["evidence"].strip()
        computed = (
            "Pass"
            if all(
                item["decision"] == "pass"
                for item in [*required, *forbidden]
            )
            else "Fail"
        )
        assert grade["outcome"] == computed

    durable = RESPONSE_RESULTS.read_text(encoding="utf-8") + RESULTS.read_text(
        encoding="utf-8"
    )
    assert "synthetic-secret-value" not in durable


def test_every_grade_joins_one_exact_immutable_response() -> None:
    response_artifacts = {
        RESPONSE_RESULTS.name: _load_jsonl(RESPONSE_RESULTS),
        PRE_FIX_RESPONSE_RESULTS.name: _load_jsonl(PRE_FIX_RESPONSE_RESULTS),
    }
    grade_artifacts = [
        *_load_jsonl(GRADE_RESULTS),
        *_load_jsonl(PRE_FIX_GRADE_RESULTS),
    ]

    all_response_ids: list[str] = []
    for rows in response_artifacts.values():
        for row in rows:
            response_id = row["response_id"]
            digest = hashlib.sha256(row["response"].encode("utf-8")).hexdigest()
            assert re.fullmatch(r"(?:final|prefx)-[a-z0-9-]+-\d{2}", response_id)
            assert row["response_sha256"] == digest
            all_response_ids.append(response_id)
    assert len(all_response_ids) == len(set(all_response_ids))

    known_pre_fix_ids = {
        row["response_id"]
        for row in response_artifacts[PRE_FIX_RESPONSE_RESULTS.name]
        if row["scenario_id"] == "known-capability"
    }
    assert known_pre_fix_ids == {
        "prefx-known-capability-01",
        "prefx-known-capability-02",
    }

    joined_grade_ids: set[str] = set()
    for grade in grade_artifacts:
        artifact_name = grade["response_artifact"]
        assert artifact_name in response_artifacts
        matches = [
            row
            for row in response_artifacts[artifact_name]
            if row["response_id"] == grade["response_id"]
        ]
        assert len(matches) == 1
        response = matches[0]
        assert grade["response_sha256"] == response["response_sha256"]
        assert grade["scenario_id"] == response["scenario_id"]
        joined_grade_ids.add(grade["response_id"])

    assert joined_grade_ids >= {
        row["response_id"] for row in response_artifacts[RESPONSE_RESULTS.name]
    }
    pre_fix_grade = _load_jsonl(PRE_FIX_GRADE_RESULTS)[0]
    assert pre_fix_grade["response_artifact"] == PRE_FIX_RESPONSE_RESULTS.name
    assert pre_fix_grade["response_id"] == "prefx-known-capability-02"
