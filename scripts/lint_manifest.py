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
PLUGIN_PATH_RE = re.compile(r"^plugins/[a-z0-9][a-z0-9_-]*$")
MIGRATION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
BUILTIN_BACKEND_PATHS = frozenset({"plugins/workflow"})
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
    plugin_paths = set()
    plugin_ids = set()
    migration_ids = set()
    if not isinstance(doc["plugins"], list):
        problems.append("plugins must be a list")
    else:
        for i, entry in enumerate(doc["plugins"]):
            if isinstance(entry, str):
                rel = entry
                if not PLUGIN_PATH_RE.fullmatch(rel):
                    problems.append(f"plugins[{i}] path must be plugins/<slug>")
                    continue
                if rel not in BUILTIN_BACKEND_PATHS:
                    for req in ("plugin.yaml", "__init__.py"):
                        if not (REPO / rel / req).exists():
                            problems.append(f"plugin missing {req}: {rel}")
            elif isinstance(entry, dict):
                allowed = {"path", "id", "enabled", "lifecycleMigration"}
                unknown = sorted(set(entry) - allowed)
                if unknown:
                    problems.append(
                        f"plugins[{i}] has unknown standalone fields: {unknown}"
                    )

                rel = entry.get("path")
                if not isinstance(rel, str) or not PLUGIN_PATH_RE.fullmatch(rel):
                    problems.append(f"plugins[{i}].path must be plugins/<slug>")
                    rel = None
                elif rel in BUILTIN_BACKEND_PATHS:
                    problems.append(
                        f"plugins[{i}].path {rel} is an enabled backend and cannot "
                        "use standalone connector metadata"
                    )

                plugin_id = entry.get("id")
                if not isinstance(plugin_id, str) or not SLUG_RE.fullmatch(plugin_id):
                    problems.append(f"plugins[{i}].id must be a slug")
                elif plugin_id in plugin_ids:
                    problems.append(f"duplicate standalone plugin id: {plugin_id}")
                else:
                    plugin_ids.add(plugin_id)

                enabled = entry.get("enabled")
                if not isinstance(enabled, bool):
                    problems.append(f"plugins[{i}].enabled must be boolean false")
                elif enabled:
                    problems.append(
                        f"plugins[{i}].enabled must be false for a standalone plugin"
                    )

                has_migration = "lifecycleMigration" in entry
                migration = entry.get("lifecycleMigration")
                if has_migration:
                    if enabled is not False or not isinstance(plugin_id, str):
                        problems.append(
                            f"plugins[{i}].lifecycleMigration is allowed only on "
                            "a disabled standalone plugin"
                        )
                    if not isinstance(migration, dict):
                        problems.append(
                            f"plugins[{i}].lifecycleMigration must be a mapping"
                        )
                    else:
                        migration_unknown = sorted(
                            set(migration) - {"id", "from"}
                        )
                        if migration_unknown:
                            problems.append(
                                f"plugins[{i}].lifecycleMigration has unknown fields: "
                                f"{migration_unknown}"
                            )
                        migration_id = migration.get("id")
                        if not isinstance(migration_id, str) or not MIGRATION_ID_RE.fullmatch(
                                migration_id):
                            problems.append(
                                f"plugins[{i}].lifecycleMigration.id must be a stable "
                                "slug of at most 64 characters"
                            )
                        elif migration_id in migration_ids:
                            problems.append(
                                f"duplicate lifecycleMigration id: {migration_id}"
                            )
                        else:
                            migration_ids.add(migration_id)
                        if migration.get("from") != "auto_seeded_backend":
                            problems.append(
                                f"plugins[{i}].lifecycleMigration.from must be "
                                "auto_seeded_backend"
                            )
            else:
                problems.append(
                    f"plugins[{i}] must be a backend path string or standalone mapping"
                )
                continue

            if rel is not None:
                if rel in plugin_paths:
                    problems.append(f"duplicate plugin path: {rel}")
                else:
                    plugin_paths.add(rel)
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
