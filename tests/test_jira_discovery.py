"""Jira discovery tools: fields, project metadata, transitions, users."""

import pytest

from jira_test_support import models, operations


JiraError = models.JiraError
JiraOperations = operations.JiraOperations


class FakeClient:
    """Records calls and replays scripted rest_json results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

        class _Auth:
            authorization = "Bearer secret-token-value"
            rest_api_version = "auto"

        self.auth = _Auth()

    def rest_json(self, method, resource, **kwargs):
        self.calls.append((method, resource, kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TestListFields:
    def test_returns_id_name_and_custom_flag(self):
        client = FakeClient([[
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10234", "name": "Story Points", "custom": True},
        ]])
        result = JiraOperations(client).list_fields()
        assert client.calls[0][:2] == ("GET", "field")
        assert result["items"] == [
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10234", "name": "Story Points", "custom": True},
        ]
        assert result["returned"] == 2

    def test_custom_only_filters(self):
        client = FakeClient([[
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10234", "name": "Story Points", "custom": True},
        ]])
        result = JiraOperations(client).list_fields(custom_only=True)
        assert [f["id"] for f in result["items"]] == ["customfield_10234"]

    def test_truncates_and_reports_total(self):
        client = FakeClient([[
            {"id": f"f{i}", "name": f"Field {i}", "custom": False}
            for i in range(10)
        ]])
        result = JiraOperations(client).list_fields(max_results=3)
        assert result["returned"] == 3
        assert result["total"] == 10
        assert result["truncated"] is True
        assert result["hint"]

    def test_malformed_payload_raises(self):
        client = FakeClient([{"not": "a list"}])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).list_fields()
        assert excinfo.value.category == "invalid_remote_data"

    def test_entries_without_an_id_are_skipped(self):
        client = FakeClient([[{"name": "Nameless"}, {"id": "ok", "name": "OK"}]])
        result = JiraOperations(client).list_fields()
        assert [f["id"] for f in result["items"]] == ["ok"]

    def test_bad_max_results_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).list_fields(max_results=0)

    def test_field_names_are_redacted(self):
        """Field names are remote text; a token echoed into one must not
        reach the model."""
        client = FakeClient([[
            {"id": "f1", "name": "Bearer secret-token-value", "custom": False}
        ]])
        result = JiraOperations(client).list_fields()
        assert "secret-token-value" not in result["items"][0]["name"]
