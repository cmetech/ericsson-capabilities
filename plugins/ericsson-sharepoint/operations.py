"""Connector operations composed from SharePoint and generic Graph clients."""

from __future__ import annotations

from typing import Any, Mapping

from .auth import build_identity_config
from .client import SharePointClient
from .models import SharePointConfiguration


def client_from_configuration(configuration: Mapping[str, Any]) -> SharePointClient:
    """Build a fresh client from the host's current opaque configuration view."""
    from tools.microsoft_graph_client import MicrosoftGraphClient
    from tools.microsoft_graph_identity import create_graph_token_provider

    config = SharePointConfiguration.from_runtime(configuration)
    provider = create_graph_token_provider(
        build_identity_config(config), interactive_allowed=False
    )
    graph = MicrosoftGraphClient(provider, timeout=config.timeout_seconds)
    return SharePointClient(
        graph,
        tenant_hosts={config.tenant_host},
        max_pages=config.max_pages,
        max_items=config.max_items,
    )


async def resolve_url(configuration: Mapping[str, Any], url: str) -> dict[str, Any]:
    return await client_from_configuration(configuration).resolve_url(url)


async def get_item(
    configuration: Mapping[str, Any],
    *,
    url: str | None = None,
    drive_id: str | None = None,
    item_id: str | None = None,
) -> dict[str, Any]:
    return await client_from_configuration(configuration).get_item(
        url=url, drive_id=drive_id, item_id=item_id
    )
