# ericsson-capabilities — agent/developer guide

Shared Ericsson coworker capabilities (skills, tool plugins, MCP servers, workflows) for
**OTTO + LOOP24**. This repo is the **source-of-truth + test harness**. The content is
**vendored (copied + committed) into `hermes-agent` on `base`** by
`hermes-agent/scripts/vendor-ericsson.mjs`, then ships inside the backend clone like Hermes'
core skills — **no runtime pull, no enable toggle.**

## The manifest is the contract

`sets/ericsson.json` is the single source of truth. The vendor script, the hermes-agent Keys
injector, and the startup seed ALL read it. Everything you add must be listed there.

## Adding a capability (the whole loop)

| Add a… | Do this here | Delivered by (after re-vendor) |
|---|---|---|
| Skill | drop `skills/ericsson/<name>/`; add path to manifest `skills[]` | skills_sync → Capabilities |
| Tool plugin | drop `plugins/<name>/` (`kind: backend`); add to `plugins[]` | bundled auto-load |
| Plugin key | add to manifest `env[]` (key/description/prompt/url/password/category) | auto-registered on Keys page |
| Local MCP server | drop `mcp/<name>/`; add to `mcpLocal[]` + an `mcp_servers.<name>` block in the file the manifest's `mcpServers` key points to (`mcp/mcp-servers.yaml`) | seeded into config on launch |
| Remote MCP | add an `mcp_servers.<name>` (url/headers) block to that same `mcpServers` file; add keys to `env[]` | seeded + keys registered |
| Workflow | drop `workflows/<name>.yml`; add to `workflows[]` | seeded to `$HERMES_HOME/workflows/` |

Then, in `hermes-agent`: `node scripts/vendor-ericsson.mjs` → `git commit` on `base` → restamp
otto/loop24 → release. Nothing in the vendor script or seed is hardcoded — they derive from the
manifest, so those steps never change.

## Gating (no toggle)

- OS: `platforms: [windows]` on any Outlook/COM skill (auto-hides elsewhere).
- Credentials: a tool plugin's `check_available()` returns whether its creds exist (Jira), or
  `True` with the tool guiding sign-in (Teams via `teams_auth`). Tools are always visible; they
  only *fire* when configured.

## Extension points (only when adding a NEW artifact TYPE)

The manifest models skills/plugins/mcp/workflows/keys today. A genuinely new type (e.g. cron
agents `agents[]`, or personas `personas[]` — P3) is a new extension point and requires editing
THREE places:
1. the manifest schema here,
2. `hermes-agent/scripts/vendor-ericsson.mjs` (add a copy rule),
3. `hermes-agent/hermes_cli/capability_staging.py` (add a seed rule).
Skills/tools/plugins/MCP/workflows/keys never need these — they're already modeled.

## Test gate

`./bootstrap.sh` (or `. .venv/bin/activate && pytest -q`) must pass before vendoring. Windows
box is the live end-to-end target (Outlook COM, Teams sign-in).
