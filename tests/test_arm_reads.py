"""Bounded Artifactory reads."""

import sys
import types
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from models import ArmError  # noqa: E402
from operations import ArmOperations  # noqa: E402
import tools as arm_tools  # noqa: E402

def _is_arm_module(module: object) -> bool:
    module_file = getattr(module, "__file__", None)
    if not isinstance(module_file, (str, Path)):
        return False
    try:
        return Path(module_file).resolve().is_relative_to(PLUGIN.resolve())
    except (OSError, ValueError):
        return False


_ARM_COMMON_MODULES = {
    name: module
    for name, module in sys.modules.items()
    if (name == "_common" or name.startswith("_common."))
    and _is_arm_module(module)
}


def _detach_arm_standalone_imports() -> None:
    """Keep this standalone-plugin test from contaminating sibling plugins."""
    for name in ("aql", "auth", "client", "models", "operations", "tools"):
        module = sys.modules.get(name)
        if _is_arm_module(module):
            sys.modules.pop(name, None)
    for name in tuple(sys.modules):
        if (
            (name == "_common" or name.startswith("_common."))
            and _is_arm_module(sys.modules[name])
        ):
            sys.modules.pop(name, None)
    while str(PLUGIN) in sys.path:
        sys.path.remove(str(PLUGIN))


_detach_arm_standalone_imports()


def test_cross_order_cleanup_removes_arm_common_modules():
    """A later standalone connector must not resolve ARM's generic _common."""
    assert "_common" in _ARM_COMMON_MODULES
    assert all(
        sys.modules.get(name) is not module
        for name, module in _ARM_COMMON_MODULES.items()
    )


def test_cleanup_removes_arm_owned_generic_common_modules(monkeypatch):
    """Only ARM's own generic imports are safe for this test to evict."""
    module = types.ModuleType("_common")
    module.__file__ = str(PLUGIN / "_common" / "__init__.py")
    child = types.ModuleType("_common.envelope")
    child.__file__ = str(PLUGIN / "_common" / "envelope.py")
    monkeypatch.setitem(sys.modules, "_common", module)
    monkeypatch.setitem(sys.modules, "_common.envelope", child)
    aql = types.ModuleType("aql")
    aql.__file__ = str(PLUGIN / "aql.py")
    monkeypatch.setitem(sys.modules, "aql", aql)

    _detach_arm_standalone_imports()

    assert "_common" not in sys.modules
    assert "_common.envelope" not in sys.modules
    assert "aql" not in sys.modules


def test_cleanup_preserves_a_foreign_generic_common_module(monkeypatch):
    """An earlier connector's module cache is not owned by ARM's test."""
    module = types.ModuleType("_common")
    module.__file__ = "/tmp/foreign-plugin/_common/__init__.py"
    child = types.ModuleType("_common.envelope")
    child.__file__ = "/tmp/foreign-plugin/_common/envelope.py"
    monkeypatch.setitem(sys.modules, "_common", module)
    monkeypatch.setitem(sys.modules, "_common.envelope", child)
    aql = types.ModuleType("aql")
    aql.__file__ = "/tmp/foreign-plugin/aql.py"
    monkeypatch.setitem(sys.modules, "aql", aql)

    _detach_arm_standalone_imports()

    assert sys.modules["_common"] is module
    assert sys.modules["_common.envelope"] is child
    assert sys.modules["aql"] is aql


class FakeClient:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

        class _Auth:
            auth_header_value = "Bearer secret-token-value"
            token = "secret-token-value"
            default_max_results = 25
            max_deploy_bytes = 1024 * 1024
            deploy_root = None

        self.auth = _Auth()
        self.path_prefix = "/artifactory/"

    def _next(self):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get_json(self, path, *, params=None, deadline=None):
        self.calls.append(("GET", path, params))
        return self._next()

    def request_json(self, method, path, *, params=None, json_body=None,
                     deadline=None):
        self.calls.append((method, path, json_body))
        return self._next()

    def post_text(self, path, text, *, deadline=None):
        self.calls.append(("POST", path, text))
        return self._next()


