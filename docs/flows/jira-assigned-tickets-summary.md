---
source_flow: flows/jira_gitlab/Jira Assigned Tickets Summary.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: d9e8c9465c6c2a2311949c788b45b9ec4201e72543b3746c3a4ec69377442ca1
status: intent-ported
target_artifacts: [ericsson-jira-plugin, my-tickets-summary-workflow]
supporting_capabilities: [jira, outlook]
platforms: [macos, linux, windows]
---

# Jira Assigned Tickets Summary

## What it does

Fetches unresolved Jira issues assigned to the current user and turns them into a concise, prioritized digest that preserves ticket keys, status, and GitLab links.

## Original Loop24 flow

1. Jira Assigned Tickets Fetcher queries assigned unresolved issues and extracts GitLab URLs from issue fields.
2. Jira Ticket Context Builder compacts all records into one context without dropping tickets.
3. The ACP-compatible LLM summarizes the set.
4. The same response is emitted to chat and the API text output.

## Inputs and outputs

The source needs Jira URL/token and an optional result limit. The Hermes workflow fetches up to 25 tickets, writes `tickets.json`, writes `summary.md` grouped by priority, and adds at most three suggested-focus bullets. Optional email delivery is guarded by approval and uses Outlook.

## Supporting capabilities and configuration

Current keys are `JIRA_BASE_URL` and `JIRA_PAT`; email delivery additionally needs Outlook. See [Jira](../configuration.md#jira) and [Outlook](../configuration.md#outlook-mcp).

## Failure, safety, and privacy behavior

The summary must not invent status or priority, omit tickets without saying so, or expose issue content to an unapproved external model. Email is a side effect and requires review/approval. A Jira read failure must not produce an “empty workload” summary.

## Hermes port status and target shape

Intent is ported through the `ericsson-jira` plugin and `workflows/my-tickets-summary.yml`. The tool layer uses direct HTTP rather than the source's curl-based Langflow component; summarization belongs to the active agent. The capability is baked into every profile and readiness depends on Jira configuration and a safe read, not a capability-set toggle.

## How Hermes should explain and configure it

Ask whether the user wants chat or approved email delivery and whether the default 25-ticket limit is appropriate. Validate Jira with a small read-only query. Show where `tickets.json` and `summary.md` will be written, and require approval after the summary is visible before sending email.
