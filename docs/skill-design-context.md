# Future explain-and-configure skill design context

This document is source material for a future Hermes skill that helps users discover, understand, configure, and validate Ericsson flows. It is not the skill implementation.

## Outcomes

After the interaction, the user should know which flow fits their goal, what it will read or change, whether it is currently available, what configuration is missing, and the safest next action. When authorized, the skill should guide configuration and run non-destructive readiness checks.

## Sources of truth

1. Use each page's frontmatter for source identity, port status, platform, target artifacts, and dependencies.
2. Use the body for user outcome, execution sequence, safety, and failure behavior.
3. Use `configuration.md` for keys, sign-in, permissions, machine prerequisites, and validation.
4. Use the capability manifest and runtime registry to determine what is actually installed. Documentation marked planned must never be presented as available.

## Conversation routes

### Explain a flow

Ask what outcome the user wants, select one or two candidates, explain the steps in plain language, name all reads/writes and approvals, report current port status, then offer readiness/configuration help. Do not begin with Langflow node names.

### Recommend a flow

Ask one question at a time about the source system, desired artifact/action, platform, frequency, and acceptable write authority. Prefer an already ported flow. If only an unported flow matches, explain that clearly and offer its manual/native Hermes alternative rather than pretending it can run.

### Configure a capability

Build a readiness checklist from the selected flow. Separate static keys, interactive sign-in, software prerequisites, permissions, and workflow inputs. Guide one missing item at a time. Open or direct the user to the protected Keys surface for secrets; never request a token in normal chat.

### Validate readiness

Use a ladder from least to most consequential: installed/discovered; dependency import or server start; authentication; read-only list/get; draft/preview; approved write. Stop at the first failure and give a capability-specific explanation.

### Troubleshoot

Classify before suggesting fixes: missing configuration, expired/rejected auth, insufficient permission, network/TLS, missing local application/dependency, invalid input, source-system error, workflow-state error, or partial side effect. Preserve the exact safe error while redacting sensitive values.

## Required response content

For every flow explanation include:

- current status: intent ported, partial, or not ported;
- supported platforms and local-app requirements;
- what data is read and where artifacts are stored;
- every external write or irreversible action;
- required keys/sign-in/permissions without exposing values;
- expected duration or scale concern when known;
- failure/recovery and approval points;
- a concrete next step.

## Configuration state model

Report each requirement as one of: `ready`, `missing`, `needs-user-action`, `unavailable-on-platform`, `planned-not-implemented`, or `unknown-needs-check`. Do not infer `ready` merely because a key name exists; use an authorized validation. Never print a secret to prove it is present.

## Flow selection cues

| User language | Candidate |
|---|---|
| “summarize my tickets,” “what should I work on” | Jira Assigned Tickets Summary |
| “read/digest my inbox” | Search and Read E-Mails / inbox digest |
| “fix this Jira defect and open an MR” | Jira to GitLab or Jira Defect Loop (partial) |
| “audit our GitLab CI” | CI File Auditor (not ported) |
| “turn requirements into test cases” | TOL Generation (not ported) |
| “check lifecycle/EOS dates in this tracker” | 3PP Support and LCM Tracker (not ported) |
| “remove PII,” “restore pseudonyms” | Privacy-vault pair (not ported) |
| “diagnose my Windows laptop” | Windows Laptop Diagnostic (not ported) |
| “make a branded infographic from this data” | Image Generation (not ported) |

## Safety invariants

- Never accept, echo, log, or persist secret values in ordinary conversation.
- Never send email, Teams messages, Jira comments, commits, branches, or merge requests merely to test configuration without explicit approval and a safe target.
- Never describe an unported flow as executable.
- Never re-run a possibly completed side effect after interruption without confirmation.
- Keep privacy mappings local and protected; anonymized data is not proof that the mapping store is safe.
- Generic shell/PowerShell execution is not an acceptable configuration shortcut.

## Authoring the eventual skill

The skill should load only the selected flow page plus the relevant configuration sections, not all documents on every turn. It should use deterministic checklists for setup/readiness while letting the agent explain and troubleshoot in natural language. Tests should cover flow selection, status honesty, refusal to collect secrets in chat, platform gating, least-risk validation ordering, and partial-side-effect recovery.
