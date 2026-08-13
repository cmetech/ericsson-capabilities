"""Load the Jira source plugin under a collision-free test package name."""

from __future__ import annotations

import importlib
import importlib.util
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
PACKAGE = "_ericsson_jira_source_tests"


def _load_package():
    existing = sys.modules.get(PACKAGE)
    if existing is not None:
        return existing
    spec = importlib.util.spec_from_file_location(
        PACKAGE,
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[PACKAGE] = module
    spec.loader.exec_module(module)
    return module


package = _load_package()
auth = importlib.import_module(f"{PACKAGE}.auth")
client = importlib.import_module(f"{PACKAGE}.client")
models = importlib.import_module(f"{PACKAGE}.models")
operations = importlib.import_module(f"{PACKAGE}.operations")
tools = importlib.import_module(f"{PACKAGE}.tools")
transport = importlib.import_module(f"{PACKAGE}.transport")
jira_tools = importlib.import_module(f"{PACKAGE}.jira_tools")
