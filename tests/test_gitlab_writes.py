from __future__ import annotations

import importlib
import importlib.util
import json
import sys
import uuid
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import quote

import httpx
import pytest
import respx


REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-gitlab"
ORIGIN = "https://gitlab.example.test"
PROJECT_API = f"{ORIGIN}/api/v4/projects/42"
WRITE_TOOLS = {
    "gitlab_create_branch",
    "gitlab_commit_changes",
    "gitlab_create_merge_request",
}


def _modules():
    assert PLUGIN.is_dir(), "Task 10 GitLab plugin production surface is missing"
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
        pat="write-secret-token",
        certificate_pair=None,
    )
    client_options.setdefault("max_retries", 2)
    return operations.GitLabOperations(
        client.GitLabClient(credentials, **client_options)
    )


def _project(default_branch="main", *, project_id=42):
    return {
        "id": project_id,
        "name": "repo",
        "path_with_namespace": "division/platform/repo",
        "default_branch": default_branch,
        "web_url": f"{ORIGIN}/division/platform/repo",
        "namespace": {"full_path": "division/platform"},
    }


def _branch(name="feature/abc-123-safe-change", sha="source-sha"):
    return {
        "name": name,
        "web_url": f"{ORIGIN}/division/platform/repo/-/tree/{name}",
        "commit": {"id": sha},
    }


def _head_file(path, *, status=200, last_commit_id="previous-sha"):
    headers = {"X-Gitlab-Last-Commit-Id": last_commit_id} if last_commit_id else {}
    encoded = quote(path, safe="")
    return respx.head(f"{PROJECT_API}/repository/files/{encoded}").mock(
        return_value=httpx.Response(status, headers=headers)
    )


def _mock_project(default_branch="main"):
    return respx.get(PROJECT_API).mock(
        return_value=httpx.Response(200, json=_project(default_branch))
    )


def _commit(identifier="commit-sha", *, title="Apply safe change"):
    return {
        "id": identifier,
        "short_id": identifier[:8],
        "title": title,
        "web_url": f"{ORIGIN}/division/platform/repo/-/commit/{identifier}",
    }


def _mr(
    iid=7,
    *,
    source="feature/abc-123",
    target="main",
    title="ABC-123",
    project_id=42,
):
    return {
        "id": 700 + iid,
        "iid": iid,
        "project_id": project_id,
        "title": title,
        "state": "opened",
        "source_branch": source,
        "target_branch": target,
        "web_url": f"{ORIGIN}/division/platform/repo/-/merge_requests/{iid}",
    }


