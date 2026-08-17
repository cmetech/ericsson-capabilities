"""Confluence tool invocation must preserve configuration-bound defaults."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-confluence"
for _module_name in ("auth", "client", "models", "operations", "storage", "tools"):
    sys.modules.pop(_module_name, None)
for _module_name in tuple(sys.modules):
    if _module_name == "_common" or _module_name.startswith("_common."):
        sys.modules.pop(_module_name, None)
for _path in list(sys.path):
    if Path(_path).name in {"ericsson-confluence", "ericsson-gitlab"}:
        sys.path.remove(_path)
sys.path.insert(0, str(PLUGIN))

import tools  # noqa: E402


try:
    sys.path.remove(str(PLUGIN))
except ValueError:
    pass
for _module_name in ("auth", "client", "models", "operations", "storage", "tools"):
    sys.modules.pop(_module_name, None)
for _module_name in tuple(sys.modules):
    if _module_name == "_common" or _module_name.startswith("_common."):
        sys.modules.pop(_module_name, None)


class _Operations:
    def __init__(self):
        self.client = type(
            "_Client", (), {"auth": type("_Auth", (), {"default_max_results": 37})()}
        )()

    def search(self, _cql, *, max_results):
        return {"effective_limit": max_results}

    def list_spaces(self, *, space_type, max_results):
        return {"effective_limit": max_results, "space_type": space_type}

    def list_children(self, _content_id, *, max_results):
        return {"effective_limit": max_results}

    def list_comments(self, _content_id, *, max_results):
        return {"effective_limit": max_results}


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("confluence_search", {"cql": "space = OPS"}),
        ("confluence_list_spaces", {}),
        ("confluence_list_children", {"content_id": "12345"}),
        ("confluence_list_comments", {"content_id": "12345"}),
    ],
)
def test_omitted_limit_reaches_each_read_tool_from_configured_default(
    monkeypatch, name, args
):
    """Would fail if invoke substitutes its own 25-item default."""
    monkeypatch.setattr(tools, "operations_from_configuration", lambda *_a, **_k: _Operations())

    result = tools.invoke(name, args, configuration=object())

    assert result["effective_limit"] == 37


@pytest.mark.parametrize(
    ("name", "args"),
    [
        ("confluence_search", {"cql": "space = OPS", "max_results": 12}),
        ("confluence_list_spaces", {"max_results": 12}),
        ("confluence_list_children", {"content_id": "12345", "max_results": 12}),
        ("confluence_list_comments", {"content_id": "12345", "max_results": 12}),
    ],
)
def test_explicit_limit_wins_over_configured_read_default(monkeypatch, name, args):
    """Would fail if the adapter ignored an explicit caller-supplied bound."""
    monkeypatch.setattr(tools, "operations_from_configuration", lambda *_a, **_k: _Operations())

    result = tools.invoke(name, args, configuration=object())

    assert result["effective_limit"] == 12
