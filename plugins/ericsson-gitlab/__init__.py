"""Ericsson GitLab standalone connector registration."""

from __future__ import annotations

import json

from . import tools as gitlab_tools  # noqa: E402
from .models import GitLabError, SAFE_ERROR_MESSAGES  # noqa: E402


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _interrupt_authority():
    try:
        from tools.interrupt import is_interrupted
    except ImportError:
        return lambda: False
    return is_interrupted


def register(ctx) -> None:
    """Register exactly the five Task 8 reads under one service-gated toolset."""

    def available() -> bool:
        try:
            configuration = ctx.configuration()
            gitlab_tools.GitLabAuth.from_configuration(configuration)
            return True
        except Exception:
            return False

    def handler(name):
        def invoke(args: dict, **kwargs) -> str:
            try:
                # Resolve the opaque host accessor and its values for this call.
                # Never retain either object across profile generations.
                configuration = ctx.configuration()
            except Exception:
                return _json(
                    {
                        "success": False,
                        "error": {
                            "category": "invalid_configuration",
                            "message": SAFE_ERROR_MESSAGES["invalid_configuration"],
                        },
                    }
                )
            try:
                result = gitlab_tools.invoke(
                    name,
                    args or {},
                    configuration,
                    cancel_check=_interrupt_authority(),
                )
                return _json({"success": True, "result": result})
            except GitLabError as exc:
                return _json(
                    {
                        "success": False,
                        "error": {
                            "category": exc.category,
                            "message": SAFE_ERROR_MESSAGES[exc.category],
                        },
                    }
                )
            except (KeyError, TypeError, ValueError):
                return _json(
                    {
                        "success": False,
                        "error": {
                            "category": "invalid_input",
                            "message": SAFE_ERROR_MESSAGES["invalid_input"],
                        },
                    }
                )
            except Exception:
                return _json(
                    {
                        "success": False,
                        "error": {
                            "category": "transient",
                            "message": SAFE_ERROR_MESSAGES["transient"],
                        },
                    }
                )

        return invoke

    handlers = {
        "gitlab_resolve_project": handler("gitlab_resolve_project"),
        "gitlab_list_repository_tree": handler("gitlab_list_repository_tree"),
        "gitlab_read_file": handler("gitlab_read_file"),
        "gitlab_read_merge_request": handler("gitlab_read_merge_request"),
        "gitlab_list_pipelines": handler("gitlab_list_pipelines"),
    }
    for name, schema in gitlab_tools.SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset="ericsson-gitlab",
            schema=schema,
            handler=handlers[name],
            check_fn=available,
            emoji="🦊",
        )