def _load_plugin():
    module_name = f"ericsson_gitlab_task10_test_{uuid.uuid4().hex}"
    spec = importlib.util.spec_from_file_location(
        module_name,
        PLUGIN / "__init__.py",
        submodule_search_locations=[str(PLUGIN)],
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


class _Configuration:
    def setting(self, field_id):
        return {
            "origin": ORIGIN,
            "client_certificate_path": "",
            "client_key_path": "",
        }[field_id]

    def secret(self, field_id):
        assert field_id == "pat"
        return "write-secret-token"


class _Context:
    def __init__(self):
        self.registrations = {}
        self.hooks = {}

    def configuration(self):
        return _Configuration()

    def register_tool(self, **registration):
        self.registrations[registration["name"]] = registration

    def register_hook(self, name, callback):
        self.hooks[name] = callback


def _admission(name):
    # Public handler contract is deliberately duck-typed. The real immutable,
    # one-shot value is host-minted and delivered only by PluginContext.
    return SimpleNamespace(approved=True, policy="plugin_approve", tool_name=name)


def test_branch_name_source_default_reuse_and_error_classification():
    # GL-WRITE-01/02/03 legacy: gitlab_branch_creator.py:GitLabBranchCreator._slugify/create_branch
    operations = _operations(max_retries=0)
    created = _branch("feature/ABC-123-safe-change")
    seen = []

    def create_response(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json=created)

    with respx.mock:
        project_route = respx.get(PROJECT_API)
        project_route.side_effect = [
            httpx.Response(200, json=_project("release/2026")),
            httpx.Response(200, json=_project("release/2026")),
            httpx.Response(200, json=_project("release/2026")),
        ]
        branch_route = respx.get(
            f"{PROJECT_API}/repository/branches/feature%2FABC-123-safe-change"
        )
        branch_route.side_effect = [
            httpx.Response(404, json={"message": "missing"}),
            httpx.Response(200, json=created),
            httpx.Response(403, text="private remote diagnostic"),
        ]
        respx.post(f"{PROJECT_API}/repository/branches").mock(
            side_effect=create_response
        )

        made = operations.create_branch(
            "42",
            prefix="feature/",
            ticket_key="ABC-123",
            summary="Safe Change",
            source_ref=None,
        )
        reused = operations.create_branch(
            "42",
            prefix="feature",
            ticket_key="ABC-123",
            summary="Safe Change",
            source_ref="release/2026",
        )
        with pytest.raises(Exception) as caught:
            operations.create_branch(
                "42",
                prefix="feature",
                ticket_key="ABC-123",
                summary="Safe Change",
            )

    assert seen == [{"branch": "feature/ABC-123-safe-change", "ref": "release/2026"}]
    assert made == {
        "project": "42",
        "branch": "feature/ABC-123-safe-change",
        "source_ref": "release/2026",
        "commit_id": "source-sha",
        "web_url": f"{ORIGIN}/division/platform/repo/-/tree/feature/ABC-123-safe-change",
        "created": True,
        "reused": False,
        "dry_run": False,
    }
    assert reused["created"] is False and reused["reused"] is True
    assert getattr(caught.value, "category", None) == "permission"
    assert "private" not in str(caught.value)


def test_branch_dry_run_requires_no_mutating_request_and_returns_bounded_preview():
    # GL-WRITE-03 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch
    operations = _operations()
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        result = operations.create_branch(
            "42",
            ticket_key="ABC-123",
            summary="Dry run",
            source_ref=None,
            dry_run=True,
        )
        assert not any(call.request.method != "GET" for call in respx.calls)
    assert result == {
        "project": "42",
        "branch": "fix/ABC-123-dry-run",
        "source_ref": "main",
        "created": False,
        "reused": False,
        "dry_run": True,
    }


def test_branch_public_contract_builds_exact_legacy_slug_and_does_not_accept_full_branch():
    # GL-WRITE-01 legacy: gitlab_branch_creator.py:GitLabBranchCreator._slugify/create_branch
    _auth, _client, models, _operations_module, tools = _modules()
    schema = tools.SCHEMAS["gitlab_create_branch"]["parameters"]
    assert schema["required"] == ["project", "ticket_key", "summary"]
    assert set(schema["properties"]) == {
        "project",
        "prefix",
        "ticket_key",
        "summary",
        "source_ref",
        "dry_run",
    }
    assert schema["properties"]["prefix"]["default"] == "fix"
    operations = _operations()
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        result = operations.create_branch(
            "42",
            prefix="fix///",
            ticket_key="ABC-123",
            summary="  This IS a very long summary!! with tail  ",
            source_ref="main",
            dry_run=True,
        )
        with pytest.raises(models.GitLabError) as caught:
            tools.invoke(
                "gitlab_create_branch",
                {"project": "42", "branch": "caller/composed"},
                _Configuration(),
            )
    assert result["branch"] == "fix/ABC-123-this-is-a-very-long-summary-wi"
    assert not result["branch"].endswith("-")
    assert caught.value.category == "invalid_input"


@pytest.mark.parametrize(
    ("prefix", "ticket_key", "summary"),
    [
        ("", "ABC-123", "safe"),
        ("../fix", "ABC-123", "safe"),
        ("fix", "ABC 123", "safe"),
        ("fix", "ABC-123", "---"),
        ("fix\nsecret", "ABC-123", "safe"),
        ("a" * 513, "ABC-123", "safe"),
    ],
)
def test_branch_validation_rejects_invalid_parts_before_transport(
    prefix, ticket_key, summary
):
    # GL-WRITE-01 legacy: gitlab_branch_creator.py:GitLabBranchCreator._slugify/create_branch
    operations = _operations()
    with respx.mock:
        with pytest.raises(Exception) as caught:
            operations.create_branch(
                "42",
                prefix=prefix,
                ticket_key=ticket_key,
                summary=summary,
                source_ref="main",
            )
        assert respx.calls.call_count == 0
    assert getattr(caught.value, "category", None) == "invalid_input"


@pytest.mark.parametrize(
    "invalid_ref",
    [
        "bad ref",
        "bad..ref",
        "bad@{ref",
        ".hidden",
        "refs/heads/topic.lock",
        "bad\\ref",
        "bad~1",
        "bad^ref",
        "bad:ref",
        "bad?ref",
        "bad*ref",
        "bad[ref",
        "bad//ref",
        "bad.",
        "@",
    ],
)
def test_commit_branch_rejects_git_check_ref_format_violations_before_transport(
    invalid_ref,
):
    # GL-WRITE-05/06 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations()
    with respx.mock:
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch=invalid_ref,
                commit_message="Safe",
                actions=[{"action": "create", "file_path": "x", "content": "x"}],
            )
        assert respx.calls.call_count == 0
    assert getattr(caught.value, "category", None) == "invalid_input"


def test_source_target_and_last_commit_refs_are_strictly_validated_before_transport():
    # GL-WRITE-02/06/08 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch; gitlab_commit_pusher.py:GitLabCommitPusher.push_commit; gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations()
    calls = (
        lambda: operations.create_branch(
            "42",
            ticket_key="ABC-123",
            summary="safe",
            source_ref="release bad",
        ),
        lambda: operations.commit_changes(
            "42",
            branch="feature/ABC-123-safe",
            commit_message="Safe",
            actions=[
                {
                    "action": "update",
                    "file_path": "x",
                    "content": "x",
                    "last_commit_id": "bad sha",
                }
            ],
        ),
        lambda: operations.create_merge_request(
            "42", source_branch="feature/ABC-123-safe", target_branch="bad target"
        ),
    )
    with respx.mock:
        for invoke in calls:
            with pytest.raises(Exception) as caught:
                invoke()
            assert getattr(caught.value, "category", None) == "invalid_input"
        assert respx.calls.call_count == 0


