from ericsson_common.errors import (
    RETRYABLE_STATUSES,
    ConnectorError,
    category_for_status,
    remediation_for,
)


class TestCategoryForStatus:
    def test_known_statuses(self):
        assert category_for_status(400) == "invalid_input"
        assert category_for_status(401) == "authentication"
        assert category_for_status(403) == "permission"
        assert category_for_status(404) == "not_found"
        assert category_for_status(409) == "conflict"
        assert category_for_status(429) == "rate_limited"

    def test_server_errors_are_transient(self):
        assert category_for_status(500) == "transient"
        assert category_for_status(503) == "transient"

    def test_unmapped_client_error_is_invalid_remote_data(self):
        assert category_for_status(418) == "invalid_remote_data"

    def test_retryable_set(self):
        assert RETRYABLE_STATUSES == frozenset({429, 502, 503, 504})


class TestRemediation:
    def test_authentication_names_the_field_to_fix(self):
        text = remediation_for("authentication", "jira")
        assert text and "jira" in text.lower()
        assert "token" in text.lower()

    def test_permission_is_distinct_from_authentication(self):
        assert remediation_for("permission", "gitlab") != remediation_for(
            "authentication", "gitlab"
        )

    def test_unknown_category_has_no_remediation(self):
        assert remediation_for("transient", "jira") is None


class TestConnectorError:
    def test_carries_category_and_remediation(self):
        err = ConnectorError("authentication", service="jira")
        assert err.category == "authentication"
        assert err.service == "jira"
        assert err.remediation and "jira" in err.remediation.lower()

    def test_str_is_the_category_for_backward_compatibility(self):
        """Existing plugin code and tests compare str(error) to a category."""
        assert str(ConnectorError("not_found")) == "not_found"

    def test_remediation_is_none_when_service_unknown(self):
        assert ConnectorError("authentication").remediation is None
