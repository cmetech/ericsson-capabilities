from __future__ import annotations

import base64
import importlib
import sys
from pathlib import Path

import httpx
import pytest
import respx


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
ORIGIN = "https://gitlab.example.test"


def _modules():
    assert PLUGIN.is_dir(), "Task 8 GitLab plugin production surface is missing"
    if str(PLUGIN) not in sys.path:
        sys.path.insert(0, str(PLUGIN))
    return (
        importlib.import_module("auth"),
        importlib.import_module("client"),
        importlib.import_module("models"),
        importlib.import_module("operations"),
    )


def _tools_module():
    tools_name = "_ericsson_gitlab_standalone_tools"
    if tools_name not in sys.modules:
        tools_spec = importlib.util.spec_from_file_location(
            tools_name,
            PLUGIN / "tools.py",
        )
        assert tools_spec is not None and tools_spec.loader is not None
        tools_module = importlib.util.module_from_spec(tools_spec)
        sys.modules[tools_name] = tools_module
        tools_spec.loader.exec_module(tools_module)
    return sys.modules[tools_name]


def _operations(**client_options):
    auth, client, _models, operations = _modules()
    credentials = auth.GitLabAuth(
        origin=ORIGIN,
        pat="secret-token",
        certificate_pair=None,
    )
    return operations.GitLabOperations(client.GitLabClient(credentials, **client_options))


def _project_json(default_branch="release/2026"):
    return {
        "id": 42,
        "name": "repo",
        "path_with_namespace": "division/platform/team/repo",
        "default_branch": default_branch,
        "web_url": f"{ORIGIN}/division/platform/team/repo",
        "namespace": {"kind": "group", "full_path": "division/platform/team"},
    }


@pytest.mark.parametrize(
    ("reference", "endpoint"),
    [
        ("division/platform/team/repo", "division%2Fplatform%2Fteam%2Frepo"),
        ("https://gitlab.example.test/division/platform/team/repo.git", "division%2Fplatform%2Fteam%2Frepo"),
        ("42", "42"),
    ],
)
def test_resolve_project_accepts_nested_slug_canonical_url_and_numeric_id(reference, endpoint):
    # GL-ID-01/02 legacy: gitlab_project_resolver.py:GitLabProjectResolver._parse_gitlab_url/resolve_project
    operations = _operations()
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/{endpoint}").mock(
            return_value=httpx.Response(200, json=_project_json())
        )
        result = operations.resolve_project(reference)
    assert route.called
    assert result["id"] == 42
    assert result["path_with_namespace"] == "division/platform/team/repo"
    assert result["default_branch"] == "release/2026"
    assert result["default_branch_fallback"] is False


def test_resolve_project_strips_supported_suffixes_and_rejects_foreign_or_unsupported_urls():
    # GL-READ-05 legacy: gitlab_file_reader.py:GitLabLinkReader._parse_url
    operations = _operations()
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/division%2Fplatform%2Fteam%2Frepo").mock(
            return_value=httpx.Response(200, json=_project_json())
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/branches").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[{"name": "release/2026"}],
            )
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tags").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": ""}, json=[])
        )
        tree = operations.resolve_project(
            f"{ORIGIN}/division/platform/team/repo/-/tree/release%2F2026/src"
        )
    assert tree["link_kind"] == "tree"
    assert tree["link_suffix"] == "release/2026/src"

    for reference in (
        "https://foreign.example.test/division/team/repo",
        f"{ORIGIN}/division/team/repo/-/issues/1",
        f"{ORIGIN}/division",
    ):
        with pytest.raises(Exception) as caught:
            operations.resolve_project(reference)
        assert getattr(caught.value, "category", None) in {
            "invalid_input",
            "group_ambiguity",
        }


def test_resolve_project_preserves_nonempty_default_and_reports_main_only_when_missing():
    # GL-ID-04 legacy: gitlab_project_resolver.py:GitLabProjectResolver.resolve_project
    operations = _operations()
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42")
        route.side_effect = [
            httpx.Response(200, json=_project_json("feature/default")),
            httpx.Response(200, json=_project_json("")),
        ]
        authoritative = operations.resolve_project("42")
        fallback = operations.resolve_project("42")
    assert authoritative["default_branch"] == "feature/default"
    assert authoritative["default_branch_fallback"] is False
    assert fallback["default_branch"] == "main"
    assert fallback["default_branch_fallback"] is True


