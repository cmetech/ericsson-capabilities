"""Ericsson Artifactory standalone connector registration."""

from __future__ import annotations

# Task 1 has no write tools. Keep the registered hook intentionally inert:
# it must not inspect, serialize, or render untrusted arguments before Task 5
# introduces bounded, argument-scoped approval summaries.
_WRITE_TOOLS: frozenset[str] = frozenset()
WRITE_APPROVALS: dict[str, object] = {}


def register(ctx: object) -> None:
    """Register the inert pre-tool hook reserved for future ARM writes."""

    def require_write_approval(
        _tool_name: object, _args: object, **_kwargs: object
    ) -> None:
        return None

    ctx.register_hook("pre_tool_call", require_write_approval)
