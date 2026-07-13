import json

import workflow_ctl as wc

APPROVAL_WF = """\
name: gated
description: workflow with an approval gate
version: 1.0.0
nodes:
  - id: draft
    kind: prompt
    prompt: draft the summary
  - id: gate
    kind: approval
    depends_on: [draft]
    message: Review the draft before it is sent.
  - id: send
    kind: tool
    depends_on: [gate]
    side_effects: true
    prompt: send it
"""


def _to_gate(ctl, write_wf):
    p = write_wf(APPROVAL_WF, name="gated.yml")
    code, out = ctl("start", str(p))
    rid = out["run_id"]
    code, nxt = ctl("next", "--run", rid)
    assert nxt["node"]["id"] == "draft"
    ctl("record", "--run", rid, "--node", "draft", "--status", "ok", "--summary", "drafted")
    return rid


def test_approval_parks_run(ctl, write_wf):
    rid = _to_gate(ctl, write_wf)
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "wait_approval" and nxt["node_id"] == "gate"
    assert "Review the draft" in nxt["message"]
    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert state["status"] == "waiting_approval"
    # next again stays parked (idempotent)
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "wait_approval"


def test_approve_continues(ctl, write_wf):
    rid = _to_gate(ctl, write_wf)
    ctl("next", "--run", rid)
    code, out = ctl("approve", "--run", rid, "--response", "looks good")
    assert code == 0 and out["run_status"] == "running" and out["approved_node"] == "gate"
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "execute" and nxt["node"]["id"] == "send"


def test_reject_ends_run(ctl, write_wf):
    rid = _to_gate(ctl, write_wf)
    ctl("next", "--run", rid)
    code, out = ctl("reject", "--run", rid, "--reason", "wrong audience")
    assert out["run_status"] == "rejected"
    code, nxt = ctl("next", "--run", rid)
    assert nxt["action"] == "rejected"
    state = json.loads((wc.find_run(rid) / "state.json").read_text())
    assert state["nodes"]["gate"]["status"] == "rejected"
    assert state["nodes"]["gate"]["approval"]["reason"] == "wrong audience"


def test_approve_without_waiting_node_fails(ctl, write_wf):
    rid = _to_gate(ctl, write_wf)
    code, out = ctl("approve", "--run", rid)      # gate not reached yet
    assert code == 1
