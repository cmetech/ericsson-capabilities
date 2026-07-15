# ericsson-capabilities

Shared Ericsson coworker capabilities for **OTTO** and **LOOP24**. This repository
is the source of truth for the `ericsson` capability set. Its manifest-driven
snapshot is vendored and committed first on neutral `hermes-agent/base`, then merged
into every discovered brand; startup seeds the bundled runtime artifacts into the
active profile.
**Public repo** — never commit credentials, internal content, or values copied from a local environment.

Spec: otto_hermes workspace `docs/superpowers/specs/2026-07-13-ericsson-capabilities-design.md`.

Flow handbook: [`docs/README.md`](docs/README.md). It inventories every Loop24 Langflow source flow, explains how each works, records port status, and links the implemented onboarding, configuration, and maintenance guidance.

## Contents

| Path | What |
|---|---|
| `sets/ericsson.json` | the set manifest (the staging-seam contract) |
| `skills/ericsson/workflow-orchestrator/` | deterministic workflow runner (YAML + `workflow_ctl.py` state machine) |
| `skills/ericsson/workflow-builder/` | interview skill that authors new workflow YAMLs |
| `skills/ericsson/opportunity-visuals/` | no-key, local opportunity progression renderer (SVG/HTML; optional PNG) |
| `skills/ericsson/onboard-ericsson-capabilities/` | catalog-driven onboarding, readiness, demonstrations, artifact guidance, troubleshooting, and resume |
| `plugins/ericsson-jira/` | Jira tools (`jira_my_tickets`, `jira_get_issue`, `jira_add_comment`) |
| `plugins/ericsson-teams/` | Teams tools via Graph/MSAL device-code (`teams_auth`, list/read/send/reply) |
| `mcp/outlook-mcp/` | stdio MCP server: Outlook email+calendar via PowerShell→COM (Windows) |
| `mcp/mcp-servers.yaml` | `mcp_servers` config fragment (outlook + glean template) |
| `workflows/` | reference workflows (`my-tickets-summary`, `inbox-digest`) |

The [Ericsson onboarding guide](docs/onboarding/README.md) documents the router,
catalog maintenance, safe demonstrations, artifact interpretation, mock sessions,
test evidence, and Windows resume release validation. The
[Opportunity Visuals showcase](docs/showcases/opportunity-visuals.md)
demonstrates its four supported views with synthetic data and documents local
configuration, audit artifacts, PNG fallback, and visual verification.

## Gating

Ericsson capabilities are baked into every profile with no Ericsson runtime toggle
or disabled-by-default delivery declaration. Jira dispatch depends on protected Jira
settings, Teams guides device-code sign-in, Glean and Outlook have their documented
service/platform requirements, and only COM-bound pieces are Windows-only. A
configured setting name alone is never proof of readiness.

## Staging semantics (consumed by the seam)

skills → `$HERMES_HOME/skills/ericsson/…` · plugins → `$HERMES_HOME/plugins/…` ·
`mcpServers` → merged into `config.yaml` (seam resolves `${CAPABILITY_DIR}`) ·
`mcpLocal` → staged next to plugins · workflows → `$HERMES_HOME/workflows/` ·
`env` → Keys-page metadata (seam-side). Generic capability staging still supports
environment gates and disabled seeds for other sets, but Ericsson does not use
them. Unknown manifest keys must be ignored.

## Dev (macOS primary)

    ./bootstrap.sh                                  # venv + deps + pytest
    .venv/bin/python scripts/lint_manifest.py sets/ericsson.json

Primary integration and Windows-resume verification target is a Windows release
installation. Use the [Windows resume checklist](docs/onboarding/windows-resume-release-validation.md)
and capability-specific read-only validation; never use a live write merely as a
configuration test.

## Future: marketplace exposure

The layout is Skills-Hub-tap compatible (`hermes skills tap add <owner>/<repo>`
path `skills/ericsson/`) and exportable to a `/.well-known/skills/index.json`
intranet hub (generator backlogged).
