import pytest

from ericsson_common.errors import ConnectorError
from ericsson_common.guardrails import require_explicit_intent


class TestRequireExplicitIntent:
    def test_confirm_executes(self):
        assert require_explicit_intent(
            dry_run=False, confirm=True, action="merge request"
        ) is True

    def test_dry_run_does_not_execute(self):
        assert require_explicit_intent(
            dry_run=True, confirm=False, action="merge request"
        ) is False

    def test_neither_is_refused(self):
        with pytest.raises(ConnectorError) as excinfo:
            require_explicit_intent(
                dry_run=False, confirm=False, action="merge request"
            )
        assert excinfo.value.category == "confirmation_required"

    def test_refusal_names_the_action(self):
        with pytest.raises(ConnectorError) as excinfo:
            require_explicit_intent(
                dry_run=False, confirm=False, action="delete page"
            )
        assert "delete page" in str(excinfo.value.detail)

    def test_both_is_refused_as_contradictory(self):
        with pytest.raises(ConnectorError) as excinfo:
            require_explicit_intent(
                dry_run=True, confirm=True, action="merge request"
            )
        assert excinfo.value.category == "invalid_input"

    def test_non_boolean_is_rejected(self):
        with pytest.raises(ConnectorError):
            require_explicit_intent(
                dry_run="yes", confirm=False, action="merge request"
            )