def test_branch_create_partial_response_reconciles_exact_identity_once():
    # GL-WRITE-02/10 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch
    operations = _operations(max_retries=2)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        branch_route = respx.get(
            f"{PROJECT_API}/repository/branches/feature%2FABC-123-safe"
        )
        branch_route.side_effect = [
            httpx.Response(404, json={"message": "missing"}),
            httpx.Response(200, json=_branch("feature/ABC-123-safe", "source-sha")),
        ]
        post = respx.post(f"{PROJECT_API}/repository/branches").mock(
            return_value=httpx.Response(201, json={"name": "feature/ABC-123-safe"})
        )
        result = operations.create_branch(
            "42",
            prefix="feature",
            ticket_key="ABC-123",
            summary="safe",
            source_ref="main",
        )
    assert post.call_count == 1
    assert result["branch"] == "feature/ABC-123-safe"
    assert result["commit_id"] == "source-sha"
    assert result["created"] is True


def test_branch_partial_post_identity_must_match_reconciliation_get_identity():
    # GL-WRITE-02/10 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch
    operations = _operations(max_retries=0)
    branch = "feature/ABC-123-safe"
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        branch_route = respx.get(
            f"{PROJECT_API}/repository/branches/feature%2FABC-123-safe"
        )
        branch_route.side_effect = [
            httpx.Response(404, json={"message": "missing"}),
            httpx.Response(
                200,
                json={
                    **_branch(branch, "sha-B"),
                    "project_id": 42,
                    "commit": {
                        "id": "sha-B",
                        "short_id": "sha-B",
                        "web_url": f"{ORIGIN}/division/platform/repo/-/commit/sha-B",
                    },
                },
            ),
        ]
        respx.post(f"{PROJECT_API}/repository/branches").mock(
            return_value=httpx.Response(
                201,
                json={
                    "name": branch,
                    "project_id": 42,
                    "commit": {
                        "id": "sha-A",
                        "short_id": "sha-A",
                        "web_url": f"{ORIGIN}/division/platform/repo/-/commit/sha-A",
                    },
                },
            )
        )
        with pytest.raises(Exception) as caught:
            operations.create_branch(
                "42",
                prefix="feature",
                ticket_key="ABC-123",
                summary="safe",
                source_ref="main",
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


@pytest.mark.parametrize("malformed_project_id", [True, 1.0])
@pytest.mark.parametrize("partial", [False, True])
def test_branch_full_and_partial_project_identity_require_an_exact_integer(
    malformed_project_id, partial
):
    # GL-WRITE-02/10 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch
    operations = _operations(max_retries=0)
    branch = "feature/ABC-123-safe"
    branch_api = (
        f"{ORIGIN}/api/v4/projects/1/repository/branches/feature%2FABC-123-safe"
    )
    post_payload = {
        **_branch(branch, "sha-A"),
        "project_id": malformed_project_id,
    }
    if partial:
        post_payload.pop("web_url")
    with respx.mock:
        respx.get(PROJECT_API).mock(
            return_value=httpx.Response(200, json=_project(project_id=1))
        )
        branch_route = respx.get(branch_api)
        branch_route.side_effect = [
            httpx.Response(404, json={"message": "missing"}),
            httpx.Response(
                200,
                json={**_branch(branch, "sha-A"), "project_id": 1},
            ),
        ]
        respx.post(f"{ORIGIN}/api/v4/projects/1/repository/branches").mock(
            return_value=httpx.Response(201, json=post_payload)
        )
        with pytest.raises(Exception) as caught:
            operations.create_branch(
                "42",
                prefix="feature",
                ticket_key="ABC-123",
                summary="safe",
                source_ref="main",
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_branch_contradictory_response_is_not_reconciled_as_partial():
    # GL-WRITE-02/10 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch
    operations = _operations(max_retries=0)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.get(f"{PROJECT_API}/repository/branches/feature%2FABC-123-safe").mock(
            return_value=httpx.Response(404, json={"message": "missing"})
        )
        respx.post(f"{PROJECT_API}/repository/branches").mock(
            return_value=httpx.Response(201, json=_branch("feature/other"))
        )
        with pytest.raises(Exception) as caught:
            operations.create_branch(
                "42",
                prefix="feature",
                ticket_key="ABC-123",
                summary="safe",
                source_ref="main",
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


@pytest.mark.parametrize(
    "contradiction",
    [
        {"commit": {"id": ""}},
        {"commit": {"id": "source-sha", "short_id": "different"}},
        {"web_url": f"{ORIGIN}/other/project/-/tree/feature/ABC-123-safe"},
        {"project_id": 99},
    ],
)
def test_branch_partial_response_rejects_every_present_contradictory_identity(
    contradiction,
):
    # GL-WRITE-02/10 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch
    operations = _operations(max_retries=0)
    with respx.mock:
        get_branch = respx.get(
            f"{PROJECT_API}/repository/branches/feature%2FABC-123-safe"
        ).mock(return_value=httpx.Response(404, json={"message": "missing"}))
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.post(f"{PROJECT_API}/repository/branches").mock(
            return_value=httpx.Response(
                201,
                json={"name": "feature/ABC-123-safe", **contradiction},
            )
        )
        with pytest.raises(Exception) as caught:
            operations.create_branch(
                "42",
                prefix="feature",
                ticket_key="ABC-123",
                summary="safe",
                source_ref="main",
            )
    assert get_branch.call_count == 1
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_branch_duplicate_race_reconciles_without_repeating_mutation():
    # GL-WRITE-02/10 legacy: gitlab_branch_creator.py:GitLabBranchCreator.create_branch
    operations = _operations(max_retries=4)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        branch_route = respx.get(
            f"{PROJECT_API}/repository/branches/feature%2FABC-123-safe"
        )
        branch_route.side_effect = [
            httpx.Response(404, json={"message": "missing"}),
            httpx.Response(200, json=_branch("feature/ABC-123-safe", "source-sha")),
        ]
        post = respx.post(f"{PROJECT_API}/repository/branches").mock(
            return_value=httpx.Response(409, json={"message": "Branch already exists"})
        )
        result = operations.create_branch(
            "42",
            prefix="feature",
            ticket_key="ABC-123",
            summary="safe",
            source_ref="main",
        )
    assert post.call_count == 1
    assert result["created"] is False and result["reused"] is True


def test_atomic_commit_projects_create_update_delete_without_content():
    # GL-WRITE-05/06 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit (inline action loop)
    operations = _operations(max_retries=0)
    actions = [
        {"action": "create", "file_path": "src/new.py", "content": "new secret"},
        {
            "action": "update",
            "file_path": "src/current.py",
            "content": "updated secret",
            "last_commit_id": "previous-sha",
        },
        {
            "action": "delete",
            "file_path": "src/old.py",
            "last_commit_id": "previous-sha",
        },
    ]
    seen = []

    def response(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json=_commit())

    with respx.mock:
        _mock_project()
        _head_file("src/new.py", status=404)
        _head_file("src/current.py", last_commit_id="previous-sha")
        _head_file("src/old.py", last_commit_id="previous-sha")
        route = respx.post(f"{PROJECT_API}/repository/commits").mock(
            side_effect=response
        )
        result = operations.commit_changes(
            "42",
            branch="feature/abc-123",
            commit_message="Apply safe change",
            actions=actions,
        )
    assert route.call_count == 1
    assert seen == [
        {
            "branch": "feature/abc-123",
            "commit_message": "Apply safe change",
            "actions": actions,
        }
    ]
    assert result["action_count"] == 3
    assert result["actions"] == [
        {"action": "create", "file_path": "src/new.py"},
        {"action": "update", "file_path": "src/current.py"},
        {"action": "delete", "file_path": "src/old.py"},
    ]
    assert "secret" not in repr(result)
    assert result["commit_id"] == "commit-sha"


@pytest.mark.parametrize(
    "actions",
    [
        [],
        [{"action": "move", "file_path": "x", "content": "x"}],
        [{"action": "create", "file_path": "../escape", "content": "x"}],
        [{"action": "delete", "file_path": "x", "content": "must-not-exist"}],
        [{"action": "update", "file_path": "x"}],
        [{"action": "create", "file_path": "x", "content": "x"}] * 101,
        [
            {
                "action": "create",
                "file_path": f"{index}.txt",
                "content": "x" * 20_000,
            }
            for index in range(30)
        ],
    ],
)
def test_atomic_commit_validates_action_count_shape_paths_and_aggregate_bytes_before_transport(
    actions,
):
    # GL-WRITE-04/05 replacement: gitlab_code_context_builder.py:GitLabCodeContextBuilder.build_context is replaced by structured inputs validated against gitlab_commit_pusher.py:GitLabCommitPusher.push_commit's inline action loop.
    operations = _operations()
    with respx.mock:
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42", branch="feature/safe", commit_message="Safe", actions=actions
            )
        assert respx.calls.call_count == 0
    assert getattr(caught.value, "category", None) in {"invalid_input", "capacity"}


def test_atomic_commit_head_reconciliation_is_deterministic_and_matches_dry_run_preview():
    # GL-WRITE-06 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit (inline HEAD/action loop)
    operations = _operations(max_retries=0)
    requested = [
        {
            "action": "update",
            "file_path": "new.txt",
            "content": "new",
        },
        {
            "action": "create",
            "file_path": "existing.txt",
            "content": "updated",
        },
        {"action": "delete", "file_path": "old.txt"},
    ]
    expected_actions = [
        {"action": "create", "file_path": "new.txt"},
        {"action": "update", "file_path": "existing.txt"},
        {"action": "delete", "file_path": "old.txt"},
    ]
    seen = []

    def response(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json=_commit())

    with respx.mock:
        _head_file("new.txt", status=404)
        _head_file("existing.txt", last_commit_id="existing-sha")
        _head_file("old.txt", last_commit_id="old-sha")
        preview = operations.commit_changes(
            "42",
            branch="feature/ABC-123-safe",
            commit_message="Apply safe change",
            actions=requested,
            dry_run=True,
        )
        _mock_project()
        respx.post(f"{PROJECT_API}/repository/commits").mock(side_effect=response)
        result = operations.commit_changes(
            "42",
            branch="feature/ABC-123-safe",
            commit_message="Apply safe change",
            actions=requested,
        )
    assert preview["actions"] == expected_actions
    assert result["actions"] == expected_actions
    assert seen == [
        {
            "branch": "feature/ABC-123-safe",
            "commit_message": "Apply safe change",
            "actions": [
                {"action": "create", "file_path": "new.txt", "content": "new"},
                {
                    "action": "update",
                    "file_path": "existing.txt",
                    "content": "updated",
                    "last_commit_id": "existing-sha",
                },
                {
                    "action": "delete",
                    "file_path": "old.txt",
                    "last_commit_id": "old-sha",
                },
            ],
        }
    ]


@pytest.mark.parametrize(
    ("action", "head_status", "expected_category"),
    [
        ({"action": "delete", "file_path": "gone.txt"}, 404, "conflict"),
        (
            {"action": "update", "file_path": "denied.txt", "content": "x"},
            403,
            "permission",
        ),
        (
            {"action": "create", "file_path": "busy.txt", "content": "x"},
            503,
            "transient",
        ),
    ],
)
def test_atomic_commit_head_reconciliation_fails_closed_before_post(
    action, head_status, expected_category
):
    # GL-WRITE-06/07 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit (inline HEAD/action loop)
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        head = _head_file(action["file_path"], status=head_status)
        post = respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(201, json=_commit())
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/ABC-123-safe",
                commit_message="Apply safe change",
                actions=[action],
            )
    assert head.call_count == 1
    assert post.call_count == 0
    assert getattr(caught.value, "category", None) == expected_category


def test_atomic_commit_rejects_missing_or_malformed_head_identity_before_post():
    # GL-WRITE-06 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit (inline HEAD/action loop)
    operations = _operations(max_retries=0)
    failures = []
    with respx.mock:
        _mock_project()
        head = respx.head(f"{PROJECT_API}/repository/files/existing.txt")
        head.side_effect = [
            httpx.Response(200),
            httpx.Response(200, headers={"X-Gitlab-Last-Commit-Id": "bad sha"}),
        ]
        post = respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(201, json=_commit())
        )
        for _case in range(2):
            with pytest.raises(Exception) as caught:
                operations.commit_changes(
                    "42",
                    branch="feature/ABC-123-safe",
                    commit_message="Apply safe change",
                    actions=[
                        {
                            "action": "create",
                            "file_path": "existing.txt",
                            "content": "x",
                        }
                    ],
                )
            failures.append(getattr(caught.value, "category", None))
    assert failures == ["conflict", "conflict"]
    assert post.call_count == 0


