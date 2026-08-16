# Session 5 — Wave 3 (parallel): Confluence connector, Tasks 2–13

**Repo:** `ericsson-capabilities` · **Wave:** 3 · **Requires Wave 2 merged to `main`**
**Runs in parallel with Sessions 4 and 6 — use a worktree.**

---

Execute part of an implementation plan, task by task.

**Repository:** `ericsson-capabilities` (this repo)

**Plan file:** `docs/superpowers/plans/2026-08-15-ericsson-confluence-connector.md`

**Scope: Tasks 2 through 13.** Task 1 (scaffold, manifest, shared-code registration) was
already completed and merged in Wave 2 — **do not run it again.** It created
`plugins/ericsson-confluence/` with `models.py`, `plugin.yaml`, `config.schema.json`, the
vendored `_common/`, the `sets/ericsson.json` entry and the `CONSUMERS` update. Read Task 1
for context so you know what exists, then start work at Task 2.

## Isolation

Two other sessions are working in this repo at the same time. Work in your own worktree:

```bash
# run from the ericsson-capabilities repo root
git worktree add .worktrees/confluence-connector -b feat/ericsson-confluence-connector main
cd .worktrees/confluence-connector
./bootstrap.sh
```

Your file footprint is `plugins/ericsson-confluence/**` and `tests/test_confluence_*.py`.
Task 1 already did all the shared-file registration, so **nothing in Tasks 2–13 should
touch** `sets/ericsson.json`, `scripts/sync_shared.py`, `tests/test_shared_sync.py`, or
`shared/ericsson_common/**`. If a task seems to ask you to, stop and check you are not
accidentally re-running Task 1.

Running `python scripts/sync_shared.py` is fine and expected — it regenerates vendored
`_common/` copies from unchanged shared source, so it produces no diff.

## Before you start

```bash
git rev-parse --abbrev-ref HEAD                       # expect: feat/ericsson-confluence-connector
ls plugins/ericsson-confluence/models.py              # Task 1 output — must exist
ls plugins/ericsson-confluence/_common/client.py      # vendored shared code — must exist
ls plugins/ericsson-arm/                              # Wave 2 must be merged
. .venv/bin/activate && pytest -q tests/test_confluence_manifest.py   # Task 1's tests, green
```

If `plugins/ericsson-confluence/models.py` is missing, Wave 2 has not merged — **stop.**

## How to execute

Read the plan in full first, including Task 1 for context. Use
`superpowers:subagent-driven-development` — fresh subagent per task, review between tasks.
When dispatching a subagent, state the task number explicitly and note that Task 1 is
already done.

Follow the TDD cycle exactly: failing test → confirm it fails → implement → confirm it
passes → wire the tool → parity check → commit.

## Guardrails

- **Tests:** `. .venv/bin/activate && pytest -q` from inside your worktree.
- **Task 4 ports `storage_to_md.py` verbatim — do not rewrite it.** It already handles
  tables, CDATA code blocks, nested lists, task checkboxes, callout macros and attachment
  rewriting. The task's job is to copy it and give it the test suite it has never had. A
  fresh converter would be worse output for more work.
- **Every body-bearing read carries the untrusted-content warning.** Not optional. A
  Confluence page is editable by anyone in the organisation, making it the
  lowest-privilege, highest-reach content in the integration.
- **Every write escapes.** Callers supply Markdown; markup inside it becomes visible text,
  never page structure. A model must not be able to inject `<ac:structured-macro>` through
  this connector.
- Approval `rule_key` argument-derived, never the bare tool name.
- Task 13 verifies both invariants mechanically. Run those checks — they are what keeps the
  properties true as tools are added.

## Definition of done

- Tasks 2–13 complete, each with its own commit
- Task 13's contract check reports the tool and gated-write counts the plan states
- `. .venv/bin/activate && python scripts/sync_shared.py && pytest -q` green, no drift
- Branch `feat/ericsson-confluence-connector` pushed
- Report: what landed, deviations and why, anything the plan got wrong

**Do not merge to `main`.** Report back.
