---
source_flow: flows/how-to/Search and Read E-Mails.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: 2dba7deb49f0e153d599cf5c0e95c2afc2ff6267cf08acf61db550ef179ec8ec
status: intent-ported
target_artifacts: [outlook-mcp, inbox-digest-workflow]
supporting_capabilities: [outlook]
platforms: [windows]
---

# Search and Read E-Mails

## What it does

Searches a local Outlook folder, iterates matching messages, reads each full message, and presents the results. The Hermes `inbox-digest` adaptation adds summarization and an action list rather than reproducing the source's raw per-message display.

## Original Loop24 flow

1. E-Mail Search queries desktop Outlook. The checked-in graph uses Inbox and a subject filter; the components also support folder, sender, subject, attachment, and limit filters.
2. A loop emits each matching search record.
3. E-Mail Read resolves the message and loads its full body and metadata. Attachment download is optional and disabled in the checked-in graph.
4. Chat Output displays each result and advances the loop.

## Inputs and outputs

Inputs are mailbox folder and search filters. Outputs include message metadata, body, and optionally local attachment paths. The `inbox-digest` workflow instead accepts `since` and `limit`, writes `inbox.json`, and produces `digest.md` grouped by sender/thread with a short action-needed list.

## Supporting capabilities and configuration

The port uses the bundled Outlook MCP server; no API key is required. Windows, logged-in desktop Outlook, PowerShell, and COM availability are required. See [Outlook configuration](../configuration.md#outlook-mcp).

## Failure, safety, and privacy behavior

Email bodies and attachments are sensitive. Save only what the workflow needs under the run artifact directory, avoid logging content, and never send or reply as part of a read-only request. Message positions can change; prefer stable identifiers where the MCP exposes them. Report Outlook closed/offline separately from “no matches.”

## Hermes port status and target shape

Intent is ported through Outlook MCP plus `workflows/inbox-digest.yml`. It is not a byte-for-byte clone: the active Hermes agent decides which truncated messages need a full read and creates the digest. The original “show every message” behavior remains possible by invoking Outlook tools directly.

## How Hermes should explain and configure it

Ask for timeframe, unread-only preference, sender/subject filters, result limit, and whether attachments may be read. Validate by listing mailboxes and a small message set. Explain that Outlook must remain open and that a digest reads message content locally.
