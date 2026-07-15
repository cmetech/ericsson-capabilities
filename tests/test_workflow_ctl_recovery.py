import json
import time

import workflow_ctl as wc
from conftest import VALID_WF

SIDE_EFFECT_FIRST_WF = """\
name: sender
description: side-effecting first node
version: 1.0.0
nodes:
  - id: send
    kind: tool
    tools: [example_send]
    side_effects: true
    prompt: send the thing with example_send
  - id: log
    kind: prompt
    depends_on: [send]
    prompt: log it
"""


def _started(ctl, write_wf, text=VALID_WF, name="wf.yml", *inputs):
    p = write_wf(text, name=name)
    args = ["start", str(p)]
    for kv in inputs:
        args += ["--input", kv]
    code, out = ctl(*args)
    return out["run_id"], p


def _make_stale(rid, node_id):
    run_dir = wc.find_run(rid)
    state = json.loads((run_dir / "state.json").read_text())
    state["nodes"][node_id]["started_at"] = "2020-01-01T00:00:00Z"
    (run_dir / "state.json").write_text(json.dumps(state))


def test_resume_failed_node(ctl, write_wf):
    rid, _ = _started(ctl, write_wf)
    ctl("next", "--run", rid)
    ctl("record", "--run", rid, "--node", "fetch", "--status", "failed", "--error", "boom")
    code, out = ctl("resume", "--run", rid)
    assert code == 0 and out["resumed_node"] == "fetch" and out["run_status"] == "running"
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "execute" and nxt["node"]["id"] == "fetch"
    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert state["nodes"]["fetch"]["attempts"] == 2


def test_stale_running_node_interrupted_then_resume(ctl, write_wf):
    rid, _ = _started(ctl, write_wf)
    ctl("next", "--run", rid)              # fetch running
    _make_stale(rid, "fetch")
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "interrupted" and nxt["node_id"] == "fetch"
    code, out = ctl("resume", "--run", rid)
    assert code == 0 and out["resumed_node"] == "fetch"


def test_side_effect_node_needs_force(ctl, write_wf):
    rid, _ = _started(ctl, write_wf, SIDE_EFFECT_FIRST_WF, "sender.yml")
    ctl("next", "--run", rid)              # send running
    _make_stale(rid, "send")
    code, out = ctl("resume", "--run", rid)
    assert code == 1 and "side" in out["error"].lower()
    code, out = ctl("resume", "--run", rid, "--force-node", "send")
    assert code == 0 and out["resumed_node"] == "send"


def test_skip_side_effect_node(ctl, write_wf):
    rid, _ = _started(ctl, write_wf, SIDE_EFFECT_FIRST_WF, "sender.yml")
    ctl("next", "--run", rid)
    _make_stale(rid, "send")
    code, out = ctl("skip", "--run", rid, "--node", "send", "--reason", "already sent")
    assert code == 0 and out["node_status"] == "skipped"
    code, nxt = ctl("next", "--run", rid)   # log depends on send(skipped) -> skipped -> done
    assert nxt["action"] == "done"


def test_accept_changes(ctl, write_wf):
    rid, p = _started(ctl, write_wf)
    ctl("next", "--run", rid)
    ctl("record", "--run", rid, "--node", "fetch", "--status", "ok", "--summary", "s")
    # insert an extra node at the END of the nodes list (before the report block)
    p.write_text(VALID_WF.replace(
        "report:",
        "  - id: extra\n    kind: prompt\n    depends_on: [send]\n    prompt: extra step\nreport:"))
    code, out = ctl("next", "--run", rid)
    assert code == 1
    code, out = ctl("resume", "--run", rid, "--accept-changes")
    assert code == 0
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "execute" and nxt["node"]["id"] == "summarize"
    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert "extra" in state["nodes"] and state["nodes"]["extra"]["status"] == "pending"


def test_cancel_and_clean(ctl, write_wf):
    rid, _ = _started(ctl, write_wf)
    code, out = ctl("clean", "--run", rid)
    assert code == 1                        # running -> refuses without --force
    code, out = ctl("cancel", "--run", rid)
    assert out["run_status"] == "cancelled"
    code, out = ctl("clean", "--run", rid)
    assert code == 0 and rid in out["removed"]
    import pytest
    with pytest.raises(FileNotFoundError):
        wc.find_run(rid)


