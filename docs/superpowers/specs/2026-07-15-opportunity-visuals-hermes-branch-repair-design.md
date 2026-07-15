# Opportunity Visuals Hermes Branch Repair Design

## Goal

Place the approved Opportunity Visuals vendor snapshot on the neutral Hermes `base` branch, deliver
that shared snapshot to both `otto` and `loop24`, preserve all existing work, and make the placement
rule durable for future capability creation.

## Decisions

- The Ericsson source repository remains authoritative.
- Shared vendored content is committed on Hermes `base`, never directly on a brand branch.
- The current unpushed OTTO tip is preserved on a safety branch before its branch pointer moves.
- Hermes receives one final generated vendor commit on `base`; the detailed implementation history
  remains in the source repository.
- `base` is merged independently into every brand discovered by the brand descriptors.
- Brand generation and verification run on both OTTO and LOOP24 even though the shared skill is not
  itself brand-emitter-owned.
- No worktree, push, release, dependency installation, or remote mutation is part of the repair.

## Data flow

The final source commit is vendored onto `base`, producing the Ericsson manifest stamp and the runtime
skill tree. The updated `base` is merged into `loop24` and into a clean OTTO line rooted at its current
remote tip. Each brand re-applies its generated overlay. The final skill bytes and vendor stamp must
match across `base`, `otto`, and `loop24`.

## Failure handling

The old OTTO tip is retained on a named safety branch. Any conflict, failed brand check, failed test,
or unexpected path change stops the repair before a push. No branch is deleted during the repair.

## Documentation and memory

A reader-facing guide explains the capability in non-technical language. The source agent guide and
workspace CLAUDE/AGENTS memory explicitly state that shared capability vendoring starts on `base` and
then flows to every brand branch.

## Verification

- Ericsson manifest lint and full source tests pass.
- Source CLAUDE and AGENTS are byte-identical.
- Hermes vendor test and capability wrapper tests pass on `base` and both brands as appropriate.
- Brand generator checks pass for OTTO and LOOP24.
- The Opportunity Visuals runtime tree and `vendoredFrom` stamp match across all three branches.
- Brand-only diffs do not contain shared Opportunity Visuals files.
- All working trees are clean and the final checkout is `otto`.
