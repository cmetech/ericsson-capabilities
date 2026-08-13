"""Model-visible schemas and dispatch for SharePoint identity operations."""

from __future__ import annotations

from typing import Any, Mapping

from . import operations


SCHEMAS = {
    "sharepoint_resolve_url": {
        "name": "sharepoint_resolve_url",
        "description": "Resolve an authorized SharePoint URL to bounded site, drive, and item identity.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "minLength": 1, "maxLength": 8192}
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
    "sharepoint_get_item": {
        "name": "sharepoint_get_item",
        "description": "Read bounded SharePoint DriveItem metadata by URL or explicit drive/item IDs.",
        "parameters": {
            "type": "object",
            "properties": {
                "url": {"type": "string", "minLength": 1, "maxLength": 8192},
                "drive_id": {"type": "string", "minLength": 1, "maxLength": 1024},
                "item_id": {"type": "string", "minLength": 1, "maxLength": 1024}
            },
            "additionalProperties": False,
        },
    },
}


async def invoke(
    name: str,
    arguments: Mapping[str, Any],
    configuration: Mapping[str, Any],
) -> dict[str, Any]:
    if name == "sharepoint_resolve_url":
        return await operations.resolve_url(configuration, str(arguments.get("url") or ""))
    if name == "sharepoint_get_item":
        return await operations.get_item(
            configuration,
            url=arguments.get("url"),
            drive_id=arguments.get("drive_id"),
            item_id=arguments.get("item_id"),
        )
    raise ValueError("unknown SharePoint tool")

