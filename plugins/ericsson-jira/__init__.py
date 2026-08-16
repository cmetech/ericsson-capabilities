"""Ericsson Jira standalone connector registration."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

from . import tools as jira_tools
from .models import JiraError, SAFE_ERROR_MESSAGES, safe_remediation


_WRITE_TOOLS = frozenset({"jira_add_comment", "jira_transition_issue"})


def _arg(args: dict, name: str) -> str:
    """Render one argument for an approval prompt, safely and bounded."""
    value = args.get(name) if isinstance(args, dict) else None
    return json.dumps(value, ensure_ascii=True)[:512]


WRITE_APPROVALS = {
    "jira_add_comment": lambda a: (
        f"Issue: {_arg(a, 'key')}\nBody: {_arg(a, 'body')}"
    ),
    "jira_transition_issue": lambda a: (
        f"Issue: {_arg(a, 'key')}\nTransition: {_arg(a, 'transition_id')}"
    ),
}


_PLUGIN_SKILLS = (
    ("ticket-research", "Research one bounded Jira ticket."),
    ("defect-triage", "Triage one Jira defect and prepare an approved comment."),
)

def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _interrupt_authority():
    try:
        from tools.interrupt import is_interrupted
    except ImportError:
        return lambda: False
    return is_interrupted


def _has_write_admission(admission, tool_name: str) -> bool:
    try:
        return (
            getattr(admission, "approved", None) is True
            and getattr(admission, "policy", None) == "plugin_approve"
            and getattr(admission, "tool_name", None) == tool_name
        )
    except Exception:
        return False


def register(ctx) -> None:
    """Register stable Jira tools using fresh opaque profile configuration."""

    def available() -> bool:
        try:
            return jira_tools.check_available(ctx.configuration())
        except Exception:
            return False

    def handler(name):
        def invoke(args: dict, **_kwargs) -> str:
            if name in _WRITE_TOOLS and not _has_write_admission(
                _kwargs.get("tool_admission"), name
            ):
                return _json(
                    {
                        "success": False,
                        "error": {
                            "category": "permission",
                            "message": SAFE_ERROR_MESSAGES["permission"],
                        },
                    }
                )
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
                error = {
                    "category": exc.category,
                    "message": SAFE_ERROR_MESSAGES[exc.category],
                }
                remediation = safe_remediation(getattr(exc, "remediation", None))
                if remediation:
                    error["remediation"] = remediation
                return _json(
                    {
                        "success": False,
                        "error": error,
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

    def require_write_approval(tool_name: str, args: dict, **_kwargs):
        summarise = WRITE_APPROVALS.get(tool_name)
        if summarise is None:
            return None
        canonical_args = json.dumps(
            args if isinstance(args, dict) else {},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "action": "approve",
            "message": (
                f"Approve Ericsson Jira change: {tool_name}\n"
                f"{summarise(args if isinstance(args, dict) else {})}"
            ),
            "rule_key": (
                f"{tool_name}:"
                f"{hashlib.sha256(canonical_args.encode('utf-8')).hexdigest()}"
            ),
        }

    ctx.register_hook("pre_tool_call", require_write_approval)

    for name, schema in jira_tools.SCHEMAS.items():
        ctx.register_tool(
            name=name,
            toolset="ericsson-jira",
            schema=schema,
            handler=handler(name),
            check_fn=available,
            emoji="🎫",
        )

    register_skill = getattr(ctx, "register_skill", None)
    if register_skill is not None:
        skill_root = Path(__file__).parent / "skills"
        for name, description in _PLUGIN_SKILLS:
            register_skill(name, skill_root / name / "SKILL.md", description)
