from __future__ import annotations

import base64
import importlib
import json
import sys
from datetime import datetime
from pathlib import Path

import httpx
import pytest
import respx


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-gitlab"
FIXTURES = REPO / "tests" / "fixtures" / "gitlab" / "ci"
ORIGIN = "https://gitlab.example.test"
PROJECT_API = f"{ORIGIN}/api/v4/projects/42"
PIPELINES_API = f"{PROJECT_API}/pipelines"
BRANCHES_API = f"{PROJECT_API}/repository/branches"
CI_FILE_API = f"{PROJECT_API}/repository/files/.gitlab-ci.yml"


def _modules():
    assert PLUGIN.is_dir(), "Task 8 GitLab plugin production surface is missing"
    if str(PLUGIN) not in sys.path:
        sys.path.insert(0, str(PLUGIN))
    return (
        importlib.import_module("auth"),
        importlib.import_module("client"),
        importlib.import_module("models"),
        importlib.import_module("operations"),
        importlib.import_module("tools"),
    )


def _operations(**client_options):
    auth, client, _models, operations, _tools = _modules()
    credentials = auth.GitLabAuth(
        origin=ORIGIN,
        pat="fixture-token",
        certificate_pair=None,
    )
    return operations.GitLabOperations(
        client.GitLabClient(credentials, **client_options)
    )


def _fixture(name: str) -> str:
    return (FIXTURES / name).read_text(encoding="utf-8")


def _project_json():
    return {
        "id": 42,
        "name": "repo",
        "path_with_namespace": "division/platform/team/repo",
        "default_branch": "main",
        "web_url": f"{ORIGIN}/division/platform/team/repo",
        "namespace": {"kind": "group", "full_path": "division/platform/team"},
    }


def _file_payload(text: str, *, path: str = ".gitlab-ci.yml"):
    encoded = text.encode("utf-8")
    return {
        "file_name": Path(path).name,
        "file_path": path,
        "blob_id": "blob-fixture",
        "size": len(encoded),
        "encoding": "base64",
        "content": base64.b64encode(encoded).decode("ascii"),
    }


def _mock_project():
    return respx.get(PROJECT_API).mock(
        return_value=httpx.Response(200, json=_project_json())
    )


def _mock_pipeline_window(*, total="7", latest="success", discovery=None):
    seen = []

    def response(request):
        params = dict(request.url.params)
        seen.append(params)
        if params.get("per_page") == "1" and "updated_after" in params:
            headers = {} if total is None else {"X-Total": str(total)}
            return httpx.Response(200, headers=headers, json=[])
        if params.get("per_page") == "1":
            body = [] if latest is None else [{"id": 9, "status": latest}]
            return httpx.Response(200, json=body)
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=list(discovery or []),
        )

    respx.get(PIPELINES_API).mock(side_effect=response)
    return seen


def _mock_ci_file(branch: str, text: str | None = None, *, status=200):
    route = respx.get(CI_FILE_API, params={"ref": branch})
    if status == 200:
        return route.mock(
            return_value=httpx.Response(200, json=_file_payload(text or "build: {}\n"))
        )
    return route.mock(return_value=httpx.Response(status, text="must-not-leak"))


def test_exact_branch_and_pipeline_window_are_bounded_and_normalized():
    # GL-CI-01/02 legacy: gitlab_cicd_collector.py:_discover_branches/_fetch_pipeline_stats
    operations = _operations()
    with respx.mock:
        _mock_project()
        seen = _mock_pipeline_window(total="7", latest="success")
        _mock_ci_file("release/2026")
        result = operations.inspect_ci(
            "42", branch_spec="release/2026", collect_variables=False
        )
    assert [branch["name"] for branch in result["branches"]] == ["release/2026"]
    assert result["pipeline_window"]["count"] == 7
    assert result["pipeline_window"]["count_status"] == "reported"
    assert result["pipeline_window"]["latest_status"] == "success"
    start = datetime.fromisoformat(result["pipeline_window"]["start_at"])
    end = datetime.fromisoformat(result["pipeline_window"]["end_at"])
    assert (end - start).days == 10
    assert any("updated_after" in params for params in seen)


