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


def _user(user_id=7, username="reviewer", name="Review Person"):
    return {
        "id": user_id,
        "username": username,
        "name": name,
        "state": "active",
        "avatar_url": "https://private.example.test/avatar.png",
        "email": "private@example.test",
    }


def _note(note_id=100, *, body="Please adjust this.", position=None):
    return {
        "id": note_id,
        "body": body,
        "author": _user(),
        "created_at": "2026-08-12T14:00:00Z",
        "updated_at": "2026-08-12T14:05:00+00:00",
        "system": False,
        "resolvable": True,
        "resolved": False,
        "resolved_by": None,
        "resolved_at": None,
        "position": position,
    }


def _merge_request(iid=17, *, state="opened", draft=False):
    return {
        "id": 900 + iid,
        "iid": iid,
        "title": "Improve event delivery",
        "state": state,
        "draft": draft,
        "source_branch": "feature/event-delivery",
        "target_branch": "main",
        "author": _user(8, "author", "MR Author"),
        "created_at": "2026-08-12T10:00:00Z",
        "updated_at": "2026-08-12T14:00:00+00:00",
        "merged_at": None,
        "closed_at": None,
        "labels": ["backend", "review-ready"],
        "user_notes_count": 4,
        "blocking_discussions_resolved": False,
        "web_url": f"{ORIGIN}/group/repo/-/merge_requests/{iid}",
    }


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


@pytest.mark.parametrize("commit", ["a" * 40, "release/2026", "v3.1.3"])
def test_commit_comments_normalize_display_safe_data_and_encode_commit_reference(commit):
    operations = _operations()
    seen = {}

    def response(request):
        seen["path"] = request.url.path
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[
                {
                    "note": "Line-level feedback",
                    "author": _user(),
                    "created_at": "2026-08-12T14:00:00Z",
                    "path": "src/core.py",
                    "line": 18,
                    "line_type": "new",
                }
            ],
        )

    encoded = commit.replace("/", "%2F")
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(
            f"{ORIGIN}/api/v4/projects/42/repository/commits/{encoded}/comments"
        ).mock(side_effect=response)
        result = operations.list_commit_comments(42, commit)

    assert seen["path"].endswith(f"/repository/commits/{commit}/comments")
    assert result["comments"] == [
        {
            "body": "Line-level feedback",
            "author": {
                "id": 7,
                "username": "reviewer",
                "name": "Review Person",
                "state": "active",
            },
            "created_at": "2026-08-12T14:00:00Z",
            "path": "src/core.py",
            "line": 18,
            "line_type": "new",
        }
    ]
    assert "email" not in repr(result).lower()
    assert "avatar" not in repr(result).lower()


def test_commit_discussions_bound_outer_pages_and_nested_notes_independently():
    operations = _operations()
    position = {
        "position_type": "text",
        "base_sha": "b" * 40,
        "start_sha": "c" * 40,
        "head_sha": "a" * 40,
        "old_path": "src/old.py",
        "new_path": "src/new.py",
        "old_line": 10,
        "new_line": 12,
    }
    discussions = [
        {
            "id": "discussion-one",
            "individual_note": False,
            "notes": [_note(1, position=position), _note(2)],
        },
        {
            "id": "discussion-two",
            "individual_note": True,
            "notes": [_note(3)],
        },
    ]
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(
            f"{ORIGIN}/api/v4/projects/42/repository/commits/main/discussions"
        ).mock(return_value=httpx.Response(200, json=discussions))
        result = operations.list_commit_discussions(
            42,
            "main",
            max_discussions=1,
            max_notes_per_discussion=1,
        )

    assert result["truncated"] is True
    assert result["continuation"] == {"page": 1, "offset": 1}
    assert result["discussions"][0]["id"] == "discussion-one"
    assert result["discussions"][0]["individual_note"] is False
    assert result["discussions"][0]["notes_truncated"] is True
    assert result["discussions"][0]["note_count"] == 2
    assert result["discussions"][0]["returned_note_count"] == 1
    assert result["discussions"][0]["notes"][0]["position"] == position
    assert result["discussions"][0]["notes"][0]["resolved"] is False
    assert "email" not in repr(result).lower()
    assert "avatar" not in repr(result).lower()