def test_resolve_project_preserves_valid_default_branch_bytes_and_rejects_invalid_remote_refs():
    # GL-ID-04 legacy: gitlab_project_resolver.py:GitLabProjectResolver.resolve_project
    operations = _operations()
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42")
        route.side_effect = [
            httpx.Response(200, json=_project_json("Feature/Release-2026")),
            httpx.Response(200, json=_project_json(" release/2026 ")),
            httpx.Response(200, json=_project_json("release/\n2026")),
        ]
        exact = operations.resolve_project("42")
        failures = []
        for _case in range(2):
            with pytest.raises(Exception) as caught:
                operations.resolve_project("42")
            failures.append(getattr(caught.value, "category", None))
    assert exact["default_branch"] == "Feature/Release-2026"
    assert exact["default_branch_fallback"] is False
    assert failures == ["invalid_remote_data", "invalid_remote_data"]


def test_project_identity_rejects_cross_origin_web_url_and_builds_canonical_links():
    # GL-ID-01/02 legacy: gitlab_project_resolver.py:GitLabProjectResolver.resolve_project
    operations = _operations()
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42")
        route.side_effect = [
            httpx.Response(
                200,
                json={**_project_json(), "web_url": "https://foreign.example.test/steal"},
            ),
            httpx.Response(200, json=_project_json()),
        ]
        with pytest.raises(Exception) as caught:
            operations.resolve_project("42")
        resolved = operations.resolve_project("42")
    assert getattr(caught.value, "category", None) == "invalid_remote_data"
    assert resolved["links"] == {
        "root": f"{ORIGIN}/division/platform/team/repo",
        "tree": f"{ORIGIN}/division/platform/team/repo/-/tree/release%2F2026",
        "blob": None,
    }


def test_tree_listing_encodes_ref_and_path_and_returns_deterministic_bounded_entries():
    # GL-READ-01 legacy: gitlab_file_fetcher.py:GitLabFileFetcher._get_tree/fetch_files
    operations = _operations()
    seen = {}

    def response(request):
        seen["params"] = dict(request.url.params)
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[
                {"id": "b", "name": "z.py", "path": "src/z.py", "type": "blob", "mode": "100644"},
                {"id": "a", "name": "a", "path": "src/a", "type": "tree", "mode": "040000"},
            ],
        )

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tree").mock(side_effect=response)
        result = operations.list_repository_tree(
            "42", ref="release/2026", path="src/lib", recursive=True, max_items=10
        )
    assert seen["params"]["ref"] == "release/2026"
    assert seen["params"]["path"] == "src/lib"
    assert result["entries"] == [
        {"id": "a", "name": "a", "path": "src/a", "type": "tree", "mode": "040000"},
        {"id": "b", "name": "z.py", "path": "src/z.py", "type": "blob", "mode": "100644"},
    ]
    assert result["truncated"] is False


def test_tree_pagination_honors_headers_short_pages_and_hard_item_page_ceilings():
    # GL-READ-02/GL-CI-10 legacy: gitlab_file_reader.py:_get_tree; gitlab_cicd_collector.py list loops
    operations = _operations(max_pages=2)
    calls = []

    def response(request):
        page = int(request.url.params["page"])
        calls.append(page)
        return httpx.Response(
            200,
            headers={"X-Next-Page": str(page + 1)},
            json=[{"id": str(page), "name": f"{page}.py", "path": f"{page}.py", "type": "blob", "mode": "100644"}],
        )

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tree").mock(side_effect=response)
        result = operations.list_repository_tree("42", ref="main", max_items=2)
    assert calls == [1, 2]
    assert len(result["entries"]) == 2
    assert result["truncated"] is True
    assert result["continuation"] == {"next_page": 3}


def test_general_pagination_jump_beyond_page_ceiling_is_truthfully_truncated():
    # GL-READ-02/GL-CI-10 legacy: gitlab_file_reader.py:_get_tree; GitLab list loops
    operations = _operations(max_pages=2)
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tree").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": "99"},
                json=[
                    {
                        "id": "one",
                        "name": "one.py",
                        "path": "one.py",
                        "type": "blob",
                        "mode": "100644",
                    }
                ],
            )
        )
        result = operations.list_repository_tree("42", ref="main", max_items=10)
    assert result["truncated"] is True
    assert result["continuation"] == {"next_page": 99}


