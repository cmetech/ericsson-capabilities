"""Compatibility facade for the Ericsson Jira connector's public tools."""

from __future__ import annotations

import json
import re
from typing import Any, Mapping

if __package__:
    from .auth import authentication_from_configuration
    from .client import JiraClient
    from .models import JiraAuth, JiraError
else:
    from auth import authentication_from_configuration
    from client import JiraClient
    from models import JiraAuth, JiraError


GITLAB_URL_RE = re.compile(r"https?://[^\s|\]>)\"',]*gitlab[^\s|\]>)\"',]*", re.I)
MY_TICKETS_JQL = (
    "assignee = currentUser() AND resolution = Unresolved "
    "ORDER BY priority DESC, updated DESC"
)


def _clean_urls(urls):
    return [url.rstrip(".,;:!?") for url in urls]


def _text(value) -> str:
    return json.dumps(value) if isinstance(value, dict) else (value or "")


def check_available(configuration=None) -> bool:
    """Configuration presence is diagnostic only; plugin enablement is host-owned."""

    if configuration is None:
        return False
    try:
        authentication_from_configuration(configuration)
        return True
    except JiraError:
        return False


def client_from_configuration(configuration, **options) -> JiraClient:
    return JiraClient(authentication_from_configuration(configuration), **options)


def my_tickets(
    max_results: int | None = None,
    *,
    client: JiraClient,
) -> list[dict[str, Any]]:
    if max_results is None:
        max_results = client.auth.default_max_results
    if type(max_results) is not int or not 1 <= max_results <= 100:
        raise JiraError("invalid_input")
    payload = client.rest_json(
        "GET",
        "search",
        params={
            "jql": MY_TICKETS_JQL,
            "maxResults": max_results,
            "fields": "summary,status,priority,updated,description",
        },
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("issues", []), list):
        raise JiraError("invalid_remote_data")
    output = []
    for issue in payload.get("issues", []):
        if not isinstance(issue, dict) or not isinstance(issue.get("fields", {}), dict):
            raise JiraError("invalid_remote_data")
        fields = issue.get("fields", {})
        description = _text(fields.get("description"))
        output.append(
            {
                "key": issue.get("key"),
                "summary": fields.get("summary"),
                "status": (fields.get("status") or {}).get("name"),
                "priority": (fields.get("priority") or {}).get("name"),
                "updated": fields.get("updated"),
                "gitlab_urls": _clean_urls(GITLAB_URL_RE.findall(description)),
            }
        )
    return output


def get_issue(key: str, *, client: JiraClient) -> dict[str, Any]:
    if not isinstance(key, str) or not key or len(key) > 128:
        raise JiraError("invalid_input")
    payload = client.rest_json(
        "GET",
        f"issue/{key}",
        params={"fields": "summary,status,priority,description,comment"},
    )
    if not isinstance(payload, dict) or not isinstance(payload.get("fields"), dict):
        raise JiraError("invalid_remote_data")
    fields = payload["fields"]
    raw_comments = (fields.get("comment") or {}).get("comments", [])
    if not isinstance(raw_comments, list):
        raise JiraError("invalid_remote_data")
    comments = [
        {
            "author": (comment.get("author") or {}).get("displayName"),
            "body": _text(comment.get("body")),
            "created": comment.get("created"),
        }
        for comment in raw_comments[-5:]
        if isinstance(comment, dict)
    ]
    description = _text(fields.get("description"))
    return {
        "key": payload.get("key"),
        "summary": fields.get("summary"),
        "status": (fields.get("status") or {}).get("name"),
        "priority": (fields.get("priority") or {}).get("name"),
        "description": description,
        "gitlab_urls": _clean_urls(GITLAB_URL_RE.findall(description)),
        "comments": comments,
    }


def add_comment(key: str, body: str, *, client: JiraClient) -> dict[str, Any]:
    if not isinstance(key, str) or not key or not isinstance(body, str) or not body:
        raise JiraError("invalid_input")
    payload = client.rest_json(
        "POST", f"issue/{key}/comment", json_body={"body": body}
    )
    if not isinstance(payload, dict):
        raise JiraError("invalid_remote_data")
    return {"ok": True, "id": payload.get("id")}


def invoke(
    name: str,
    args: Mapping[str, Any],
    configuration,
    **client_options,
):
    operations = {
        "jira_my_tickets": my_tickets,
        "jira_get_issue": get_issue,
        "jira_add_comment": add_comment,
    }
    operation = operations.get(name)
    if operation is None or not isinstance(args, Mapping):
        raise JiraError("invalid_input")
    with client_from_configuration(configuration, **client_options) as client:
        return operation(**dict(args), client=client)


_STR = {"type": "string"}
SCHEMAS = {
    "jira_my_tickets": {
        "name": "jira_my_tickets",
        "description": "List open Jira tickets assigned to the current user, with any GitLab URLs found in their descriptions.",
        "parameters": {
            "type": "object",
            "properties": {
                "max_results": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 100,
                    "description": "Maximum tickets (configured default 25)",
                }
            },
            "additionalProperties": False,
        },
    },
    "jira_get_issue": {
        "name": "jira_get_issue",
        "description": "Fetch one Jira issue: summary, status, priority, description, last 5 comments, GitLab URLs.",
        "parameters": {
            "type": "object",
            "properties": {"key": _STR},
            "required": ["key"],
            "additionalProperties": False,
        },
    },
    "jira_add_comment": {
        "name": "jira_add_comment",
        "description": "Add a comment to a Jira issue.",
        "parameters": {
            "type": "object",
            "properties": {"key": _STR, "body": _STR},
            "required": ["key", "body"],
            "additionalProperties": False,
        },
    },
}
