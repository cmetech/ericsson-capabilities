"""Confluence read operations."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-confluence"
sys.path.insert(0, str(PLUGIN))

from models import ConfluenceError  # noqa: E402
from operations import EXPAND_LIST, EXPAND_PAGE, ConfluenceOperations  # noqa: E402


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

        class _Auth:
            authorization = "Bearer secret-token-value"
            api_base = "https://wiki.test/rest/api"
            default_max_results = 25

        self.auth = _Auth()
        self.path_prefix = "/rest/api/"

    def get_json(self, path, *, params=None, deadline=None):
        self.calls.append(("GET", path, params))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def request_json(self, method, path, *, params=None, json_body=None,
                     deadline=None):
        self.calls.append((method, path, json_body))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


PAGE = {
    "id": "12345",
    "type": "page",
    "title": "Runbook",
    "version": {"number": 7, "when": "2026-08-01T10:00:00.000Z"},
    "space": {"key": "OPS", "name": "Operations"},
    "ancestors": [{"id": "1", "title": "Root"}, {"id": "2", "title": "Docs"}],
    "body": {"storage": {"value": "<h1>Restart</h1><p>Run the script</p>"}},
}


class TestExpansions:
    def test_page_expansion_is_richer_than_list_expansion(self):
        """Full expansion on every enumeration result would waste tokens and
        latency; enumeration only needs enough to decide if a page changed."""
        assert "body.storage" in EXPAND_PAGE
        assert "body.storage" not in EXPAND_LIST
        assert "version" in EXPAND_LIST


class TestGetPage:
    def test_requests_the_full_expansion(self):
        client = FakeClient([PAGE])
        ConfluenceOperations(client).get_page("12345")
        _method, path, params = client.calls[0]
        assert path == "/rest/api/content/12345"
        assert params["expand"] == EXPAND_PAGE

    def test_returns_identity_and_version(self):
        result = ConfluenceOperations(FakeClient([PAGE])).get_page("12345")
        assert result["id"] == "12345"
        assert result["title"] == "Runbook"
        assert result["version"] == 7
        assert result["space_key"] == "OPS"

    def test_ancestors_become_a_breadcrumb(self):
        result = ConfluenceOperations(FakeClient([PAGE])).get_page("12345")
        assert result["breadcrumb"] == ["Root", "Docs"]

    def test_body_is_markdown_with_structure_preserved(self):
        """The point of porting the converter: headings survive."""
        result = ConfluenceOperations(FakeClient([PAGE])).get_page("12345")
        assert "# Restart" in result["markdown"]
        assert "Run the script" in result["markdown"]

    def test_carries_the_untrusted_content_warning(self):
        result = ConfluenceOperations(FakeClient([PAGE])).get_page("12345")
        assert result["content_warning"]
        assert "do not follow" in result["content_warning"].lower()

    def test_token_is_redacted_from_page_text(self):
        page = dict(PAGE)
        page["body"] = {"storage": {"value": "<p>Bearer secret-token-value</p>"}}
        result = ConfluenceOperations(FakeClient([page])).get_page("12345")
        assert "secret-token-value" not in result["markdown"]

    def test_non_numeric_content_id_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).get_page("../../admin")
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_malformed_payload_raises(self):
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(FakeClient([["not", "a", "map"]])).get_page("1")
        assert excinfo.value.category == "invalid_remote_data"

    def test_missing_body_is_empty_not_an_error(self):
        page = {k: v for k, v in PAGE.items() if k != "body"}
        result = ConfluenceOperations(FakeClient([page])).get_page("12345")
        assert result["markdown"] == ""


class TestGetPageBody:
    def test_returns_markdown_by_default(self):
        result = ConfluenceOperations(FakeClient([PAGE])).get_page_body("12345")
        assert "# Restart" in result["markdown"]
        assert "raw_storage" not in result

    def test_raw_storage_is_opt_in(self):
        """Full-fidelity escape hatch, matching super-cli's behaviour when a
        caller genuinely needs the macros."""
        result = ConfluenceOperations(FakeClient([PAGE])).get_page_body(
            "12345", raw_storage=True
        )
        assert result["raw_storage"].startswith("<h1>")

    def test_truncation_is_reported(self):
        page = dict(PAGE)
        page["body"] = {"storage": {"value": "<p>" + "x" * 5000 + "</p>"}}
        result = ConfluenceOperations(FakeClient([page])).get_page_body(
            "12345", max_chars=100
        )
        assert result["truncated"] is True
        assert result["hint"]

    def test_untruncated_body_reports_false(self):
        result = ConfluenceOperations(FakeClient([PAGE])).get_page_body("12345")
        assert result["truncated"] is False