def test_mid_page_item_ceiling_returns_unambiguous_page_and_offset_continuation():
    # GL-READ-01/02/GL-CI-10 legacy: gitlab_file_fetcher.py:_get_tree; GitLab list loops
    operations = _operations(max_pages=2)
    page = [
        {
            "id": str(index),
            "name": f"{index}.py",
            "path": f"{index}.py",
            "type": "blob",
            "mode": "100644",
        }
        for index in range(3)
    ]
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tree").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": "2"}, json=page)
        )
        result = operations.list_repository_tree("42", ref="main", max_items=2)
    assert result["truncated"] is True
    assert result["continuation"] == {"page": 1, "offset": 2}


def test_tree_pagination_uses_one_aggregate_operation_deadline():
    # GL-READ-01/02 legacy: gitlab_file_fetcher.py:GitLabFileFetcher._get_tree
    now = [0.0]
    operations = _operations(
        max_pages=2,
        total_timeout_seconds=1.0,
        clock=lambda: now[0],
    )

    def response(request):
        now[0] += 0.6
        page = int(request.url.params["page"])
        return httpx.Response(
            200,
            headers={"X-Next-Page": "2" if page == 1 else ""},
            json=[{"id": str(page), "name": f"{page}.py", "path": f"{page}.py", "type": "blob", "mode": "100644"}],
        )

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tree").mock(
            side_effect=response
        )
        with pytest.raises(Exception) as caught:
            operations.list_repository_tree("42", ref="main", max_items=20)
    assert getattr(caught.value, "category", None) == "deadline"


def test_root_tree_and_blob_links_resolve_longest_slash_ref_with_bounded_ref_pages():
    # GL-READ-06 legacy: gitlab_file_reader.py:_list_refs/_resolve_ref
    operations = _operations(max_ref_pages=2)
    project_endpoint = f"{ORIGIN}/api/v4/projects/division%2Fplatform%2Fteam%2Frepo"
    with respx.mock:
        respx.get(project_endpoint).mock(return_value=httpx.Response(200, json=_project_json()))
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/branches").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[{"name": "feature"}, {"name": "feature/with/slashes"}],
            )
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tags").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": ""}, json=[])
        )
        result = operations.resolve_project(
            f"{ORIGIN}/division/platform/team/repo/-/blob/feature/with/slashes/src/app.py"
        )
    assert result["resolved_ref"] == "feature/with/slashes"
    assert result["repository_path"] == "src/app.py"
    assert result["link_kind"] == "blob"


def test_unlisted_fallback_ref_is_api_verified_before_access():
    # GL-READ-06 legacy: gitlab_file_reader.py:_resolve_ref
    operations = _operations()
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/division%2Fplatform%2Fteam%2Frepo").mock(
            return_value=httpx.Response(200, json=_project_json())
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/branches").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": ""}, json=[])
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tags").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": ""}, json=[])
        )
        verified = respx.get(f"{ORIGIN}/api/v4/projects/42/repository/commits/unlisted-sha").mock(
            return_value=httpx.Response(200, json={"id": "unlisted-sha"})
        )
        result = operations.resolve_project(
            f"{ORIGIN}/division/platform/team/repo/-/tree/unlisted-sha/src"
        )
    assert verified.called
    assert result["resolved_ref"] == "unlisted-sha"
    assert result["repository_path"] == "src"


def test_incomplete_ref_inventory_fails_closed_instead_of_selecting_shorter_prefix():
    # GL-READ-06/GL-CI-10 legacy: gitlab_file_reader.py:_list_refs/_resolve_ref
    operations = _operations(max_ref_pages=1)
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/division%2Fplatform%2Fteam%2Frepo").mock(
            return_value=httpx.Response(200, json=_project_json())
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/branches").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": "2"},
                json=[{"name": "feature"}],
            )
        )
        with pytest.raises(Exception) as caught:
            operations.resolve_project(
                f"{ORIGIN}/division/platform/team/repo/-/tree/feature/long/ref/src"
            )
    assert getattr(caught.value, "category", None) == "capacity"


def test_ref_inventory_page_jump_beyond_ceiling_fails_capacity_closed():
    # GL-READ-06/GL-CI-10 legacy: gitlab_file_reader.py:_list_refs/_resolve_ref
    operations = _operations(max_ref_pages=2)
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/division%2Fplatform%2Fteam%2Frepo").mock(
            return_value=httpx.Response(200, json=_project_json())
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/branches").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": "99"},
                json=[{"name": "feature"}],
            )
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/tags").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": ""}, json=[])
        )
        with pytest.raises(Exception) as caught:
            operations.resolve_project(
                f"{ORIGIN}/division/platform/team/repo/-/tree/feature/long/ref/src"
            )
    assert getattr(caught.value, "category", None) == "capacity"


