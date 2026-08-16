# Session 8 — Wave 4B: Ericsson connector CLI and SuperCLI migration map

**Repo:** `ericsson-capabilities` · **Wave:** 4B · **Runs only after Wave 4A is merged to neutral Hermes base**

Execute the approved connector CLI implementation plan task by task.

**Repository:** `ericsson-capabilities` (this repo)

**Plan file:** `docs/superpowers/plans/2026-08-16-ericsson-connector-cli.md`

**Design:** `docs/superpowers/specs/2026-08-16-ericsson-connector-cli-design.md`

**Scope:** all 9 tasks, nothing outside the plan.

## Before you start

Run from the source repository root and stop on the first failure:

```bash
git fetch origin
git rev-parse --abbrev-ref HEAD
# expect: main

git status --porcelain --untracked-files=no
# expect: no output

git rev-list --count origin/main..main
# expect: 0
git rev-list --count main..origin/main
# expect: 0

test -f docs/superpowers/plans/2026-08-16-ericsson-connector-cli.md
test -f docs/superpowers/specs/2026-08-16-ericsson-connector-cli-design.md
test -d plugins/ericsson-jira
test -d plugins/ericsson-gitlab
test -d plugins/ericsson-confluence
test -d plugins/ericsson-arm

grep -q 'jira_link_issues' plugins/ericsson-jira/plugin.yaml
grep -q 'gitlab_retry_pipeline' plugins/ericsson-gitlab/plugin.yaml
grep -q 'confluence_update_page' plugins/ericsson-confluence/plugin.yaml
grep -q 'arm_deploy' plugins/ericsson-arm/plugin.yaml

test -f ../hermes-agent/hermes_cli/plugin_application_commands.py
git -C ../hermes-agent fetch origin
test "$(git -C ../hermes-agent rev-list --count origin/base..base)" = 0
test "$(git -C ../hermes-agent rev-list --count base..origin/base)" = 0
git -C ../hermes-agent grep -q 'register_application_commands' base -- hermes_cli/plugins.py
git -C ../hermes-agent grep -q 'invoke_application_command' base -- hermes_cli/plugins.py
```

If the repositories are not sibling checkouts, locate `hermes-agent` by repository name/remote and run the same read-only checks there. Locate the SuperCLI analysis workspace by these required files and stop if any is absent:

```text
SUPER-CLI-ARCHITECTURE.md
PLUGIN-GAP-ANALYSIS.md
out/func-strings.txt
```

Establish the source baseline:

```bash
. .venv/bin/activate
HERMES_AGENT_DIR=../hermes-agent pytest -q
```

Expected: PASS, allowing only the repository's documented platform skips. `HERMES_AGENT_DIR` is environment setup, not a plan change. If any test fails, verify it against `main~1` before calling it baseline; stop if the failure is introduced on current `main`.

Only then create the branch:

```bash
git checkout -b feat/ericsson-connector-cli main
```

## How to execute

Read the design and plan in full. Use `superpowers:subagent-driven-development` with a fresh implementer and review checkpoint per task, or `superpowers:executing-plans` for inline batches. Follow every stated red-green-refactor and commit step.

## Non-negotiable guardrails

- Do not edit or revive Wave 1-3 branches; this branch starts from their merged result.
- The facade is network-free and must not import connector internals.
- Model and direct adapters share each connector's one application executor.
- Do not construct, alias, or bypass either Hermes authority type.
- Every write requires exactly one of `--dry-run` and `--confirm` before any side effect.
- Preserve `write_ambiguous` as exit 5; never retry it because the user confirmed.
- Do not accept secrets, origins, certificates, or profile selection on argv.
- Do not guess SuperCLI commands/flags; use the pinned evidence files.
- Update onboarding and generated artifacts in the same branch.
- Stop and report if post-Wave-3 schemas differ from the plan's approved command table.

## Definition of done

- all 9 tasks complete in focused commits;
- connector CLI, connector regressions, generated checks, and `./bootstrap.sh` pass;
- branch `feat/ericsson-connector-cli` is pushed;
- report command coverage, mapping disposition counts, output/exit contract, tests, and deviations.

**Do not merge, vendor to Hermes, merge neutral base into brands, regenerate brand overlays, restamp, or release.** Those actions remain a separate source-first delivery session after review and merge authorization.
