"""Ericsson SharePoint standalone connector registration."""

from __future__ import annotations

import json

from . import auth, client, tools  # noqa: F401
from .models import (
    SharePointConfigurationError,
    SharePointFileBoundaryError,
    SharePointResolutionError,
)


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def register(ctx) -> None:
    """Register user-invoked setup actions; tools are added by later slices."""
    ctx.register_setup_action(
        "authenticate", auth.authenticate, readiness=auth.graph_ready
    )
    ctx.register_setup_action("test_connection", auth.test_connection)
    ctx.register_setup_action("enroll_browser", auth.enroll_browser)
    ctx.register_setup_action("clear_session", auth.clear_session)

    def available() -> bool:
        try:
            return auth.graph_ready(ctx.configuration())
        except Exception:
            return False

    def handler(name):
        async def invoke(arguments: dict, **_kwargs) -> str:
            try:
                configuration = ctx.configuration()
                try:
                    from tools.interrupt import is_interrupted
                except ImportError:
                    def is_interrupted():
                        return False
                result = await tools.invoke(
                    name,
                    arguments or {},
                    configuration,
                    file_authorization=_kwargs.get("file_authorization"),
                    unattended=_kwargs.get("unattended") is True,
                    cancel_check=is_interrupted,
                )
                return _json({"success": True, "result": result})
            except SharePointConfigurationError:
                category = "configuration_required"
            except SharePointFileBoundaryError:
                category = "permission_denied"
            except (SharePointResolutionError, ValueError, TypeError, KeyError):
                category = "invalid_input"
            except Exception:
                category = "remote_unavailable"
            return _json(
                {
                    "success": False,
                    "error": {
                        "category": category,
                        "message": "SharePoint operation could not be completed.",
                    },
                }
            )

        return invoke

    for name, schema in tools.SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset="ericsson-sharepoint",
            schema=schema,
            handler=handler(name),
            check_fn=available,
            is_async=True,
            emoji="📁",
        )
