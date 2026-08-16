"""Ericsson Jira standalone connector registration."""

from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path

from . import tools as jira_tools
from .models import JiraError, SAFE_ERROR_MESSAGES, safe_remediation


_WRITE_TOOLS = frozenset(
    {
        "jira_add_comment",
        "jira_transition_issue",
        "jira_assign_issue",
        "jira_update_fields",
    }
)
_INVALID_APPROVAL_ARGS = "<invalid-approval-args>"
_MAX_APPROVAL_CANONICAL_BYTES = 131_072
_MAX_APPROVAL_CANONICAL_DEPTH = 64
_MAX_APPROVAL_CANONICAL_NODES = 12_000
_MAX_APPROVAL_RENDERED_ARGUMENT = 256
_MAX_APPROVAL_PREVIEW_STRING = 128


class _InvalidApprovalArguments(Exception):
    """Internal marker for values that cannot safely bind an approval."""


def _canonical_approval_args(args) -> str:
    """Return an exact bounded canonical form, or one invalid-input sentinel.

    Valid tool arguments are JSON-shaped and fit the operation-level limits,
    so a sorted compact encoding binds every argument byte-for-byte.  This
    boundary runs before operation validation, however, and must also safely
    absorb arbitrary Python objects, cycles, and pathological JSON shapes.
    Those cannot reach a write: they use one deliberately non-specific
    sentinel rather than serializing or exposing their caller content.
    """

    nodes = 0
    active: set[int] = set()

    def normalize(value, depth: int):
        nonlocal nodes
        nodes += 1
        if (
            nodes > _MAX_APPROVAL_CANONICAL_NODES
            or depth > _MAX_APPROVAL_CANONICAL_DEPTH
        ):
            raise _InvalidApprovalArguments
        if value is None or type(value) in {bool, int, str}:
            if type(value) is str and len(value) > _MAX_APPROVAL_CANONICAL_BYTES:
                raise _InvalidApprovalArguments
            return value
        if type(value) is float:
            if not math.isfinite(value):
                raise _InvalidApprovalArguments
            return value
        if type(value) is dict:
            identity = id(value)
            if identity in active:
                raise _InvalidApprovalArguments
            active.add(identity)
            try:
                normalized = {}
                for key, nested in value.items():
                    if type(key) is not str:
                        raise _InvalidApprovalArguments
                    if len(key) > _MAX_APPROVAL_CANONICAL_BYTES:
                        raise _InvalidApprovalArguments
                    normalized[key] = normalize(nested, depth + 1)
                return normalized
            finally:
                active.remove(identity)
        if type(value) is list:
            identity = id(value)
            if identity in active:
                raise _InvalidApprovalArguments
            active.add(identity)
            try:
                return [normalize(nested, depth + 1) for nested in value]
            finally:
                active.remove(identity)
        raise _InvalidApprovalArguments

    try:
        normalized = normalize(args, 0)
        encoded = json.dumps(
            normalized,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
            allow_nan=False,
        )
        if len(encoded.encode("utf-8")) > _MAX_APPROVAL_CANONICAL_BYTES:
            raise _InvalidApprovalArguments
        return encoded
    except (Exception,):
        return _INVALID_APPROVAL_ARGS


def _arg(args: dict, name: str) -> str:
    """Render one argument for an approval prompt, safely and bounded."""
    value = args.get(name) if type(args) is dict else None
    budget = 8

    def bounded(item, depth: int = 0):
        nonlocal budget
        budget -= 1
        if budget < 0 or depth > 4:
            return "<truncated>"
        if item is None or type(item) in {bool, int}:
            return item
        if type(item) is float:
            return item if math.isfinite(item) else "<unsupported>"
        if type(item) is str:
            return (
                item
                if len(item) <= _MAX_APPROVAL_PREVIEW_STRING
                else "<truncated>"
            )
        if type(item) is dict:
            normalized = {}
            for index, (key, nested) in enumerate(item.items()):
                if index >= 8:
                    break
                normalized[
                    key
                    if type(key) is str and len(key) <= _MAX_APPROVAL_PREVIEW_STRING
                    else "<invalid-key>"
                ] = bounded(nested, depth + 1)
            return normalized
        if type(item) is list:
            return [bounded(nested, depth + 1) for nested in item[:8]]
        return "<unsupported>"

    try:
        return json.dumps(bounded(value), ensure_ascii=True, allow_nan=False)[
            :_MAX_APPROVAL_RENDERED_ARGUMENT
        ]
    except Exception:
        return '"<unrepresentable>"'


WRITE_APPROVALS = {
    "jira_add_comment": lambda a: (
        f"Issue: {_arg(a, 'key')}\nBody: {_arg(a, 'body')}"
    ),
    "jira_transition_issue": lambda a: (
        f"Issue: {_arg(a, 'key')}\nTransition: {_arg(a, 'transition_id')}"
    ),
    "jira_assign_issue": lambda a: (
        f"Issue: {_arg(a, 'key')}\nAssignee: {_arg(a, 'assignee')}"
    ),
    "jira_update_fields": lambda a: (
        f"Issue: {_arg(a, 'key')}\nFields: {_arg(a, 'fields')}"
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
        canonical_args = _canonical_approval_args(args)
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
