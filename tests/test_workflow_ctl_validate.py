import pytest
import workflow_ctl as wc
from conftest import VALID_WF


def _doc(yaml_text):
    import yaml
    return yaml.safe_load(yaml_text)


def test_valid_workflow_passes():
    errors, warnings = wc.validate_workflow(_doc(VALID_WF))
    assert errors == []


def test_missing_required_top_keys():
    errors, _ = wc.validate_workflow({"nodes": []})
    joined = " ".join(errors)
    assert "name" in joined and "description" in joined and "version" in joined
    assert any("nodes" in e for e in errors)  # empty nodes list


def test_bad_slug_and_unknown_top_key():
    doc = _doc(VALID_WF)
    doc["name"] = "Bad Name!"
    doc["bogus"] = 1
    errors, _ = wc.validate_workflow(doc)
    assert any("name" in e for e in errors)
    assert any("bogus" in e for e in errors)


def test_duplicate_node_id_and_unknown_kind():
    doc = _doc(VALID_WF)
    doc["nodes"].append({"id": "fetch", "kind": "magic", "prompt": "x"})
    errors, _ = wc.validate_workflow(doc)
    assert any("duplicate" in e for e in errors)
    assert any("kind" in e for e in errors)


def test_unknown_depends_on_and_cycle():
    doc = _doc(VALID_WF)
    doc["nodes"][0]["depends_on"] = ["send"]        # fetch -> send -> summarize -> fetch: cycle
    errors, _ = wc.validate_workflow(doc)
    assert any("cycle" in e for e in errors)
    doc2 = _doc(VALID_WF)
    doc2["nodes"][1]["depends_on"] = ["ghost"]
    errors2, _ = wc.validate_workflow(doc2)
    assert any("ghost" in e for e in errors2)


def test_when_validation():
    doc = _doc(VALID_WF)
    doc["nodes"][2]["when"] = "$inputs.nope == 'x'"     # unknown input
    errors, _ = wc.validate_workflow(doc)
    assert any("nope" in e for e in errors)
    doc["nodes"][2]["when"] = "garbage here"
    errors, _ = wc.validate_workflow(doc)
    assert any("when" in e for e in errors)


def test_approval_requires_message_and_output_traversal():
    doc = _doc(VALID_WF)
    doc["nodes"].append({"id": "gate", "kind": "approval", "depends_on": ["send"]})
    doc["nodes"][0]["output"] = "../evil.txt"
    errors, _ = wc.validate_workflow(doc)
    assert any("message" in e for e in errors)
    assert any("output" in e for e in errors)


def test_requires_env_warning(monkeypatch):
    monkeypatch.delenv("NOPE_VAR", raising=False)
    doc = _doc(VALID_WF)
    doc["requires"] = {"env": ["NOPE_VAR"], "toolsets": ["ericsson-jira"]}
    errors, warnings = wc.validate_workflow(doc)
    assert errors == []
    assert any("NOPE_VAR" in w for w in warnings)


def test_parse_and_eval_when():
    groups = wc.parse_when("$inputs.a == 'x' && $n1.output != y || $inputs.b == z")
    assert len(groups) == 2 and len(groups[0]) == 2
    resolver = {"$inputs.a": "x", "$n1.output": "other", "$inputs.b": "no"}.get
    assert wc.eval_when("$inputs.a == 'x' && $n1.output != y", resolver) is True
    assert wc.eval_when("$inputs.b == z", resolver) is False
    assert wc.eval_when("not an expression", resolver) is False       # fail-closed
    assert wc.eval_when("$missing.output == 'x'", resolver) is False  # unresolvable -> False


def test_cli_validate(ctl, write_wf):
    from conftest import VALID_WF
    p = write_wf(VALID_WF)
    code, out = ctl("validate", str(p))
    assert code == 0 and out["ok"] is True and out["name"] == "demo"
    p2 = write_wf("name: [broken", name="bad.yml")
    code, out = ctl("validate", str(p2))
    assert code == 1 and "error" in out
