"""Tool schemas and safe invocation adapters for bounded GitLab reads."""

from __future__ import annotations

from typing import Any, Mapping

if __package__:
    from .auth import GitLabAuth
    from .client import GitLabClient
    from .models import GitLabError
    from .operations import GitLabOperations
else:  # Standalone source tests import modules directly from the plugin root.
    from auth import GitLabAuth
    from client import GitLabClient
    from models import GitLabError
    from operations import GitLabOperations


_PROJECT = {
    "oneOf": [
        {"type": "string", "minLength": 1, "maxLength": 2048},
        {"type": "integer", "minimum": 1},
    ],
    "description": (
        "Project numeric id, namespace/project slug, or URL on the configured "
        "GitLab origin."
    ),
}
_REF = {"type": "string", "minLength": 1, "maxLength": 512}
_PATH = {"type": "string", "maxLength": 4096}


def _schema(name: str, description: str, properties: dict, required: list[str]):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


SCHEMAS = {
    "gitlab_resolve_project": _schema(
        "gitlab_resolve_project",
        "Resolve one GitLab project and an optional repository tree/blob link "
        "to bounded canonical identity.",
        {"project": _PROJECT},
        ["project"],
    ),
    "gitlab_list_repository_tree": _schema(
        "gitlab_list_repository_tree",
        "List a bounded, normalized repository tree at one explicit ref.",
        {
            "project": _PROJECT,
            "ref": _REF,
            "path": _PATH,
            "recursive": {"type": "boolean"},
            "max_items": {"type": "integer", "minimum": 1, "maximum": 2000},
        },
        ["project", "ref"],
    ),
    "gitlab_read_file": _schema(
        "gitlab_read_file",
        "Read one bounded UTF-8 repository file or return safe binary metadata.",
        {
            "project": _PROJECT,
            "file_path": {**_PATH, "minLength": 1},
            "ref": _REF,
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 524288},
        },
        ["project", "file_path", "ref"],
    ),
    "gitlab_read_merge_request": _schema(
        "gitlab_read_merge_request",
        "Read bounded merge-request metadata and structured diffs.",
        {
            "project": _PROJECT,
            "iid": {"type": "integer", "minimum": 1, "maximum": 2147483647},
        },
        ["project", "iid"],
    ),
    "gitlab_list_pipelines": _schema(
        "gitlab_list_pipelines",
        "List bounded pipeline summaries without CI variables or job details.",
        {
            "project": _PROJECT,
            "ref": _REF,
            "status": {"type": "string", "minLength": 1, "maxLength": 64},
            "max_items": {"type": "integer", "minimum": 1, "maximum": 500},
        },
        ["project"],
    ),
}


def operations_from_configuration(configuration, **client_options) -> GitLabOperations:
    authentication = GitLabAuth.from_configuration(configuration)
    return GitLabOperations(GitLabClient(authentication, **client_options))


def invoke(name: str, args: Mapping[str, Any], configuration, **client_options):
    if name not in SCHEMAS or not isinstance(args, Mapping):
        raise GitLabError("invalid_input")
    parameters = SCHEMAS[name]["parameters"]
    allowed = set(parameters["properties"])
    required = set(parameters.get("required", ()))
    if (
        any(not isinstance(key, str) for key in args)
        or not required.issubset(args)
        or not set(args).issubset(allowed)
    ):
        raise GitLabError("invalid_input")
    operations = operations_from_configuration(configuration, **client_options)
    values = dict(args)
    try:
        if name == "gitlab_resolve_project":
            return operations.resolve_project(values["project"])
        if name == "gitlab_list_repository_tree":
            return operations.list_repository_tree(
                values["project"],
                ref=values["ref"],
                path=values.get("path", ""),
                recursive=values.get("recursive", False),
                max_items=values.get("max_items", 200),
            )
        if name == "gitlab_read_file":
            return operations.read_file(
                values["project"],
                values["file_path"],
                ref=values["ref"],
                max_bytes=values.get("max_bytes", 100 * 1024),
            )
        if name == "gitlab_read_merge_request":
            return operations.read_merge_request(values["project"], values["iid"])
        return operations.list_pipelines(
            values["project"],
            ref=values.get("ref"),
            status=values.get("status"),
            max_items=values.get("max_items", 50),
        )
    finally:
        operations.client.close()
