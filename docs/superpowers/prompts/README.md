# Execution prompts — Ericsson connector programme

Eight prompts, one per session. Paste the file's contents into a fresh session at the right
time. Each is self-contained: repo, branch, plan file, exact task scope, guardrails, and a
definition of done.

**Session 1 lives in the other repo.** This programme spans `hermes-agent` and
`ericsson-capabilities`; each prompt is stored with the repo whose work it drives, following
that repo's own docs convention.

| Session | Prompt location |
|---|---|
| 1 | `hermes-agent` → `docs/2026-08-15-hermes-credential-storage-execution-prompt.md` |
| 2–6 | this directory |
| 7 | `hermes-agent` → `docs/2026-08-16-plugin-application-command-port-execution-prompt.md` |
| 8 | `07-wave4b-connector-cli.md` in this directory |

## Order and gating

```
WAVE 1  (start both now, they do not interact)
  [hermes-agent] credential-storage-execution-prompt   Plan 1, tasks 1-9
  02-plan2-shared-transport.md                         Plan 2, tasks 1-9  <-- gates waves 2-3

        merge Plan 2 to main
                 |
WAVE 2  (one session, four scoped pieces in order)
  03-wave2-foundation-jira-registrations.md
        ARM Task 2  ->  Jira Tasks 1-11  ->  Confluence Task 1  ->  ARM Task 1

        merge wave 2 to main
                 |
WAVE 3  (three sessions in parallel, each in its own worktree)
  04-wave3-gitlab-coverage.md             GitLab      tasks 1-9
  05-wave3-confluence-rest.md             Confluence  tasks 2-13
  06-wave3-arm-rest.md                    ARM         tasks 3-10

        merge all three to main
                 |
        merge credential storage to hermes-agent/base
                 |
WAVE 4A [hermes-agent]
  plugin-application-command-port-execution-prompt     tasks 1-6

        review + merge Wave 4A to hermes-agent/base
                 |
WAVE 4B [ericsson-capabilities]
  07-wave4b-connector-cli.md                         tasks 1-9
```

Session 1 is independent of everything — it can run at any point, including through all
three waves.

## Why the work is split this way

**Plan 2 gates the repo.** All four connector plans declare a hard dependency on the
`_common` package it creates.

**ARM Task 2 runs early, out of plan order.** It amends `shared/ericsson_common/` and
regenerates the vendored `_common/` inside every plugin. Landing it once, before the
fan-out, keeps that cross-cutting change out of three parallel branches.

**Jira runs alone as a canary.** It is the first connector built on Plan 2's `_common`.
Finding a foundation defect through one plan is far cheaper than through four.

**Confluence Task 1 and ARM Task 1 run back-to-back, in that order.** Both edit the same
three registration files — `sets/ericsson.json`, `scripts/sync_shared.py`,
`tests/test_shared_sync.py`. Doing them sequentially here is what makes wave 3 conflict-free.
The order matters: ARM Task 1 sets `CONSUMERS` to a list that already names
`ericsson-confluence`, so the Confluence plugin directory must exist first.

**Wave 3 is genuinely disjoint.** After wave 2, the three remaining streams touch only
`plugins/ericsson-gitlab/**`, `plugins/ericsson-confluence/**` and `plugins/ericsson-arm/**`
plus their own test files. Verified: registration edits are confined to Task 1 in both
connector plans.

## Plan file locations

| Plan | Repo | Path |
|---|---|---|
| 1 — credential storage | hermes-agent | `docs/plans/2026-08-15-hermes-credential-storage-parity.md` |
| 2 — shared transport | ericsson-capabilities | `docs/superpowers/plans/2026-08-15-ericsson-shared-transport.md` |
| 3a — Jira coverage | ericsson-capabilities | `docs/superpowers/plans/2026-08-15-ericsson-jira-coverage.md` |
| 3b — GitLab coverage | ericsson-capabilities | `docs/superpowers/plans/2026-08-15-ericsson-gitlab-coverage.md` |
| 3c — Confluence connector | ericsson-capabilities | `docs/superpowers/plans/2026-08-15-ericsson-confluence-connector.md` |
| 3d — ARM connector | ericsson-capabilities | `docs/superpowers/plans/2026-08-15-ericsson-arm-connector.md` |
| 4a — plugin application command port | hermes-agent | `docs/plans/2026-08-16-plugin-application-command-port.md` |
| 4b — connector CLI and migration map | ericsson-capabilities | `docs/superpowers/plans/2026-08-16-ericsson-connector-cli.md` |

Note the two repos use different conventions — `docs/plans/` in hermes-agent (because
`docs/superpowers/*` is gitignored there), `docs/superpowers/plans/` in
ericsson-capabilities.

## Branches each session creates

| Session | Branch | Off |
|---|---|---|
| 1 | `feat/hermes-credential-storage-parity` | `base` (hermes-agent) |
| 2 | `feat/ericsson-shared-transport` | `main` |
| 3 | `feat/ericsson-connector-foundation` | `main` |
| 4 | `feat/ericsson-gitlab-coverage` | `main` (worktree) |
| 5 | `feat/ericsson-confluence-connector` | `main` (worktree) |
| 6 | `feat/ericsson-arm-connector` | `main` (worktree) |
| 7 | `feat/hermes-plugin-application-command-port` | `base` (hermes-agent) |
| 8 | `feat/ericsson-connector-cli` | post-Wave-3 `main` |

No session merges its own work. Each reports and stops; you decide when to merge.

## Approved Wave 4 — connector CLI migration surface

After Wave 2 and all three Wave 3 branches are merged, Wave 4 adds model-free,
domain-shaped Jira, GitLab, Confluence, and ARM commands plus a verified
SuperCLI migration mapping. It does not modify or gate Waves 1–3. Wave 4 is
split across the two source repositories:

```text
Wave 4A  hermes-agent/base: generic owner-bound plugin command port
    |
Wave 4B  ericsson-capabilities/main: connector CLI + migration mapping
```

Wave 4A must be reviewed, merged to neutral Hermes `base`, and green before
Wave 4B starts. The approved interface and sequencing constraints live in
[`2026-08-16-ericsson-connector-cli-design.md`](../specs/2026-08-16-ericsson-connector-cli-design.md).

Wave 4A's plan and trigger live in `hermes-agent`; Wave 4B's plan and trigger
live here. Neither Wave 4 session performs source delivery or brand merges.

## Vendoring

Every ericsson-capabilities plan stops at the commit in that repo. Vendoring into
`hermes-agent/base` via `node scripts/vendor-ericsson.mjs` is a separate operation —
`ericsson-capabilities/CLAUDE.md:32-34`. None of these prompts do it.