@pytest.mark.parametrize("branch_spec", ["ALL", "RECENT"])
def test_all_and_recent_keep_first_seen_live_pipeline_refs(branch_spec):
    # GL-CI-01 legacy: gitlab_cicd_collector.py:_fetch_all_pipeline_branches/_fetch_recent_pipeline_branches/_fetch_live_branch_set
    operations = _operations()
    discovery = [
        {"id": 5, "ref": "deleted"},
        {"id": 4, "ref": "main"},
        {"id": 3, "ref": "dev"},
        {"id": 2, "ref": "main"},
    ]
    with respx.mock:
        _mock_project()
        seen = _mock_pipeline_window(discovery=discovery)
        respx.get(BRANCHES_API).mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[{"name": "main"}, {"name": "dev"}],
            )
        )
        _mock_ci_file("main")
        _mock_ci_file("dev")
        result = operations.inspect_ci(
            "42", branch_spec=branch_spec, collect_variables=False
        )
    assert [branch["name"] for branch in result["branches"]] == ["main", "dev"]
    discovery_request = next(
        params for params in seen if params.get("per_page") == "100"
    )
    assert ("updated_after" in discovery_request) is (branch_spec == "RECENT")


def test_branch_selection_exposes_source_distinguishable_mid_page_and_jump_continuations():
    # GL-CI-10 legacy: gitlab_cicd_collector.py:_fetch_pipeline_branches/_fetch_live_branch_set
    operations = _operations()

    def pipelines(request):
        params = dict(request.url.params)
        if params.get("per_page") == "1" and "updated_after" in params:
            return httpx.Response(200, headers={"X-Total": "11"}, json=[])
        if params.get("per_page") == "1":
            return httpx.Response(200, json=[{"id": 11, "status": "success"}])
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[{"id": index, "ref": f"branch-{index}"} for index in range(11)],
        )

    with respx.mock:
        _mock_project()
        respx.get(PIPELINES_API).mock(side_effect=pipelines)
        respx.get(BRANCHES_API).mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": "7"},
                json=[{"name": "branch-0"}],
            )
        )
        _mock_ci_file("branch-0")
        result = operations.inspect_ci(
            "42",
            branch_spec="ALL",
            collect_variables=False,
            max_branches=1,
            max_pages=2,
        )
    assert result["branch_selection"] == {
        "truncated": True,
        "continuations": [
            {"source": "pipelines", "page": 1, "offset": 10},
            {"source": "live_branches", "next_page": 7},
        ],
    }


@pytest.mark.parametrize(
    ("total", "status"),
    [(None, "missing"), ("not-a-count", "malformed")],
)
def test_pipeline_count_evidence_is_explicit_when_missing_or_malformed(total, status):
    # GL-CI-02 legacy: gitlab_cicd_collector.py:_fetch_pipeline_stats
    operations = _operations()
    with respx.mock:
        _mock_project()
        _mock_pipeline_window(total=total, latest=None)
        _mock_ci_file("main")
        result = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    assert result["pipeline_window"]["count"] is None
    assert result["pipeline_window"]["count_status"] == status
    assert result["pipeline_window"]["latest_status"] is None


@pytest.mark.parametrize(
    ("http_status", "file_status", "warning"),
    [
        (404, "not_found", "ci_file_not_found"),
        (403, "permission", "ci_file_permission"),
        (500, "transient", "ci_file_transient"),
    ],
)
def test_ci_file_failures_are_partial_fixed_warnings_without_remote_bodies(
    http_status, file_status, warning
):
    # GL-CI-03 legacy: gitlab_cicd_collector.py:_fetch_ci_file
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", status=http_status)
        result = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    assert result["branches"][0]["ci_file"]["status"] == file_status
    assert warning in result["warnings"]
    assert "must-not-leak" not in repr(result)


