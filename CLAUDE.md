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
| Workflow | drop `workflows/<name>.yml`; add to `workflows[]`; declare each tool node's exact `tools` and source them through `requires.toolsets`, `requires.mcp_servers`, or explicit `workflowCoreTools` | seeded to `$HERMES_HOME/workflows/` |

Then, in `hermes-agent`: `node scripts/vendor-ericsson.mjs` → `git commit` on `base` → restamp
otto/loop24 → release. Nothing in the vendor script or seed is hardcoded — they derive from the
manifest, so those steps never change.

**Branch-placement invariant:** every shared Ericsson skill, plugin, MCP definition, workflow,
and capability-manifest update must first be vendored and committed on the neutral
`hermes-agent/base` branch. Never commit shared vendored content directly to `otto`, `loop24`,
or another brand branch, even when that brand branch is the current checkout. Merge `base` into
every brand discovered from `brands/*.json`, run the brand generator's `--write` and `--check`
gates, and finish on clean `otto`. Only generated branding overlays or explicitly brand-specific
assets belong directly on a brand branch. If a request says "use this branch" while a brand
branch is checked out, stop and reconcile that wording with this invariant before vendoring.

## Gating (no toggle)

- OS: `platforms: [windows]` on any Outlook/COM skill (auto-hides elsewhere).
- Credentials: a tool plugin's `check_available()` returns whether its creds exist (Jira), or
  `True` with the tool guiding sign-in (Teams via `teams_auth`). Tools are always visible; they
  only *fire* when configured.

## Ericsson onboarding contract

`skills/ericsson/onboard-ericsson-capabilities/` is the bundled, all-profile entry point for
capability discovery, education, readiness, safe demonstrations, artifact interpretation,
troubleshooting, and consented resume. It is a thin catalog-driven router; domain behavior stays
in the selected skill/plugin/MCP/workflow. Its compact `references/catalog.json` is generated,
never hand-edited. After entry changes run:

```bash
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py --check
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/validate_catalog.py
```

Adding, removing, or materially changing a capability must update its implementation; manifest
and runtime registration; user-facing capability/flow documentation; configuration,
authentication, permissions, dependencies, and platforms; natural-language triggers; reads,
writes, approvals, outputs, and artifact guidance; demo/test artifacts and troubleshooting where
applicable; onboarding entry/generated catalog; and vendored Hermes snapshot. Prefer the
validators over checklist memory.

Ericsson has no capability-set toggle or set-level `disabledByDefault`
declaration. The remote Glean MCP entry is a deliberate server-level exception:
it is seeded with `enabled: false` until the user supplies their token and opts in.
Keep generic staging infrastructure available for other sets. Pseudonymization is the
recommendation-ineligible
`not-supported-no-port-planned` historical tombstone and has no roadmap. Re-Identification is
non-runnable because its protected mapping dependency is unavailable. Windows resume uses explicit
OS dispatch to a native backend; portable tests pass off Windows, while the 11 native acceptance
cases remain a Windows release gate documented in `docs/onboarding/windows-resume-release-validation.md`.

Delivery remains source-first: verify/commit here, vendor the exact source revision on neutral
Hermes `base`, discover every brand from `brands/*.json`, merge `base` into each, regenerate/check
each overlay, verify shared bytes, and finish clean on `otto`. Never author shared onboarding
content directly on a brand branch.

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

The source material for future ports is the internal `loop_24` repository (authoritative remote `sd-americas-css/sd-americas-ai/loop_24`) at pinned snapshot `3f124f5`. Checkout locations vary by environment; locate the checkout by repository name or remote rather than assuming a home-directory path. The durable inventory and explanation layer lives in `docs/`; start with `docs/README.md`, use one page under `docs/flows/` per source JSON flow, and use `docs/configuration.md` for all keys, authentication, permissions, dependencies, and validation.

At source snapshot `3f124f5`, there are 11 JSON flows. Two have intent-level Hermes ports: Jira Assigned Tickets Summary → `my-tickets-summary`, and Search and Read E-Mails → `inbox-digest`. Jira to GitLab and Jira Defect Loop are partial because Jira tools exist but the GitLab tool/write path and end-to-end workflows do not. The other seven are not ported. Supporting foundations already ported independently are Jira, Teams, Outlook MCP, Glean MCP configuration, and the workflow orchestrator/builder.

Port the intent, controls, safety, and user outcome—not Langflow's graph runtime. Embedded LLM nodes become work for the active Hermes agent; reusable external operations become tools/plugins/MCP; deterministic ordering and approvals become workflow YAML; guidance becomes skills. Before planning or implementing a port, update/read its flow page and configuration dependencies. When a port lands, update its page status and target artifacts in the same change.
