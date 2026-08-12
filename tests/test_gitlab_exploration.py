from __future__ import annotations

import importlib
import sys
from pathlib import Path

import httpx
import pytest
import respx


PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
ORIGIN = "https://gitlab.example.test"


def _modules():
    if str(PLUGIN) not in sys.path:
        sys.path.insert(0, str(PLUGIN))
    return (
        importlib.import_module("auth"),
        importlib.import_module("client"),
        importlib.import_module("models"),
        importlib.import_module("operations"),
    )


def _operations(*, now=None, **client_options):
    auth, client, _models, operations = _modules()
    credentials = auth.GitLabAuth(
        origin=ORIGIN,
        pat="secret-token",
        certificate_pair=None,
    )
    return operations.GitLabOperations(
        client.GitLabClient(credentials, **client_options),
        **({"now": now} if now is not None else {}),
    )


def _group(group_id=10, full_path="sd-macs-att-rnam-hosting", parent_id=None):
    return {
        "id": group_id,
        "name": full_path.rsplit("/", 1)[-1],
        "full_path": full_path,
        "web_url": f"{ORIGIN}/{full_path}",
        "parent_id": parent_id,
    }


def _project(
    project_id,
    path_with_namespace,
    *,
    archived=False,
    namespace_kind="group",
):
    namespace = path_with_namespace.rsplit("/", 1)[0]
    return {
        "id": project_id,
        "name": path_with_namespace.rsplit("/", 1)[-1],
        "path_with_namespace": path_with_namespace,
        "default_branch": "main",
        "web_url": f"{ORIGIN}/{path_with_namespace}",
        "archived": archived,
        "namespace": {"kind": namespace_kind, "full_path": namespace},
    }


def _commit(
    sha="a" * 40,
    *,
    short_sha="a" * 8,
    committed_date="2026-08-12T13:00:00Z",
    stats=None,
):
    payload = {
        "id": sha,
        "short_id": short_sha,
        "created_at": committed_date,
        "parent_ids": ["b" * 40],
        "title": "Fix the thing",
        "message": "Fix the thing\n\nDetailed commit message.",
        "author_name": "Ada Author",
        "author_email": "ada@example.test",
        "authored_date": "2026-08-12T12:55:00+00:00",
        "committer_name": "Casey Committer",
        "committer_email": "casey@example.test",
        "committed_date": committed_date,
        "web_url": f"{ORIGIN}/group/repo/-/commit/{sha}",
    }
    if stats is not None:
        payload["stats"] = stats
    return payload


@pytest.mark.parametrize(
    "reference",
    [
        "sd-macs-att-rnam-hosting",
        f"{ORIGIN}/sd-macs-att-rnam-hosting",
        "10",
    ],
)
def test_group_discovery_resolves_group_and_preserves_empty_subgroups(reference):
    operations = _operations()
    seen = {}

    def projects_response(request):
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[
                _project(31, "sd-macs-att-rnam-hosting/oscar_app/eventmesh"),
                _project(30, "sd-macs-att-rnam-hosting/root-repo"),
            ],
        )

    endpoint = "10" if reference == "10" else "sd-macs-att-rnam-hosting"
    with respx.mock:
        root = respx.get(f"{ORIGIN}/api/v4/groups/{endpoint}").mock(
            return_value=httpx.Response(200, json=_group())
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/descendant_groups").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[
                    _group(12, "sd-macs-att-rnam-hosting/empty", 10),
                    _group(11, "sd-macs-att-rnam-hosting/oscar_app", 10),
                ],
            )
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/projects").mock(
            side_effect=projects_response
        )
        result = operations.list_group_projects(reference)

    assert root.called
    assert seen == {
        "include_subgroups": "true",
        "with_shared": "false",
        "archived": "false",
        "order_by": "path",
        "sort": "asc",
        "per_page": "100",
        "page": "1",
    }
    assert result["root_group"]["full_path"] == "sd-macs-att-rnam-hosting"
    assert [group["full_path"] for group in result["groups"]] == [
        "sd-macs-att-rnam-hosting",
        "sd-macs-att-rnam-hosting/empty",
        "sd-macs-att-rnam-hosting/oscar_app",
    ]
    assert result["groups"][1]["project_count"] == 0
    assert [project["path_with_namespace"] for project in result["projects"]] == [
        "sd-macs-att-rnam-hosting/oscar_app/eventmesh",
        "sd-macs-att-rnam-hosting/root-repo",
    ]
    assert result["projects"][0]["owning_namespace"] == (
        "sd-macs-att-rnam-hosting/oscar_app"
    )
    assert result["projects"][0]["shared"] is False
    assert result["complete"] is True


