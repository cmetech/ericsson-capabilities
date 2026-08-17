"""Ericsson Confluence standalone connector registration."""

from __future__ import annotations

import json

# Task 1 registers the hook shape before write tools exist. Keep both write
# collections empty until bounded, argument-scoped approval summaries exist.
_WRITE_TOOLS: frozenset[str] = frozenset()
WRITE_APPROVALS: dict[str, object] = {}


def register(ctx: object) -> None:
    """Register bounded Confluence reads and the future write hook."""

    def require_write_approval(
        _tool_name: object, _args: object, **_kwargs: object
    ) -> None:
        # No Task 1 tool writes, so no untrusted argument is inspected,
        # serialized, or rendered in an approval prompt.
        return None

    ctx.register_hook("pre_tool_call", require_write_approval)

    # Task 1's minimal hook-only context intentionally has no tool API.
    # Preserve that loading contract while allowing normal plugin hosts to
    # register the read tools below.
    if not hasattr(ctx, "register_tool"):
        return

    from . import tools as confluence_tools
    from .models import ConfluenceError, SAFE_ERROR_MESSAGES, safe_remediation

    def json_error(category: str, remediation: object = None) -> str:
        error = {"category": category, "message": SAFE_ERROR_MESSAGES[category]}
        safe = safe_remediation(remediation)
        if safe:
            error["remediation"] = safe
        return json.dumps(
            {"success": False, "error": error},
            ensure_ascii=False,
            separators=(",", ":"),
        )

    def available() -> bool:
        try:
            return confluence_tools.check_available(ctx.configuration())
        except Exception:
            return False

    def handler(name: str):
        def invoke(args: dict, **_kwargs) -> str:
            try:
                configuration = ctx.configuration()
            except Exception:
                return json_error("invalid_configuration")
            try:
                result = confluence_tools.invoke(name, args or {}, configuration)
                return json.dumps(
                    {"success": True, "result": result},
                    ensure_ascii=False,
                    separators=(",", ":"),
                )
            except ConfluenceError as exc:
                return json_error(exc.category, exc.remediation)
            except (KeyError, TypeError, ValueError):
                return json_error("invalid_input")
            except Exception:
                return json_error("transient")

        return invoke

    for name, schema in confluence_tools.SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset="ericsson-confluence",
            schema=schema,
            handler=handler(name),
            check_fn=available,
            emoji="📄",
        )
