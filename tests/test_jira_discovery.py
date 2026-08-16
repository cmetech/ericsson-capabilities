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

    @pytest.mark.parametrize("custom_only", [False, True])
    def test_non_boolean_custom_flag_raises(self, custom_only):
        client = FakeClient([[
            {"id": "f1", "name": "Field", "custom": "false"}
        ]])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).list_fields(custom_only=custom_only)
        assert excinfo.value.category == "invalid_remote_data"

    def test_entries_without_an_id_are_skipped(self):
        client = FakeClient([[
            {"name": "Nameless"},
            {"id": "ok", "name": "OK", "custom": False},
        ]])
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


class TestGetProject:
    def test_returns_metadata_needed_to_create_an_issue(self):
        client = FakeClient([{
            "key": "PROJ",
            "name": "Project",
            "id": "10000",
            "projectTypeKey": "software",
            "archived": False,
            "issueTypes": [
                {"id": "1", "name": "Bug", "subtask": False},
                {"id": "5", "name": "Sub-task", "subtask": True},
            ],
            "components": [{"id": "9", "name": "API"}],
            "versions": [{"id": "3", "name": "1.2.0", "released": False}],
        }])

        result = JiraOperations(client).get_project("PROJ")

        assert client.calls[0][:2] == ("GET", "project/PROJ")
        assert result["key"] == "PROJ"
        assert [item["name"] for item in result["issue_types"]] == ["Bug", "Sub-task"]
        assert result["issue_types"][1]["subtask"] is True
        assert [item["name"] for item in result["components"]] == ["API"]
        assert [item["name"] for item in result["versions"]] == ["1.2.0"]

    def test_missing_collections_default_to_empty(self):
        client = FakeClient([{"key": "PROJ", "name": "Project", "id": "1"}])

        result = JiraOperations(client).get_project("PROJ")

        assert result["issue_types"] == []
        assert result["components"] == []
        assert result["versions"] == []

    def test_invalid_key_rejected_without_a_request(self):
        client = FakeClient([])

        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).get_project("../admin")

        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_non_mapping_payload_raises(self):
        client = FakeClient([["not", "a", "mapping"]])

        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).get_project("PROJ")

        assert excinfo.value.category == "invalid_remote_data"


    def test_project_text_is_redacted(self):
        client = FakeClient([{
            "key": "PROJ-secret-token-value",
            "name": "Bearer secret-token-value",
            "id": "id-secret-token-value",
            "projectTypeKey": "type-secret-token-value",
            "issueTypes": [{
                "id": "issue-type-secret-token-value",
                "name": "issue-name-secret-token-value",
                "subtask": False,
            }],
            "components": [{
                "id": "component-secret-token-value",
                "name": "component-name-secret-token-value",
            }],
            "versions": [{
                "id": "version-secret-token-value",
                "name": "version-name-secret-token-value",
                "released": False,
            }],
        }])

        result = JiraOperations(client).get_project("PROJ")

        assert "secret-token-value" not in repr(result)

    @pytest.mark.parametrize(
        "payload",
        [
            {"archived": "false"},
            {"issueTypes": [{"id": "1", "name": "Bug", "subtask": "false"}]},
            {"versions": [{"id": "1", "name": "1.0", "released": "false"}]},
        ],
    )
    def test_malformed_remote_boolean_flags_fail_closed(self, payload):
        client = FakeClient([{"key": "PROJ", "name": "Project", "id": "1", **payload}])

        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).get_project("PROJ")

        assert excinfo.value.category == "invalid_remote_data"


class TestListTransitions:
    def test_returns_id_name_and_target_status(self):
        client = FakeClient([{
            "transitions": [
                {"id": "21", "name": "In Progress",
                 "to": {"name": "In Progress", "id": "3"}},
                {"id": "31", "name": "Done", "to": {"name": "Done", "id": "6"}},
            ]
        }])

        result = JiraOperations(client).list_transitions("ABC-1")

        assert client.calls[0][:2] == ("GET", "issue/ABC-1/transitions")
        assert result["items"] == [
            {"id": "21", "name": "In Progress", "to_status": "In Progress"},
            {"id": "31", "name": "Done", "to_status": "Done"},
        ]
        assert result["returned"] == 2
        assert result["total"] == 2
        assert result["truncated"] is False

    def test_empty_transitions_is_valid_not_an_error(self):
        """A closed issue legitimately offers no transitions."""
        client = FakeClient([{"transitions": []}])

        result = JiraOperations(client).list_transitions("ABC-1")

        assert result["items"] == []
        assert result["returned"] == 0

    @pytest.mark.parametrize("payload", [{"unexpected": True}, {"transitions": "no"}])
    def test_malformed_payload_raises(self, payload):
        client = FakeClient([payload])

        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).list_transitions("ABC-1")

        assert excinfo.value.category == "invalid_remote_data"

    @pytest.mark.parametrize(
        "key",
        ["not a key", "ABC-0", "1ABC-1", "ABC-000000000000000000000", "A" * 65 + "-1"],
    )
    def test_invalid_issue_key_rejected_without_a_request(self, key):
        client = FakeClient([])

        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).list_transitions(key)

        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_transition_without_an_id_is_skipped(self):
        client = FakeClient([{
            "transitions": [{"name": "Broken"}, {"id": "5", "name": "Fine"}]
        }])

        result = JiraOperations(client).list_transitions("ABC-1")

        assert [transition["id"] for transition in result["items"]] == ["5"]

    def test_transition_strings_including_ids_are_redacted(self):
        client = FakeClient([{
            "transitions": [{
                "id": "id-secret-token-value",
                "name": "name-secret-token-value",
                "to": {"name": "target-secret-token-value"},
            }]
        }])

        result = JiraOperations(client).list_transitions("ABC-1")

        assert "secret-token-value" not in repr(result)

    def test_transition_results_are_bounded_to_the_first_200_items(self):
        client = FakeClient([{
            "transitions": [
                {"id": str(index), "name": f"Transition {index}"}
                for index in range(201)
            ]
        }])

        result = JiraOperations(client).list_transitions("ABC-1")

        assert result["returned"] == 200
        assert result["total"] == 200
        assert result["items"][-1]["id"] == "199"