def test_read_file_validates_base64_and_returns_bounded_utf8_without_duplicate_markdown():
    # GL-READ-03/08 legacy: gitlab_file_fetcher.py:_get_file/fetch_files
    operations = _operations()
    payload = base64.b64encode("hello π\n".encode()).decode()
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42/repository/files/src%2Fapp.py").mock(
            return_value=httpx.Response(
                200,
                json={"file_path": "src/app.py", "ref": "main", "blob_id": "abc", "size": 9, "encoding": "base64", "content": payload},
            )
        )
        result = operations.read_file("42", "src/app.py", ref="main", max_bytes=1024)
    assert route.called
    assert result["kind"] == "text"
    assert result["content"] == "hello π\n"
    assert "```" not in repr(result)
    assert "text" not in result


@pytest.mark.parametrize(
    ("content", "diagnostic"),
    [
        (base64.b64encode(b"\x00\x01binary").decode(), "binary"),
        (base64.b64encode(b"\xff\xfe").decode(), "undecodable"),
        ("***not-base64***", "invalid_base64"),
    ],
)
def test_read_file_never_projects_binary_undecodable_or_invalid_base64(content, diagnostic):
    # GL-READ-03 legacy: gitlab_file_reader.py:GitLabLinkReader._get_file
    operations = _operations()
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/files/data.bin").mock(
            return_value=httpx.Response(
                200,
                json={"file_path": "data.bin", "ref": "main", "blob_id": "abc", "size": 10, "encoding": "base64", "content": content},
            )
        )
        if diagnostic == "invalid_base64":
            with pytest.raises(Exception) as caught:
                operations.read_file("42", "data.bin", ref="main", max_bytes=1024)
            assert getattr(caught.value, "category", None) == "invalid_remote_data"
        else:
            result = operations.read_file("42", "data.bin", ref="main", max_bytes=1024)
            assert result["kind"] == "binary"
            assert result["diagnostic"] == diagnostic
            assert "content" not in result
            assert content not in repr(result)


def test_read_file_rejects_declared_or_decoded_capacity_before_projection():
    # GL-READ-03 legacy: gitlab_file_fetcher.py:GitLabFileFetcher._get_file
    operations = _operations()
    body = base64.b64encode(b"0123456789").decode()
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42/repository/files/large.txt")
        route.side_effect = [
            httpx.Response(200, json={"file_path": "large.txt", "ref": "main", "blob_id": "a", "size": 1000, "encoding": "base64", "content": body}),
            httpx.Response(200, json={"file_path": "large.txt", "ref": "main", "blob_id": "a", "size": 1, "encoding": "base64", "content": body}),
        ]
        for _case in range(2):
            with pytest.raises(Exception) as caught:
                operations.read_file("42", "large.txt", ref="main", max_bytes=4)
            assert getattr(caught.value, "category", None) == "capacity"


def test_repository_reads_require_one_explicit_ref_identity_and_validate_paths():
    # GL-READ-04/07 legacy: gitlab_file_fetcher.py:fetch_files; gitlab_file_reader.py:read_files
    operations = _operations()
    for ref, path in (("", "src"), ("main", "../secret"), ("main", "/absolute")):
        with pytest.raises(Exception) as caught:
            operations.list_repository_tree("42", ref=ref, path=path)
        assert getattr(caught.value, "category", None) == "invalid_input"


def test_read_merge_request_bounds_change_count_and_aggregate_diff_bytes():
    # GL-REVIEW-01 legacy: code_review_runner.py:CodeReviewRunner._fetch_diff
    operations = _operations(max_diff_bytes=12, max_changes=2)
    changes = [
        {"old_path": "a.py", "new_path": "a.py", "new_file": False, "renamed_file": False, "deleted_file": False, "diff": "12345678"},
        {"old_path": "b.py", "new_path": "b.py", "new_file": False, "renamed_file": False, "deleted_file": False, "diff": "abcdefgh"},
        {"old_path": "c.py", "new_path": "c.py", "new_file": True, "renamed_file": False, "deleted_file": False, "diff": "must-not-appear"},
    ]
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests/7/changes").mock(
            return_value=httpx.Response(
                200,
                json={"id": 70, "iid": 7, "sha": "a" * 40, "title": "Review", "state": "opened", "source_branch": "feature", "target_branch": "main", "web_url": f"{ORIGIN}/x/y/-/merge_requests/7", "changes": changes},
            )
        )
        result = operations.read_merge_request("42", 7)
    assert result["head_sha"] == "a" * 40
    assert len(result["changes"]) == 2
    assert sum(len(change["diff"].encode()) for change in result["changes"]) <= 12
    assert result["truncated"] is True
    assert result["warnings"] == ["merge_request_changes_truncated"]
    assert "must-not-appear" not in repr(result)


