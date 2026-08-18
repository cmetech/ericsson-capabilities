# Session 8 — Wave 4B: Ericsson connector CLI and SuperCLI migration map

**Repo:** `ericsson-capabilities` · **Wave:** 4B · **Runs only after Wave 4A is merged to neutral Hermes base**

Execute the approved connector CLI implementation plan task by task.

**Repository:** `ericsson-capabilities` (this repo)

**Plan file:** `docs/superpowers/plans/2026-08-16-ericsson-connector-cli.md`

**Design:** `docs/superpowers/specs/2026-08-16-ericsson-connector-cli-design.md`

**Scope:** all 9 tasks, nothing outside the plan. Task 1 contains two ordered
commits: Task 1A adds the approved GitLab compatibility operations, then Task
1B scaffolds the facade against the complete 60-operation contract.

## Approved post-Wave-3 reconciliation

The 2026-08-18 reconciliation is part of the approved design and plan. Before
Task 1A, expect 58 existing operations. The following differences are approved
and must not trigger the general schema-drift stop rule:

- add `gitlab_read_pipeline` for
  `gitlab pipeline view <project> <pipeline-id>`;
- add `gitlab_create_named_branch` for
  `gitlab branch create <project> <branch> <ref>`;
- expose the existing `gitlab_inspect_ci` as
  `gitlab ci inspect <project>`;
- expose the existing ticket-derived `gitlab_create_branch` as
  `gitlab branch create-ticket <project> <ticket-key> --summary <text>`; and
- require `<project>` for `gitlab mr list`.

Task 1A implements the two missing canonical operations with connector-local
TDD, parity, approval, ambiguity, and bounded-output tests. Task 1B then
requires exactly 60 descriptors: Jira 15, GitLab 30, Confluence 9, ARM 6. Stop
for any other added, removed, renamed, or incompatible operation.

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
```

Locate `hermes-agent` by repository name or Git remote; do not assume it is a
sibling checkout. Set `HERMES_AGENT_DIR` to that resolved checkout, then use
that same checkout for every gate and Ericsson test:

```bash
HERMES_AGENT_DIR=/resolved/path/to/hermes-agent
git -C "$HERMES_AGENT_DIR" fetch origin
test "$(git -C "$HERMES_AGENT_DIR" branch --show-current)" = base
test -z "$(git -C "$HERMES_AGENT_DIR" status --porcelain --untracked-files=no)"
test "$(git -C "$HERMES_AGENT_DIR" rev-list --count origin/base..base)" = 0
test "$(git -C "$HERMES_AGENT_DIR" rev-list --count base..origin/base)" = 0
git -C "$HERMES_AGENT_DIR" cat-file -e \
  origin/base:hermes_cli/plugin_application_commands.py
git -C "$HERMES_AGENT_DIR" grep -q \
  'register_application_commands' \
  origin/base -- hermes_cli/plugins.py
git -C "$HERMES_AGENT_DIR" grep -q \
  'invoke_application_command' \
  origin/base -- hermes_cli/plugins.py
```

The Hermes checkout must remain on tracked-clean `base` (existing untracked user
files are allowed), with zero divergence from `origin/base`. Verifying a local
ahead branch or the local tree instead of `origin/base` is not sufficient.

Locate the SuperCLI analysis workspace by these required files and stop if any
is absent:

```text
SUPER-CLI-ARCHITECTURE.md
PLUGIN-GAP-ANALYSIS.md
out/func-strings.txt
```

Establish the source baseline:

```bash
. .venv/bin/activate
HERMES_AGENT_DIR="$HERMES_AGENT_DIR" pytest -q
```

Expected: PASS, allowing only the repository's documented platform skips.
`HERMES_AGENT_DIR` must be the exact clean synchronized `base` checkout gated
above; it is environment setup, not a plan change. If any test fails, reproduce
the same failing test with the same Hermes checkout in a separate untouched
worktree at the exact current `origin/main` commit before calling it baseline.
Never use `main~1` as baseline evidence. Stop if the failure does not reproduce
at exact `origin/main`.

Only then create the branch:

```bash
git checkout -b feat/ericsson-connector-cli main
```

## How to execute

Read the design and plan in full. Execute Task 1A before Task 1B, then continue
Tasks 2-9 in order. Use `superpowers:subagent-driven-development` with a fresh
implementer and review checkpoint per task, or `superpowers:executing-plans`
for inline batches. Follow every stated red-green-refactor and commit step.

## Non-negotiable guardrails

- Do not edit or revive Wave 1-3 branches; this branch starts from their merged result.
- The facade is network-free and must not import connector internals.
- Model and direct adapters share each connector's one application executor.
- Do not construct, alias, or bypass either Hermes authority type.
- Every write requires exactly one of `--dry-run` and `--confirm` before any side effect.
- Named-branch creation resolves the requested ref to an exact commit identity.
  Preview may perform bounded project/ref/branch reads but no mutation;
  pre-existing mismatch is `conflict`, and an unproved post-dispatch identity
  is `write_ambiguous`.
- Provider adapters validate a genuine active Wave 4A invocation before
  translating host mode. Direct dry-run applies `dry_run=True`; direct confirm
  applies `confirm=True` where supported or the plan's bounded dry-run-shaped
  `dry_run=False` normalization. Model writes still require genuine
  `PluginToolAdmission`; neither adapter accepts the other's authority.
- Preserve `write_ambiguous` as exit 5; never retry it because the user confirmed.
- Do not accept secrets, origins, certificates, or profile selection on argv.
- Do not guess SuperCLI commands/flags; use the pinned evidence files.
- Update onboarding and generated artifacts in the same branch.
- Stop and report if schemas differ from the reconciled plan beyond the two
  Task 1A additions and three corrected public signatures listed above.

## Definition of done

- all 9 tasks complete in focused commits, including separate Task 1A and 1B
  commits;
- connector CLI, connector regressions, generated checks, and `./bootstrap.sh` pass;
- branch `feat/ericsson-connector-cli` is pushed;
- report command coverage, mapping disposition counts, output/exit contract, tests, and deviations.

**Do not merge, vendor to Hermes, merge neutral base into brands, regenerate brand overlays, restamp, or release.** Those actions remain a separate source-first delivery session after review and merge authorization.