def test_one_level_includes_use_current_or_explicit_project_and_never_interpolate():
    # GL-CI-04/05 legacy: gitlab_cicd_collector.py:_parse_includes/_resolve_includes_shallow
    operations = _operations()
    root = _fixture("root.yml")
    local = _fixture("local.yml")
    local_api = f"{PROJECT_API}/repository/files/.ci%2Flocal.yml"
    project_api = (
        f"{ORIGIN}/api/v4/projects/division%2Fshared%2Fci/"
        "repository/files/templates%2Fbuild.yml"
    )
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("feature/x", root)
        local_route = respx.get(local_api, params={"ref": "feature/x"}).mock(
            return_value=httpx.Response(
                200, json=_file_payload(local, path=".ci/local.yml")
            )
        )
        project_route = respx.get(project_api, params={"ref": "main"}).mock(
            return_value=httpx.Response(
                200, json=_file_payload("shared: {}\n", path="templates/build.yml")
            )
        )
        result = operations.inspect_ci(
            "42", branch_spec="feature/x", collect_variables=False
        )
    includes = result["branches"][0]["ci_file"]["includes"]
    assert local_route.called and project_route.called
    assert [item["type"] for item in includes] == [
        "local",
        "project",
        "remote",
        "template",
    ]
    assert includes[0]["status"] == "success"
    assert includes[1]["ref"] == "main"
    assert "include_ref_not_interpolated" in includes[1]["warnings"]
    assert includes[2]["status"] == "unsupported"
    assert includes[3]["status"] == "unsupported"
    assert "nested-must-not-be-fetched" not in repr(result)


def test_remote_and_template_includes_are_explicit_and_make_no_external_request():
    # GL-CI-06/07 legacy: gitlab_cicd_collector.py:_parse_includes
    operations = _operations()
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", _fixture("root.yml"))
        respx.get(
            f"{PROJECT_API}/repository/files/.ci%2Flocal.yml",
            params={"ref": "main"},
        ).mock(
            return_value=httpx.Response(
                200,
                json=_file_payload(_fixture("local.yml"), path=".ci/local.yml"),
            )
        )
        respx.get(
            (
                f"{ORIGIN}/api/v4/projects/division%2Fshared%2Fci/"
                "repository/files/templates%2Fbuild.yml"
            ),
            params={"ref": "main"},
        ).mock(
            return_value=httpx.Response(
                200, json=_file_payload("shared: {}\n", path="templates/build.yml")
            )
        )
        result = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    unsupported = [
        item
        for item in result["branches"][0]["ci_file"]["includes"]
        if item["status"] == "unsupported"
    ]
    assert [(item["type"], item["warning"]) for item in unsupported] == [
        ("remote", "unsupported_include"),
        ("template", "unsupported_include"),
    ]
    assert all("content" not in item for item in unsupported)


@pytest.mark.parametrize(
    ("status_code", "status"),
    [(200, "success"), (404, "not_found"), (403, "permission"), (500, "transient")],
)
def test_include_fetches_have_stable_status_and_hash_only_success(status_code, status):
    # GL-CI-08 legacy: gitlab_cicd_collector.py:_fetch_include_file
    operations = _operations(max_retries=0)
    root = "include:\n  - local: /.ci/local.yml\n"
    include_api = f"{PROJECT_API}/repository/files/.ci%2Flocal.yml"
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", root)
        route = respx.get(include_api, params={"ref": "main"})
        if status_code == 200:
            route.mock(
                return_value=httpx.Response(
                    200,
                    json=_file_payload("included: true\n", path=".ci/local.yml"),
                )
            )
        else:
            route.mock(return_value=httpx.Response(status_code, text="private-body"))
        result = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    include = result["branches"][0]["ci_file"]["includes"][0]
    assert include["status"] == status
    assert (include["sha256"] is not None) is (status == "success")
    assert "private-body" not in repr(result)


def test_include_count_and_cycle_bounds_are_truthful_and_do_not_recurse():
    # GL-CI-04/10 legacy: gitlab_cicd_collector.py:_resolve_includes_shallow/list loops
    operations = _operations()
    root = "include:\n  - local: /.gitlab-ci.yml\n  - local: /.ci/over-limit.yml\n"
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", root)
        result = operations.inspect_ci(
            "42",
            branch_spec="main",
            collect_variables=False,
            max_includes=1,
        )
    ci_file = result["branches"][0]["ci_file"]
    assert ci_file["includes"][0]["status"] == "cycle"
    assert ci_file["includes_truncated"] is True
    assert "include_limit_reached" in result["warnings"]


@pytest.mark.parametrize("include_project", ["42", "division/platform/team/repo"])
def test_equivalent_current_project_includes_are_canonical_cycles(include_project):
    # GL-CI-04/10 legacy: gitlab_cicd_collector.py:_resolve_includes_shallow
    operations = _operations()
    root = (
        "include:\n"
        f"  - project: {include_project}\n"
        "    file: /.gitlab-ci.yml\n"
        "    ref: main\n"
    )
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        root_route = _mock_ci_file("main", root)
        result = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    include = result["branches"][0]["ci_file"]["includes"][0]
    assert include["status"] == "cycle"
    assert include["project"] == "division/platform/team/repo"
    assert root_route.call_count == 1