def test_group_discovery_filters_shared_and_archived_by_default_and_labels_continuations():
    operations = _operations(max_pages=4)
    project_page = [
        _project(1, "root/one"),
        _project(2, "outside/shared"),
        _project(3, "root/archived", archived=True),
    ]
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/groups/root").mock(
            return_value=httpx.Response(200, json=_group(10, "root"))
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/descendant_groups").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": "2"},
                json=[_group(11, "root/a", 10), _group(12, "root/b", 10)],
            )
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/projects").mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": "2"},
                json=project_page,
            )
        )
        result = operations.list_group_projects(
            "root",
            max_groups=2,
            max_projects=1,
        )

    assert [group["full_path"] for group in result["groups"]] == ["root", "root/a"]
    assert [project["path_with_namespace"] for project in result["projects"]] == [
        "root/one"
    ]
    assert result["truncated"] is True
    assert result["complete"] is False
    assert result["continuation"] == {
        "groups": {"page": 1, "offset": 1},
        "projects": {"page": 1, "offset": 1},
    }


def test_group_discovery_can_include_shared_archived_and_resume_sources_independently():
    operations = _operations()
    seen = []

    def response(request):
        seen.append((request.url.path, dict(request.url.params)))
        if request.url.path.endswith("descendant_groups"):
            return httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[_group(12, "root/b", 10)],
            )
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[
                _project(2, "outside/shared"),
                _project(3, "root/archived", archived=True),
            ],
        )

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/groups/root").mock(
            return_value=httpx.Response(200, json=_group(10, "root"))
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/descendant_groups").mock(
            side_effect=response
        )
        respx.get(f"{ORIGIN}/api/v4/groups/10/projects").mock(side_effect=response)
        result = operations.list_group_projects(
            "root",
            include_shared=True,
            include_archived=True,
            continuation={
                "groups": {"page": 1, "offset": 0},
                "projects": {"page": 1, "offset": 0},
            },
        )

    assert result["projects"][0]["shared"] is True
    assert result["projects"][1]["archived"] is True
    project_params = next(params for path, params in seen if path.endswith("/projects"))
    assert project_params["with_shared"] == "true"
    assert project_params["archived"] == "true"


@pytest.mark.parametrize(
    "reference",
    [
        "https://foreign.example.test/root",
        f"{ORIGIN}/root/-/projects/1",
        "/root",
        "root//child",
    ],
)
def test_group_discovery_rejects_foreign_project_style_and_malformed_references(reference):
    with pytest.raises(Exception) as caught:
        _operations().list_group_projects(reference)
    assert getattr(caught.value, "category", None) == "invalid_input"


@pytest.mark.parametrize(
    "payload",
    [
        {**_group(), "parent_id": "bad"},
        {**_group(), "full_path": "root//child"},
        {**_group(), "web_url": "https://foreign.example.test/root"},
        ["not-an-object"],
    ],
)
def test_group_discovery_rejects_invalid_remote_root_shapes(payload):
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/groups/root").mock(
            return_value=httpx.Response(200, json=payload)
        )
        with pytest.raises(Exception) as caught:
            _operations().list_group_projects("root")
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_commit_history_lists_latest_first_with_ref_path_and_time_filters():
    operations = _operations()
    seen = {}

    def commits_response(request):
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[_commit(), _commit("c" * 40, short_sha="c" * 8)],
        )

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/group%2Frepo").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/commits").mock(
            side_effect=commits_response
        )
        result = operations.list_commits(
            "group/repo",
            ref="release/2026",
            path="src/core.py",
            since="2026-08-11T00:00:00Z",
            until="2026-08-12T14:00:00+00:00",
        )

    assert seen["ref_name"] == "release/2026"
    assert seen["path"] == "src/core.py"
    assert seen["since"] == "2026-08-11T00:00:00Z"
    assert seen["until"] == "2026-08-12T14:00:00Z"
    assert seen["order"] == "default"
    assert result["project"]["id"] == 42
    assert result["ref"] == "release/2026"
    assert result["commits"][0] == {
        "sha": "a" * 40,
        "short_sha": "a" * 8,
        "title": "Fix the thing",
        "message": "Fix the thing\n\nDetailed commit message.",
        "author_name": "Ada Author",
        "committer_name": "Casey Committer",
        "authored_at": "2026-08-12T12:55:00Z",
        "committed_at": "2026-08-12T13:00:00Z",
        "created_at": "2026-08-12T13:00:00Z",
        "parent_shas": ["b" * 40],
        "web_url": f"{ORIGIN}/group/repo/-/commit/{'a' * 40}",
    }
    assert "email" not in repr(result).lower()