class TestToolProfileDefaults:
    def test_omitted_list_and_search_limits_use_the_profile_default(self, monkeypatch):
        calls = []
        created = []

        class Operations:
            class Client:
                class Auth:
                    default_max_results = 7

                auth = Auth()

                def close(self):
                    calls.append(("close",))

            client = Client()

            def list_repositories(self, **kwargs):
                calls.append(("list", kwargs))
                return {"ok": True}

            def search_artifacts(self, query, **kwargs):
                calls.append(("search", query, kwargs))
                return {"ok": True}

        def build_operations(*_args, **_kwargs):
            created.append(object())
            return Operations()

        monkeypatch.setattr(arm_tools, "operations_from_configuration", build_operations)

        assert arm_tools.invoke("arm_list_repositories", {}, object()) == {"ok": True}
        assert arm_tools.invoke(
            "arm_search_artifacts", {"query": 'items.find({})'}, object()
        ) == {"ok": True}

        assert created and len(created) == 2
        assert calls == [
            ("list", {"repository_type": None, "package_type": None, "max_results": 7}),
            ("close",),
            ("search", 'items.find({})', {"max_results": 7}),
            ("close",),
        ]

    def test_explicit_list_and_search_limits_override_the_profile_default(self, monkeypatch):
        calls = []

        class Operations:
            class Client:
                class Auth:
                    default_max_results = 7

                auth = Auth()

                def close(self):
                    pass

            client = Client()

            def list_repositories(self, **kwargs):
                calls.append(("list", kwargs))
                return {"ok": True}

            def search_artifacts(self, query, **kwargs):
                calls.append(("search", query, kwargs))
                return {"ok": True}

        monkeypatch.setattr(
            arm_tools, "operations_from_configuration", lambda *_args, **_kwargs: Operations()
        )

        arm_tools.invoke("arm_list_repositories", {"max_results": 3}, object())
        arm_tools.invoke(
            "arm_search_artifacts",
            {"query": 'items.find({})', "max_results": 4},
            object(),
        )

        assert calls == [
            ("list", {"repository_type": None, "package_type": None, "max_results": 3}),
            ("search", 'items.find({})', {"max_results": 4}),
        ]


REPOSITORIES = [
    {"key": "generic-local", "type": "LOCAL", "packageType": "Generic",
     "description": "Release tarballs", "url": "https://artifactory.test/x"},
    {"key": "docker-remote", "type": "REMOTE", "packageType": "Docker",
     "description": "", "url": "https://artifactory.test/y"},
]

FILE_INFO = {
    "repo": "generic-local",
    "path": "/Infra/images/release-26.2.6/oscar.tar.gz",
    "created": "2026-07-01T10:00:00.000Z",
    "lastModified": "2026-07-01T10:05:00.000Z",
    "size": "5242880",
    "mimeType": "application/gzip",
    "downloadUri": "https://artifactory.test/artifactory/generic-local/Infra/images/release-26.2.6/oscar.tar.gz",
    "checksums": {"md5": "m" * 32, "sha1": "s" * 40, "sha256": "x" * 64},
}

FOLDER_INFO = {
    "repo": "generic-local",
    "path": "/Infra/images",
    "created": "2026-01-01T10:00:00.000Z",
    "children": [
        {"uri": "/release-26.2.5", "folder": True},
        {"uri": "/release-26.2.6", "folder": True},
        {"uri": "/oscar.tar.gz", "folder": False},
    ],
}


