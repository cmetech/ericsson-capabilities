"""Ericsson Confluence standalone connector registration."""

from __future__ import annotations

# Task 1 registers the hook shape before write tools exist. Keep both write
# collections empty until bounded, argument-scoped approval summaries exist.
_WRITE_TOOLS: frozenset[str] = frozenset()
WRITE_APPROVALS: dict[str, object] = {}


def register(ctx: object) -> None:
    """Register the inert pre-tool hook used by future Confluence writes."""

    def require_write_approval(
        _tool_name: object, _args: object, **_kwargs: object
    ) -> None:
        # No Task 1 tool writes, so no untrusted argument is inspected,
        # serialized, or rendered in an approval prompt.
        return None

    ctx.register_hook("pre_tool_call", require_write_approval)
