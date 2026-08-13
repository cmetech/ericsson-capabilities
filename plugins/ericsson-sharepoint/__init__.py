"""Ericsson SharePoint standalone connector registration."""

from __future__ import annotations

from . import auth


def register(ctx) -> None:
    """Register user-invoked setup actions; tools are added by later slices."""
    ctx.register_setup_action(
        "authenticate", auth.authenticate, readiness=auth.graph_ready
    )
    ctx.register_setup_action("test_connection", auth.test_connection)
    ctx.register_setup_action("enroll_browser", auth.enroll_browser)
    ctx.register_setup_action("clear_session", auth.clear_session)

