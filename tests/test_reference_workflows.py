from pathlib import Path

import workflow_ctl as wc

REPO = Path(__file__).resolve().parents[1]
REFS = sorted((REPO / "workflows").glob("*.yml"))


def test_two_reference_workflows_exist():
    assert {p.stem for p in REFS} == {"my-tickets-summary", "inbox-digest"}


def test_reference_workflows_validate_cleanly():
    for p in REFS:
        doc = wc.load_workflow(p)
        errors, _warnings = wc.validate_workflow(doc)
        assert errors == [], f"{p.name}: {errors}"
        assert "ericsson" in doc.get("tags", []), f"{p.name}: missing ericsson tag"
        for n in doc.get("nodes", []):
            assert "$inputs" not in n.get("prompt", ""), f"{p.name} node {n.get('id')}: prompt uses non-interpolated $inputs syntax"


def test_tickets_summary_has_approval_and_side_effect():
    doc = wc.load_workflow(REPO / "workflows/my-tickets-summary.yml")
    kinds = {n["id"]: n["kind"] for n in doc["nodes"]}
    assert "approval" in kinds.values()
    send = [n for n in doc["nodes"] if n.get("side_effects")]
    assert send, "delivery node must declare side_effects: true"
