from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
MCP_DIR = REPO / "mcp/outlook-mcp"

EXPECTED_TOOLS = {
    "mailbox_list", "message_list", "message_read", "message_send",
    "message_reply", "message_delete", "message_attachments_download",
    "calendar_list", "calendar_create", "calendar_update",
    "calendar_delete", "calendar_accept",
}


def test_port_files_present():
    for rel in ("pyproject.toml", "run_server.py", "outlook-cli.ps1",
                "src/outlook_cli/__init__.py", "src/outlook_cli/server.py",
                "src/outlook_cli/cli.py"):
        assert (MCP_DIR / rel).exists(), f"missing ported file: {rel}"


def test_server_defines_all_12_tools():
    src = (MCP_DIR / "src/outlook_cli/server.py").read_text()
    for tool in EXPECTED_TOOLS:
        assert f'Tool(name="{tool}"' in src, f"tool missing from server: {tool}"


def test_run_helper_importable_without_mcp_package():
    import sys
    sys.path.insert(0, str(MCP_DIR / "src"))
    import outlook_cli
    assert callable(outlook_cli.run)
    assert outlook_cli.SCRIPT_PATH.endswith("outlook-cli.ps1")


def test_mcp_servers_yaml():
    doc = yaml.safe_load((REPO / "mcp/mcp-servers.yaml").read_text())
    servers = doc["mcp_servers"]
    assert set(servers) == {"outlook", "glean"}
    assert "${CAPABILITY_DIR}/outlook-mcp/run_server.py" in servers["outlook"]["args"]
    assert servers["glean"]["url"] == "${GLEAN_MCP_URL}"
    assert servers["glean"]["headers"]["Authorization"] == "Bearer ${GLEAN_API_TOKEN}"
