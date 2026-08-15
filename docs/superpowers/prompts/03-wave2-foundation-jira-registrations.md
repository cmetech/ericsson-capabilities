# Session 3 — Wave 2: shared amendment, Jira coverage, and both connector registrations

**Repo:** `ericsson-capabilities` · **Wave:** 2 · **Requires Plan 2 merged to `main`**

---

This session runs **four scoped pieces from three different plan files, in this exact
order**. Read the scope table carefully — you are deliberately *not* running any of these
plans end to end.

| # | Plan file | Tasks to run | Why here |
|---|---|---|---|
| 1 | `2026-08-15-ericsson-arm-connector.md` | **Task 2 ONLY** | Amends `shared/ericsson_common/`. Must land once, before four connector streams fan out. |
| 2 | `2026-08-15-ericsson-jira-coverage.md` | **Tasks 1–11 (all)** | Canary: first real connector built on Plan 2's `_common`. Validates the foundation before three more plans commit to it. |
| 3 | `2026-08-15-ericsson-confluence-connector.md` | **Task 1 ONLY** | Registration. Must precede ARM Task 1 — see the ordering note below. |
| 4 | `2026-08-15-ericsson-arm-connector.md` | **Task 1 ONLY** | Registration. |

**Repository:** `/Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities`
**Plan files:** all under `docs/superpowers/plans/`

## Explicitly out of scope

- Confluence Tasks 2–13 — a later session runs those
- ARM Tasks 3–10 — a later session runs those
- Anything in the GitLab coverage plan
- ARM Task 2 must **not** be run again after piece 1

Stop at the end of piece 4. Do not continue into the rest of either connector plan, however
natural it feels.

## Why this exact order

Confluence Task 1 and ARM Task 1 both edit the same three registration files —
`sets/ericsson.json`, `scripts/sync_shared.py`, `tests/test_shared_sync.py`. Running them
back-to-back here, sequentially, is what lets the later Confluence and ARM sessions run in
parallel without colliding.

The order between them is not arbitrary. ARM Task 1 Step 5 sets:

```python
CONSUMERS = ["ericsson-jira", "ericsson-gitlab", "ericsson-confluence", "ericsson-arm"]
```

That list names `ericsson-confluence`, so the Confluence plugin directory must already
exist or `scripts/sync_shared.py` will point at a directory that is not there. **Confluence
Task 1 first, ARM Task 1 second.** If you find yourself running them the other way round,
stop.

ARM Task 2 comes first of all because it modifies `shared/ericsson_common/transport.py` and
`client.py` and re-runs the sync, which regenerates `_common/` inside every plugin. Doing it
once, up front, keeps that cross-cutting change out of the parallel streams.

## Before you start

```bash
cd /Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities
git rev-parse --abbrev-ref HEAD          # expect: main
git status --porcelain --untracked-files=no | wc -l   # expect: 0
ls shared/ericsson_common/client.py shared/ericsson_common/transport.py   # Plan 2 must be merged
grep -n "^CONSUMERS" scripts/sync_shared.py   # expect: ["ericsson-jira", "ericsson-gitlab"]
. .venv/bin/activate && pytest -q             # expect: green
```

If `shared/ericsson_common/` does not exist, Plan 2 has not been merged to `main` yet —
**stop and say so.** Everything here depends on it.

Create the working branch:

```bash
git checkout -b feat/ericsson-connector-foundation main
```

## How to execute

Read all three plan files' headers, Global Constraints and Decisions Taken sections before
starting — then read each task in full immediately before running it.

Use `superpowers:subagent-driven-development`, one subagent per task, with a review
checkpoint between tasks. When you dispatch a subagent, **state the plan file and the task
number explicitly** in its brief, because three plan files are in play and a subagent
starting from "Task 1" alone would have no way to know which.

Follow the TDD cycle exactly: failing test → confirm it fails → implement → confirm it
passes → wire the tool → parity check → commit.

## Guardrails

- **Tests:** `./bootstrap.sh`, or `. .venv/bin/activate && pytest -q`.
- After ARM Task 2, run the **full** suite — that task changes shared code every existing
  connector consumes, and its Step 6 exists precisely to prove nothing regressed.
- Each connector task ends with a schema ↔ `plugin.yaml` parity check. Run it. The plans
  give the exact snippet and the expected tool count.
- Approval `rule_key` must be argument-derived (`f"{tool}:{sha256(canonical_args)}"`), never
  the bare tool name. A tool-name key turns one "always" click into a permanent standing
  grant. Jira coverage Task 1 fixes exactly this defect — do not reintroduce it.
- `ConnectorError` must never escape a connector; translate it at the boundary.

## Definition of done

- ARM Task 2 committed; Jira Tasks 1–11 committed; Confluence Task 1 committed;
  ARM Task 1 committed
- `grep -n "^CONSUMERS" scripts/sync_shared.py` shows all four connectors
- `plugins/ericsson-confluence/` and `plugins/ericsson-arm/` exist, each with `_common/`
  vendored, both `enabled: false` in `sets/ericsson.json`
- `. .venv/bin/activate && python scripts/sync_shared.py && pytest -q` green
- Branch `feat/ericsson-connector-foundation` pushed
- Report: what landed, deviations and why, and — since Jira was the canary — **anything
  you learned about Plan 2's `_common` that the three remaining plans should know**

**Do not merge to `main`.** Report back.

## Downstream note

Sessions 4, 5 and 6 run in parallel and all require this work merged to `main` first. Say
plainly in your report whether it is ready.
