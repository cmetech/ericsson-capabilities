import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import lint_manifest  # noqa: E402

REPO = Path(__file__).resolve().parents[1]
LINT = REPO / "scripts/lint_manifest.py"
MANIFEST = REPO / "sets/ericsson.json"
FROZEN_LOOP24_SHA = "fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6"
LEGACY_FLOW_SHA = "3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e"

VALID_ARCHON_SIDECAR = {
    "language_compatibility": "archon-2026-07",
    "delivery_defaults": {},
    "required_services": ["example-tools"],
    "retention": {},
    "tags": ["example"],
    "outward_action_nodes": ["write"],
    "outward_action_policy": "approval_required",
    "execution_environment": "trusted_local",
    "overlap_policy": "queue",
    "concurrency_key": "example",
    "limits": {"max_parallel_nodes": 2},
    "resource_limits": {"max_descendants": 2},
    "required_secrets": ["EXAMPLE_TOKEN"],
    "scheduling": {},
}
INVALID_ARCHON_SIDECARS = {
    "unknown": {"unknown_policy": True},
    "outward_type": {"outward_action_nodes": "write"},
    "outward_item": {"outward_action_nodes": [1]},
    "outward_unknown": {"outward_action_nodes": ["missing"]},
    "outward_policy_type": {"outward_action_policy": 1},
    "outward_policy_empty": {"outward_action_policy": ""},
    "execution_environment": {"execution_environment": "remote"},
    "overlap_policy": {"overlap_policy": "sometimes"},
    "pause_lane_policy": {"pause_lane_policy": "sometimes"},
    "pause_lane_cross_field": {
        "pause_lane_policy": "hold",
        "overlap_policy": "forbid",
    },
    "delivery_defaults": {"delivery_defaults": []},
    "required_services_type": {"required_services": "example-tools"},
    "required_services_item": {"required_services": [""]},
    "retention": {"retention": []},
    "tags_type": {"tags": "example"},
    "tags_item": {"tags": [1]},
    "concurrency_key": {"concurrency_key": ""},
    "limits_type": {"limits": []},
    "limits_unknown": {"limits": {"max_iterations": 12}},
    "limits_value": {"limits": {"max_parallel_nodes": 0}},
    "limits_lease_relationship": {
        "limits": {"heartbeat_seconds": 5, "lease_seconds": 10}
    },
    "limits_idle_relationship": {
        "limits": {"ai_idle_timeout_seconds": 20, "ai_wall_timeout_seconds": 10}
    },
    "limits_provider_relationship": {
        "limits": {
            "provider_request_timeout_seconds": 20,
            "ai_wall_timeout_seconds": 10,
        }
    },
    "resource_limits_type": {"resource_limits": []},
    "resource_limits_unknown": {"resource_limits": {"unknown": 1}},
    "required_secrets_type": {"required_secrets": "EXAMPLE_TOKEN"},
    "required_secrets_item": {"required_secrets": [""]},
    "scheduling": {"scheduling": []},
}
COMPILER_LENIENT_SCHEMA_INVALID = {
    "outward_policy_type",
    "outward_policy_empty",
    "overlap_policy",
    "delivery_defaults",
    "required_services_type",
    "required_services_item",
    "retention",
    "tags_type",
    "tags_item",
    "concurrency_key",
    "scheduling",
}


def _lint(path):
    proc = subprocess.run(
        [sys.executable, str(LINT), str(path)], capture_output=True, text=True, cwd=REPO
    )
    if not proc.stdout:
        return proc.returncode, {
            "ok": False,
            "problems": [proc.stderr.strip() or "linter produced no JSON output"],
        }
    return proc.returncode, json.loads(proc.stdout)


def _write_manifest(tmp_path, doc, name="manifest.json"):
    path = tmp_path / name
    path.write_text(json.dumps(doc))
    return path


def _standalone_plugin(plugin_id, *, enabled=False, path=None):
    return {
        "path": path if path is not None else f"plugins/{plugin_id}",
        "id": plugin_id,
        "enabled": enabled,
    }


