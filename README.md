# ericsson-capabilities

Shared Ericsson coworker capabilities for **OTTO** and **LOOP24** — standard
Hermes artifacts bundled as the `ericsson` capability set and staged into
each brand's build by the hermes-agent capability-staging seam.
**Public repo** — never commit credentials, internal content, or values copied from a local environment.

Spec: otto_hermes workspace `docs/superpowers/specs/2026-07-13-ericsson-capabilities-design.md`.

Flow handbook: [`docs/README.md`](docs/README.md). It inventories every Loop24 Langflow source flow, explains how each works, records port status, and provides the configuration and future interactive-skill design context.

## Contents

| Path | What |
|---|---|
| `sets/ericsson.json` | the set manifest (the staging-seam contract) |
| `skills/ericsson/workflow-orchestrator/` | deterministic workflow runner (YAML + `workflow_ctl.py` state machine) |
| `skills/ericsson/workflow-builder/` | interview skill that authors new workflow YAMLs |
| `skills/ericsson/opportunity-visuals/` | no-key, local opportunity progression renderer (SVG/HTML; optional PNG) |
| `plugins/ericsson-jira/` | Jira tools (`jira_my_tickets`, `jira_get_issue`, `jira_add_comment`) |
| `plugins/ericsson-teams/` | Teams tools via Graph/MSAL device-code (`teams_auth`, list/read/send/reply) |
| `mcp/outlook-mcp/` | stdio MCP server: Outlook email+calendar via PowerShell→COM (Windows) |
| `mcp/mcp-servers.yaml` | `mcp_servers` config fragment (outlook + glean template) |
| `workflows/` | reference workflows (`my-tickets-summary`, `inbox-digest`) |

The [Opportunity Visuals showcase](docs/showcases/opportunity-visuals.md)
demonstrates its four supported views with synthetic data and documents local
configuration, audit artifacts, PNG fallback, and visual verification.

## Gating

The intended baked-in model has no Ericsson runtime toggle: Jira dispatch is gated by its credentials, Teams guides device-code sign-in, and only COM-bound pieces are Windows-only. Some manifest/plugin/workflow metadata still contains legacy `ERICSSON_ENV` and disabled-by-default declarations; this known inconsistency is documented in `docs/configuration.md` and must be removed consistently before relying on the no-toggle contract in workflows.

## Staging semantics (consumed by the seam)

skills → `$HERMES_HOME/skills/ericsson/…` · plugins → `$HERMES_HOME/plugins/…` ·
`mcpServers` → merged into `config.yaml` (seam resolves `${CAPABILITY_DIR}`) ·
`mcpLocal` → staged next to plugins · workflows → `$HERMES_HOME/workflows/` ·
`env` → Keys-page metadata (seam-side) · requiresEnv gates whether the set stages at all · disabledByDefault seeds skills.disabled / disabled_toolsets. Unknown manifest keys must be ignored.

## Dev (macOS primary)

    ./bootstrap.sh                                  # venv + deps + pytest
    python3 scripts/lint_manifest.py sets/ericsson.json

Primary end-to-end verification target is the Windows box (real OTTO install,
`ERICSSON_ENV=1`, live Outlook) — see the spec §12.

## Future: marketplace exposure

The layout is Skills-Hub-tap compatible (`hermes skills tap add <owner>/<repo>`
path `skills/ericsson/`) and exportable to a `/.well-known/skills/index.json`
intranet hub (generator backlogged).
