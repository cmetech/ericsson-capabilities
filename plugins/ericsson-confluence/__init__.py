"""Ericsson Confluence standalone connector registration."""

from __future__ import annotations

import hashlib
import json

_WRITE_TOOLS = frozenset({
    "confluence_create_page", "confluence_update_page", "confluence_add_comment",
})


def _arg(args: dict, name: str) -> str:
    """Render one argument for an approval prompt, safely and bounded."""
    value = args.get(name) if isinstance(args, dict) else None
    try:
        return json.dumps(value, ensure_ascii=True)[:512]
    except (TypeError, ValueError):
        return '"<unrepresentable>"'


WRITE_APPROVALS = {
    "confluence_create_page": lambda a: (
        f"Space: {_arg(a, 'space_key')}\nTitle: {_arg(a, 'title')}\n"
        f"Parent: {_arg(a, 'parent_id')}\nBody: {_arg(a, 'markdown')}"
    ),
    "confluence_update_page": lambda a: (
        f"Page: {_arg(a, 'content_id')}\nNew title: {_arg(a, 'title')}\n"
        f"New body: {_arg(a, 'markdown')}"
    ),
    "confluence_add_comment": lambda a: (
        f"Page: {_arg(a, 'content_id')}\nComment: {_arg(a, 'markdown')}"
    ),
}


def _has_write_admission(admission: object, tool_name: str) -> bool:
    """Accept only the host admission minted for this exact write tool."""
    try:
        return (
            getattr(admission, "approved", None) is True
            and getattr(admission, "policy", None) == "plugin_approve"
            and getattr(admission, "tool_name", None) == tool_name
        )
    except Exception:
        return False


def register(ctx: object) -> None:
    """Register bounded Confluence reads and the future write hook."""

    def require_write_approval(tool_name: str, args: dict, **_kwargs: object):
        summarise = WRITE_APPROVALS.get(tool_name)
        if summarise is None:
            return None
        try:
            canonical_args = json.dumps(
                args if isinstance(args, dict) else {},
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
        except (TypeError, ValueError):
            return {"action": "block", "message": "Confluence write arguments cannot be safely approved"}
        return {
            "action": "approve",
            "message": (
                f"Approve Ericsson Confluence change: {tool_name}\n"
                f"{summarise(args if isinstance(args, dict) else {})}"
            ),
            "rule_key": (
                f"{tool_name}:"
                f"{hashlib.sha256(canonical_args.encode('utf-8')).hexdigest()}"
            ),
        }

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
            if name in _WRITE_TOOLS and not _has_write_admission(
                _kwargs.get("tool_admission"), name
            ):
                return json_error("permission")
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