@pytest.mark.parametrize(
    "remote_incomplete_evidence",
    [{"overflow": True}, {"changes_count": "2"}, {"changes_count": "1000+"}],
)
def test_merge_request_remote_incomplete_evidence_forces_truncation_warning(
    remote_incomplete_evidence,
):
    # GL-REVIEW-01 legacy: code_review_runner.py:CodeReviewRunner._fetch_diff
    operations = _operations()
    payload = {
        "id": 70,
        "iid": 7,
        "sha": "a" * 40,
        "title": "Review",
        "state": "opened",
        "source_branch": "feature",
        "target_branch": "main",
        "web_url": f"{ORIGIN}/x/y/-/merge_requests/7",
        "changes": [
            {
                "old_path": "a.py",
                "new_path": "a.py",
                "new_file": False,
                "renamed_file": False,
                "deleted_file": False,
                "diff": "one complete visible change",
            }
        ],
        **remote_incomplete_evidence,
    }
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests/7/changes").mock(
            return_value=httpx.Response(200, json=payload)
        )
        result = operations.read_merge_request("42", 7)
    assert result["truncated"] is True
    assert "merge_request_remote_truncated" in result["warnings"]


@pytest.mark.parametrize("changes_count", ["many", "0", -1, True])
def test_merge_request_rejects_malformed_or_under_count_remote_change_evidence(
    changes_count,
):
    # GL-REVIEW-01 legacy: code_review_runner.py:CodeReviewRunner._fetch_diff
    operations = _operations()
    payload = {
        "id": 70,
        "iid": 7,
        "sha": "a" * 40,
        "title": "Review",
        "state": "opened",
        "source_branch": "feature",
        "target_branch": "main",
        "web_url": f"{ORIGIN}/x/y/-/merge_requests/7",
        "changes": [
            {
                "old_path": "a.py",
                "new_path": "a.py",
                "new_file": False,
                "renamed_file": False,
                "deleted_file": False,
                "diff": "visible",
            }
        ],
        "changes_count": changes_count,
    }
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests/7/changes").mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(Exception) as caught:
            operations.read_merge_request("42", 7)
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_merge_request_rejects_cross_origin_url_and_non_scalar_identity():
    # GL-REVIEW-01 legacy: code_review_runner.py:CodeReviewRunner._fetch_diff
    operations = _operations()
    base = {
        "id": 70,
        "iid": 7,
        "sha": "a" * 40,
        "title": "Review",
        "state": "opened",
        "source_branch": "feature",
        "target_branch": "main",
        "web_url": f"{ORIGIN}/x/y/-/merge_requests/7",
        "changes": [],
    }
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests/7/changes")
        route.side_effect = [
            httpx.Response(200, json={**base, "web_url": "https://foreign.example.test/mr/7"}),
            httpx.Response(200, json={**base, "id": {"raw": "object"}}),
            httpx.Response(200, json={**base, "iid": [7]}),
        ]
        for _case in range(3):
            with pytest.raises(Exception) as caught:
                operations.read_merge_request("42", 7)
            assert getattr(caught.value, "category", None) == "invalid_remote_data"


class _RemoteString(str):
    """A hostile mapping can supply a string subclass outside JSON decoding."""