def test_atomic_commit_last_commit_mismatch_is_conflict_and_remote_body_is_hidden():
    # GL-WRITE-06/07 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=2)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", last_commit_id="actual-sha")
        route = respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(
                400,
                json={
                    "message": "last_commit_id does not match",
                    "private": "write-secret-token remote detail",
                },
            )
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/safe",
                commit_message="Safe",
                actions=[
                    {
                        "action": "update",
                        "file_path": "x.txt",
                        "content": "new",
                        "last_commit_id": "stale",
                    }
                ],
            )
    assert route.call_count == 0
    assert getattr(caught.value, "category", None) == "conflict"
    assert "secret" not in str(caught.value) and "remote" not in str(caught.value)


def test_write_http_error_category_does_not_depend_on_remote_json_shape():
    # GL-WRITE-07 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(401, text="private non-json write-secret-token")
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/safe",
                commit_message="Safe",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert getattr(caught.value, "category", None) == "authentication"
    assert "private" not in str(caught.value)


def test_write_conflict_category_does_not_require_a_remote_json_body():
    # GL-WRITE-07 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(409, text="private non-json conflict")
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/safe",
                commit_message="Safe",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert getattr(caught.value, "category", None) == "conflict"
    assert "private" not in str(caught.value)


def test_atomic_commit_dry_run_is_admission_gated_but_never_mutates_or_projects_content():
    # GL-WRITE-05/06/07 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations()
    with respx.mock:
        _head_file("x.txt", status=404)
        result = operations.commit_changes(
            "42",
            branch="feature/safe",
            commit_message="Safe preview",
            actions=[{"action": "create", "file_path": "x.txt", "content": "private"}],
            dry_run=True,
        )
        assert not any(call.request.method == "POST" for call in respx.calls)
    assert result == {
        "project": "42",
        "branch": "feature/safe",
        "commit_message": "Safe preview",
        "action_count": 1,
        "actions": [{"action": "create", "file_path": "x.txt"}],
        "dry_run": True,
    }
    assert "private" not in repr(result)