def _minimal_lint_repo(tmp_path: Path, workflow: dict) -> Path:
    (tmp_path / "sets").mkdir()
    (tmp_path / "mcp").mkdir()
    (tmp_path / "workflows").mkdir()
    (tmp_path / "mcp/servers.yaml").write_text("mcp_servers: {}\n")
    (tmp_path / "workflows/example.yml").write_text(
        yaml.safe_dump(workflow, sort_keys=False)
    )
    (tmp_path / "workflows/example.hermes.yaml").write_text(
        "language_compatibility: archon-2026-07\n"
    )
    manifest = {
        "name": "example",
        "version": "1.0.0",
        "description": "Example",
        "skills": [],
        "plugins": [],
        "mcpServers": "mcp/servers.yaml",
        "mcpLocal": [],
        "workflows": ["workflows/example.yml"],
        "personas": [],
        "env": [],
    }
    path = tmp_path / "sets/example.json"
    path.write_text(json.dumps(manifest))
    return path


def test_lint_accepts_generic_flat_archon_and_rejects_malformed_nodes(
    tmp_path, monkeypatch
):
    valid = {
        "name": "example",
        "description": "Example flat workflow",
        "requires": ["example-tools"],
        "nodes": [
            {
                "id": "read",
                "prompt": "Read evidence",
                "allowed_tools": ["example_read"],
            },
            {
                "id": "approve",
                "depends_on": ["read"],
                "approval": {"message": "Review the outward action."},
            },
            {
                "id": "write",
                "depends_on": ["approve"],
                "prompt": "Perform the approved action",
                "allowed_tools": ["example_write"],
            },
        ],
    }
    manifest = _minimal_lint_repo(tmp_path, valid)
    monkeypatch.setattr(lint_manifest, "REPO", tmp_path)
    assert lint_manifest.lint(manifest) == []

    sidecar = tmp_path / "workflows/example.hermes.yaml"
    sidecar.unlink()
    assert any(
        "missing Archon workflow sidecar" in problem
        for problem in lint_manifest.lint(manifest)
    )
    sidecar.write_text("language_compatibility: hermes-legacy\n")
    assert any(
        "incompatible workflow sidecar" in problem
        for problem in lint_manifest.lint(manifest)
    )
    sidecar.write_text("language_compatibility: archon-2026-07\n")

    invalid = dict(valid)
    invalid["nodes"] = [{"id": "broken", "allowed_tools": "example_read"}]
    (tmp_path / "workflows/example.yml").write_text(
        yaml.safe_dump(invalid, sort_keys=False)
    )
    assert any(
        "allowed_tools must be a list of strings" in problem
        for problem in lint_manifest.lint(manifest)
    )

    invalid["requires"] = []
    invalid["nodes"] = valid["nodes"]
    (tmp_path / "workflows/example.yml").write_text(
        yaml.safe_dump(invalid, sort_keys=False)
    )
    assert any(
        "requires must be a non-empty list" in problem
        for problem in lint_manifest.lint(manifest)
    )