class TestListRepositories:
    def test_returns_bounded_identities(self):
        result = ArmOperations(FakeClient([REPOSITORIES])).list_repositories()
        assert [item["key"] for item in result["items"]] == [
            "generic-local", "docker-remote"
        ]
        assert result["items"][0]["package_type"] == "Generic"
        assert result["returned"] == 2

    def test_filters_are_sent_as_query_parameters(self):
        client = FakeClient([REPOSITORIES])
        ArmOperations(client).list_repositories(
            repository_type="local", package_type="generic"
        )
        _method, path, params = client.calls[0]
        assert path == "/artifactory/api/repositories"
        assert params == {"type": "local", "packageType": "generic"}

    def test_filters_are_omitted_when_unset(self):
        client = FakeClient([REPOSITORIES])
        ArmOperations(client).list_repositories()
        assert client.calls[0][2] == {}

    def test_total_is_reported_because_the_endpoint_is_unpaged(self):
        """/api/repositories returns every visible repository in one array,
        so the count is exact rather than a guess."""
        result = ArmOperations(FakeClient([REPOSITORIES])).list_repositories()
        assert result["total"] == 2
        assert result["truncated"] is False

    def test_truncation_is_reported(self):
        many = [dict(REPOSITORIES[0], key=f"repo-{i}") for i in range(40)]
        result = ArmOperations(FakeClient([many])).list_repositories(max_results=10)
        assert result["returned"] == 10
        assert result["total"] == 40
        assert result["truncated"] is True and result["hint"]

    def test_non_list_payload_raises(self):
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(FakeClient([{"error": "x"}])).list_repositories()
        assert excinfo.value.category == "invalid_remote_data"

    def test_bad_max_results_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).list_repositories(max_results=0)
        assert client.calls == []

    def test_every_exposed_remote_repository_string_is_redacted(self):
        """Remote fields can carry an echoed credential, not only the URL."""
        payload = [dict(
            REPOSITORIES[0],
            type="secret-token-value",
            packageType="secret-token-value",
            description="secret-token-value",
            url="secret-token-value",
        )]
        result = ArmOperations(FakeClient([payload])).list_repositories()
        assert "secret-token-value" not in repr(result)

    def test_one_character_token_is_redacted_from_remote_output(self):
        """Configured tokens are valid at one character and must not echo."""
        client = FakeClient([[
            dict(REPOSITORIES[0], description="beforeQafter")
        ]])
        client.auth.token = "Q"
        client.auth.auth_header_value = "Bearer Q"

        result = ArmOperations(client).list_repositories()

        assert "Q" not in result["items"][0]["description"]

    def test_redaction_happens_before_field_bounding(self):
        """A secret crossing a field cap must not leave its prefix behind."""
        client = FakeClient([[
            dict(REPOSITORIES[0], description=("a" * 510) + "WXYZtail")
        ]])
        client.auth.token = "WXYZ"
        client.auth.auth_header_value = "Bearer WXYZ"

        result = ArmOperations(client).list_repositories()
        description = result["items"][0]["description"]

        assert "WX" not in description
        assert len(description) <= 512


class TestArtifactInfo:
    def test_file_returns_checksums_and_size(self):
        result = ArmOperations(FakeClient([FILE_INFO])).artifact_info(
            "generic-local", "Infra/images/release-26.2.6/oscar.tar.gz"
        )
        assert result["kind"] == "file"
        assert result["size"] == 5242880
        assert result["checksums"]["sha256"] == "x" * 64
        assert result["download_uri"].endswith("oscar.tar.gz")

    def test_size_is_an_integer_even_though_artifactory_sends_a_string(self):
        """Artifactory returns size as a JSON string. Leaving it a string
        makes every downstream comparison silently wrong."""
        result = ArmOperations(FakeClient([FILE_INFO])).artifact_info(
            "generic-local", "Infra/images/oscar.tar.gz"
        )
        assert isinstance(result["size"], int)

    def test_folder_returns_children(self):
        result = ArmOperations(FakeClient([FOLDER_INFO])).artifact_info(
            "generic-local", "Infra/images"
        )
        assert result["kind"] == "folder"
        assert result["size"] is None
        assert [child["name"] for child in result["children"]] == [
            "release-26.2.5", "release-26.2.6", "oscar.tar.gz"
        ]
        assert result["children"][0]["folder"] is True
        assert result["children"][2]["folder"] is False

    def test_children_are_bounded(self):
        payload = dict(
            FOLDER_INFO,
            children=[{"uri": f"/f{i}", "folder": False} for i in range(300)],
        )
        result = ArmOperations(FakeClient([payload])).artifact_info(
            "generic-local", "Infra/images", max_children=10
        )
        assert len(result["children"]) == 10
        assert result["children_truncated"] is True

    def test_storage_path_is_built_correctly(self):
        client = FakeClient([FILE_INFO])
        ArmOperations(client).artifact_info("generic-local", "Infra/images/a.tgz")
        _method, path, _params = client.calls[0]
        assert path == "/artifactory/api/storage/generic-local/Infra/images/a.tgz"

    def test_a_leading_slash_on_the_path_is_tolerated(self):
        client = FakeClient([FILE_INFO])
        ArmOperations(client).artifact_info("generic-local", "/Infra/images/a.tgz")
        assert client.calls[0][1] == (
            "/artifactory/api/storage/generic-local/Infra/images/a.tgz"
        )

    @pytest.mark.parametrize(
        "bad_repo", ["", "../etc", "a/b", "repo?x=1", "a" * 300]
    )
    def test_hostile_repository_names_rejected_without_a_request(self, bad_repo):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).artifact_info(bad_repo, "a.tgz")
        assert client.calls == []

    @pytest.mark.parametrize(
        "bad_path",
        ["../../etc/passwd", "Infra/../../secrets", "a\x00b", "a" * 5000],
    )
    def test_traversal_paths_rejected_without_a_request(self, bad_path):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).artifact_info("generic-local", bad_path)
        assert client.calls == []

    def test_the_token_is_redacted_from_remote_text(self):
        payload = dict(FILE_INFO, downloadUri="https://x/?t=secret-token-value")
        result = ArmOperations(FakeClient([payload])).artifact_info(
            "generic-local", "a.tgz"
        )
        assert "secret-token-value" not in result["download_uri"]

    def test_every_exposed_remote_artifact_string_is_redacted(self):
        """Metadata, checksums and timestamps are all remote output fields."""
        payload = dict(
            FILE_INFO,
            repo="secret-token-value",
            path="secret-token-value",
            created="secret-token-value",
            lastModified="secret-token-value",
            mimeType="secret-token-value",
            downloadUri="secret-token-value",
            checksums={
                "md5": "secret-token-value",
                "sha1": "secret-token-value",
                "sha256": "secret-token-value",
            },
        )
        result = ArmOperations(FakeClient([payload])).artifact_info(
            "generic-local", "a.tgz"
        )
        assert "secret-token-value" not in repr(result)