def test_ambiguous_commit_transport_is_never_retried():
    # GL-WRITE-06/07/10 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=4)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        route = respx.post(f"{PROJECT_API}/repository/commits").mock(
            side_effect=httpx.ReadTimeout("outcome unknown")
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/safe",
                commit_message="Safe",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert route.call_count == 1
    assert getattr(caught.value, "category", None) == "transient"
    assert "unknown" not in str(caught.value)


def test_commit_partial_response_reconciles_only_proven_commit_identity():
    # GL-WRITE-06/07/10 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(201, json={"id": "commit-sha"})
        )
        respx.get(f"{PROJECT_API}/repository/commits/commit-sha").mock(
            return_value=httpx.Response(200, json=_commit())
        )
        result = operations.commit_changes(
            "42",
            branch="feature/safe",
            commit_message="Apply safe change",
            actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
        )
    assert result["commit_id"] == "commit-sha"
    assert result["title"] == "Apply safe change"


def test_commit_partial_post_identity_must_match_reconciliation_get_identity():
    # GL-WRITE-06/07/10 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(
                201,
                json={
                    "id": "commit-A",
                    "short_id": "commit-A",
                    "project_id": 42,
                    "branch": "feature/ABC-123-safe",
                    "web_url": (f"{ORIGIN}/division/platform/repo/-/commit/commit-A"),
                },
            )
        )
        respx.get(f"{PROJECT_API}/repository/commits/commit-A").mock(
            return_value=httpx.Response(200, json=_commit("commit-B"))
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/ABC-123-safe",
                commit_message="Apply safe change",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


@pytest.mark.parametrize("malformed_project_id", [True, 1.0])
@pytest.mark.parametrize("partial", [False, True])
def test_commit_full_and_partial_project_identity_require_an_exact_integer(
    malformed_project_id, partial
):
    # GL-WRITE-06/07/10 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    post_payload = {
        **_commit("commit-A"),
        "project_id": malformed_project_id,
    }
    if partial:
        post_payload.pop("title")
    with respx.mock:
        respx.get(PROJECT_API).mock(
            return_value=httpx.Response(200, json=_project(project_id=1))
        )
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(201, json=post_payload)
        )
        respx.get(f"{PROJECT_API}/repository/commits/commit-A").mock(
            return_value=httpx.Response(
                200, json={**_commit("commit-A"), "project_id": 1}
            )
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/ABC-123-safe",
                commit_message="Apply safe change",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


@pytest.mark.parametrize(
    "contradiction",
    [
        {"title": "Different title"},
        {"message": "Different full commit message"},
        {"short_id": "different"},
        {"web_url": f"{ORIGIN}/other/project/-/commit/commit-sha"},
        {"project_id": 99},
        {"branch": "other/ref"},
    ],
)
def test_commit_partial_response_rejects_every_present_contradictory_identity(
    contradiction,
):
    # GL-WRITE-06/07/10 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(201, json={"id": "commit-sha", **contradiction})
        )
        reconcile = respx.get(f"{PROJECT_API}/repository/commits/commit-sha").mock(
            return_value=httpx.Response(200, json=_commit())
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/ABC-123-safe",
                commit_message="Apply safe change",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert reconcile.call_count == 0
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_commit_contradictory_response_is_not_reconciled_as_partial():
    # GL-WRITE-06/07/10 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(201, json=_commit(title="Different title"))
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/safe",
                commit_message="Apply safe change",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_write_success_requires_the_documented_created_status():
    # GL-WRITE-07 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(200, json=_commit())
        )
        with pytest.raises(Exception) as caught:
            operations.commit_changes(
                "42",
                branch="feature/safe",
                commit_message="Apply safe change",
                actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_multiline_commit_message_reconciles_against_gitlab_title_semantics():
    # GL-WRITE-05/07 legacy: gitlab_commit_pusher.py:GitLabCommitPusher.push_commit
    operations = _operations(max_retries=0)
    message = "Apply safe change\n\nBounded detail"
    with respx.mock:
        _mock_project()
        _head_file("x.txt", status=404)
        respx.post(f"{PROJECT_API}/repository/commits").mock(
            return_value=httpx.Response(201, json=_commit(title="Apply safe change"))
        )
        result = operations.commit_changes(
            "42",
            branch="feature/safe",
            commit_message=message,
            actions=[{"action": "create", "file_path": "x.txt", "content": "x"}],
        )
    assert result["title"] == "Apply safe change"


def test_merge_request_defaults_and_safe_normalized_result():
    # GL-WRITE-08 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    seen = []

    def response(request):
        seen.append(json.loads(request.content))
        return httpx.Response(201, json=_mr(title="Feature abc 123"))

    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.post(f"{PROJECT_API}/merge_requests").mock(side_effect=response)
        result = operations.create_merge_request("42", source_branch="feature/abc-123")
    assert seen == [
        {
            "source_branch": "feature/abc-123",
            "target_branch": "main",
            "title": "Feature abc 123",
            "description": "",
            "remove_source_branch": True,
            "squash": False,
        }
    ]
    assert result == {
        "project": "42",
        "iid": 7,
        "title": "Feature abc 123",
        "state": "opened",
        "source_branch": "feature/abc-123",
        "target_branch": "main",
        "web_url": f"{ORIGIN}/division/platform/repo/-/merge_requests/7",
        "created": True,
        "reused": False,
        "dry_run": False,
    }


@pytest.mark.parametrize("status", [409, 400])
def test_merge_request_duplicate_409_and_proven_400_recover_one_exact_open_mr(status):
    # GL-WRITE-09/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=2)
    duplicate = (
        "Another open merge request already exists for this source branch"
        if status == 409
        else "Another open merge request already exists for this source branch: !7"
    )
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        post = respx.post(f"{PROJECT_API}/merge_requests").mock(
            return_value=httpx.Response(status, json={"message": [duplicate]})
        )
        respx.get(
            f"{PROJECT_API}/merge_requests",
            params={
                "scope": "all",
                "state": "opened",
                "source_branch": "feature/abc-123",
                "target_branch": "main",
            },
        ).mock(return_value=httpx.Response(200, json=[_mr()]))
        result = operations.create_merge_request(
            "42", source_branch="feature/abc-123", title="ABC-123"
        )
    assert post.call_count == 1
    assert result["created"] is False and result["reused"] is True
    assert result["iid"] == 7


def test_merge_request_duplicate_recovery_rejects_ambiguous_or_mismatched_identity():
    # GL-WRITE-09/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.post(f"{PROJECT_API}/merge_requests").mock(
            return_value=httpx.Response(
                409,
                json={"message": "Another open merge request already exists"},
            )
        )
        route = respx.get(f"{PROJECT_API}/merge_requests")
        route.side_effect = [
            httpx.Response(200, json=[_mr(iid=7), _mr(iid=8)]),
            httpx.Response(200, json=[_mr(source="other")]),
        ]
        failures = []
        for _case in range(2):
            with pytest.raises(Exception) as caught:
                operations.create_merge_request(
                    "42", source_branch="feature/abc-123", title="ABC-123"
                )
            failures.append(getattr(caught.value, "category", None))
    assert failures == ["conflict", "conflict"]


