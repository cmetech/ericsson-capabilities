---
source_flow: flows/jira_gitlab/Jira -_ Gitlab.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: cf68ba438816621d3d2e30b2bff00a872060928ac60c9824e2f05f998f4c3815
status: intent-ported
target_artifacts: [ericsson-gitlab, jira-to-gitlab]
supporting_capabilities: [jira, gitlab, hermes-agent]
platforms: [macos, linux, windows]
---

# Jira to GitLab

## What it does

Selects an assigned Jira ticket, creates a proposed code fix in the linked GitLab project, opens a merge request, performs two review passes, and comments the result back on Jira.

## Original Loop24 flow

1. Fetch assigned tickets and select one key.
2. Resolve the GitLab URL embedded in the ticket to project ID/default branch.
3. Create or reuse `fix/<ticket-key>-<slug>`.
4. Fetch up to 20 source files matching configured extensions.
5. Build a prompt from the ticket and complete file contents.
6. The LLM returns strict JSON: commit message, fix summary, and full contents/actions for each file.
7. Push one atomic GitLab commit, then create or reuse an MR.
8. Fetch the MR diff and run independent security and adversarial-correctness reviews; combine their scores, capped when the fix does not address the ticket.
9. Add the MR link and review summary to the Jira issue.
10. The source then passes the result into a general agent with MCP tools for a final response.

## Inputs and outputs

Inputs include Jira/GitLab auth, ticket key, branch prefix, file extension allowlist, file limit, target branch, and optional mTLS paths. External writes are branch creation, commit, MR, and Jira comment. Outputs include fetched context, fix JSON, commit/MR metadata, review reports, and final summary.

## Supporting capabilities and configuration

Jira read/comment tools and the bounded GitLab project/read/write tools now exist. See [Jira](../configuration.md#jira) and [GitLab configuration](../configuration.md#gitlab).

## Failure, safety, and privacy behavior

This is high-consequence automation. Require explicit approval before the first write and preferably again before Jira commenting. Never commit secrets, truncate files silently, or treat an LLM-generated patch as reviewed code. Preserve idempotency for branches/MRs, record every side effect, and do not auto-retry an uncertain commit/MR after interruption.

## Hermes port status and target shape

Intent ported: the source now supplies Jira reads/comments, nine bounded GitLab tools, active-agent guidance, visible approval nodes, and a flat portable workflow. It deliberately replaces hidden aggregation and model clients with explicit tool contracts. Multi-ticket `loop_group` parity remains deferred.

## How Hermes should explain and configure it

Explain every write before setup. Ask for the ticket, permitted project, desired branch prefix, target branch, file scope, and approval policy. Validate Jira and GitLab read-only first, preview mutations, and obtain current-invocation host approval for each outward action.
