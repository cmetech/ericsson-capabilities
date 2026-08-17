"""Ericsson Artifactory standalone connector registration."""

from __future__ import annotations

import json

# Task 1 has no write tools. Keep the registered hook intentionally inert:
# it must not inspect, serialize, or render untrusted arguments before Task 5
# introduces bounded, argument-scoped approval summaries.
_WRITE_TOOLS: frozenset[str] = frozenset()
WRITE_APPROVALS: dict[str, object] = {}


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


def register(ctx: object) -> None:
    """Register bounded ARM reads and reserve the hook for future writes."""

    def require_write_approval(
        _tool_name: object, _args: object, **_kwargs: object
    ) -> None:
        return None

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