def test_include_bytes_are_one_aggregate_operation_budget():
    # GL-CI-04/08/10 legacy: gitlab_cicd_collector.py:_resolve_includes_shallow/_fetch_include_file
    operations = _operations()
    root = "include:\n  - local: /first.yml\n  - local: /second.yml\n"
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", root)
        respx.get(
            f"{PROJECT_API}/repository/files/first.yml", params={"ref": "main"}
        ).mock(
            return_value=httpx.Response(
                200, json=_file_payload("a: 1\n", path="first.yml")
            )
        )
        respx.get(
            f"{PROJECT_API}/repository/files/second.yml", params={"ref": "main"}
        ).mock(
            return_value=httpx.Response(
                200, json=_file_payload("b: 22\n", path="second.yml")
            )
        )
        result = operations.inspect_ci(
            "42",
            branch_spec="main",
            collect_variables=False,
            max_include_bytes=10,
        )
    includes = result["branches"][0]["ci_file"]["includes"]
    assert [item["status"] for item in includes] == ["success", "capacity"]
    assert sum(item["size"] for item in includes) <= 10
    assert "include_capacity" in result["warnings"]


def test_include_count_and_bytes_are_shared_across_all_selected_branches():
    # GL-CI-04/08/10 legacy: gitlab_cicd_collector.py:_resolve_includes_shallow/list loops
    operations = _operations()
    first_root = "include:\n  - local: /shared.yml\n"
    later_root = "include:\n  - local: /shared.yml\n  - local: /must-not-fetch.yml\n"
    with respx.mock:
        _mock_project()
        _mock_pipeline_window(
            discovery=[{"id": 2, "ref": "main"}, {"id": 1, "ref": "dev"}]
        )
        respx.get(BRANCHES_API).mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[{"name": "main"}, {"name": "dev"}],
            )
        )
        _mock_ci_file("main", first_root)
        _mock_ci_file("dev", later_root)
        respx.get(
            f"{PROJECT_API}/repository/files/shared.yml", params={"ref": "main"}
        ).mock(
            return_value=httpx.Response(
                200, json=_file_payload("a: 1\n", path="shared.yml")
            )
        )
        later_route = respx.get(
            f"{PROJECT_API}/repository/files/shared.yml", params={"ref": "dev"}
        ).mock(
            return_value=httpx.Response(
                200, json=_file_payload("b: 2\n", path="shared.yml")
            )
        )
        omitted_route = respx.get(
            f"{PROJECT_API}/repository/files/must-not-fetch.yml",
            params={"ref": "dev"},
        ).mock(
            return_value=httpx.Response(
                200, json=_file_payload("c: 3\n", path="must-not-fetch.yml")
            )
        )
        result = operations.inspect_ci(
            "42",
            branch_spec="ALL",
            collect_variables=False,
            max_includes=2,
            max_include_bytes=5,
        )
    first, second = [branch["ci_file"] for branch in result["branches"]]
    assert first["includes"][0]["status"] == "success"
    assert len(second["includes"]) == 1
    assert second["includes"][0]["status"] == "capacity"
    assert second["includes_truncated"] is True
    assert later_route.call_count == 0
    assert omitted_route.call_count == 0
    assert (
        sum(
            include["size"]
            for branch in result["branches"]
            for include in branch["ci_file"]["includes"]
        )
        <= 5
    )


def test_bounded_yaml_include_parser_ignores_unknown_job_tags_without_erasing_includes():
    # GL-CI-04 legacy: gitlab_cicd_collector.py:_parse_includes
    operations = _operations()
    root = (
        "include:\n"
        "  - local: /first.yml\n"
        ".base:\n"
        "  script: [echo fixture]\n"
        "job:\n"
        "  script: !reference [.base, script]\n"
    )
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", root)
        respx.get(
            f"{PROJECT_API}/repository/files/first.yml", params={"ref": "main"}
        ).mock(
            return_value=httpx.Response(
                200, json=_file_payload("a: 1\n", path="first.yml")
            )
        )
        result = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    ci_file = result["branches"][0]["ci_file"]
    assert ci_file["include_parse_status"] == "ok"
    assert ci_file["includes"][0]["status"] == "success"
    assert "job" not in repr(ci_file)


