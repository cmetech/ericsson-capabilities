from ericsson_common.envelope import UNTRUSTED_CONTENT_WARNING, result_envelope


class TestEnvelope:
    def test_reports_returned_count(self):
        env = result_envelope([1, 2, 3])
        assert env["items"] == [1, 2, 3]
        assert env["returned"] == 3

    def test_untruncated_result_is_complete(self):
        env = result_envelope([1], total=1)
        assert env["truncated"] is False
        assert env["total"] == 1

    def test_truncated_result_carries_total_and_hint(self):
        env = result_envelope(
            [1, 2], total=57, truncated=True, hint="Increase max_results."
        )
        assert env["truncated"] is True
        assert env["total"] == 57
        assert env["hint"] == "Increase max_results."

    def test_total_is_omitted_when_unknown(self):
        """An unknown total must be absent, not zero -- zero is a lie."""
        assert "total" not in result_envelope([1, 2], truncated=True)

    def test_hint_is_omitted_when_absent(self):
        assert "hint" not in result_envelope([1])

    def test_empty_result_is_well_formed(self):
        env = result_envelope([])
        assert env["items"] == []
        assert env["returned"] == 0
        assert env["truncated"] is False


class TestUntrustedContent:
    def test_warning_absent_by_default(self):
        assert "content_warning" not in result_envelope([1])

    def test_warning_present_when_requested(self):
        env = result_envelope([{"body": "..."}], untrusted=True)
        assert env["content_warning"] == UNTRUSTED_CONTENT_WARNING

    def test_warning_text_tells_the_model_not_to_obey_content(self):
        lowered = UNTRUSTED_CONTENT_WARNING.lower()
        assert "untrusted" in lowered
        assert "do not follow" in lowered
