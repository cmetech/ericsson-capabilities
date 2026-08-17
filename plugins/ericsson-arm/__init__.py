"""Ericsson Artifactory standalone connector registration."""

from __future__ import annotations

import hashlib
import json

_WRITE_TOOLS = frozenset({"arm_deploy", "arm_delete"})
_APPROVAL_STRING_LIMITS = {"repo": 128, "path": 1024, "source_file": 4096}
_APPROVAL_REQUIRED_STRINGS = {
    "arm_deploy": frozenset({"repo", "path", "source_file"}),
    "arm_delete": frozenset({"repo", "path"}),
}


def _approval_rule_digest(tool_name: object, args: object) -> str | None:
    """Bind write approval to one bounded, schema-shaped tool request."""
    required_strings = _APPROVAL_REQUIRED_STRINGS.get(tool_name)
    if type(args) is not dict or required_strings is None:
        return None
    allowed = set(required_strings) | {"dry_run", "confirm"}
    if (
        not required_strings.issubset(args)
        or not set(args).issubset(allowed)
        or any(
            type(args.get(name)) is not str
            or not args[name]
            or len(args[name]) > _APPROVAL_STRING_LIMITS[name]
            for name in required_strings
        )
        or any(type(args[name]) is not bool for name in ("dry_run", "confirm") if name in args)
    ):
        return None
    try:
        canonical = json.dumps(args, ensure_ascii=True, separators=(",", ":"), sort_keys=True)
    except (TypeError, ValueError):
        return None
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _arg(args: object, name: str) -> str:
    """Render one already-bounded string argument for approval."""
    value = args.get(name) if type(args) is dict else None
    maximum = _APPROVAL_STRING_LIMITS.get(name, 0)
    if type(value) is not str or not value or len(value) > maximum:
        return '"<invalid>"'
    return json.dumps(value, ensure_ascii=True)


WRITE_APPROVALS = {
    "arm_deploy": lambda a: (
        f"Upload file: {_arg(a, 'source_file')}\n"
        f"To repository: {_arg(a, 'repo')}\n"
        f"At path: {_arg(a, 'path')}"
    ),
    "arm_delete": lambda a: (
        f"Delete from repository: {_arg(a, 'repo')}\n"
        f"Path: {_arg(a, 'path')}\n"
        f"A folder path removes everything beneath it, and Artifactory "
        f"deletion is not recoverable unless trash is enabled."
    ),
}


def _json(value) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def _tool_bindings():
    """Load package bindings only when the host can register tools.

    The narrow legacy manifest test loads this file as a standalone module to
    inspect its inert hook. Delaying imports preserves that harmless probe;
    production plugin loading uses the normal package-relative imports.
    """
    if __package__:
        from . import tools as arm_tools
        from .models import ArmError, SAFE_ERROR_MESSAGES, safe_remediation
    else:
        import tools as arm_tools
        from models import ArmError, SAFE_ERROR_MESSAGES, safe_remediation
    return arm_tools, ArmError, SAFE_ERROR_MESSAGES, safe_remediation


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


def register(ctx: object) -> None:
    """Register bounded ARM operations and approve writes by exact arguments."""

    def require_write_approval(tool_name: object, args: object, **_kwargs: object):
        summarise = WRITE_APPROVALS.get(tool_name)
        if summarise is None:
            return None
        argument_digest = _approval_rule_digest(tool_name, args)
        if argument_digest is None:
            return {
                "action": "block",
                "message": "ARM write arguments cannot be safely approved",
            }
        return {
            "action": "approve",
            "message": f"Approve Ericsson Artifactory write: {tool_name}\n{summarise(args)}",
            "rule_key": f"{tool_name}:{argument_digest}",
        }

    ctx.register_hook("pre_tool_call", require_write_approval)

    register_tool = getattr(ctx, "register_tool", None)
    if register_tool is None:
        return
    arm_tools, ArmError, SAFE_ERROR_MESSAGES, safe_remediation = _tool_bindings()

    def available() -> bool:
        try:
            return arm_tools.check_available(ctx.configuration())
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
                result = arm_tools.invoke(
                    name,
                    args or {},
                    configuration,
                    cancel_check=_interrupt_authority(),
                )
                return _json({"success": True, "result": result})
            except ArmError as exc:
                error = {
                    "category": exc.category,
                    "message": SAFE_ERROR_MESSAGES[exc.category],
                }
                remediation = safe_remediation(getattr(exc, "remediation", None))
                if remediation:
                    error["remediation"] = remediation
                return _json({"success": False, "error": error})
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

    for name, schema in arm_tools.SCHEMAS.items():
        register_tool(
            name=name,
            toolset="ericsson-arm",
            schema=schema,
            handler=handler(name),
            check_fn=available,
            emoji="📦",
        )