@pytest.mark.parametrize(
    "sha_override",
    [
        pytest.param({}, id="missing"),
        pytest.param({"sha": "a" * 39}, id="short"),
        pytest.param({"sha": "a" * 41}, id="long"),
        pytest.param({"sha": "A" * 40}, id="uppercase"),
        pytest.param({"sha": "g" * 40}, id="non-hex"),
        pytest.param({"sha": 7}, id="integer"),
        pytest.param({"sha": ["a" * 40]}, id="list"),
        pytest.param({"sha": _RemoteString("a" * 40)}, id="string-subclass"),
    ],
)
def test_read_merge_request_rejects_missing_or_noncanonical_head_sha(
    monkeypatch, sha_override
):
    """Removing exact lowercase 40-hex validation must fail this contract."""
    operations = _operations()
    payload = {
        "id": 70,
        "iid": 7,
        "title": "Review",
        "state": "opened",
        "source_branch": "feature",
        "target_branch": "main",
        "web_url": f"{ORIGIN}/x/y/-/merge_requests/7",
        "changes": [],
        **sha_override,
    }
    monkeypatch.setattr(operations.client, "get_json", lambda *_a, **_kw: payload)

    with pytest.raises(Exception) as caught:
        operations.read_merge_request("42", 7)

    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_read_merge_request_reread_exposes_changed_remote_head_sha():
    """A new push must be visible before an agent approves or merges."""
    operations = _operations()
    base = {
        "id": 70,
        "iid": 7,
        "title": "Review",
        "state": "opened",
        "source_branch": "feature",
        "target_branch": "main",
        "web_url": f"{ORIGIN}/x/y/-/merge_requests/7",
        "changes": [],
    }
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests/7/changes")
        route.side_effect = [
            httpx.Response(200, json={**base, "sha": "a" * 40}),
            httpx.Response(200, json={**base, "sha": "b" * 40}),
        ]
        reviewed = operations.read_merge_request("42", 7)
        reread = operations.read_merge_request("42", 7)

    assert reviewed["head_sha"] == "a" * 40
    assert reread["head_sha"] == "b" * 40
    assert reread["head_sha"] != reviewed["head_sha"]


def test_list_pipelines_is_bounded_paginated_and_normalized_for_public_task8_tool():
    # GL-CI-10 Task 8 portion legacy: gitlab_cicd_collector.py:_fetch_recent_pipeline_branches
    operations = _operations(max_pages=2)
    with respx.mock:
        route = respx.get(f"{ORIGIN}/api/v4/projects/42/pipelines")
        route.side_effect = [
            httpx.Response(200, headers={"X-Next-Page": "2"}, json=[{"id": 3, "iid": 3, "ref": "main", "sha": "abc", "status": "success", "source": "push", "web_url": f"{ORIGIN}/x/y/-/pipelines/3", "created_at": "2026-08-09T00:00:00Z", "updated_at": "2026-08-09T00:01:00Z"}]),
            httpx.Response(200, headers={"X-Next-Page": "3"}, json=[{"id": 2, "iid": 2, "ref": "dev", "sha": "def", "status": "failed", "source": "push", "web_url": f"{ORIGIN}/x/y/-/pipelines/2", "created_at": "2026-08-08T00:00:00Z", "updated_at": "2026-08-08T00:01:00Z"}]),
        ]
        result = operations.list_pipelines("42", max_items=2)
    assert [item["id"] for item in result["pipelines"]] == [3, 2]
    assert result["truncated"] is True
    assert result["continuation"] == {"next_page": 3}


def test_pipeline_list_rejects_cross_origin_web_urls():
    # GL-CI-10 Task 8 portion legacy: gitlab_cicd_collector.py:_fetch_pipeline_stats
    operations = _operations()
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42/pipelines").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[{
                    "id": 3,
                    "ref": "main",
                    "sha": "abc",
                    "status": "success",
                    "source": "push",
                    "web_url": "https://foreign.example.test/pipeline/3",
                    "created_at": "2026-08-09T00:00:00Z",
                    "updated_at": "2026-08-09T00:01:00Z",
                }],
            )
        )
        with pytest.raises(Exception) as caught:
            operations.list_pipelines("42")
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def _pipeline_json(pipeline_id=918, **overrides):
    payload = {
        "id": pipeline_id,
        "status": "success",
        "ref": "main",
        "sha": "a" * 40,
        "source": "push",
        "web_url": f"{ORIGIN}/division/platform/team/repo/-/pipelines/{pipeline_id}",
        "created_at": "2026-08-18T10:00:00Z",
        "updated_at": "2026-08-18T10:01:00Z",
        "started_at": None,
        "finished_at": "2026-08-18T10:02:00Z",
        "user": {"name": "must not escape"},
        "variables": [{"key": "SECRET", "value": "must not escape"}],
        "jobs": [{"name": "must not escape"}],
    }
    payload.update(overrides)
    return payload


