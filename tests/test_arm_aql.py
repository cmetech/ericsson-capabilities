"""AQL preparation: bounds, permission fields, and shape validation."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from aql import prepare  # noqa: E402
from models import ArmError  # noqa: E402


def _is_arm_module(module: object) -> bool:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, (str, Path)):
        return False
    try:
        return Path(module_file).resolve().is_relative_to(PLUGIN.resolve())
    except (OSError, ValueError):
        return False


def _detach_arm_standalone_imports() -> None:
    """Keep AQL's standalone imports from contaminating sibling plugins."""
    for name in ("aql", "models"):
        module = sys.modules.get(name)
        if _is_arm_module(module):
            sys.modules.pop(name, None)
    while str(PLUGIN) in sys.path:
        sys.path.remove(str(PLUGIN))


_detach_arm_standalone_imports()


class TestShape:
    def test_a_domain_find_call_is_required(self):
        with pytest.raises(ArmError) as excinfo:
            prepare("SELECT * FROM artifacts", max_results=10)
        assert excinfo.value.category == "invalid_input"

    @pytest.mark.parametrize(
        "query",
        [
            'items.find({"repo":"x"})',
            'builds.find({"name":"y"})',
            'archive.entries.find({"archive.name":"z"})',
            '  items . find ( {"repo":"x"} )  ',
        ],
    )
    def test_recognised_domains_are_accepted(self, query):
        assert prepare(query, max_results=5)

    def test_empty_query_is_rejected(self):
        with pytest.raises(ArmError):
            prepare("   ", max_results=10)

    def test_oversized_query_is_rejected(self):
        with pytest.raises(ArmError):
            prepare('items.find({"repo":"' + "x" * 9000 + '"})', max_results=10)

    def test_non_string_is_rejected(self):
        with pytest.raises(ArmError):
            prepare(None, max_results=10)


class TestLimit:
    def test_the_connector_appends_its_own_limit(self):
        assert prepare('items.find({"repo":"x"})', max_results=25).endswith(
            ".limit(25)"
        )

    def test_a_caller_supplied_limit_is_refused(self):
        """AQL accepts exactly one limit, so the connector cannot append its
        own alongside a caller's. Refusing keeps the bound enforceable."""
        with pytest.raises(ArmError) as excinfo:
            prepare('items.find({"repo":"x"}).limit(5000)', max_results=25)
        assert "max_results" in (excinfo.value.remediation or "")

    def test_spacing_does_not_hide_a_limit(self):
        with pytest.raises(ArmError):
            prepare('items.find({"repo":"x"}) . limit ( 5000 )', max_results=25)

    def test_literal_limit_text_in_a_predicate_is_not_a_modifier(self):
        query = 'items.find({"name":{"$match":"literal .limit("}})'
        prepared = prepare(query, max_results=10)
        assert prepared == query + (
            '.include("repo","path","name","size","created","modified")'
            ".limit(10)"
        )

    def test_escaped_quote_and_backslash_do_not_end_a_predicate_string(self):
        query = (
            r'items.find({"name":{"$match":"escaped \" quote and \\ '
            r'literal .limit("}})'
        )
        prepared = prepare(query, max_results=10)
        assert prepared.endswith(".limit(10)")


class TestIncludeInjection:
    def test_a_default_include_is_added_when_absent(self):
        """Without .include() Artifactory returns roughly forty columns per
        row, which bloats the response by an order of magnitude."""
        prepared = prepare('items.find({"repo":"x"})', max_results=10)
        assert '.include(' in prepared
        for field in ("repo", "path", "name", "size", "created"):
            assert f'"{field}"' in prepared

    def test_required_permission_fields_are_injected_into_a_caller_include(self):
        """Artifactory: 'For permissions reasons AQL demands the following
        fields: repo, path and name.' Documented at
        cleanup_artifactory_releases.sh:174-178."""
        prepared = prepare(
            'items.find({"repo":"x"}).include("size","created")', max_results=10
        )
        for field in ("repo", "path", "name", "size", "created"):
            assert f'"{field}"' in prepared

    def test_an_already_complete_include_is_left_alone(self):
        query = 'items.find({"repo":"x"}).include("repo","path","name")'
        prepared = prepare(query, max_results=10)
        assert prepared.count(".include(") == 1
        assert prepared == query + ".limit(10)"

    def test_single_quoted_include_fields_are_recognised(self):
        prepared = prepare(
            "items.find({\"repo\":\"x\"}).include('repo','path','name')",
            max_results=10,
        )
        assert prepared.count(".include(") == 1

    def test_injection_does_not_duplicate_an_existing_field(self):
        prepared = prepare(
            'items.find({"repo":"x"}).include("repo")', max_results=10
        )
        assert prepared.count('"repo"') == 2, "repo appears in find and include only"

    def test_literal_include_text_in_a_predicate_does_not_block_injection(self):
        query = 'items.find({"name":{"$match":"literal .include(bar)"}})'
        prepared = prepare(query, max_results=10)
        assert prepared == query + (
            '.include("repo","path","name","size","created","modified")'
            ".limit(10)"
        )


class TestMaxResults:
    @pytest.mark.parametrize("max_results", [0, True, 101])
    def test_invalid_max_results_is_rejected(self, max_results):
        with pytest.raises(ArmError) as excinfo:
            prepare('items.find({"repo":"x"})', max_results=max_results)
        assert excinfo.value.category == "invalid_input"


class TestSortAndOffsetSurvive:
    def test_caller_sort_is_preserved(self):
        prepared = prepare(
            'items.find({"repo":"x"}).sort({"$desc":["created"]})', max_results=10
        )
        assert '.sort({"$desc":["created"]})' in prepared
        assert prepared.endswith(".limit(10)")

    def test_caller_offset_is_preserved(self):
        prepared = prepare('items.find({"repo":"x"}).offset(20)', max_results=10)
        assert ".offset(20)" in prepared
