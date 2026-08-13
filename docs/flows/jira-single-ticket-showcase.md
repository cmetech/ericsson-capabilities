---
source_flow: flows/jira_gitlab/Jira_Defect_Loop.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: dfa08945d8f0ee215f772feb5098c7196fc5cc1d9b4ef313a19770f8376939de
status: intent-ported
target_artifacts: [ericsson-jira-plugin, jira-single-ticket-showcase-workflow]
supporting_capabilities: [jira, hermes-agent]
platforms: [macos, linux, windows]
---

# Jira Single-Ticket Showcase

## What it does

Accepts exactly one Jira issue key, reads bounded normalized context, lets the active agent produce one triage classification and comment proposal, shows the exact target/body for approval, and then either posts that one comment or stops truthfully.

## Scope and deliberate exclusions

This is a Release 2 demonstration of the advertised Jira read, active-agent triage, and approval-gated comment path. It is not a multi-ticket workflow, does not edit/assign/transition issues, does not create GitLab changes, and does not aggregate results. Exact batch behavior remains deferred to Phase 6 `loop_group`.

## Configuration and readiness

Enable `ericsson-jira` explicitly through Tools, configure bearer or basic authentication in the protected plugin fields, start a fresh conversation, and prove readiness with a small permitted read. Never comment merely to test setup.

## Safety and failure behavior

Triage confidence is advisory and does not grant write authority. The workflow sidecar marks only `post-comment` as an outward action under `approval_required`; the plugin separately requires current-invocation host admission. Duplicate comments are reconciled before posting. An ambiguous write is inspected read-only and never blindly retried.

## Installed validation

On supported installed builds, exercise the one-key input, read-only failure categories, triage output bounds, rejected approval, approved comment against an authorized test issue, duplicate reconciliation, and uncertain-outcome stop. The Windows installed-only matrix is in [Windows Jira release validation](../onboarding/windows-jira-release-validation.md).