def test_merge_request_response_must_prove_current_project_identity():
    # GL-WRITE-08/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.post(f"{PROJECT_API}/merge_requests").mock(
            return_value=httpx.Response(201, json=_mr(project_id=99))
        )
        with pytest.raises(Exception) as caught:
            operations.create_merge_request(
                "42", source_branch="feature/abc-123", title="ABC-123"
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_new_merge_request_response_must_preserve_requested_title_identity():
    # GL-WRITE-08/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.post(f"{PROJECT_API}/merge_requests").mock(
            return_value=httpx.Response(201, json=_mr(title="Different title"))
        )
        with pytest.raises(Exception) as caught:
            operations.create_merge_request(
                "42", source_branch="feature/abc-123", title="ABC-123"
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_merge_request_title_preserves_255_and_deterministically_caps_256():
    # GL-WRITE-08 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    title_255 = "x" * 255
    title_256 = title_255 + "y"
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        exact = operations.create_merge_request(
            "42",
            source_branch="feature/ABC-123-safe",
            title=title_255,
            dry_run=True,
        )
        capped = operations.create_merge_request(
            "42",
            source_branch="feature/ABC-123-safe",
            title=title_256,
            dry_run=True,
        )
    assert exact["title"] == title_255
    assert capped["title"] == title_255


@pytest.mark.parametrize(
    "contradiction",
    [
        {"project_id": 99},
        {"source_branch": "other/source"},
        {"target_branch": "other/target"},
        {"title": "Different title"},
        {"state": "closed"},
        {"web_url": f"{ORIGIN}/other/project/-/merge_requests/7"},
    ],
)
def test_merge_request_partial_response_rejects_every_present_contradictory_identity(
    contradiction,
):
    # GL-WRITE-08/09/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.post(f"{PROJECT_API}/merge_requests").mock(
            return_value=httpx.Response(201, json={"iid": 7, **contradiction})
        )
        reconcile = respx.get(f"{PROJECT_API}/merge_requests/7").mock(
            return_value=httpx.Response(200, json=_mr())
        )
        with pytest.raises(Exception) as caught:
            operations.create_merge_request(
                "42", source_branch="feature/abc-123", title="ABC-123"
            )
    assert reconcile.call_count == 0
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_merge_request_partial_response_reconciles_by_iid_and_ambiguous_transport_is_not_retried():
    # GL-WRITE-08/09/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=4)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        post = respx.post(f"{PROJECT_API}/merge_requests")
        post.side_effect = [
            httpx.Response(201, json={"iid": 7}),
            httpx.ReadTimeout("private uncertain outcome"),
        ]
        respx.get(f"{PROJECT_API}/merge_requests/7").mock(
            return_value=httpx.Response(200, json=_mr())
        )
        reconciled = operations.create_merge_request(
            "42", source_branch="feature/abc-123", title="ABC-123"
        )
        with pytest.raises(Exception) as caught:
            operations.create_merge_request(
                "42", source_branch="feature/abc-123", title="ABC-123"
            )
    assert reconciled["iid"] == 7
    assert post.call_count == 2
    assert getattr(caught.value, "category", None) == "transient"
    assert "private" not in str(caught.value)


