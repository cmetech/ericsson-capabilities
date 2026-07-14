---
source_flow: flows/utils/Windows Laptop Diagnostic.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: f3f7fc494c8a4106f985a19a5ddfbb149370c75be87369eb7b43625210c56705
status: not-ported
target_artifacts: [windows-diagnostic-skill, reviewed-diagnostic-script]
supporting_capabilities: [powershell, hermes-agent]
platforms: [windows]
---

# Windows Laptop Diagnostic

## What it does

Collects a read-only Windows system report and lets the active agent answer questions or recommend concrete remediation based on that evidence.

## Original Loop24 flow

1. Run `.\utils\system_diagnostic.ps1` through the generic PowerShell Script Runner.
2. The checked-in flow does not request elevation and sets a 300-second timeout.
3. The report covers CPU/RAM/disk/GPU/page file, top processes, services/startup programs, power/network/uptime/temp/performance state, and recent diagnostic history.
4. Feed the report into an LLM as system context.
5. Accept the user's question and respond with evidence-based repair/optimization steps.

## Inputs and outputs

Inputs are the user's diagnostic question and optional scope. Output is a timestamped local report plus a chat explanation. The source example retains several historical reports for trend comparison.

## Supporting capabilities and configuration

Requires Windows, PowerShell, desktop access if elevation is ever introduced, and a reviewed bundled diagnostic script. No API key is flow-specific. See [Windows diagnostic configuration](../configuration.md#windows-diagnostics-and-powershell).

## Failure, safety, and privacy behavior

System reports can expose usernames, paths, process names, network identifiers, and installed software. Keep artifacts local, redact before sharing, and distinguish observation from recommendation. A generic arbitrary-PowerShell tool is too broad for the port; ship a fixed reviewed script with timeout/cancellation. Never make system changes automatically from diagnostic findings.

## Hermes port status and target shape

Not ported. Prefer a Windows-only skill bundling the narrowly scoped script and instructions for collection, interpretation, artifact retention, and optional follow-up actions. Any remediation should be a separate, previewed, approved step.

## How Hermes should explain and configure it

Ask what symptom the user sees, when it began, whether collection may include process/network/software inventories, and whether the report can leave the machine. Validate PowerShell and run read-only collection without elevation. On timeout or partial failure, retain and label partial evidence rather than claiming a complete diagnosis.