def test_commit_history_uses_default_ref_and_injected_utc_lookback():
    from datetime import datetime, timezone

    operations = _operations(
        now=lambda: datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)
    )
    seen = {}

    def response(request):
        seen.update(dict(request.url.params))
        return httpx.Response(200, headers={"X-Next-Page": ""}, json=[])

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(
                200,
                json={**_project(42, "group/repo"), "default_branch": "develop"},
            )
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/commits").mock(
            side_effect=response
        )
        result = operations.list_commits(42, lookback_hours=24)

    assert result["ref"] == "develop"
    assert seen["ref_name"] == "develop"
    assert seen["since"] == "2026-08-11T15:30:00Z"
    assert result["time_window"] == {
        "since": "2026-08-11T15:30:00Z",
        "until": None,
        "lookback_hours": 24,
    }


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lookback_hours": 24, "since": "2026-08-11T00:00:00Z"},
        {"since": "2026-08-11T00:00:00"},
        {"until": "not-a-date"},
        {"lookback_hours": 0},
    ],
)
def test_commit_history_rejects_conflicting_or_invalid_time_filters(kwargs):
    with pytest.raises(Exception) as caught:
        _operations().list_commits("group/repo", ref="main", **kwargs)
    assert getattr(caught.value, "category", None) == "invalid_input"


def test_commit_history_returns_mid_page_continuation_without_total_headers():
    operations = _operations()
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/commits").mock(
            return_value=httpx.Response(
                200,
                json=[_commit(), _commit("c" * 40, short_sha="c" * 8)],
            )
        )
        result = operations.list_commits(42, ref="main", max_items=1)
    assert len(result["commits"]) == 1
    assert result["truncated"] is True
    assert result["continuation"] == {"page": 1, "offset": 1}


def test_read_commit_returns_normalized_detail_and_bounded_stats():
    operations = _operations()
    sha = "a" * 40
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/commits/{sha}").mock(
            return_value=httpx.Response(
                200,
                json=_commit(sha, stats={"additions": 12, "deletions": 3, "total": 15}),
            )
        )
        result = operations.read_commit(42, sha)
    assert result["commit"]["sha"] == sha
    assert result["commit"]["stats"] == {
        "additions": 12,
        "deletions": 3,
        "total": 15,
    }
    assert "email" not in repr(result).lower()


@pytest.mark.parametrize(
    "mutator",
    [
        lambda value: {**value, "id": "not-a-sha"},
        lambda value: {**value, "short_id": "xyz"},
        lambda value: {**value, "committed_date": "2026-08-12T13:00:00"},
        lambda value: {**value, "parent_ids": ["bad"]},
        lambda value: {**value, "web_url": "https://foreign.example.test/commit"},
        lambda value: {**value, "stats": {"additions": -1, "deletions": 0, "total": 0}},
    ],
)
def test_read_commit_rejects_malformed_remote_commit_data(mutator):
    sha = "a" * 40
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/repository/commits/{sha}").mock(
            return_value=httpx.Response(
                200,
                json=mutator(_commit(sha, stats={"additions": 1, "deletions": 0, "total": 1})),
            )
        )
        with pytest.raises(Exception) as caught:
            _operations().read_commit(42, sha)
    assert getattr(caught.value, "category", None) == "invalid_remote_data"
