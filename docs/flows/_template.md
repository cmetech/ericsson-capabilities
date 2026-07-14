---
source_flow: flows/category/Flow.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: replace-with-source-hash
status: not-ported
target_artifacts: []
supporting_capabilities: []
platforms: [macos, linux, windows]
---

# Flow name

## What it does

State the user's outcome and why the automation exists. Do not describe implementation first.

## When to use it

Give concrete requests that should select this flow and cases that should not.

## Original Loop24 flow

Describe the graph in execution order, including branches, loops, approvals, external side effects, and what the embedded LLM is asked to decide. Distinguish graph wiring from configuration defaults.

## Inputs and outputs

List required and optional inputs, generated artifacts, external writes, and what appears in chat.

## Supporting capabilities and configuration

Link to `../configuration.md`. Name every tool, MCP server, dependency, operating-system constraint, credential, permission scope, and interactive sign-in requirement. Never include a secret value.

## Failure, safety, and privacy behavior

Explain partial completion, retries, idempotency, approval needs, sensitive data, local persistence, and safe recovery.

## Hermes port status and target shape

Record what is current, what is partial, and the recommended workflow/skill/plugin/MCP split. Embedded LLM nodes normally become prompt nodes handled by the active Hermes agent.

## How Hermes should explain and configure it

Provide example user requests, readiness questions, safe configuration sequence, validation checks, and actionable troubleshooting messages for the future interactive skill.
