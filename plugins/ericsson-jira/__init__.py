"""Ericsson Jira standalone connector registration."""

from __future__ import annotations

import json

from . import tools as jira_tools
from .models import JiraError, SAFE_ERROR_MESSAGES


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _interrupt_authority():
    try:
        from tools.interrupt import is_interrupted
    except ImportError:
        return lambda: False
    return is_interrupted


def register(ctx) -> None:
    """Register stable Jira tools using fresh opaque profile configuration."""

    def available() -> bool:
        try:
            return jira_tools.check_available(ctx.configuration())
        except Exception:
            return False

    def handler(name):
        def invoke(args: dict, **_kwargs) -> str:
            try:
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
                result = jira_tools.invoke(
                    name,
                    args or {},
                    configuration,
                    cancel_check=_interrupt_authority(),
                )
                return _json({"success": True, "result": result})
            except JiraError as exc:
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

    for name, schema in jira_tools.SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset="ericsson-jira",
            schema=schema,
            handler=handler(name),
            check_fn=available,
            emoji="🎫",
        )
