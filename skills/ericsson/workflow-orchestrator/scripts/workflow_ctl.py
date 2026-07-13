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
import calendar
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


# --- run state io ------------------------------------------------------------

def _sha256_file(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def find_run(run_id: str) -> Path:
    root = runs_root()
    if root.exists():
        for wf_dir in sorted(root.iterdir()):
            cand = wf_dir / run_id
            if cand.is_dir():
                return cand
    raise FileNotFoundError(f"run not found: {run_id}")


def save_state(run_dir: Path, state: dict) -> None:
    state["updated_at"] = now_iso()
    tmp = run_dir / "state.json.tmp"
    tmp.write_text(json.dumps(state, indent=2))
    os.replace(tmp, run_dir / "state.json")


REQUIRED_STATE_KEYS = {"run_id", "status", "nodes", "node_order", "report", "inputs"}


def _quarantine_state(run_dir: Path, sf: Path) -> RuntimeError:
    """Rename a corrupt/malformed state.json out of the way and return the
    actionable error to raise. Shared by the decode-error and shape-error
    paths in load_state() so both fail the same way."""
    quarantine = run_dir / f"state.json.corrupt-{time.strftime('%Y%m%d-%H%M%S')}"
    os.replace(sf, quarantine)
    return RuntimeError(
        f"state.json was corrupt and has been quarantined to {quarantine.name}. "
        "Start a fresh run with 'start', or delete this run with 'clean --run'."
    )


def load_state(run_dir: Path) -> dict:
    sf = run_dir / "state.json"
    if not sf.exists():
        raise FileNotFoundError(f"no state.json in {run_dir}")
    try:
        data = json.loads(sf.read_text())
    except json.JSONDecodeError:
        raise _quarantine_state(run_dir, sf) from None
    if not isinstance(data, dict) or not REQUIRED_STATE_KEYS.issubset(data.keys()):
        raise _quarantine_state(run_dir, sf) from None
    return data


def _load_run(run_id: str):
    """(run_dir, state) or fail()."""
    try:
        run_dir = find_run(run_id)
        return run_dir, load_state(run_dir)
    except (FileNotFoundError, RuntimeError) as e:
        fail(str(e))


def _check_yaml_unchanged(state: dict) -> None:
    p = Path(state["yaml_path"])
    if not p.exists():
        fail(f"workflow file has been deleted: {p}. Use 'restart' with a new file or 'clean --run'.")
    if _sha256_file(p) != state["yaml_sha256"]:
        fail(f"workflow file changed since this run started: {p}. "
             "Use 'resume --run <id> --accept-changes' to adopt the new file, or 'restart'.")


# --- start -------------------------------------------------------------------

def _parse_inputs(pairs, doc):
    values = {}
    for item in doc.get("inputs", []) or []:
        if isinstance(item, dict) and "default" in item:
            values[item["name"]] = item["default"]
    declared = {item["name"] for item in doc.get("inputs", []) or []
                if isinstance(item, dict) and "name" in item}
    for pair in pairs or []:
        if "=" not in pair:
            fail(f"--input must be key=value, got: {pair}")
        k, v = pair.split("=", 1)
        if k not in declared:
            fail(f"unknown input: {k} (declared: {sorted(declared) or 'none'})")
        values[k] = v
    return values


def cmd_start(args):
    try:
        doc = load_workflow(args.workflow)
    except Exception as e:
        fail(str(e))
    errors, warnings = validate_workflow(doc)
    if errors:
        fail("workflow is invalid; fix it or run 'validate' for details", errors=errors)
    inputs = _parse_inputs(args.input, doc)

    run_id = time.strftime("%Y%m%d-%H%M%S", time.gmtime()) + "-" + secrets.token_hex(2)
    run_dir = runs_root() / doc["name"] / run_id
    run_dir.mkdir(parents=True, exist_ok=False)

    report = dict(doc.get("report") or {})
    state = {
        "workflow": doc["name"], "version": doc["version"],
        "yaml_path": str(Path(args.workflow).resolve()),
        "yaml_sha256": _sha256_file(args.workflow),
        "run_id": run_id, "status": "running",
        "created_at": now_iso(), "updated_at": now_iso(),
        "inputs": inputs,
        "report": {"kanban": report.get("kanban", "auto"),
                   "notify": report.get("notify", []),
                   "kanban_task_id": None},
        "node_order": [n["id"] for n in doc["nodes"]],
        "nodes": {n["id"]: {"kind": n["kind"], "status": "pending",
                             "side_effects": bool(n.get("side_effects")),
                             "attempts": 0, "started_at": None, "finished_at": None,
                             "outputs": [], "summary": None, "error": None,
                             "approval": None, "skip_reason": None}
                   for n in doc["nodes"]},
    }
    save_state(run_dir, state)
    emit({"run_id": run_id, "workflow": doc["name"], "run_dir": str(run_dir),
          "report": state["report"], "warnings": warnings})


# --- next --------------------------------------------------------------------

def _state_resolver(state):
    def resolve(ref):
        if ref.startswith("$inputs."):
            return state["inputs"].get(ref[len("$inputs."):])
        m = re.match(r"^\$([A-Za-z0-9_-]+)\.output$", ref)
        if m:
            node = state["nodes"].get(m.group(1))
            if node and node["status"] == "ok":
                return node.get("summary")
        return None
    return resolve


def _parse_iso(ts):
    return calendar.timegm(time.strptime(ts, "%Y-%m-%dT%H:%M:%SZ"))


def _is_stale(node, stale_after_min):
    if not node.get("started_at"):
        return False
    age_min = (time.time() - _parse_iso(node["started_at"])) / 60.0
    return age_min > stale_after_min


def compute_next(state, doc, stale_after_min=STALE_AFTER_MIN):
    """Advance the frontier. Mutates state (skips / marks running / parks) and
    returns the response dict. Caller saves state afterwards."""
    if state["status"] in TERMINAL:
        return {"action": state["status"], "report": state["report"]}
    node_defs = {n["id"]: n for n in doc["nodes"]}
    resolver = _state_resolver(state)

    # Skip-cascades can span node_order in either direction (a dependency may
    # be declared AFTER its dependent in the YAML). A single left-to-right
    # pass only propagates one hop of "dependency skipped" per call, which
    # can leave the frontier with no runnable node and nothing returned yet
    # every node effectively resolved. Re-run the scan to a fixpoint: only
    # stop once a full pass changes no node's status.
    while True:
        changed = False
        for nid in state["node_order"]:
            node = state["nodes"][nid]
            if node["status"] == "running":
                if _is_stale(node, stale_after_min):
                    return {"action": "interrupted", "node_id": nid,
                            "hint": f"agent died mid-node; run 'resume --run {state['run_id']}'"}
                return {"action": "in_progress", "node_id": nid}
            if node["status"] == "waiting_approval":
                return {"action": "wait_approval", "node_id": nid,
                        "message": node_defs[nid].get("message", ""),
                        "report": state["report"]}
            if node["status"] != "pending":
                continue

            deps = node_defs[nid].get("depends_on", []) or []
            dep_states = [state["nodes"][d]["status"] for d in deps]
            if any(s in ("failed", "rejected") for s in dep_states):
                continue  # run already failed via record; defensive
            if any(s == "skipped" for s in dep_states):
                node["status"] = "skipped"
                node["skip_reason"] = "dependency skipped"
                changed = True
                continue
            if not all(s == "ok" for s in dep_states):
                continue  # some dependency still ahead in order

            when = node_defs[nid].get("when")
            if when and not eval_when(when, resolver):
                node["status"] = "skipped"
                node["skip_reason"] = f"when evaluated false: {when}"
                changed = True
                continue

            if node["kind"] == "approval":
                node["status"] = "waiting_approval"
                state["status"] = "waiting_approval"
                return {"action": "wait_approval", "node_id": nid,
                        "message": node_defs[nid].get("message", ""),
                        "report": state["report"]}

            node["status"] = "running"
            node["attempts"] += 1
            node["started_at"] = now_iso()
            d = node_defs[nid]
            return {"action": "execute", "run_id": state["run_id"],
                    "node": {"id": nid, "kind": d["kind"], "prompt": d.get("prompt"),
                             "command": d.get("command"), "output": d.get("output"),
                             "side_effects": bool(d.get("side_effects"))},
                    "run_dir": str(find_run(state["run_id"])),
                    "report": state["report"]}

        if not changed:
            break

    statuses = {n["status"] for n in state["nodes"].values()}
    if statuses <= {"ok", "skipped"}:
        state["status"] = "done"
        return {"action": "done", "report": state["report"]}
    # Defensive fallback: unreachable for a valid DAG once the fixpoint scan
    # above has run — a full pass changed nothing and some node is still not
    # ok/skipped, which validate_workflow()'s cycle/dependency checks should
    # have already ruled out.
    return {"action": state["status"], "report": state["report"]}


def cmd_next(args):
    run_dir, state = _load_run(args.run)
    if state["status"] in TERMINAL:
        # Terminal runs are done; don't touch the YAML at all (it may have
        # been deleted/moved since the run finished).
        emit({"action": state["status"], "report": state["report"]})
    _check_yaml_unchanged(state)
    try:
        doc = load_workflow(state["yaml_path"])
    except Exception as e:
        fail(str(e))
    resp = compute_next(state, doc, args.stale_after_minutes)
    save_state(run_dir, state)
    emit(resp)


# --- record / set-kanban -------------------------------------------------------

def cmd_record(args):
    run_dir, state = _load_run(args.run)
    node = state["nodes"].get(args.node)
    if node is None:
        fail(f"unknown node: {args.node}")
    if node["status"] != "running":
        fail(f"node {args.node} is {node['status']}, not running — only running "
             "nodes can be recorded (approvals use approve/reject)")
    warnings = []
    if args.status == "ok":
        node["status"] = "ok"
        node["summary"] = args.summary
        node["outputs"] = list(args.output or [])
        for rel in node["outputs"]:
            if not (run_dir / rel).exists():
                warnings.append(f"declared output not found in run dir: {rel}")
    else:
        if not args.error:
            fail("--error is required when --status failed")
        node["status"] = "failed"
        node["error"] = args.error
        state["status"] = "failed"
    node["finished_at"] = now_iso()
    save_state(run_dir, state)
    emit({"ok": True, "run_status": state["status"], "node_status": node["status"],
          "report": state["report"], "warnings": warnings})


def cmd_set_kanban(args):
    run_dir, state = _load_run(args.run)
    state["report"]["kanban_task_id"] = args.task_id
    save_state(run_dir, state)
    emit({"ok": True, "kanban_task_id": args.task_id})


# --- approvals -----------------------------------------------------------------

def _waiting_node(state):
    for nid in state["node_order"]:
        if state["nodes"][nid]["status"] == "waiting_approval":
            return nid
    return None


def cmd_approve(args):
    run_dir, state = _load_run(args.run)
    nid = _waiting_node(state)
    if nid is None:
        fail("no node is waiting for approval on this run")
    node = state["nodes"][nid]
    node["status"] = "ok"
    node["finished_at"] = now_iso()
    node["approval"] = {"decision": "approved", "response": args.response, "at": now_iso()}
    state["status"] = "running"
    save_state(run_dir, state)
    emit({"ok": True, "run_status": "running", "approved_node": nid,
          "report": state["report"]})


def cmd_reject(args):
    run_dir, state = _load_run(args.run)
    nid = _waiting_node(state)
    if nid is None:
        fail("no node is waiting for approval on this run")
    node = state["nodes"][nid]
    node["status"] = "rejected"
    node["finished_at"] = now_iso()
    node["approval"] = {"decision": "rejected", "reason": args.reason, "at": now_iso()}
    state["status"] = "rejected"
    save_state(run_dir, state)
    emit({"ok": True, "run_status": "rejected", "rejected_node": nid,
          "reason": args.reason, "report": state["report"]})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="workflow_ctl", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("validate", help="structurally validate a workflow YAML")
    p.add_argument("workflow")
    p.set_defaults(fn=cmd_validate)

    p = sub.add_parser("start", help="start a new run")
    p.add_argument("workflow")
    p.add_argument("--input", action="append", metavar="k=v")
    p.set_defaults(fn=cmd_start)

    p = sub.add_parser("next", help="get the next runnable node")
    p.add_argument("--run", required=True)
    p.add_argument("--stale-after-minutes", type=int, default=STALE_AFTER_MIN)
    p.set_defaults(fn=cmd_next)

    p = sub.add_parser("record", help="record a node result")
    p.add_argument("--run", required=True)
    p.add_argument("--node", required=True)
    p.add_argument("--status", required=True, choices=["ok", "failed"])
    p.add_argument("--output", action="append")
    p.add_argument("--summary")
    p.add_argument("--error")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("set-kanban", help="record the mirroring kanban task id")
    p.add_argument("--run", required=True)
    p.add_argument("--task-id", required=True)
    p.set_defaults(fn=cmd_set_kanban)

    p = sub.add_parser("approve", help="approve the waiting approval node")
    p.add_argument("--run", required=True)
    p.add_argument("--response")
    p.set_defaults(fn=cmd_approve)

    p = sub.add_parser("reject", help="reject the waiting approval node (ends the run)")
    p.add_argument("--run", required=True)
    p.add_argument("--reason", required=True)
    p.set_defaults(fn=cmd_reject)

    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
