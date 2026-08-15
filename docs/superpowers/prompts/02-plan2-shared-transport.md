# Session 2 — Plan 2: Ericsson shared transport

**Repo:** `ericsson-capabilities` · **Wave:** 1 · **Gates everything else in this repo**

---

Execute an implementation plan, task by task.

**Repository:** `/Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities`

**Plan file:** `docs/superpowers/plans/2026-08-15-ericsson-shared-transport.md`

**Scope:** All 9 tasks. Nothing outside this plan.

## Why this one is load-bearing

Four further plans (Jira coverage, GitLab coverage, Confluence connector, ARM connector)
all declare a hard dependency on this one. Every connector in this repo will be built on
the `_common` package you create here. A defect that ships from this plan gets copied into
four consumers before anyone notices, so favour stopping and asking over improvising.

## Before you start

```bash
cd /Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities
git rev-parse --abbrev-ref HEAD          # expect: main
git status --porcelain --untracked-files=no | wc -l   # expect: 0
ls docs/superpowers/plans/2026-08-15-ericsson-shared-transport.md
ls shared/ 2>/dev/null || echo "no shared/ yet — correct, Task 1 creates it"
```

Untracked plan `.md` files under `docs/superpowers/plans/` are expected — leave them alone.

Create the working branch off `main`:

```bash
git checkout -b feat/ericsson-shared-transport main
```

## How to execute

Read the plan file in full first. Then use the `superpowers:subagent-driven-development`
skill — a fresh subagent per task with a review checkpoint between tasks. Alternatively
`superpowers:executing-plans` for inline batched execution.

Follow the plan's TDD cycle exactly: failing test → confirm it fails → implement → confirm
it passes → commit. Do not skip the confirm-it-fails step.

## Guardrails

- **Tests:** `./bootstrap.sh`, or `. .venv/bin/activate && pytest -q`. Shared-module tests
  need `PYTHONPATH=shared` — the plan gives the exact command per task.
- **Tasks 8 and 9 migrate the existing `ericsson-gitlab` and `ericsson-jira` connectors**
  onto the new client. These are live plugins. The full suite must stay green through both
  migrations, not merely at the end.
- `scripts/sync_shared.py` is the mechanism that copies `shared/ericsson_common/` into each
  plugin's vendored `_common/`. After any change to `shared/`, re-run it and let the drift
  test confirm the copies match.
- Read the plan's **Global Constraints** and **Decisions Taken** before Task 1.
- One thing worth carrying in your head: `SAFE_ERROR_MESSAGES` in each connector must
  contain **every** category the shared client can raise. Unknown categories coerce to
  `"transient"`, so a missing entry destroys the signal instead of failing loudly. That
  defect is why this plan exists.

## Definition of done

- All 9 tasks complete, each with its own commit
- `. .venv/bin/activate && python scripts/sync_shared.py && pytest -q` green
- Branch `feat/ericsson-shared-transport` pushed
- Report: what landed, deviations and why, anything the plan got wrong

**Do not merge to `main` and do not vendor into `hermes-agent`.** Report back.

## Downstream note

Session 3 cannot start until this work is merged to `main`. When you report, say plainly
whether it is ready to merge or whether something needs resolving first.