def test_read_pipeline_resolves_project_and_returns_only_exact_bounded_contract():
    operations = _operations()
    with respx.mock:
        project = respx.get(f"{ORIGIN}/api/v4/projects/division%2Fplatform%2Fteam%2Frepo").mock(
            return_value=httpx.Response(200, json=_project_json())
        )
        pipeline = respx.get(f"{ORIGIN}/api/v4/projects/42/pipelines/918").mock(
            return_value=httpx.Response(200, json=_pipeline_json())
        )
        result = operations.read_pipeline("division/platform/team/repo", 918)
    assert project.called and pipeline.called
    assert result == {
        "project": {"id": 42, "path": "division/platform/team/repo"},
        "pipeline_id": 918,
        "status": "success",
        "ref": "main",
        "sha": "a" * 40,
        "source": "push",
        "web_url": f"{ORIGIN}/division/platform/team/repo/-/pipelines/918",
        "created_at": "2026-08-18T10:00:00Z",
        "updated_at": "2026-08-18T10:01:00Z",
        "started_at": None,
        "finished_at": "2026-08-18T10:02:00Z",
    }
    assert "user" not in repr(result)
    assert "variables" not in repr(result)
    assert "jobs" not in repr(result)


@pytest.mark.parametrize("pipeline_id", [True, 0, -1, 1.5, "918"])
def test_read_pipeline_rejects_nonpositive_or_wrongly_typed_id_before_transport(
    pipeline_id,
):
    operations = _operations()
    with respx.mock:
        with pytest.raises(Exception) as caught:
            operations.read_pipeline("42", pipeline_id)
        assert respx.calls.call_count == 0
    assert getattr(caught.value, "category", None) == "invalid_input"


@pytest.mark.parametrize(
    "override",
    [
        {"id": 919},
        {"project_id": 99},
        {"status": None},
        {"ref": 7},
        {"sha": "x" * 2049},
        {"source": ""},
        {"web_url": "https://foreign.example.test/pipelines/918"},
        {"created_at": "x" * 129},
        {"updated_at": 7},
    ],
)
def test_read_pipeline_rejects_missing_wrong_overbound_cross_origin_or_inconsistent_data(
    override,
):
    operations = _operations()
    payload = _pipeline_json(**override)
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project_json())
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/pipelines/918").mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(Exception) as caught:
            operations.read_pipeline("42", 918)
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_read_pipeline_requires_every_public_remote_field():
    operations = _operations()
    for missing in (
        "status",
        "ref",
        "sha",
        "source",
        "web_url",
        "created_at",
        "updated_at",
        "started_at",
        "finished_at",
    ):
        payload = _pipeline_json()
        payload.pop(missing)
        with respx.mock:
            respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
                return_value=httpx.Response(200, json=_project_json())
            )
            respx.get(f"{ORIGIN}/api/v4/projects/42/pipelines/918").mock(
                return_value=httpx.Response(200, json=payload)
            )
            with pytest.raises(Exception) as caught:
                operations.read_pipeline("42", 918)
        assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_read_pipeline_schema_is_bounded_and_tools_invoke_dispatches(monkeypatch):
    tools = _tools_module()
    schema = tools.SCHEMAS["gitlab_read_pipeline"]["parameters"]
    assert schema["required"] == ["project", "pipeline_id"]
    assert set(schema["properties"]) == {"project", "pipeline_id"}
    assert schema["properties"]["pipeline_id"] == {
        "type": "integer",
        "minimum": 1,
        "maximum": 2147483647,
    }

    seen = []

    class Operations:
        client = type("Client", (), {"close": lambda self: None})()

        def read_pipeline(self, project, pipeline_id):
            seen.append((project, pipeline_id))
            return {"ok": True}

    monkeypatch.setattr(
        tools, "operations_from_configuration", lambda *args, **kwargs: Operations()
    )
    assert tools.invoke(
        "gitlab_read_pipeline",
        {"project": "group/repo", "pipeline_id": 918},
        object(),
    ) == {"ok": True}
    assert seen == [("group/repo", 918)]


def test_project_endpoint_rejects_nonpositive_numeric_strings_before_transport():
    _auth, _client, _models, operations = _modules()
    with pytest.raises(operations.GitLabError, match="input is invalid"):
        operations._project_endpoint("0")
    with pytest.raises(operations.GitLabError, match="input is invalid"):
        operations._project_endpoint("000")
