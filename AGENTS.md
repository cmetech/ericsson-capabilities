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

## Loop24 Langflow porting program

The source material for future ports is the internal `loop_24` repository at `/Users/coreyellis/code/gitlab.rosetta.ericssondevops.com/loop_24` (remote `sd-americas-css/sd-americas-ai/loop_24`). The durable inventory and explanation layer lives in `docs/`; start with `docs/README.md`, use one page under `docs/flows/` per source JSON flow, and use `docs/configuration.md` for all keys, authentication, permissions, dependencies, and validation.

At source snapshot `3f124f5`, there are 11 JSON flows. Two have intent-level Hermes ports: Jira Assigned Tickets Summary → `my-tickets-summary`, and Search and Read E-Mails → `inbox-digest`. Jira to GitLab and Jira Defect Loop are partial because Jira tools exist but the GitLab tool/write path and end-to-end workflows do not. The other seven are not ported. Supporting foundations already ported independently are Jira, Teams, Outlook MCP, Glean MCP configuration, and the workflow orchestrator/builder.

Port the intent, controls, safety, and user outcome—not Langflow's graph runtime. Embedded LLM nodes become work for the active Hermes agent; reusable external operations become tools/plugins/MCP; deterministic ordering and approvals become workflow YAML; guidance becomes skills. Before planning or implementing a port, update/read its flow page and configuration dependencies. When a port lands, update its page status and target artifacts in the same change.
