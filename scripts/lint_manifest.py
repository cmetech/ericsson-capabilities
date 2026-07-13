#!/usr/bin/env python3
"""Lint a capability-set manifest (sets/<name>.json) against the repo tree.

Usage: python3 scripts/lint_manifest.py sets/ericsson.json
Prints one JSON object; exit 0 when ok, 1 when problems were found.
Run from the repo root (paths in the manifest are repo-relative).
"""
import json
import re
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
REQUIRED = ["name", "version", "description", "skills", "plugins",
            "mcpServers", "mcpLocal", "workflows", "personas", "env"]


def lint(manifest_path: Path) -> list[str]:
    problems = []
    try:
        doc = json.loads(manifest_path.read_text())
    except (OSError, json.JSONDecodeError) as e:
        return [f"cannot read manifest: {e}"]

    for key in REQUIRED:
        if key not in doc:
            problems.append(f"missing required key: {key}")
    if problems:
        return problems
    if not SLUG_RE.match(doc["name"]):
        problems.append(f"name must be a slug: {doc['name']!r}")

    for rel in doc["skills"]:
        if not (REPO / rel / "SKILL.md").exists():
            problems.append(f"skill missing or lacks SKILL.md: {rel}")
    for rel in doc["plugins"]:
        for req in ("plugin.yaml", "__init__.py"):
            if not (REPO / rel / req).exists():
                problems.append(f"plugin missing {req}: {rel}")
    mcp_cfg = REPO / doc["mcpServers"]
    if not mcp_cfg.exists():
        problems.append(f"mcpServers file missing: {doc['mcpServers']}")
    else:
        try:
            parsed = yaml.safe_load(mcp_cfg.read_text())
            if "mcp_servers" not in (parsed or {}):
                problems.append("mcpServers file lacks an mcp_servers key")
        except yaml.YAMLError as e:
            problems.append(f"mcpServers file is invalid YAML: {e}")
    for rel in doc["mcpLocal"]:
        if not (REPO / rel).is_dir():
            problems.append(f"mcpLocal dir missing: {rel}")

    sys.path.insert(0, str(REPO / "skills/ericsson/workflow-orchestrator/scripts"))
    import workflow_ctl as wc
    for rel in doc["workflows"]:
        p = REPO / rel
        if not p.exists():
            problems.append(f"workflow missing: {rel}")
            continue
        try:
            errors, _ = wc.validate_workflow(wc.load_workflow(p))
            problems += [f"{rel}: {e}" for e in errors]
        except Exception as e:
            problems.append(f"{rel}: {e}")

    for i, entry in enumerate(doc["env"]):
        if not isinstance(entry, dict) or not entry.get("key") or not entry.get("description"):
            problems.append(f"env[{i}] needs key + description")

    req_env = doc.get("requiresEnv", {})
    if not isinstance(req_env, dict) or not all(
            isinstance(k, str) and isinstance(v, str) for k, v in req_env.items()):
        problems.append("requiresEnv must be a mapping of env-var name -> required value")
    dbd = doc.get("disabledByDefault", {})
    if not isinstance(dbd, dict):
        problems.append("disabledByDefault must be a mapping")
    else:
        for key in ("skills", "toolsets"):
            val = dbd.get(key, [])
            if not (isinstance(val, list) and all(isinstance(x, str) for x in val)):
                problems.append(f"disabledByDefault.{key} must be a list of strings")
    return problems


def main():
    if len(sys.argv) != 2:
        print(json.dumps({"error": "usage: lint_manifest.py <manifest.json>"}))
        sys.exit(1)
    problems = lint(Path(sys.argv[1]))
    if problems:
        print(json.dumps({"ok": False, "problems": problems}, indent=2))
        sys.exit(1)
    print(json.dumps({"ok": True}))


if __name__ == "__main__":
    main()