@pytest.mark.parametrize(
    ("root", "status", "warning"),
    [
        ("include: [\n", "invalid", "ci_yaml_invalid"),
        (
            "\n".join(
                ["nested:"]
                + [f"{'  ' * depth}value:" for depth in range(1, 71)]
                + [f"{'  ' * 71}leaf: true", "include: []"]
            )
            + "\n",
            "capacity",
            "ci_yaml_capacity",
        ),
        (
            "anchor: &shared {}\naliases: ["
            + ",".join("*shared" for _ in range(140))
            + "]\ninclude: []\n",
            "capacity",
            "ci_yaml_capacity",
        ),
    ],
)
def test_bounded_yaml_include_parser_reports_malformed_depth_and_alias_caps(
    root, status, warning
):
    # GL-CI-04/10 legacy: gitlab_cicd_collector.py:_parse_includes/list loops
    operations = _operations()
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", root)
        result = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    ci_file = result["branches"][0]["ci_file"]
    assert ci_file["include_parse_status"] == status
    assert ci_file["includes"] == []
    assert warning in result["warnings"]


def test_project_and_ancestor_group_variables_are_metadata_only_deduplicated_and_bounded():
    # GL-CI-09/10 legacy: gitlab_cicd_collector.py:_fetch_project_variables/_fetch_group_variables
    operations = _operations(max_pages=2)
    variables = json.loads(_fixture("variables.json"))

    def project_variables(request):
        page = request.url.params["page"]
        if page == "1":
            return httpx.Response(200, headers={"X-Next-Page": "2"}, json=variables)
        return httpx.Response(200, headers={"X-Next-Page": ""}, json=variables)

    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main")
        respx.get(f"{PROJECT_API}/variables").mock(side_effect=project_variables)
        respx.get(f"{ORIGIN}/api/v4/groups/division").mock(
            return_value=httpx.Response(200, json={"id": 10})
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/variables").mock(
            return_value=httpx.Response(403, text="group-secret-body")
        )
        respx.get(f"{ORIGIN}/api/v4/groups/division%2Fplatform").mock(
            return_value=httpx.Response(200, json={"id": 11})
        )
        respx.get(f"{ORIGIN}/api/v4/groups/11/variables").mock(
            return_value=httpx.Response(
                200, headers={"X-Next-Page": ""}, json=variables
            )
        )
        result = operations.inspect_ci(
            "42",
            branch_spec="main",
            max_groups=2,
            max_variables=10,
        )
    items = result["variables"]["items"]
    assert len(items) == 2
    assert [(item["scope"], item["source"]) for item in items] == [
        ("project", "division/platform/team/repo"),
        ("group", "division/platform"),
    ]
    assert set(items[0]) == {
        "key",
        "type",
        "protected",
        "masked",
        "hidden",
        "raw",
        "environment_scope",
        "description",
        "scope",
        "source",
    }
    assert "value" not in repr(result).lower()
    assert "must-not-be-projected" not in repr(result)
    assert "group_variable_permission" in result["variables"]["warnings"]
    assert result["variables"]["groups_truncated"] is True


def test_two_denied_ancestor_variable_reads_keep_fixed_identity_records():
    # GL-CI-09 legacy: gitlab_cicd_collector.py:_fetch_group_variables
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main")
        respx.get(f"{PROJECT_API}/variables").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": ""}, json=[])
        )
        for ancestor, group_id in (("division", 10), ("division/platform", 11)):
            encoded = ancestor.replace("/", "%2F")
            respx.get(f"{ORIGIN}/api/v4/groups/{encoded}").mock(
                return_value=httpx.Response(200, json={"id": group_id})
            )
            respx.get(f"{ORIGIN}/api/v4/groups/{group_id}/variables").mock(
                return_value=httpx.Response(403, text=f"private-{ancestor}")
            )
        result = operations.inspect_ci(
            "42", branch_spec="main", max_groups=2, max_variables=10
        )
    assert result["variables"]["permission_records"] == [
        {
            "category": "permission",
            "scope": "group",
            "source": "division",
            "ancestor": "division",
        },
        {
            "category": "permission",
            "scope": "group",
            "source": "division/platform",
            "ancestor": "division/platform",
        },
    ]
    assert "private-" not in repr(result)


