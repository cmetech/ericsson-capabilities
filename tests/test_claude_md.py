from pathlib import Path
REPO = Path(__file__).resolve().parents[1]

def test_claude_md_covers_the_contract():
    body = (REPO / "CLAUDE.md").read_text()
    for needle in ("sets/ericsson.json", "vendor-ericsson", "manifest", "skills[]",
                   "plugins[]", "mcpServers", "workflows[]", "env[]",
                   "extension point", "pytest"):
        assert needle in body, f"CLAUDE.md must document: {needle}"
