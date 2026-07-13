import json
import time
from pathlib import Path

import pytest
import workflow_ctl as wc
from conftest import VALID_WF


def _start(ctl, write_wf, *inputs):
    p = write_wf(VALID_WF)
    args = ["start", str(p)]
    for kv in inputs:
        args += ["--input", kv]
    code, out = ctl(*args)
    assert code == 0
    return out


def test_start_creates_state(ctl, write_wf, home):
    out = _start(ctl, write_wf)
    run_dir = Path(out["run_dir"])
    assert run_dir.exists()
    state = json.loads((run_dir / "state.json").read_text())
    assert state["status"] == "running"
    assert state["inputs"]["deliver_to"] == "chat"          # default filled
    assert state["node_order"] == ["fetch", "summarize", "send"]
    assert all(n["status"] == "pending" for n in state["nodes"].values())
    assert out["report"]["kanban"] == "auto"


def test_start_rejects_invalid_workflow(ctl, write_wf):
    p = write_wf("name: demo\nnodes: []\n", name="bad.yml")
    code, out = ctl("start", str(p))
    assert code == 1 and "error" in out


def test_happy_path_with_when_skip(ctl, write_wf):
    out = _start(ctl, write_wf)               # deliver_to=chat -> send is skipped
    rid = out["run_id"]

    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "execute" and nxt["node"]["id"] == "fetch"
    # a second next while fetch is running reports in_progress (concurrency guard)
    code, again = ctl("next", "--run", rid)
    assert again["action"] == "in_progress" and again["node_id"] == "fetch"

    code, rec = ctl("record", "--run", rid, "--node", "fetch",
                    "--status", "ok", "--summary", "42 things")
    assert rec["ok"] and rec["run_status"] == "running"

    code, nxt = ctl("next", "--run", rid)
    assert nxt["node"]["id"] == "summarize"
    ctl("record", "--run", rid, "--node", "summarize", "--status", "ok",
        "--summary", "summarized")

    code, nxt = ctl("next", "--run", rid)     # send: when false -> skipped -> done
    assert nxt["action"] == "done"
    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert state["nodes"]["send"]["status"] == "skipped"
    assert state["status"] == "done"


def test_when_true_executes_send(ctl, write_wf):
    out = _start(ctl, write_wf, "deliver_to=email")
    rid = out["run_id"]
    for node in ("fetch", "summarize"):
        code, nxt = ctl("next", "--run", rid)
        assert nxt["node"]["id"] == node
        if node == "fetch":
            assert nxt["inputs"]["deliver_to"] == "email"
        ctl("record", "--run", rid, "--node", node, "--status", "ok", "--summary", "s")
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "execute" and nxt["node"]["id"] == "send"
    assert nxt["node"]["side_effects"] is True


def test_record_failure_fails_run(ctl, write_wf):
    rid = _start(ctl, write_wf)["run_id"]
    ctl("next", "--run", rid)
    code, rec = ctl("record", "--run", rid, "--node", "fetch",
                    "--status", "failed", "--error", "jira 401")
    assert rec["run_status"] == "failed"
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "failed"


def test_record_output_file_check(ctl, write_wf):
    rid = _start(ctl, write_wf)["run_id"]
    ctl("next", "--run", rid)
    run_dir = wc.find_run(rid)
    (run_dir / "things.json").write_text("[]")
    code, rec = ctl("record", "--run", rid, "--node", "fetch", "--status", "ok",
                    "--output", "things.json", "--output", "missing.txt")
    assert rec["ok"]
    assert any("missing.txt" in w for w in rec["warnings"])


def test_yaml_edit_mid_run_detected(ctl, write_wf, home):
    p = write_wf(VALID_WF)
    code, out = ctl("start", str(p))
    rid = out["run_id"]
    p.write_text(VALID_WF + "\n# edited\n")
    code, out = ctl("next", "--run", rid)
    assert code == 1 and "changed" in out["error"]