def test_clean_keep_n(ctl, write_wf):
    rids = []
    for _ in range(3):
        rid, _ = _started(ctl, write_wf)
        ctl("cancel", "--run", rid)
        rids.append(rid)
        time.sleep(1.1)                     # distinct run-id timestamps
    code, out = ctl("clean", "--workflow", "demo", "--keep", "1")
    assert code == 0 and set(out["removed"]) == set(rids[:2])


def test_status_and_list(ctl, write_wf):
    rid, _ = _started(ctl, write_wf)
    code, out = ctl("status", "--run", rid)
    assert out["run_id"] == rid and out["status"] == "running"
    assert {n["id"] for n in out["nodes"]} == {"fetch", "summarize", "send"}
    code, out = ctl("status", "--workflow", "demo")
    assert any(r["run_id"] == rid for r in out["runs"])
    code, out = ctl("list")
    assert any(w["name"] == "demo" for w in out["workflows"])
    assert any(r["run_id"] == rid for r in out["runs"])


def test_corrupt_state_quarantined(ctl, write_wf):
    rid, _ = _started(ctl, write_wf)
    run_dir = wc.find_run(rid)
    (run_dir / "state.json").write_text("{not json")
    code, out = ctl("next", "--run", rid)
    assert code == 1 and "quarantine" in out["error"].lower()
    assert list(run_dir.glob("state.json.corrupt-*"))


def test_skip_wrong_node_does_not_revive_stalled_run(ctl, write_wf):
    """Finding 1: skipping a node that is NOT the blocker must not flip a
    failed run back to "running" — that produces a silent, unrecoverable
    stall where 'next' just keeps reporting {"action": "running"} forever."""
    rid, _ = _started(ctl, write_wf)
    ctl("next", "--run", rid)  # fetch running
    ctl("record", "--run", rid, "--node", "fetch", "--status", "failed", "--error", "boom")
    code, out = ctl("skip", "--run", rid, "--node", "send", "--reason", "not needed")
    assert code == 0 and out["node_status"] == "skipped"
    assert out["run_status"] == "failed"      # NOT revived to "running"
    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert state["status"] == "failed"
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "failed"          # never a bare "running"


def test_accept_changes_prunes_orphaned_pending_node(ctl, write_wf):
    """Finding 2: resume --accept-changes must drop state entries for PENDING
    nodes that were removed from the edited YAML, or node_counts in
    status/list stays corrupted forever."""
    rid, p = _started(ctl, write_wf)
    ctl("next", "--run", rid)
    ctl("record", "--run", rid, "--node", "fetch", "--status", "ok", "--summary", "s")
    # Edit the YAML to remove the still-pending 'send' node, keep 'summarize'.
    edited = """\
name: demo
description: demo workflow
version: 1.0.0
tags: [ericsson]
inputs:
  - {name: deliver_to, default: chat}
nodes:
  - id: fetch
    kind: tool
    tools: [example_fetch]
    prompt: fetch things with example_fetch
    output: things.json
  - id: summarize
    kind: prompt
    depends_on: [fetch]
    prompt: summarize things.json
    output: summary.md
report:
  kanban: auto
"""
    p.write_text(edited)
    code, out = ctl("resume", "--run", rid, "--accept-changes")
    assert code == 0
    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert "send" not in state["nodes"]
    assert set(state["node_order"]) == {"fetch", "summarize"}
    code, out = ctl("status", "--run", rid)
    assert {n["id"] for n in out["nodes"]} == {"fetch", "summarize"}


def test_clean_all_sweeps_corrupt_and_quarantined_runs(ctl, write_wf):
    """Finding 3: a run whose state.json was quarantined must still show up
    (as "corrupt") in list, and 'clean --all' must be able to sweep it even
    though it can have no valid updated_at / age."""
    rid, _ = _started(ctl, write_wf)
    run_dir = wc.find_run(rid)
    (run_dir / "state.json").write_text("{not json")
    code, out = ctl("next", "--run", rid)   # triggers quarantine
    assert code == 1
    assert list(run_dir.glob("state.json.corrupt-*"))
    assert not (run_dir / "state.json").exists()

    code, out = ctl("list")
    assert any(r["run_id"] == rid and r["status"] == "corrupt" for r in out["runs"])

    code, out = ctl("clean", "--all", "--older-than", "30d")
    assert code == 0 and rid in out["removed"]
    assert not run_dir.exists()