PROPERTIES = {
    "uri": "https://artifactory.test/artifactory/api/storage/generic-local/a.tgz",
    "properties": {
        "build.number": ["1284"],
        "build.name": ["oscar-release"],
        "vcs.revision": ["9f2c1ab"],
        "qa.approved": ["yes", "by-ci"],
    },
}


AQL_RESPONSE = {
    "results": [
        {"repo": "generic-local", "path": "Infra/images/release-26.2.6",
         "name": "oscar.tar.gz", "size": "5242880",
         "created": "2026-07-01T10:00:00.000Z"},
        {"repo": "generic-local", "path": "Infra/images/release-26.2.6",
         "name": "oscar.manifest", "size": "512",
         "created": "2026-07-01T10:01:00.000Z"},
    ],
    "range": {"start_pos": 0, "end_pos": 2, "total": 2},
}


class TestSearchArtifacts:
    def test_posts_prepared_aql_as_text(self):
        client = FakeClient([AQL_RESPONSE])
        ArmOperations(client).search_artifacts(
            'items.find({"repo":"generic-local"})', max_results=25
        )
        method, path, body = client.calls[0]
        assert (method, path) == ("POST", "/artifactory/api/search/aql")
        assert body.endswith(".limit(25)")
        assert ".include(" in body

    def test_returns_bounded_rows_with_a_full_path(self):
        result = ArmOperations(FakeClient([AQL_RESPONSE])).search_artifacts(
            'items.find({"repo":"generic-local"})'
        )
        first = result["items"][0]
        assert first["name"] == "oscar.tar.gz"
        assert first["full_path"] == (
            "generic-local/Infra/images/release-26.2.6/oscar.tar.gz"
        )
        assert first["size"] == 5242880

    def test_total_is_omitted_because_aql_reports_the_limited_set(self):
        """range.total counts the returned rows, not the matching ones.
        Reporting it as total would be a wrong number, and the envelope's
        contract is that a wrong number is worse than none."""
        result = ArmOperations(FakeClient([AQL_RESPONSE])).search_artifacts(
            'items.find({"repo":"generic-local"})'
        )
        assert "total" not in result

    def test_a_full_page_is_reported_as_truncated(self):
        rows = [dict(AQL_RESPONSE["results"][0], name=f"f{i}.tgz") for i in range(10)]
        result = ArmOperations(FakeClient([{"results": rows}])).search_artifacts(
            'items.find({"repo":"x"})', max_results=10
        )
        assert result["truncated"] is True and result["hint"]

    def test_a_short_page_is_not_truncated(self):
        result = ArmOperations(FakeClient([AQL_RESPONSE])).search_artifacts(
            'items.find({"repo":"x"})', max_results=25
        )
        assert result["truncated"] is False

    def test_a_full_raw_page_is_truncated_even_with_a_malformed_row(self):
        rows = [dict(AQL_RESPONSE["results"][0], name=f"f{i}.tgz") for i in range(9)]
        result = ArmOperations(FakeClient([{"results": [*rows, "malformed"]}])).search_artifacts(
            'items.find({"repo":"x"})', max_results=10
        )
        assert result["returned"] == 9
        assert result["truncated"] is True and result["hint"]

    def test_missing_results_key_raises(self):
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(FakeClient([{"range": {}}])).search_artifacts(
                'items.find({"repo":"x"})'
            )
        assert excinfo.value.category == "invalid_remote_data"

    def test_an_invalid_query_is_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).search_artifacts("DROP TABLE artifacts")
        assert client.calls == []


