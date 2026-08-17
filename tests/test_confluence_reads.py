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


SEARCH_PAGE = {
    "results": [
        {"id": "1", "title": "First", "type": "page", "space": {"key": "OPS"}},
        {"id": "2", "title": "Second", "type": "blogpost", "space": {"key": "DEV"}},
    ],
    "start": 0, "limit": 25, "size": 2, "totalSize": 2,
}


class TestSearch:
    def test_sends_cql_paging_and_light_expansion(self):
        client = FakeClient([SEARCH_PAGE])
        ConfluenceOperations(client).search("space = OPS", max_results=25)
        _method, path, params = client.calls[0]
        assert path == "/rest/api/content/search"
        assert params["cql"] == "space = OPS"
        assert params["expand"] == EXPAND_LIST
        assert params["limit"] == 25 and params["start"] == 0

    def test_returns_bounded_identities(self):
        result = ConfluenceOperations(FakeClient([SEARCH_PAGE])).search("x")
        assert [item["id"] for item in result["items"]] == ["1", "2"]
        assert result["items"][0]["space_key"] == "OPS"
        assert result["returned"] == 2

    def test_total_is_reported_when_known(self):
        result = ConfluenceOperations(FakeClient([SEARCH_PAGE])).search("x")
        assert result["total"] == 2
        assert result["truncated"] is False

    def test_total_is_omitted_when_absent(self):
        """Confluence Server does not always return totalSize. A wrong number
        is worse than none."""
        page = {k: v for k, v in SEARCH_PAGE.items() if k != "totalSize"}
        assert "total" not in ConfluenceOperations(FakeClient([page])).search("x")

    def test_paginates_until_max_results(self):
        first = {"results": [{"id": str(i), "title": f"P{i}", "type": "page"}
                             for i in range(25)],
                 "start": 0, "limit": 25, "size": 25, "totalSize": 30}
        second = {"results": [{"id": str(i), "title": f"P{i}", "type": "page"}
                              for i in range(25, 30)],
                  "start": 25, "limit": 25, "size": 5, "totalSize": 30}
        client = FakeClient([first, second])
        result = ConfluenceOperations(client).search("x", max_results=30)
        assert result["returned"] == 30
        assert client.calls[1][2]["start"] == 25

    def test_empty_page_stops_without_repeating_request(self):
        first = {"results": [{"id": str(i), "title": f"P{i}", "type": "page"}
                             for i in range(25)],
                 "start": 0, "limit": 25, "size": 25, "totalSize": 50}
        empty = {"results": [], "start": 25, "limit": 25, "size": 0, "totalSize": 50}
        client = FakeClient([first, empty])
        result = ConfluenceOperations(client).search("x", max_results=100)
        assert result["returned"] == 25
        assert result["truncated"] is True
        assert [call[2]["start"] for call in client.calls] == [0, 25]

    def test_unknown_total_full_pages_stop_at_max_pages(self):
        page = {"results": [{"id": str(i), "title": f"P{i}", "type": "page"}
                            for i in range(100)],
                "start": 0, "limit": 100, "size": 100}
        client = FakeClient([page, dict(page)])
        rows, total, truncated = ConfluenceOperations(client, max_pages=2)._paged(
            "/rest/api/content/search", {}, 250
        )
        assert len(rows) == 200
        assert total is None
        assert truncated is True
        assert [call[2]["start"] for call in client.calls] == [0, 100]

    def test_stops_at_max_results_and_reports_truncation(self):
        page = {"results": [{"id": str(i), "title": f"P{i}", "type": "page"}
                            for i in range(25)],
                "start": 0, "limit": 25, "size": 25, "totalSize": 500}
        result = ConfluenceOperations(FakeClient([page])).search("x", max_results=10)
        assert result["returned"] == 10
        assert result["truncated"] is True and result["hint"]

    def test_results_carry_the_untrusted_content_warning(self):
        assert ConfluenceOperations(FakeClient([SEARCH_PAGE])).search("x")[
            "content_warning"
        ]

    def test_empty_cql_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError):
            ConfluenceOperations(client).search("   ")
        assert client.calls == []

    def test_oversized_cql_rejected(self):
        with pytest.raises(ConfluenceError):
            ConfluenceOperations(FakeClient([])).search("x" * 5000)

    def test_missing_results_key_raises(self):
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(FakeClient([{"start": 0}])).search("x")
        assert excinfo.value.category == "invalid_remote_data"


class TestListSpaces:
    def test_lists_key_and_name(self):
        client = FakeClient([{
            "results": [
                {"key": "OPS", "name": "Operations", "type": "global"},
                {"key": "~alice", "name": "Alice", "type": "personal"},
            ],
            "start": 0, "limit": 25, "size": 2,
        }])
        result = ConfluenceOperations(client).list_spaces()
        assert client.calls[0][1] == "/rest/api/space"
        assert [s["key"] for s in result["items"]] == ["OPS", "~alice"]

    def test_type_filter_is_forwarded(self):
        client = FakeClient([{"results": [], "start": 0, "limit": 25, "size": 0}])
        ConfluenceOperations(client).list_spaces(space_type="global")
        assert client.calls[0][2]["type"] == "global"

    def test_invalid_type_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError):
            ConfluenceOperations(client).list_spaces(space_type="nonsense")
        assert client.calls == []

    def test_empty_space_list_is_valid(self):
        client = FakeClient([{"results": [], "start": 0, "limit": 25, "size": 0}])
        result = ConfluenceOperations(client).list_spaces()
        assert result["items"] == [] and result["returned"] == 0


class TestListChildren:
    def test_lists_child_pages(self):
        client = FakeClient([{
            "results": [{"id": "9", "title": "Child", "type": "page"}],
            "start": 0, "limit": 25, "size": 1,
        }])
        result = ConfluenceOperations(client).list_children("12345")
        assert client.calls[0][1] == "/rest/api/content/12345/child/page"
        assert result["items"][0]["id"] == "9"

    def test_invalid_parent_id_rejected(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError):
            ConfluenceOperations(client).list_children("not-an-id")
        assert client.calls == []

    def test_children_carry_the_untrusted_warning(self):
        client = FakeClient([{
            "results": [{"id": "9", "title": "Child", "type": "page"}],
            "start": 0, "limit": 25, "size": 1,
        }])
        assert ConfluenceOperations(client).list_children("1")["content_warning"]