def test_denied_project_variable_read_keeps_one_fixed_safe_identity_record():
    # GL-CI-09 legacy: gitlab_cicd_collector.py:_fetch_project_variables
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main")
        respx.get(f"{PROJECT_API}/variables").mock(
            return_value=httpx.Response(
                403, text="private-project-variable-body arbitrary-error-detail"
            )
        )
        respx.get(f"{ORIGIN}/api/v4/groups/division").mock(
            return_value=httpx.Response(200, json={"id": 10})
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/variables").mock(
            return_value=httpx.Response(200, headers={"X-Next-Page": ""}, json=[])
        )
        result = operations.inspect_ci(
            "42", branch_spec="main", max_groups=1, max_variables=10
        )
    assert result["variables"]["permission_records"] == [
        {
            "category": "permission",
            "scope": "project",
            "source": "division/platform/team/repo",
        }
    ]
    rendered = repr(result)
    assert "private-project-variable-body" not in rendered
    assert "arbitrary-error-detail" not in rendered
    assert "fixture-token" not in rendered


def test_one_normalized_result_is_not_cached_and_partial_failures_do_not_abort():
    # GL-CI-11 legacy: gitlab_cicd_collector.py:_collect_all/get_combined and six output methods
    operations = _operations()
    with respx.mock:
        project = _mock_project()
        _mock_pipeline_window()
        _mock_ci_file("main", status=404)
        first = operations.inspect_ci("42", branch_spec="main", collect_variables=False)
        second = operations.inspect_ci(
            "42", branch_spec="main", collect_variables=False
        )
    assert project.call_count == 2
    assert set(first) == {
        "project",
        "branch_spec",
        "branch_selection",
        "lookback_days",
        "pipeline_window",
        "branches",
        "variables",
        "warnings",
        "truncated",
    }
    assert set(first) == set(second)
    assert first["project"] == second["project"]
    assert first["branches"][0]["ci_file"]["status"] == "not_found"


def test_ci_operation_uses_one_deadline_and_current_cancellation_contract():
    # GL-CI-10/11 legacy: gitlab_cicd_collector.py list loops/_collect_all
    _auth, _client, models, _operations_module, _tools = _modules()
    cancelled = _operations(cancel_check=lambda: True)
    with pytest.raises(models.GitLabError) as stopped:
        cancelled.inspect_ci("42")
    assert stopped.value.category == "cancelled"

    now = [0.0]
    operations = _operations(total_timeout_seconds=1.0, clock=lambda: now[0])

    def project_response(_request):
        now[0] += 0.6
        return httpx.Response(200, json=_project_json())

    def pipeline_response(_request):
        now[0] += 0.6
        return httpx.Response(200, headers={"X-Total": "0"}, json=[])

    with respx.mock:
        respx.get(PROJECT_API).mock(side_effect=project_response)
        respx.get(PIPELINES_API).mock(side_effect=pipeline_response)
        with pytest.raises(models.GitLabError) as timed_out:
            operations.inspect_ci("42", branch_spec="main", collect_variables=False)
    assert timed_out.value.category == "deadline"


def test_ci_schema_and_operation_bounds_reject_invalid_inputs_before_transport():
    # GL-CI-01/04/09/10 legacy: gitlab_cicd_collector.py:inputs and bounded list helpers
    _auth, _client, models, _operations_module, tools = _modules()
    schema = tools.SCHEMAS["gitlab_inspect_ci"]["parameters"]
    assert schema["required"] == ["project"]
    assert schema["additionalProperties"] is False
    assert set(schema["properties"]) == {
        "project",
        "branch_spec",
        "lookback_days",
        "collect_variables",
        "max_branches",
        "max_pages",
        "max_includes",
        "max_include_bytes",
        "max_groups",
        "max_variables",
    }

    operations = _operations()
    invalid = [
        {"branch_spec": ""},
        {"lookback_days": 0},
        {"max_branches": 0},
        {"max_pages": 0},
        {"max_includes": 0},
        {"max_include_bytes": 0},
        {"max_groups": 0},
        {"max_variables": 0},
    ]
    for options in invalid:
        with pytest.raises(models.GitLabError) as caught:
            operations.inspect_ci("42", **options)
        assert caught.value.category == "invalid_input"