@pytest.mark.parametrize(
    "payload",
    [
        {"note": "body", "author": {**_user(), "id": "bad"}, "created_at": "2026-08-12T14:00:00Z", "path": None, "line": None, "line_type": None},
        {"note": "body", "author": _user(), "created_at": "bad", "path": None, "line": None, "line_type": None},
        {"note": "body", "author": _user(), "created_at": "2026-08-12T14:00:00Z", "path": "../secret", "line": 1, "line_type": "new"},
        {"note": "body", "author": _user(), "created_at": "2026-08-12T14:00:00Z", "path": None, "line": True, "line_type": None},
        {"note": "x" * (128 * 1024 + 1), "author": _user(), "created_at": "2026-08-12T14:00:00Z", "path": None, "line": None, "line_type": None},
    ],
)
def test_commit_comments_reject_malformed_authors_dates_lines_and_oversized_bodies(payload):
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(
            f"{ORIGIN}/api/v4/projects/42/repository/commits/main/comments"
        ).mock(return_value=httpx.Response(200, json=[payload]))
        with pytest.raises(Exception) as caught:
            _operations().list_commit_comments(42, "main")
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


@pytest.mark.parametrize(
    "mutation",
    [
        {"individual_note": "false"},
        {"notes": "not-a-list"},
        {"notes": [{**_note(), "system": "false"}]},
        {"notes": [{**_note(), "resolved": "false"}]},
        {"notes": [{**_note(), "position": {"position_type": "unknown"}}]},
    ],
)
def test_commit_discussions_reject_malformed_nested_discussion_data(mutation):
    discussion = {
        "id": "discussion-one",
        "individual_note": False,
        "notes": [_note()],
        **mutation,
    }
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(
            f"{ORIGIN}/api/v4/projects/42/repository/commits/main/discussions"
        ).mock(return_value=httpx.Response(200, json=[discussion]))
        with pytest.raises(Exception) as caught:
            _operations().list_commit_discussions(42, "main")
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


@pytest.mark.parametrize(
    ("requested", "sent"),
    [("open", "opened"), ("opened", "opened"), ("closed", "closed"), ("merged", "merged"), ("all", "all")],
)
def test_merge_request_listing_supports_states_filters_ordering_and_safe_normalization(
    requested, sent
):
    operations = _operations()
    seen = {}

    def response(request):
        seen.update(dict(request.url.params))
        return httpx.Response(
            200,
            headers={"X-Next-Page": ""},
            json=[_merge_request()],
        )

    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests").mock(
            side_effect=response
        )
        result = operations.list_merge_requests(
            42,
            state=requested,
            source_branch="feature/event-delivery",
            target_branch="main",
            search="delivery",
            order_by="updated_at",
            sort="desc",
        )

    assert seen["state"] == sent
    assert seen["scope"] == "all"
    assert seen["source_branch"] == "feature/event-delivery"
    assert seen["target_branch"] == "main"
    assert seen["search"] == "delivery"
    assert seen["order_by"] == "updated_at"
    assert seen["sort"] == "desc"
    assert result["merge_requests"] == [
        {
            "id": 917,
            "iid": 17,
            "title": "Improve event delivery",
            "state": "opened",
            "draft": False,
            "source_branch": "feature/event-delivery",
            "target_branch": "main",
            "author": {
                "id": 8,
                "username": "author",
                "name": "MR Author",
                "state": "active",
            },
            "created_at": "2026-08-12T10:00:00Z",
            "updated_at": "2026-08-12T14:00:00Z",
            "merged_at": None,
            "closed_at": None,
            "labels": ["backend", "review-ready"],
            "note_count": 4,
            "discussion_resolution": {"all_resolved": False},
            "web_url": f"{ORIGIN}/group/repo/-/merge_requests/17",
        }
    ]
    assert "email" not in repr(result).lower()
    assert "avatar" not in repr(result).lower()


