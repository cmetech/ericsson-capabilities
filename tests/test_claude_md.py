from pathlib import Path
REPO = Path(__file__).resolve().parents[1]


def test_agent_memory_files_are_byte_identical():
    assert (REPO / "AGENTS.md").read_bytes() == (REPO / "CLAUDE.md").read_bytes()


def test_claude_md_covers_the_contract():
    body = (REPO / "CLAUDE.md").read_text()
    for needle in ("sets/ericsson.json", "vendor-ericsson", "manifest", "skills[]",
                   "plugins[]", "mcpServers", "workflows[]", "env[]",
                   "extension point", "pytest", "onboard-ericsson-capabilities",
                   "build_catalog.py --check", "not-supported-no-port-planned",
                   "base", "brands/*.json"):
        assert needle in body, f"CLAUDE.md must document: {needle}"
