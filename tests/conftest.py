import json
import sys
from pathlib import Path

import pytest

SCRIPTS = Path(__file__).resolve().parents[1] / "skills/ericsson/workflow-orchestrator/scripts"
sys.path.insert(0, str(SCRIPTS))


@pytest.fixture
def home(tmp_path, monkeypatch):
    """Isolated HERMES_HOME with a workflows dir."""
    h = tmp_path / "home"
    (h / "workflows").mkdir(parents=True)
    monkeypatch.setenv("HERMES_HOME", str(h))
    return h


@pytest.fixture
def write_wf(home):
    def _write(text, name="wf.yml"):
        p = home / "workflows" / name
        p.write_text(text)
        return p
    return _write


@pytest.fixture
def ctl(capsys):
    """Run workflow_ctl.main(argv); return (exit_code, parsed_json)."""
    import workflow_ctl

    def _run(*argv):
        with pytest.raises(SystemExit) as ei:
            workflow_ctl.main(list(argv))
        out = capsys.readouterr().out
        return ei.value.code or 0, json.loads(out)
    return _run


VALID_WF = """\
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
  - id: send
    kind: tool
    tools: [example_send]
    depends_on: [summarize]
    when: "$inputs.deliver_to == 'email'"
    side_effects: true
    prompt: email summary.md with example_send
report:
  kanban: auto
"""
