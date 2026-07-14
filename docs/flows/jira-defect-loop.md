---
source_flow: flows/jira_gitlab/Jira_Defect_Loop.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: dfa08945d8f0ee215f772feb5098c7196fc5cc1d9b4ef313a19770f8376939de
status: partially-ported
target_artifacts: [ericsson-gitlab-plugin, jira-defect-loop-workflow]
supporting_capabilities: [jira, gitlab, outlook, hermes-agent]
platforms: [macos, linux, windows]
---

# Jira Defect Loop

## What it does

Triage all assigned Jira tickets, process every fixable defect through the Jira-to-GitLab pipeline, and produce one summary suitable for an Outlook email. It is the batch/flagship form of the single-ticket Jira-to-GitLab flow.

## Original Loop24 flow

1. Fetch unresolved assigned Jira issues.
2. Jira Ticket Triage uses the LLM to classify issues as auto-fix, needs information, manual review, or not a code fix. It may comment on skipped tickets when configured.
3. Loop over the fixable subset.
4. For each ticket: resolve GitLab project; create/reuse a fix branch; fetch source; generate strict fix JSON; push an atomic commit; create/reuse an MR; run security and adversarial reviews; comment the result on Jira.
5. Each Jira update advances the loop.
6. Fix Summary Composer flattens completed items into one email-ready summary.
7. A general agent with MCP tools presents or delivers the summary.

## Inputs and outputs

Inputs cover Jira/GitLab auth, triage policy, file/branch limits, approval policy, and delivery choice. Outputs are per-ticket run records, branches/commits/MRs/comments, review artifacts, skipped-ticket reasons, and one aggregate summary.

## Supporting capabilities and configuration

Jira and Outlook foundations exist; GitLab tools do not. See [configuration](../configuration.md). A future batch run should authenticate once but keep authorization and artifact state scoped per ticket.

## Failure, safety, and privacy behavior

Batching magnifies risk. Default to review-required rather than autonomous writes, cap ticket count/concurrency, and isolate failures so one issue does not erase other results. Never re-run an uncertain side effect. Skipped/failed tickets must appear in the final summary. Triage is advisory: classification cannot grant permission to modify a repository.

## Hermes port status and target shape

Partially ported through Jira tools and the workflow orchestrator, but workflow schema v1 explicitly deferred loop support. The port needs GitLab tools and either safe loop semantics added to the workflow engine or a controller pattern that starts one child run per ticket. Prefer building the single-ticket Jira-to-GitLab path first and composing it only after its approvals/idempotency are proven.

## How Hermes should explain and configure it

Ask how many tickets may be processed, which classifications are eligible, whether skipped-ticket comments are allowed, where approval occurs, and how the final summary is delivered. Make the write count explicit. Until implemented, offer ticket summarization or one manually supervised fix at a time.
