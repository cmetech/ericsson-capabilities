# Opportunity Visuals Hermes Branch Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the approved shared Opportunity Visuals vendor snapshot from an OTTO-only delivery to Hermes `base`, then propagate it to OTTO and LOOP24.

**Architecture:** Keep Ericsson capabilities as the source of truth. Preserve the current OTTO-only history on a safety branch, create one generated vendor commit on neutral `base`, and rebuild each brand by merging `base` and running its generator gates.

**Tech Stack:** Git, Node.js vendor/brand scripts, Python 3.11+, pytest, Markdown.

## Global Constraints

- Do not create worktrees.
- Do not push, release, install dependencies, or mutate remotes.
- Preserve the current OTTO tip before moving the local OTTO branch pointer.
- Finish on clean `otto` with shared runtime bytes and stamp identical across all brands.

---

### Task 1: Durable documentation and memory

**Files:**
- Create: `docs/opportunity-visuals-explained.md`
- Create: `docs/superpowers/specs/2026-07-15-opportunity-visuals-hermes-branch-repair-design.md`
- Modify: `docs/README.md`
- Modify: `CLAUDE.md`
- Modify: `AGENTS.md`
- Modify: workspace `CLAUDE.md` and `AGENTS.md`

- [ ] Add the reader-facing explanation and link it from the handbook.
- [ ] Add the explicit `base`-first branch invariant to both source agent guides.
- [ ] Add the same invariant to synchronized workspace memory.
- [ ] Verify each CLAUDE/AGENTS pair with `cmp` and run Markdown link/privacy checks.
- [ ] Commit the source-repository documentation changes.

### Task 2: Put the vendor snapshot on base

**Files:**
- Generated: Hermes `capabilities/ericsson.json`
- Generated: Hermes `skills/ericsson/opportunity-visuals/**`

- [ ] Create a safety branch at the current OTTO tip.
- [ ] Check out clean `base` and run the manifest-driven Ericsson vendor command.
- [ ] Confirm only the manifest and Opportunity Visuals runtime package differ.
- [ ] Run the vendor test, capability wrapper tests, compilation, stamp, and byte-parity checks.
- [ ] Commit the generated snapshot on `base`.

### Task 3: Rebuild both brand branches through base

**Files:**
- Generated branding overlay files only if a restamp is necessary.

- [ ] While checked out away from OTTO, point local `otto` back to `origin/otto`; the safety branch retains the old tip.
- [ ] Merge updated `base` into `loop24`, run `generate loop24 --write` and `--check`, run capability tests, and commit the merge.
- [ ] Merge updated `base` into `otto`, run `generate otto --write` and `--check`, run capability tests, and commit the merge.
- [ ] Verify neither brand-only diff contains shared Opportunity Visuals paths.

### Task 4: Final cross-repository gate

**Files:** None expected.

- [ ] Run Ericsson manifest lint and the full source pytest suite.
- [ ] Run Hermes vendor and capability wrapper tests on final OTTO.
- [ ] Compile all three source and vendored runtime helpers with bytecode outside the repositories.
- [ ] Compare the manifest stamp and all tracked Opportunity Visuals bytes across `base`, `otto`, and `loop24`.
- [ ] Run `git diff --check`, confirm all trees are clean, and finish on `otto`.
- [ ] Report exact source, base, OTTO, LOOP24, and safety-branch tips without pushing.