def test_record_wrong_node_or_status(ctl, write_wf):
    rid = _start(ctl, write_wf)["run_id"]
    code, out = ctl("record", "--run", rid, "--node", "fetch", "--status", "ok")
    assert code == 1                       # fetch is pending, not running
    code, out = ctl("next", "--run", rid)
    code, out = ctl("record", "--run", rid, "--node", "ghost", "--status", "ok")
    assert code == 1


def test_set_kanban(ctl, write_wf):
    rid = _start(ctl, write_wf)["run_id"]
    code, out = ctl("set-kanban", "--run", rid, "--task-id", "KB-7")
    assert code == 0
    code, nxt = ctl("next", "--run", rid)
    assert nxt["report"]["kanban_task_id"] == "KB-7"


# --- regression tests for review findings ------------------------------------

SKIP_CASCADE_OUT_OF_ORDER_WF = """\
name: skiptest
description: skip cascade spans declaration order
version: 1.0.0
inputs:
  - {name: run_a, default: "no"}
nodes:
  - id: a
    kind: tool
    prompt: do a
    when: "$inputs.run_a == 'yes'"
  - id: c
    kind: tool
    depends_on: [b]
    prompt: do c
  - id: b
    kind: tool
    depends_on: [a]
    prompt: do b
"""


def test_compute_next_fixpoint_skip_cascade_out_of_order(ctl, write_wf):
    """Finding 1: node_order [a, c, b] with c depends_on [b], b depends_on [a],
    and a skipped via `when`. A single left-to-right pass can't propagate the
    skip from a -> b -> c in declaration order; compute_next must re-scan to a
    fixpoint so the FIRST next() call sees the whole run resolved to done,
    rather than leaking an off-contract {"action": "running"}."""
    p = write_wf(SKIP_CASCADE_OUT_OF_ORDER_WF, name="skiptest.yml")
    code, out = ctl("start", str(p))
    assert code == 0
    rid = out["run_id"]

    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "done"

    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert state["status"] == "done"
    assert all(state["nodes"][n]["status"] == "skipped" for n in ("a", "b", "c"))


def test_parse_iso_matches_wallclock():
    """Finding 2: _parse_iso must use a DST-independent conversion
    (calendar.timegm), not time.mktime(...) - time.timezone which uses the
    standard (non-DST) UTC offset year-round."""
    assert abs(wc._parse_iso(wc.now_iso()) - time.time()) < 5


def test_next_on_terminal_run_short_circuits_without_yaml(ctl, write_wf):
    """Finding 3: cmd_next must not reload the workflow YAML for a run that's
    already terminal — deleting the YAML after completion must not break
    re-querying `next` on a done run."""
    p = write_wf(VALID_WF)
    code, out = ctl("start", str(p))
    rid = out["run_id"]
    for node in ("fetch", "summarize"):
        code, nxt = ctl("next", "--run", rid)
        assert nxt["node"]["id"] == node
        ctl("record", "--run", rid, "--node", node, "--status", "ok", "--summary", "s")
    code, nxt = ctl("next", "--run", rid)     # send: when false -> skipped -> done
    assert nxt["action"] == "done"

    p.unlink()                                # workflow YAML gone
    code, nxt = ctl("next", "--run", rid)
    assert code == 0
    assert nxt["action"] == "done"


def test_load_state_quarantines_wrong_shape(ctl, write_wf):
    """Finding 4: a valid-JSON-but-wrong-shape state.json (e.g. `[]`) must be
    quarantined the same way a JSONDecodeError is, not raise uncaught."""
    rid = _start(ctl, write_wf)["run_id"]
    run_dir = wc.find_run(rid)
    (run_dir / "state.json").write_text("[]")

    code, out = ctl("next", "--run", rid)
    assert code == 1
    assert "quarantine" in out["error"]
    assert any(child.name.startswith("state.json.corrupt-") for child in run_dir.iterdir())
