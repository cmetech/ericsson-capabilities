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


def _operations(**client_options):
    auth, client, _models, operations = _modules()
    credentials = auth.GitLabAuth(
        origin=ORIGIN,
        pat="secret-token",
        certificate_pair=None,
    )
    return operations.GitLabOperations(client.GitLabClient(credentials, **client_options))


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
