# ericsson-capabilities

Shared Ericsson coworker capabilities for **OTTO** and **LOOP24** — standard
Hermes artifacts bundled as the `ericsson` capability set and staged into
each brand's build by the hermes-agent capability-staging seam.
**Internal Ericsson content — keep the repo private.**

Spec: otto_hermes workspace `docs/superpowers/specs/2026-07-13-ericsson-capabilities-design.md`.

## Contents

| Path | What |
|---|---|
| `sets/ericsson.json` | the set manifest (the staging-seam contract) |
| `skills/ericsson/workflow-orchestrator/` | deterministic workflow runner (YAML + `workflow_ctl.py` state machine) |
| `skills/ericsson/workflow-builder/` | interview skill that authors new workflow YAMLs |
| `plugins/ericsson-jira/` | Jira tools (`jira_my_tickets`, `jira_get_issue`, `jira_add_comment`) |
| `plugins/ericsson-teams/` | Teams tools via Graph/MSAL device-code (`teams_auth`, list/read/send/reply) |
| `mcp/outlook-mcp/` | stdio MCP server: Outlook email+calendar via PowerShell→COM (Windows) |
| `mcp/mcp-servers.yaml` | `mcp_servers` config fragment (outlook + glean template) |
| `workflows/` | reference workflows (`my-tickets-summary`, `inbox-digest`) |

## Gating

Everything is gated on `ERICSSON_ENV=1` (plugin `check_fn`s; skills via
`requires_toolsets` cascade). Only COM-bound pieces are Windows-only.

## Staging semantics (consumed by the seam)

skills → `$HERMES_HOME/skills/ericsson/…` · plugins → `$HERMES_HOME/plugins/…` ·
`mcpServers` → merged into `config.yaml` (seam resolves `${CAPABILITY_DIR}`) ·
`mcpLocal` → staged next to plugins · workflows → `$HERMES_HOME/workflows/` ·
`env` → Keys-page metadata (seam-side). Unknown manifest keys must be ignored.

## Dev (macOS primary)

    ./bootstrap.sh                                  # venv + deps + pytest
    python3 scripts/lint_manifest.py sets/ericsson.json

Primary end-to-end verification target is the Windows box (real OTTO install,
`ERICSSON_ENV=1`, live Outlook) — see the spec §12.

## Future: marketplace exposure

The layout is Skills-Hub-tap compatible (`hermes skills tap add <owner>/<repo>`
path `skills/ericsson/`) and exportable to a `/.well-known/skills/index.json`
intranet hub (generator backlogged).
