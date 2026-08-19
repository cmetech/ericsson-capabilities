from __future__ import annotations

import ast
import json
import os
from pathlib import Path

import yaml
import pytest


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-connector-cli"
MANIFEST = REPO / "sets" / "ericsson.json"
FACADE_ENTRY = "plugins/ericsson-connector-cli"
CONNECTOR_IDS = {
    "ericsson-jira",
    "ericsson-gitlab",
    "ericsson-confluence",
    "ericsson-arm",
}
FORBIDDEN_IMPORT_SEGMENTS = {
    "auth",
    "client",
    "httpx",
    "operations",
    "requests",
    "tools",
    "transport",
    "urllib",
}
CONNECTOR_IMPORT_SEGMENTS = {
    "ericsson_jira",
    "ericsson_gitlab",
    "ericsson_confluence",
    "ericsson_arm",
}


def _hermes_root() -> Path:
    configured = os.environ.get("HERMES_AGENT_DIR")
    candidates = ([Path(configured)] if configured else []) + [
        ancestor / "hermes-agent" for ancestor in REPO.parents
    ]
    return next(
        candidate
        for candidate in candidates
        if (candidate / "hermes_cli" / "plugins.py").is_file()
    )


def _facade_python_sources(root: Path) -> tuple[Path, ...]:
    return tuple(sorted(root.rglob("*.py")))


def test_facade_is_an_always_loaded_network_free_backend():
    document = yaml.safe_load((PLUGIN / "plugin.yaml").read_text(encoding="utf-8"))

    assert document["name"] == "ericsson-connector-cli"
    assert document["kind"] == "backend"
    assert document["provides_tools"] == []
    forbidden = {
        "config_schema",
        "required_env",
        "optional_env",
        "provides_hooks",
        "network",
        "network_access",
        "origins",
        "permissions",
    }
    assert forbidden.isdisjoint(document)


def test_manifest_registers_facade_once_without_changing_connector_lifecycle():
    plugins = json.loads(MANIFEST.read_text(encoding="utf-8"))["plugins"]

    assert plugins.count(FACADE_ENTRY) == 1
    assert all(
        not isinstance(entry, dict) or entry.get("path") != FACADE_ENTRY
        for entry in plugins
    )
    connectors = {
        entry["id"]: entry
        for entry in plugins
        if isinstance(entry, dict) and entry.get("id") in CONNECTOR_IDS
    }
    assert connectors == {
        "ericsson-jira": {
            "path": "plugins/ericsson-jira",
            "id": "ericsson-jira",
            "enabled": False,
            "lifecycleMigration": {
                "id": "ericsson-jira-backend-to-standalone-v1",
                "from": "auto_seeded_backend",
            },
        },
        "ericsson-gitlab": {
            "path": "plugins/ericsson-gitlab",
            "id": "ericsson-gitlab",
            "enabled": False,
        },
        "ericsson-confluence": {
            "path": "plugins/ericsson-confluence",
            "id": "ericsson-confluence",
            "enabled": False,
        },
        "ericsson-arm": {
            "path": "plugins/ericsson-arm",
            "id": "ericsson-arm",
            "enabled": False,
        },
    }


def test_facade_sources_do_not_import_connector_or_network_internals():
    for path in _facade_python_sources(PLUGIN):
        assert _forbidden_imports(path.read_text(encoding="utf-8")) == set()


def test_facade_source_discovery_recursively_includes_future_nested_modules(tmp_path):
    root = tmp_path / "facade"
    nested = root / "parsers" / "inputs.py"
    nested.parent.mkdir(parents=True)
    nested.write_text("from package import operations\n", encoding="utf-8")
    top_level = root / "__init__.py"
    top_level.write_text("from .descriptors import DESCRIPTORS\n", encoding="utf-8")
    (root / "README.md").write_text("not Python\n", encoding="utf-8")

    assert _facade_python_sources(root) == (top_level, nested)
    assert _forbidden_imports(nested.read_text(encoding="utf-8")) == {
        "package.operations"
    }


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        (
            "from plugins.ericsson_gitlab import tools\n",
            {"plugins.ericsson_gitlab", "plugins.ericsson_gitlab.tools"},
        ),
        ("import ericsson_gitlab.client as c\n", {"ericsson_gitlab.client"}),
        ("import package.auth.tokens\n", {"package.auth.tokens"}),
        ("from package.transport.http import send\n", {"package.transport.http"}),
        ("from package import operations\n", {"package.operations"}),
        ("from . import client\n", {".client"}),
        ("from ..connector import auth\n", {"..connector.auth"}),
        ("import urllib.parse as parse\n", {"urllib.parse"}),
    ],
)
def test_import_policy_rejects_complete_dotted_and_relative_names(source, expected):
    assert _forbidden_imports(source) == expected


def test_import_policy_allows_stdlib_and_local_descriptor_contract():
    source = (
        "from __future__ import annotations\n"
        "import argparse\n"
        "from dataclasses import dataclass\n"
        "from .descriptors import DESCRIPTORS\n"
    )
    assert _forbidden_imports(source) == set()


def _forbidden_imports(source: str) -> set[str]:
    tree = ast.parse(source)
    forbidden = set()

    def rejected(module_name: str) -> bool:
        segments = {
            segment.replace("-", "_").lower()
            for segment in module_name.lstrip(".").split(".")
            if segment
        }
        return bool(
            segments & (FORBIDDEN_IMPORT_SEGMENTS | CONNECTOR_IMPORT_SEGMENTS)
        )

    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            forbidden.update(
                alias.name for alias in node.names if rejected(alias.name)
            )
        elif isinstance(node, ast.ImportFrom):
            base = "." * node.level + (node.module or "")
            if base and rejected(base):
                forbidden.add(base)
            for alias in node.names:
                if alias.name == "*":
                    continue
                separator = "" if base.endswith(".") else "."
                qualified = f"{base}{separator}{alias.name}"
                if rejected(alias.name):
                    forbidden.add(qualified)
    return forbidden


def test_facade_cli_domain_registration_is_atomic_on_collision(monkeypatch):
    hermes = _hermes_root()
    monkeypatch.syspath_prepend(str(hermes))
    from hermes_cli.plugins import PluginContext, PluginManager, PluginManifest

    manager = PluginManager()
    existing_setup = lambda parser: None
    PluginContext(
        PluginManifest(name="Existing owner", key="existing-owner"), manager
    ).register_cli_command("gitlab", "existing", existing_setup)
    manifest = PluginManifest(
        name="Ericsson connector CLI",
        key="ericsson-connector-cli",
        kind="backend",
        source="bundled",
        path=str(PLUGIN),
    )

    manager._load_plugin(manifest)

    loaded = manager._plugins["ericsson-connector-cli"]
    assert loaded.enabled is False
    assert "already registered" in (loaded.error or "")
    assert manager._cli_commands["gitlab"]["plugin"] == "existing-owner"
    assert manager._cli_commands["gitlab"]["setup_fn"] is existing_setup
    assert not ({"jira", "confluence", "arm"} & manager._cli_commands.keys())
