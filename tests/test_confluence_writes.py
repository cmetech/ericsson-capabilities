"""Confluence write operations: intent gating and escaped Markdown."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-confluence"
for _module_name in ("models", "operations", "storage"):
    sys.modules.pop(_module_name, None)
for _module_name in tuple(sys.modules):
    if _module_name == "_common" or _module_name.startswith("_common."):
        sys.modules.pop(_module_name, None)
for _path in list(sys.path):
    if Path(_path).name in {"ericsson-confluence", "ericsson-gitlab"}:
        sys.path.remove(_path)
sys.path.insert(0, str(PLUGIN))

from models import ConfluenceError  # noqa: E402
from operations import ConfluenceOperations  # noqa: E402

# Keep this module's already-bound objects usable without leaking generic
# connector imports into later plugin test modules during full collection.
try:
    sys.path.remove(str(PLUGIN))
except ValueError:
    pass
for _module_name in ("operations", "models", "storage"):
    sys.modules.pop(_module_name, None)
for _module_name in tuple(sys.modules):
    if _module_name == "_common" or _module_name.startswith("_common."):
        sys.modules.pop(_module_name, None)


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


class TestCreatePage:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).create_page("OPS", "Title", "Body")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient([])
        result = ConfluenceOperations(client).create_page(
            "OPS", "Title", "Body", dry_run=True
        )
        assert result["dry_run"] is True and result["id"] is None
        assert client.calls == []

    def test_confirm_posts_the_page(self):
        client = FakeClient([{"id": "999", "title": "Title"}])
        result = ConfluenceOperations(client).create_page(
            "OPS", "Title", "Body", confirm=True
        )
        method, path, body = client.calls[0]
        assert (method, path) == ("POST", "/rest/api/content")
        assert body["type"] == "page"
        assert body["space"] == {"key": "OPS"}
        assert body["body"]["storage"]["representation"] == "storage"
        assert result["id"] == "999"

    def test_markdown_structure_is_converted(self):
        client = FakeClient([{"id": "1"}])
        ConfluenceOperations(client).create_page(
            "OPS", "T", "## Heading\n\n- one\n- two", confirm=True
        )
        value = client.calls[0][2]["body"]["storage"]["value"]
        assert "<h2>Heading</h2>" in value
        assert "<li>one</li>" in value

    def test_macro_markup_in_the_body_is_escaped(self):
        client = FakeClient([{"id": "1"}])
        ConfluenceOperations(client).create_page(
            "OPS", "T", '<ac:structured-macro ac:name="html"/>', confirm=True
        )
        value = client.calls[0][2]["body"]["storage"]["value"]
        assert "<ac:structured-macro" not in value
        assert "&lt;ac:structured-macro" in value

    def test_parent_becomes_an_ancestor(self):
        client = FakeClient([{"id": "1"}])
        ConfluenceOperations(client).create_page(
            "OPS", "T", "B", parent_id="12345", confirm=True
        )
        assert client.calls[0][2]["ancestors"] == [{"id": "12345"}]

    def test_ancestors_omitted_when_no_parent(self):
        client = FakeClient([{"id": "1"}])
        ConfluenceOperations(client).create_page("OPS", "T", "B", confirm=True)
        assert "ancestors" not in client.calls[0][2]

    def test_invalid_space_key_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError):
            ConfluenceOperations(client).create_page("../x", "T", "B", confirm=True)
        assert client.calls == []

    def test_blank_title_rejected(self):
        with pytest.raises(ConfluenceError):
            ConfluenceOperations(FakeClient([])).create_page(
                "OPS", "   ", "B", confirm=True
            )

    def test_response_without_an_id_raises(self):
        client = FakeClient([{"title": "T"}])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).create_page("OPS", "T", "B", confirm=True)
        assert excinfo.value.category == "invalid_remote_data"

    def test_ambiguous_create_is_not_reconciled(self):
        client = FakeClient([ConfluenceError("write_ambiguous")])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).create_page("OPS", "T", "B", confirm=True)
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1


CURRENT = {
    "id": "12345", "type": "page", "title": "Runbook",
    "version": {"number": 7},
    "body": {"storage": {"value": "<p>Old</p>"}},
}


class TestUpdatePage:
    def test_neither_flag_is_refused_without_any_request(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).update_page("12345", title="New")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_no_change_requested_is_rejected(self):
        client = FakeClient([])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).update_page("12345", confirm=True)
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_reads_current_version_then_increments_it(self):
        client = FakeClient([CURRENT, {"id": "12345", "version": {"number": 8}}])
        result = ConfluenceOperations(client).update_page(
            "12345", markdown="New body", confirm=True
        )
        assert client.calls[0][0] == "GET"
        method, path, sent = client.calls[1]
        assert (method, path) == ("PUT", "/rest/api/content/12345")
        assert sent["version"] == {"number": 8}
        assert result["version"] == 8

    def test_title_is_carried_over_when_only_body_changes(self):
        client = FakeClient([CURRENT, {"id": "12345", "version": {"number": 8}}])
        ConfluenceOperations(client).update_page(
            "12345", markdown="New body", confirm=True
        )
        assert client.calls[1][2]["title"] == "Runbook"

    def test_body_is_carried_over_when_only_title_changes(self):
        client = FakeClient([CURRENT, {"id": "12345", "version": {"number": 8}}])
        ConfluenceOperations(client).update_page(
            "12345", title="Renamed", confirm=True
        )
        assert client.calls[1][2]["body"]["storage"]["value"] == "<p>Old</p>"
        assert client.calls[1][2]["title"] == "Renamed"

    def test_markdown_structure_is_converted(self):
        client = FakeClient([CURRENT, {"id": "12345", "version": {"number": 8}}])
        ConfluenceOperations(client).update_page(
            "12345", markdown="# Title\n\n- item", confirm=True
        )
        value = client.calls[1][2]["body"]["storage"]["value"]
        assert "<h1>Title</h1>" in value and "<li>item</li>" in value

    def test_dry_run_reads_but_does_not_write(self):
        client = FakeClient([CURRENT])
        result = ConfluenceOperations(client).update_page(
            "12345", markdown="New", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["current_version"] == 7
        assert [c[0] for c in client.calls] == ["GET"]

    def test_conflict_propagates_with_its_own_category(self):
        client = FakeClient([CURRENT, ConfluenceError("conflict")])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).update_page(
                "12345", markdown="New", confirm=True
            )
        assert excinfo.value.category == "conflict"

    def test_missing_current_version_raises(self):
        client = FakeClient([{"id": "12345", "title": "T"}])
        with pytest.raises(ConfluenceError) as excinfo:
            ConfluenceOperations(client).update_page(
                "12345", markdown="New", confirm=True
            )
        assert excinfo.value.category == "invalid_remote_data"

    def test_macro_markup_is_escaped(self):
        client = FakeClient([CURRENT, {"id": "12345", "version": {"number": 8}}])
        ConfluenceOperations(client).update_page(
            "12345", markdown="<ac:structured-macro/>", confirm=True
        )
        value = client.calls[1][2]["body"]["storage"]["value"]
        assert "<ac:structured-macro" not in value