class TestGetProperties:
    def test_returns_every_property_with_values_as_lists(self):
        """Artifactory properties are multi-valued. Flattening the single
        case to a bare string would make the shape depend on the data."""
        result = ArmOperations(FakeClient([PROPERTIES])).get_properties(
            "generic-local", "a.tgz"
        )
        assert result["properties"]["build.number"] == ["1284"]
        assert result["properties"]["qa.approved"] == ["yes", "by-ci"]

    def test_requests_the_properties_view(self):
        client = FakeClient([PROPERTIES])
        ArmOperations(client).get_properties("generic-local", "a.tgz")
        _method, path, params = client.calls[0]
        assert path == "/artifactory/api/storage/generic-local/a.tgz"
        assert params == {"properties": ""}

    def test_key_filter_is_comma_joined(self):
        """Matches super-cli's arm.joinComma helper."""
        client = FakeClient([PROPERTIES])
        ArmOperations(client).get_properties(
            "generic-local", "a.tgz", keys=["build.number", "vcs.revision"]
        )
        assert client.calls[0][2] == {"properties": "build.number,vcs.revision"}

    def test_empty_key_list_is_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).get_properties("generic-local", "a.tgz", keys=[])
        assert client.calls == []

    def test_a_key_containing_a_comma_is_rejected(self):
        """A comma inside a key would silently become two keys."""
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).get_properties(
                "generic-local", "a.tgz", keys=["a,b"]
            )
        assert client.calls == []

    def test_a_key_containing_a_semicolon_is_rejected(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).get_properties(
                "generic-local", "a.tgz", keys=["a;b"]
            )
        assert client.calls == []

    def test_missing_properties_key_yields_an_empty_map_not_an_error(self):
        """An artefact with no properties is normal, not a failure."""
        result = ArmOperations(FakeClient([{"uri": "x"}])).get_properties(
            "generic-local", "a.tgz"
        )
        assert result["properties"] == {}

    def test_property_count_is_reported(self):
        result = ArmOperations(FakeClient([PROPERTIES])).get_properties(
            "generic-local", "a.tgz"
        )
        assert result["count"] == 4

    def test_values_are_redacted_and_bounded(self):
        payload = {"properties": {"leak": ["secret-token-value"], "big": ["z" * 5000]}}
        result = ArmOperations(FakeClient([payload])).get_properties(
            "generic-local", "a.tgz"
        )
        assert "secret-token-value" not in result["properties"]["leak"][0]
        assert len(result["properties"]["big"][0]) <= 1024

    def test_every_property_name_and_value_redacts_short_tokens(self):
        client = FakeClient([{"properties": {"beforeQafter": ["beforeQafter"]}}])
        client.auth.token = "Q"
        client.auth.auth_header_value = "Bearer Q"

        result = ArmOperations(client).get_properties("generic-local", "a.tgz")

        property_name, values = next(iter(result["properties"].items()))
        assert "Q" not in property_name
        assert "Q" not in values[0]

    def test_property_names_and_values_redact_before_bounding(self):
        client = FakeClient([{
            "properties": {
                ("a" * 254) + "WXYZtail": [("z" * 1022) + "WXYZtail"]
            }
        }])
        client.auth.token = "WXYZ"
        client.auth.auth_header_value = "Bearer WXYZ"

        result = ArmOperations(client).get_properties("generic-local", "a.tgz")

        property_name, values = next(iter(result["properties"].items()))
        assert "WX" not in property_name
        assert len(property_name) <= 255
        assert "WX" not in values[0]
        assert len(values[0]) <= 1024

    def test_non_mapping_properties_raises(self):
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(FakeClient([{"properties": ["not", "a", "map"]}])).get_properties(
                "generic-local", "a.tgz"
            )
        assert excinfo.value.category == "invalid_remote_data"
