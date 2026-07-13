#!/usr/bin/env python3
"""workflow_ctl.py — deterministic state machine for Ericsson workflow runs.

The workflow-orchestrator skill is the only intended caller. Every command
prints exactly ONE JSON object to stdout; exit 0 on success, exit 1 with
{"error": ...} on failure. The agent NEVER mutates run state itself — this
script owns ordering, conditions, approvals, completion, and recovery.

Runtime deps: stdlib + PyYAML (both available in the Hermes venv).
Layout: $HERMES_HOME/workflows/<name>.yml (library) and
        $HERMES_HOME/workflows/runs/<workflow>/<run_id>/state.json (runs).
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import secrets
import shutil
import sys
import time
from pathlib import Path

import yaml

SLUG_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")
NODE_KINDS = {"prompt", "tool", "script", "approval"}
TOP_KEYS = {"name", "description", "version", "tags", "requires", "inputs", "nodes", "report"}
NODE_KEYS = {"id", "kind", "prompt", "command", "message", "depends_on", "when",
             "output", "side_effects", "toolset"}
KANBAN_MODES = {"auto", "on", "off"}
TERMINAL = {"done", "failed", "cancelled", "rejected"}
STALE_AFTER_MIN = 120  # default; overridable via --stale-after-minutes


# --- paths / io ------------------------------------------------------------

def hermes_home() -> Path:
    return Path(os.environ.get("HERMES_HOME") or (Path.home() / ".hermes"))


def workflows_dir() -> Path:
    return hermes_home() / "workflows"


def runs_root() -> Path:
    return workflows_dir() / "runs"


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def emit(obj: dict, code: int = 0) -> None:
    print(json.dumps(obj, indent=2))
    sys.exit(code)


def fail(msg: str, **extra) -> None:
    emit({"error": str(msg), **extra}, code=1)


# --- when-expression parsing (v1: ==/!=, && binds tighter than ||) ---------

class WhenError(ValueError):
    pass


_COND_RE = re.compile(
    r"^\s*(\$[A-Za-z0-9_-]+(?:\.[A-Za-z0-9_-]+)+)\s*(==|!=)\s*"
    r"(?:'([^']*)'|([A-Za-z0-9_./@:-]+))\s*$"
)


def parse_when(expr: str):
    """'$a.output == x && $b.output != y || $inputs.c == z' ->
    [[(ref,op,val),(ref,op,val)], [(ref,op,val)]]  (OR-list of AND-lists)."""
    if not isinstance(expr, str) or not expr.strip():
        raise WhenError("empty when expression")
    groups = []
    for or_part in expr.split("||"):
        conds = []
        for and_part in or_part.split("&&"):
            m = _COND_RE.match(and_part)
            if not m:
                raise WhenError(f"cannot parse condition: {and_part.strip()!r}")
            value = m.group(3) if m.group(3) is not None else m.group(4)
            conds.append((m.group(1), m.group(2), value))
        groups.append(conds)
    return groups


def when_refs(expr: str):
    return [c[0] for g in parse_when(expr) for c in g]


def eval_when(expr: str, resolver) -> bool:
    """Fail-closed: parse errors or unresolvable refs make the condition False."""
    try:
        groups = parse_when(expr)
    except WhenError:
        return False
    for conds in groups:
        ok = True
        for ref, op, value in conds:
            actual = resolver(ref)
            if actual is None:
                ok = False
                break
            matches = str(actual) == value
            if (op == "==") != matches:
                ok = False
                break
        if ok:
            return True
    return False


# --- validation -------------------------------------------------------------

def load_workflow(path) -> dict:
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"workflow file not found: {p}")
    try:
        doc = yaml.safe_load(p.read_text())
    except yaml.YAMLError as e:
        raise ValueError(f"invalid YAML: {e}")
    if not isinstance(doc, dict):
        raise ValueError("workflow must be a YAML mapping")
    return doc


def _detect_cycle(ids, deps) -> bool:
    """Kahn's algorithm; True when a cycle exists."""
    indeg = {i: 0 for i in ids}
    for n, ds in deps.items():
        for d in ds:
            if d in indeg:
                indeg[n] += 1
    queue = [i for i, d in indeg.items() if d == 0]
    seen = 0
    dependents = {i: [n for n, ds in deps.items() if i in ds] for i in ids}
    while queue:
        cur = queue.pop()
        seen += 1
        for nxt in dependents[cur]:
            indeg[nxt] -= 1
            if indeg[nxt] == 0:
                queue.append(nxt)
    return seen != len(ids)


