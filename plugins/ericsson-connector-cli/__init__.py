"""Always-visible Ericsson connector command facade registration."""

from __future__ import annotations


def _setup_domain(_parser) -> None:
    """Reserve a connector command tree; Task 5 builds its curated parser."""


def register(ctx) -> None:
    """Atomically reserve all Ericsson connector top-level command domains."""
    for domain in ("jira", "gitlab", "confluence", "arm"):
        ctx.register_cli_command(
            name=domain,
            help=f"Run bounded Ericsson {domain.title()} connector commands",
            setup_fn=_setup_domain,
        )