def test_merge_request_listing_maps_lookback_to_created_and_updated_activity_explicitly():
    from datetime import datetime, timezone

    operations = _operations(
        now=lambda: datetime(2026, 8, 12, 15, 30, tzinfo=timezone.utc)
    )
    requests = []

    def response(request):
        requests.append(dict(request.url.params))
        return httpx.Response(200, headers={"X-Next-Page": ""}, json=[])

    with respx.mock:
        project = respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        project.side_effect = [
            httpx.Response(200, json=_project(42, "group/repo")),
            httpx.Response(200, json=_project(42, "group/repo")),
        ]
        respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests").mock(
            side_effect=response
        )
        new_result = operations.list_merge_requests(42, lookback_hours=24)
        active_result = operations.list_merge_requests(
            42, updated_after="2026-08-12T12:00:00+00:00"
        )

    assert requests[0]["created_after"] == "2026-08-11T15:30:00Z"
    assert "updated_after" not in requests[0]
    assert requests[1]["updated_after"] == "2026-08-12T12:00:00Z"
    assert "created_after" not in requests[1]
    assert new_result["activity_basis"] == "created"
    assert active_result["activity_basis"] == "updated"


@pytest.mark.parametrize(
    "kwargs",
    [
        {"lookback_hours": 24, "created_after": "2026-08-12T00:00:00Z"},
        {"lookback_hours": 24, "updated_after": "2026-08-12T00:00:00Z"},
        {"created_after": "2026-08-12T00:00:00Z", "updated_after": "2026-08-12T00:00:00Z"},
        {"state": "invalid"},
        {"order_by": "title"},
        {"sort": "sideways"},
    ],
)
def test_merge_request_listing_rejects_ambiguous_windows_and_invalid_filters(kwargs):
    with pytest.raises(Exception) as caught:
        _operations().list_merge_requests(42, **kwargs)
    assert getattr(caught.value, "category", None) == "invalid_input"


def test_merge_request_commits_reuse_safe_commit_normalization_and_pagination():
    operations = _operations()
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests/17/commits").mock(
            return_value=httpx.Response(
                200,
                json=[_commit(), _commit("c" * 40, short_sha="c" * 8)],
            )
        )
        result = operations.list_merge_request_commits(42, 17, max_items=1)
    assert result["iid"] == 17
    assert result["commits"][0]["sha"] == "a" * 40
    assert result["continuation"] == {"page": 1, "offset": 1}
    assert "email" not in repr(result).lower()


def test_merge_request_discussions_reuse_resolution_and_position_normalization():
    operations = _operations()
    resolved_note = {
        **_note(
            1,
            position={
                "position_type": "text",
                "base_sha": "b" * 40,
                "start_sha": "c" * 40,
                "head_sha": "a" * 40,
                "old_path": "src/old.py",
                "new_path": "src/new.py",
                "old_line": 10,
                "new_line": 12,
            },
        ),
        "resolved": True,
        "resolved_by": _user(9, "resolver", "Resolver"),
        "resolved_at": "2026-08-12T15:00:00Z",
    }
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(
            f"{ORIGIN}/api/v4/projects/42/merge_requests/17/discussions"
        ).mock(
            return_value=httpx.Response(
                200,
                headers={"X-Next-Page": ""},
                json=[
                    {
                        "id": "mr-thread",
                        "individual_note": False,
                        "notes": [resolved_note],
                    }
                ],
            )
        )
        result = operations.list_merge_request_discussions(42, 17)
    assert result["iid"] == 17
    assert result["resolution_summary"] == {
        "resolvable_notes": 1,
        "resolved_notes": 1,
        "unresolved_notes": 0,
    }
    assert result["discussions"][0]["notes"][0]["resolved_by"]["username"] == (
        "resolver"
    )


@pytest.mark.parametrize(
    "mutation",
    [
        {"iid": 0},
        {"state": "unknown"},
        {"draft": "false"},
        {"created_at": "naive"},
        {"labels": [1]},
        {"author": {**_user(), "username": ""}},
        {"web_url": "https://foreign.example.test/mr/17"},
        {"blocking_discussions_resolved": "false"},
    ],
)
def test_merge_request_listing_rejects_malformed_remote_items(mutation):
    with respx.mock:
        respx.get(f"{ORIGIN}/api/v4/projects/42").mock(
            return_value=httpx.Response(200, json=_project(42, "group/repo"))
        )
        respx.get(f"{ORIGIN}/api/v4/projects/42/merge_requests").mock(
            return_value=httpx.Response(200, json=[{**_merge_request(), **mutation}])
        )
        with pytest.raises(Exception) as caught:
            _operations().list_merge_requests(42)
    assert getattr(caught.value, "category", None) == "invalid_remote_data"