def validate_workflow(doc: dict):
    """Structural validation. Returns (errors, warnings). requires.env presence
    is a WARNING (background installs may set env later); everything else that
    is wrong is an ERROR."""
    errors, warnings = [], []

    for key in ("name", "description", "version"):
        if not isinstance(doc.get(key), str) or not doc.get(key, "").strip():
            errors.append(f"missing or empty required key: {key}")
    if isinstance(doc.get("name"), str) and doc.get("name") and not SLUG_RE.match(doc["name"]):
        errors.append("name must be a slug: lowercase letters/digits/-/_")
    for key in doc:
        if key not in TOP_KEYS:
            errors.append(f"unknown top-level key: {key}")

    inputs = doc.get("inputs", [])
    input_names = set()
    if not isinstance(inputs, list):
        errors.append("inputs must be a list")
    else:
        for i, item in enumerate(inputs):
            if not isinstance(item, dict) or not isinstance(item.get("name"), str):
                errors.append(f"inputs[{i}] must be a mapping with a 'name'")
            else:
                input_names.add(item["name"])

    report = doc.get("report", {})
    if report and not isinstance(report, dict):
        errors.append("report must be a mapping")
    elif isinstance(report, dict):
        if report.get("kanban", "auto") not in KANBAN_MODES:
            errors.append("report.kanban must be one of auto|on|off")
        if not isinstance(report.get("notify", []), list):
            errors.append("report.notify must be a list")

    requires = doc.get("requires", {})
    if requires and not isinstance(requires, dict):
        errors.append("requires must be a mapping")
    elif isinstance(requires, dict):
        for env_var in requires.get("env", []) or []:
            if not os.environ.get(str(env_var)):
                warnings.append(f"required env var not set: {env_var}")

    nodes = doc.get("nodes")
    if not isinstance(nodes, list) or not nodes:
        errors.append("nodes must be a non-empty list")
        return errors, warnings

    ids, deps = [], {}
    for i, node in enumerate(nodes):
        if not isinstance(node, dict):
            errors.append(f"nodes[{i}] must be a mapping")
            continue
        nid = node.get("id")
        if not isinstance(nid, str) or not SLUG_RE.match(nid or ""):
            errors.append(f"nodes[{i}] needs a slug 'id'")
            continue
        if nid in ids:
            errors.append(f"duplicate node id: {nid}")
        ids.append(nid)
        for key in node:
            if key not in NODE_KEYS:
                errors.append(f"node {nid}: unknown key: {key}")
        kind = node.get("kind")
        if kind not in NODE_KINDS:
            errors.append(f"node {nid}: kind must be one of {sorted(NODE_KINDS)}")
        if kind in ("prompt", "tool") and not node.get("prompt"):
            errors.append(f"node {nid}: kind {kind} requires 'prompt'")
        if kind == "script" and not node.get("command"):
            errors.append(f"node {nid}: kind script requires 'command'")
        if kind == "approval" and not node.get("message"):
            errors.append(f"node {nid}: kind approval requires 'message'")
        out = node.get("output")
        if out is not None:
            if not isinstance(out, str) or "/" in out or "\\" in out or out.startswith("."):
                errors.append(f"node {nid}: output must be a bare filename (no paths): {out!r}")
        deps[nid] = list(node.get("depends_on", []) or [])

    known = set(ids)
    for nid, ds in deps.items():
        for d in ds:
            if d not in known:
                errors.append(f"node {nid}: unknown depends_on ref: {d}")
    if not any("unknown depends_on" in e for e in errors) and _detect_cycle(ids, deps):
        errors.append("dependency cycle detected in nodes")

    for node in nodes:
        if not isinstance(node, dict) or not node.get("when"):
            continue
        nid = node.get("id", "?")
        try:
            for ref in when_refs(node["when"]):
                if ref.startswith("$inputs."):
                    if ref[len("$inputs."):] not in input_names:
                        errors.append(f"node {nid}: when references unknown input: {ref}")
                else:
                    m = re.match(r"^\$([A-Za-z0-9_-]+)\.output$", ref)
                    if not m or m.group(1) not in known:
                        errors.append(f"node {nid}: when references unknown node output: {ref}")
        except WhenError as e:
            errors.append(f"node {nid}: invalid when expression: {e}")

    return errors, warnings


# --- CLI ---------------------------------------------------------------------

def cmd_validate(args):
    try:
        doc = load_workflow(args.workflow)
    except Exception as e:
        fail(str(e))
    errors, warnings = validate_workflow(doc)
    if errors:
        fail("validation failed", errors=errors, warnings=warnings)
    emit({"ok": True, "name": doc["name"], "version": doc["version"], "warnings": warnings})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="workflow_ctl", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="structurally validate a workflow YAML")
    p.add_argument("workflow")
    p.set_defaults(fn=cmd_validate)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
