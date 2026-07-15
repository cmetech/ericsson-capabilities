import json
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
LINT = REPO / "scripts/lint_manifest.py"
MANIFEST = REPO / "sets/ericsson.json"


def _lint(path):
    proc = subprocess.run([sys.executable, str(LINT), str(path)],
                          capture_output=True, text=True, cwd=REPO)
    return proc.returncode, json.loads(proc.stdout)


def test_manifest_content():
    doc = json.loads(MANIFEST.read_text())
    assert doc["name"] == "ericsson"
    assert "skills/ericsson/workflow-orchestrator" in doc["skills"]
    assert "skills/ericsson/workflow-builder" in doc["skills"]
    assert "skills/ericsson/opportunity-visuals" in doc["skills"]
    assert "skills/ericsson/onboard-ericsson-capabilities" in doc["skills"]
    assert doc["skills"].count("skills/ericsson/opportunity-visuals") == 1
    assert doc["skills"].count("skills/ericsson/onboard-ericsson-capabilities") == 1
    assert len(doc["skills"]) == 4
    assert set(doc["plugins"]) == {"plugins/ericsson-jira", "plugins/ericsson-teams"}
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
        "GLEAN_MCP_URL",
        "GLEAN_API_TOKEN",
        "ERICSSON_GRAPH_CLIENT_ID",
    }
    assert {e["category"] for e in doc["env"]} == {"tool"}
    assert "ERICSSON_ENV" not in {e["key"] for e in doc["env"]}
    assert doc["version"] == "0.4.0"
    assert "requiresEnv" not in doc
    assert "disabledByDefault" not in doc
    assert "ERICSSON_ENV" not in MANIFEST.read_text()


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


def test_lint_rejects_bad_disabled_block(tmp_path):
    doc = json.loads(MANIFEST.read_text())
    doc["disabledByDefault"] = {"skills": "not-a-list"}
    bad = tmp_path / "bad2.json"
    bad.write_text(json.dumps(doc))
    code, out = _lint(bad)
    assert code == 1 and any("disabledByDefault" in p for p in out["problems"])