def test_static_sidecar_validation_is_one_way_compatible_with_real_hermes(
    tmp_path, monkeypatch
):
    workflow = {
        "name": "example",
        "description": "Example flat workflow",
        "requires": ["example-tools"],
        "nodes": [
            {
                "id": "read",
                "prompt": "Use the example_read tool.",
                "allowed_tools": ["example_read"],
            },
            {
                "id": "approve",
                "depends_on": ["read"],
                "approval": {"message": "Review the outward action."},
            },
            {
                "id": "write",
                "depends_on": ["approve"],
                "prompt": "Use the example_write tool.",
                "allowed_tools": ["example_write"],
            },
        ],
    }
    manifest = _minimal_lint_repo(tmp_path, workflow)
    monkeypatch.setattr(lint_manifest, "REPO", tmp_path)
    sidecar_path = tmp_path / "workflows/example.hermes.yaml"
    cases = {"valid": VALID_ARCHON_SIDECAR} | {
        name: VALID_ARCHON_SIDECAR | override
        for name, override in INVALID_ARCHON_SIDECARS.items()
    }
    source_valid = {}
    for name, sidecar in cases.items():
        sidecar_path.write_text(yaml.safe_dump(sidecar, sort_keys=False))
        source_valid[name] = lint_manifest.lint(manifest) == []
    assert source_valid == {name: name == "valid" for name in cases}

    workspace = Path(__file__).resolve().parents[4]
    candidates = [
        Path(value) for value in [os.environ.get("HERMES_AGENT_DIR")] if value
    ] + [
        workspace / "hermes-agent/.worktrees/ericsson-gitlab-connector",
        workspace / "hermes-agent",
    ]
    hermes = next(
        candidate
        for candidate in candidates
        if (candidate / "plugins/workflow/schema.py").is_file()
    )
    script = r"""
import json
from pathlib import Path
import sys
import yaml
from jsonschema import Draft202012Validator
from plugins.workflow.compilation import WorkflowCatalogSnapshot, compile_workflow
from plugins.workflow.language_schema import sidecar_json_schema
from plugins.workflow.models import WorkflowLanguageProfile
from plugins.workflow.schema import parse_workflow_source_bytes

path = Path(sys.argv[1])
cases = json.loads(sys.argv[2])
schema = sidecar_json_schema(WorkflowLanguageProfile.ARCHON_2026_07)
results = {}
for name, sidecar in cases.items():
    schema_valid = not list(Draft202012Validator(schema).iter_errors(sidecar))
    try:
        source = parse_workflow_source_bytes(
            path,
            workflow_bytes=path.read_bytes(),
            sidecar_bytes=yaml.safe_dump(sidecar, sort_keys=False).encode(),
            source="differential",
            precedence=1,
        )
        compile_workflow(source, WorkflowCatalogSnapshot.capture((source,)))
    except Exception:
        compiler_valid = False
    else:
        compiler_valid = True
    results[name] = {"schema": schema_valid, "compiler": compiler_valid}
print(json.dumps(results, sort_keys=True))
"""
    result = subprocess.run(
        [
            str(hermes / ".venv/bin/python"),
            "-c",
            script,
            str(tmp_path / "workflows/example.yml"),
            json.dumps(cases),
        ],
        cwd=hermes,
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    authority = json.loads(result.stdout)
    for name, accepted in source_valid.items():
        if accepted:
            assert authority[name] == {"schema": True, "compiler": True}
    for name in COMPILER_LENIENT_SCHEMA_INVALID:
        assert authority[name] == {"schema": False, "compiler": True}, name


def test_manifest_content():
    doc = json.loads(MANIFEST.read_text())
    assert doc["name"] == "ericsson"
    assert doc["skills"] == [
        "skills/ericsson/opportunity-visuals",
        "skills/ericsson/onboard-ericsson-capabilities",
        "skills/ericsson/gitlab",
        "skills/ericsson/jira",
        "skills/ericsson/jira-to-gitlab",
        "skills/ericsson/sharepoint",
    ]
    assert doc["plugins"] == [
        {
            "path": "plugins/ericsson-jira",
            "id": "ericsson-jira",
            "enabled": False,
            "lifecycleMigration": {
                "id": "ericsson-jira-backend-to-standalone-v1",
                "from": "auto_seeded_backend",
            },
        },
        "plugins/ericsson-teams",
        "plugins/workflow",
        "plugins/ericsson-connector-cli",
        {
            "path": "plugins/ericsson-gitlab",
            "id": "ericsson-gitlab",
            "enabled": False,
        },
        {
            "path": "plugins/ericsson-sharepoint",
            "id": "ericsson-sharepoint",
            "enabled": False,
        },
        {
            "path": "plugins/ericsson-confluence",
            "id": "ericsson-confluence",
            "enabled": False,
        },
        {
            "path": "plugins/ericsson-arm",
            "id": "ericsson-arm",
            "enabled": False,
        },
    ]
    assert doc["mcpServers"] == "mcp/mcp-servers.yaml"
    assert doc["mcpLocal"] == ["mcp/outlook-mcp"]
    assert doc["workflowCoreTools"] == []
    assert doc["workflowPackages"] == [{
        "path": "capabilities/workflow-packages/ericsson",
        "digestManifest": "capabilities/workflow-packages/ericsson/digests.json",
    }]
    assert set(doc["workflows"]) == {
        "workflows/my-tickets-summary.yml",
        "workflows/inbox-digest.yml",
        "workflows/jira-single-ticket-showcase.yml",
        "workflows/jira-to-gitlab.yml",
        "workflows/sharepoint-document-intake.yml",
    }
    assert doc["personas"] == []
    keys = {e["key"] for e in doc["env"]}
    assert keys == {
        "GLEAN_API_TOKEN",
        "ERICSSON_GRAPH_CLIENT_ID",
    }
    assert "GLEAN_MCP_URL" not in keys
    assert {e["category"] for e in doc["env"]} == {"tool"}
    assert "ERICSSON_ENV" not in {e["key"] for e in doc["env"]}
    assert "ericsson-sharepoint" in doc["disabledByDefault"]["toolsets"]
    assert doc["version"] == "0.6.0"
    assert "requiresEnv" not in doc
    assert "ERICSSON_ENV" not in MANIFEST.read_text()


def test_workflow_package_is_complete_and_digest_bound():
    package = REPO / "capabilities/workflow-packages/ericsson"
    digests = json.loads((package / "digests.json").read_text())
    packaged_workflows = {
        path.stem: path
        for path in (package / "workflows").glob("*.yaml")
        if not path.name.endswith(".hermes.yaml")
    }
    assert set(digests["packages"]) == set(packaged_workflows)
    assert all(len(value) == 64 for value in digests["packages"].values())

    manifest = json.loads(MANIFEST.read_text())
    connector_workflows = {}
    for relative in manifest["workflows"]:
        source = REPO / relative
        document = yaml.safe_load(source.read_text(encoding="utf-8"))
        required = set(document.get("requires", []))
        if required & {"ericsson-jira", "ericsson-sharepoint"}:
            connector_workflows[source.stem] = source

    assert "sharepoint-document-intake" in connector_workflows
    for name, source in connector_workflows.items():
        packaged = package / "workflows" / f"{name}.yaml"
        source_sidecar = source.with_name(f"{name}.hermes.yaml")
        packaged_sidecar = packaged.with_name(f"{name}.hermes.yaml")
        assert packaged.read_bytes() == source.read_bytes()
        assert packaged_sidecar.read_bytes() == source_sidecar.read_bytes()


def test_guides_record_frozen_loop24_inventory_and_reviewed_flow_provenance():
    for path in (REPO / "AGENTS.md", REPO / "CLAUDE.md"):
        text = path.read_text()
        assert FROZEN_LOOP24_SHA in text
        assert "30 flow JSON files" in text

    handbook = (REPO / "docs/README.md").read_text()
    assert f"Inventory snapshot: commit `{FROZEN_LOOP24_SHA}`" in handbook
    assert "30 live, non-archived flow JSON files" in handbook

    flow_pages = sorted((REPO / "docs/flows").glob("*.md"))
    flow_pages = [path for path in flow_pages if path.name != "_template.md"]
    assert len(flow_pages) == 13
    for path in flow_pages:
        expected_commit = (
            "fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6"
            if path.name == "sharepoint-document-intake.md"
            else LEGACY_FLOW_SHA
        )
        assert f"source_commit: {expected_commit}" in path.read_text()


def test_lint_passes_on_real_manifest():
    code, out = _lint(MANIFEST)
    assert code == 0 and out["ok"] is True, out


def test_lint_fails_on_broken_manifest(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["skills"].append("skills/ericsson/ghost")
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(doc))
    code, out = _lint(bad)
    assert code == 1 and any("ghost" in p for p in out["problems"])


def test_lint_accepts_string_backends_and_disabled_standalone_plugins(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["plugins"] = [
        "plugins/ericsson-jira",
        "plugins/ericsson-teams",
        "plugins/workflow",
        _standalone_plugin("ericsson-gitlab"),
    ]

    code, out = _lint(_write_manifest(tmp_path, doc))

    assert code == 0 and out["ok"] is True, out


def test_lint_accepts_five_connectors_disabled_for_new_profiles(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["plugins"] = [
        _standalone_plugin("ericsson-jira"),
        _standalone_plugin("ericsson-gitlab"),
        _standalone_plugin("ericsson-sharepoint"),
        _standalone_plugin("ericsson-confluence"),
        _standalone_plugin("ericsson-arm"),
    ]

    code, out = _lint(_write_manifest(tmp_path, doc))

    assert code == 0 and out["ok"] is True, out
    assert all(entry["enabled"] is False for entry in doc["plugins"])


def test_lint_accepts_bounded_standalone_lifecycle_migration(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    plugin = _standalone_plugin("ericsson-gitlab")
    plugin["lifecycleMigration"] = {
        "id": "ericsson-gitlab-auto-seed-v1",
        "from": "auto_seeded_backend",
    }
    doc["plugins"] = [plugin]

    code, out = _lint(_write_manifest(tmp_path, doc))

    assert code == 0 and out["ok"] is True, out


def test_jira_manifest_declares_disabled_one_time_backend_transition():
    doc = json.loads(MANIFEST.read_text())
    jira = next(
        entry
        for entry in doc["plugins"]
        if isinstance(entry, dict) and entry.get("id") == "ericsson-jira"
    )

    assert jira == {
        "path": "plugins/ericsson-jira",
        "id": "ericsson-jira",
        "enabled": False,
        "lifecycleMigration": {
            "id": "ericsson-jira-backend-to-standalone-v1",
            "from": "auto_seeded_backend",
        },
    }
    assert all(
        not isinstance(entry, str) or entry != "plugins/ericsson-jira"
        for entry in doc["plugins"]
    )


def test_lint_rejects_non_boolean_or_enabled_standalone_plugins(tmp_path):
    for index, enabled in enumerate(("false", 0, None, True)):
        doc = json.loads(MANIFEST.read_text())
        doc["plugins"] = [_standalone_plugin("ericsson-gitlab", enabled=enabled)]

        code, out = _lint(_write_manifest(tmp_path, doc, f"enabled-{index}.json"))

        assert code == 1, out
        assert any("enabled" in problem for problem in out["problems"]), out


def test_lint_rejects_missing_or_non_plugin_standalone_paths(tmp_path):
    invalid_entries = [
        {"id": "ericsson-gitlab", "enabled": False},
        _standalone_plugin("ericsson-gitlab", path=""),
        _standalone_plugin("ericsson-gitlab", path="skills/ericsson/gitlab"),
        _standalone_plugin("ericsson-gitlab", path="workflows/gitlab.yml"),
    ]
    for index, entry in enumerate(invalid_entries):
        doc = json.loads(MANIFEST.read_text())
        doc["plugins"] = [entry]

        code, out = _lint(_write_manifest(tmp_path, doc, f"path-{index}.json"))

        assert code == 1, out
        assert any("path" in problem for problem in out["problems"]), out


def test_lint_rejects_duplicate_plugin_paths(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["plugins"] = [
        "plugins/ericsson-jira",
        _standalone_plugin(
            "ericsson-jira-next",
            path="plugins/ericsson-jira",
        ),
    ]

    code, out = _lint(_write_manifest(tmp_path, doc))

    assert code == 1
    assert any("duplicate plugin path" in problem for problem in out["problems"]), out


def test_lint_rejects_disabling_the_workflow_backend(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["plugins"] = [_standalone_plugin("workflow")]

    code, out = _lint(_write_manifest(tmp_path, doc))

    assert code == 1
    assert any("workflow" in problem for problem in out["problems"]), out


def test_lint_rejects_invalid_or_misplaced_lifecycle_migrations(tmp_path):
    cases = [
        {
            "path": "plugins/ericsson-jira",
            "lifecycleMigration": {
                "id": "jira-auto-seed-v1",
                "from": "auto_seeded_backend",
            },
        },
        {
            **_standalone_plugin("ericsson-gitlab", enabled=True),
            "lifecycleMigration": {
                "id": "gitlab-auto-seed-v1",
                "from": "auto_seeded_backend",
            },
        },
        {
            **_standalone_plugin("ericsson-gitlab"),
            "lifecycleMigration": {
                "id": "gitlab-auto-seed-v1",
                "from": "manual_opt_in",
            },
        },
        {
            **_standalone_plugin("ericsson-gitlab"),
            "lifecycleMigration": {
                "id": "x" * 65,
                "from": "auto_seeded_backend",
            },
        },
        {
            **_standalone_plugin("ericsson-gitlab"),
            "lifecycleMigration": None,
        },
    ]
    for index, entry in enumerate(cases):
        doc = json.loads(MANIFEST.read_text())
        doc["plugins"] = [entry]

        code, out = _lint(_write_manifest(tmp_path, doc, f"migration-{index}.json"))

        assert code == 1, out
        assert any("lifecycleMigration" in problem for problem in out["problems"]), out


def test_lint_rejects_duplicate_lifecycle_migration_ids(tmp_path):
    migration = {
        "id": "connector-auto-seed-v1",
        "from": "auto_seeded_backend",
    }
    doc = json.loads(MANIFEST.read_text())
    doc["plugins"] = [
        {
            **_standalone_plugin("ericsson-gitlab"),
            "lifecycleMigration": migration,
        },
        {
            **_standalone_plugin("ericsson-sharepoint"),
            "lifecycleMigration": migration,
        },
    ]

    code, out = _lint(_write_manifest(tmp_path, doc))

    assert code == 1
    assert any(
        "duplicate lifecycleMigration id" in problem for problem in out["problems"]
    ), out


def test_lint_rejects_bad_disabled_block(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["disabledByDefault"] = {"skills": "not-a-list"}
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps(doc))
    code, out = _lint(bad)
    assert code == 1 and any("disabledByDefault" in p for p in out["problems"])
