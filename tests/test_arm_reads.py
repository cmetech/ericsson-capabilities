"""Bounded Artifactory reads."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from models import ArmError  # noqa: E402
from operations import ArmOperations  # noqa: E402

_ARM_COMMON_MODULES = tuple(
    name for name in sys.modules if name == "_common" or name.startswith("_common.")
)


def _detach_arm_standalone_imports() -> None:
    """Keep this standalone-plugin test from contaminating sibling plugins."""
    for name in ("auth", "client", "models", "operations", "tools"):
        module = sys.modules.get(name)
        module_file = getattr(module, "__file__", None)
        if module_file is not None and Path(module_file).parent == PLUGIN:
            sys.modules.pop(name, None)
    for name in tuple(sys.modules):
        if name == "_common" or name.startswith("_common."):
            sys.modules.pop(name, None)
    while str(PLUGIN) in sys.path:
        sys.path.remove(str(PLUGIN))


_detach_arm_standalone_imports()


def test_cross_order_cleanup_removes_arm_common_modules():
    """A later standalone connector must not resolve ARM's generic _common."""
    assert "_common" in _ARM_COMMON_MODULES
    assert not any(
        name == "_common" or name.startswith("_common.") for name in sys.modules
    )


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
