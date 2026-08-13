from __future__ import annotations

import json
import sys
from pathlib import Path


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "jira"
sys.path.insert(0, str(PLUGIN))

from operations import adf_to_text, extract_gitlab_urls  # noqa: E402


def test_rich_adf_preserves_paragraph_link_mention_list_code_and_table():
    document = json.loads((FIXTURES / "adf-rich.json").read_text(encoding="utf-8"))

    assert adf_to_text(document) == (
        "See [the runbook](https://docs.example.test/runbook) and @Alice\n"
        "- first\n"
        "- second\n"
        "```\nraise RuntimeError()\n```\n"
        "Key | Value\n"
        "mode | safe"
    )


def test_plain_server_text_is_preserved_and_non_text_scalars_are_safe():
    assert adf_to_text("plain Server/DC description") == "plain Server/DC description"
    assert adf_to_text(None) == ""
    assert adf_to_text(42) == ""


def test_unknown_nodes_recurse_without_projecting_arbitrary_attributes():
    document = {
        "type": "futureWidget",
        "attrs": {"secret": "must-not-project", "text": "must-not-project"},
        "content": [{"type": "text", "text": "known child"}],
    }

    assert adf_to_text(document) == "known child"


def test_malformed_and_excessively_deep_adf_is_bounded_not_recursive_failure():
    malformed = {"type": "doc", "content": "not-a-list", "secret": "hidden"}
    assert adf_to_text(malformed) == ""

    node = {"type": "text", "text": "too deep"}
    for _ in range(40):
        node = {"type": "panel", "content": [node]}
    assert adf_to_text(node) == ""


def test_gitlab_urls_are_cleaned_and_deduplicated_in_first_seen_order():
    text = (
        "See https://gitlab.example.test/g/repo). then "
        "https://gitlab.example.test/g/repo, and "
        "https://example.test/path/gitlab/project;"
    )

    assert extract_gitlab_urls(text) == [
        "https://gitlab.example.test/g/repo",
        "https://example.test/path/gitlab/project",
    ]
