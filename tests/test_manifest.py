import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LINT = REPO / "scripts/lint_manifest.py"
MANIFEST = REPO / "sets/ericsson.json"
FROZEN_LOOP24_SHA = "fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6"
LEGACY_FLOW_SHA = "3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e"


def _lint(path):
    proc = subprocess.run([sys.executable, str(LINT), str(path)],
                          capture_output=True, text=True, cwd=REPO)
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


def test_manifest_content():
    doc = json.loads(MANIFEST.read_text())
    assert doc["name"] == "ericsson"
    assert doc["skills"] == [
        "skills/ericsson/opportunity-visuals",
        "skills/ericsson/onboard-ericsson-capabilities",
    ]
    assert doc["plugins"] == [
        "plugins/ericsson-jira",
        "plugins/ericsson-teams",
        "plugins/workflow",
        {
            "path": "plugins/ericsson-gitlab",
            "id": "ericsson-gitlab",
            "enabled": False,
        },
    ]
    assert doc["mcpServers"] == "mcp/mcp-servers.yaml"
    assert doc["mcpLocal"] == ["mcp/outlook-mcp"]
    assert doc["workflowCoreTools"] == []
    assert set(doc["workflows"]) == {"workflows/my-tickets-summary.yml",
                                      "workflows/inbox-digest.yml"}
    assert doc["personas"] == []
    keys = {e["key"] for e in doc["env"]}
    assert keys == {
        "JIRA_BASE_URL",
        "JIRA_PAT",
        "GLEAN_API_TOKEN",
        "ERICSSON_GRAPH_CLIENT_ID",
    }
    assert "GLEAN_MCP_URL" not in keys
    assert {e["category"] for e in doc["env"]} == {"tool"}
    assert "ERICSSON_ENV" not in {e["key"] for e in doc["env"]}
    assert doc["version"] == "0.5.0"
    assert "requiresEnv" not in doc
    assert "disabledByDefault" not in doc
    assert "ERICSSON_ENV" not in MANIFEST.read_text()


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
    assert len(flow_pages) == 11
    for path in flow_pages:
        assert f"source_commit: {LEGACY_FLOW_SHA}" in path.read_text()


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


def test_lint_accepts_four_connectors_disabled_for_new_profiles(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["plugins"] = [
        _standalone_plugin("ericsson-jira"),
        _standalone_plugin("ericsson-gitlab"),
        _standalone_plugin("ericsson-sharepoint"),
        _standalone_plugin("ericsson-confluence"),
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
    assert any("duplicate lifecycleMigration id" in problem for problem in out["problems"]), out


def test_lint_rejects_bad_disabled_block(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["disabledByDefault"] = {"skills": "not-a-list"}
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps(doc))
    code, out = _lint(bad)
    assert code == 1 and any("disabledByDefault" in p for p in out["problems"])
