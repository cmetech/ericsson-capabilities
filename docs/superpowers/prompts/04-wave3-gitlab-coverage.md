# Session 4 — Wave 3 (parallel): GitLab coverage

**Repo:** `ericsson-capabilities` · **Wave:** 3 · **Requires Wave 2 merged to `main`**
**Runs in parallel with Sessions 5 and 6 — use a worktree.**

---

Execute an implementation plan, task by task.

**Repository:** `/Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities`

**Plan file:** `docs/superpowers/plans/2026-08-15-ericsson-gitlab-coverage.md`

**Scope:** All 9 tasks. Nothing outside this plan.

## Isolation

Two other sessions are working in this repo at the same time. Work in your own git
worktree so you cannot collide with them:

```bash
cd /Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities
git worktree add .worktrees/gitlab-coverage -b feat/ericsson-gitlab-coverage main
cd .worktrees/gitlab-coverage
```

The `superpowers:using-git-worktrees` skill covers this if you want the fuller treatment.
Your worktree needs its own virtualenv — run `./bootstrap.sh` inside it before Task 1.

Your file footprint is `plugins/ericsson-gitlab/**` and `tests/test_gitlab_*.py`, which
does not overlap the other two sessions at all. If you find yourself editing
`sets/ericsson.json`, `scripts/sync_shared.py`, `shared/ericsson_common/**`, or anything
under `plugins/ericsson-confluence/` or `plugins/ericsson-arm/`, **stop** — that is someone
else's lane and the plan does not ask for it.

## Before you start

```bash
git rev-parse --abbrev-ref HEAD                    # expect: feat/ericsson-gitlab-coverage
ls shared/ericsson_common/client.py                # Plan 2 must be merged
grep -n "^CONSUMERS" scripts/sync_shared.py        # expect all four connectors listed
ls plugins/ericsson-arm/ plugins/ericsson-confluence/   # Wave 2 must be merged
. .venv/bin/activate && pytest -q                  # expect: green
```

If `plugins/ericsson-arm/` is missing, Wave 2 has not merged yet — **stop and say so.**

## How to execute

Read the plan in full first. Use `superpowers:subagent-driven-development` — fresh subagent
per task, review checkpoint between tasks. Follow the TDD cycle exactly: failing test →
confirm it fails → implement → confirm it passes → wire the tool → parity check → commit.

## Guardrails

- **Tests:** `. .venv/bin/activate && pytest -q` from inside your worktree.
- **Task 1 fixes a live security defect** — GitLab currently ships tool-name approval
  `rule_key`s, which turn one "always" click into a permanent standing grant for every
  future call with any arguments. Do that task first and do not weaken it later.
- Every write tool: `require_explicit_intent(dry_run=, confirm=, action=)`. Neither flag
  is a refusal, not an implicit execute.
- `_WRITE_TOOLS` ↔ `WRITE_APPROVALS` parity, and every tool exposing `confirm` must be in
  `_WRITE_TOOLS`. The plan gives the verification snippet — run it.
- `SAFE_ERROR_MESSAGES` must contain every category the shared client can raise. GitLab
  was missing `write_ambiguous` once already.

## Definition of done

- All 9 tasks complete, each with its own commit
- Schema ↔ `plugin.yaml` parity check passes with the tool count the plan states
- `. .venv/bin/activate && pytest -q` green
- Branch `feat/ericsson-gitlab-coverage` pushed
- Report: what landed, deviations and why, anything the plan got wrong

**Do not merge to `main`.** Report back — three branches land together after all of Wave 3
reports.