def test_merge_request_partial_post_identity_must_match_reconciliation_get_identity():
    # GL-WRITE-08/09/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        respx.post(f"{PROJECT_API}/merge_requests").mock(
            return_value=httpx.Response(
                201,
                json={
                    "iid": 7,
                    "project_id": 42,
                    "source_branch": "feature/abc-123",
                    "target_branch": "main",
                    "title": "ABC-123",
                    "state": "opened",
                },
            )
        )
        respx.get(f"{PROJECT_API}/merge_requests/7").mock(
            return_value=httpx.Response(200, json=_mr(iid=8))
        )
        with pytest.raises(Exception) as caught:
            operations.create_merge_request(
                "42", source_branch="feature/abc-123", title="ABC-123"
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


@pytest.mark.parametrize("malformed_project_id", [True, 1.0])
@pytest.mark.parametrize("partial", [False, True])
def test_merge_request_full_and_partial_project_identity_require_an_exact_integer(
    malformed_project_id, partial
):
    # GL-WRITE-08/09/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations(max_retries=0)
    post_payload = _mr(project_id=malformed_project_id)
    if partial:
        post_payload.pop("web_url")
    with respx.mock:
        respx.get(PROJECT_API).mock(
            return_value=httpx.Response(200, json=_project(project_id=1))
        )
        respx.post(f"{ORIGIN}/api/v4/projects/1/merge_requests").mock(
            return_value=httpx.Response(201, json=post_payload)
        )
        respx.get(f"{ORIGIN}/api/v4/projects/1/merge_requests/7").mock(
            return_value=httpx.Response(200, json=_mr(project_id=1))
        )
        with pytest.raises(Exception) as caught:
            operations.create_merge_request(
                "42", source_branch="feature/abc-123", title="ABC-123"
            )
    assert getattr(caught.value, "category", None) == "invalid_remote_data"


def test_merge_request_dry_run_never_mutates_and_has_no_caller_approval_field():
    # GL-WRITE-08/10 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    _auth, _client, _models, _operations_module, tools = _modules()
    schema = tools.SCHEMAS["gitlab_create_merge_request"]["parameters"]
    assert "approved" not in schema["properties"]
    assert "tool_admission" not in schema["properties"]
    operations = _operations()
    with respx.mock:
        respx.get(PROJECT_API).mock(return_value=httpx.Response(200, json=_project()))
        result = operations.create_merge_request(
            "42", source_branch="feature/abc-123", dry_run=True
        )
        assert not any(call.request.method != "GET" for call in respx.calls)
    assert result["dry_run"] is True
    assert result["created"] is False and result["reused"] is False


def test_merge_request_rejects_identical_source_and_target_before_transport():
    # GL-WRITE-08 legacy: gitlab_mr_creator.py:GitLabMRCreator.create_mr
    operations = _operations()
    with respx.mock:
        with pytest.raises(Exception) as caught:
            operations.create_merge_request(
                "42", source_branch="main", target_branch="main"
            )
        assert respx.calls.call_count == 0
    assert getattr(caught.value, "category", None) == "invalid_input"


def test_registered_writes_require_exact_public_admission_before_configuration_or_transport(
    monkeypatch,
):
    # GL-WRITE-10 replacement: all legacy mutators lacked authenticated host admission.
    plugin = _load_plugin()
    context = _Context()
    plugin.register(context)
    calls = []
    monkeypatch.setattr(
        plugin.gitlab_tools,
        "invoke",
        lambda name, args, configuration, **options: calls.append(name) or {"ok": True},
    )

    class ExplosiveAdmission:
        @property
        def approved(self):
            raise RuntimeError("caller-controlled admission detail")

    for name in sorted(WRITE_TOOLS):
        handler = context.registrations[name]["handler"]
        for kwargs in (
            {},
            {
                "tool_admission": SimpleNamespace(
                    approved=True, policy="caller", tool_name=name
                )
            },
            {"tool_admission": _admission("gitlab_read_file")},
            {"tool_admission": ExplosiveAdmission()},
        ):
            result = json.loads(handler({"project": "42"}, **kwargs))
            assert result == {
                "success": False,
                "error": {
                    "category": "permission",
                    "message": "GitLab permission denied",
                },
            }
    assert calls == []


def test_registered_write_hook_requests_host_approval_and_delivers_reserved_admission(
    monkeypatch,
):
    # GL-WRITE-10 replacement: all legacy mutators lacked authenticated host admission.
    plugin = _load_plugin()
    context = _Context()
    plugin.register(context)
    assert "pre_tool_call" in context.hooks
    for name in WRITE_TOOLS:
        assert context.hooks["pre_tool_call"](name, {}) == {
            "action": "approve",
            "message": "Approve Ericsson GitLab mutation",
            "rule_key": name,
        }
    assert context.hooks["pre_tool_call"]("gitlab_read_file", {}) is None

    calls = []
    monkeypatch.setattr(
        plugin.gitlab_tools,
        "invoke",
        lambda name, args, configuration, **options: calls.append(name) or {"ok": True},
    )
    for name in sorted(WRITE_TOOLS):
        result = json.loads(
            context.registrations[name]["handler"](
                {"project": "42"}, tool_admission=_admission(name)
            )
        )
        assert result == {"success": True, "result": {"ok": True}}
    assert calls == sorted(WRITE_TOOLS)


def test_direct_invoke_rejects_missing_unknown_and_caller_auth_fields_before_transport(
    monkeypatch,
):
    # GL-WRITE-04/08/10 replacement: gitlab_code_context_builder.py:GitLabCodeContextBuilder.build_context; gitlab_mr_creator.py:GitLabMRCreator.create_mr; legacy mutators lacked host admission.
    _auth, _client, models, _operations_module, tools = _modules()
    monkeypatch.setattr(
        tools,
        "operations_from_configuration",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("no transport")),
    )
    for name, args in (
        (
            "gitlab_create_branch",
            {
                "project": "42",
                "ticket_key": "ABC-123",
                "summary": "safe",
                "approved": True,
            },
        ),
        ("gitlab_commit_changes", {"project": "42"}),
        (
            "gitlab_create_merge_request",
            {"project": "42", "source_branch": "safe", "tool_admission": True},
        ),
    ):
        with pytest.raises(models.GitLabError) as caught:
            tools.invoke(name, args, _Configuration())
        assert caught.value.category == "invalid_input"
