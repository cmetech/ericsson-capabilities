# Ericsson onboarding skill context

The implemented `onboard-ericsson-capabilities` skill is the single Ericsson
training and onboarding entry point. This page records its durable runtime and
authoring context; the [onboarding documentation](onboarding/README.md) contains the
operational procedures.

## Outcome

After an interaction, the user should know which capability fits their goal, its
product maturity, what it reads or changes, the active profile's evidence-based
readiness, and the safest next action. The router can guide protected configuration,
non-destructive readiness checks, synthetic demonstrations, first-run preparation,
artifact interpretation, troubleshooting, and consented resume.

It does not replace Jira, Teams, Outlook, Glean, Opportunity Visuals, or workflow
domain behavior. A direct domain request can go to the domain capability; onboarding
activates for learning, choosing, configuring, validating, demonstrating,
interpreting, troubleshooting, or resuming.

## Sources and progressive disclosure

1. Implementation and runtime registration determine whether executable behavior
   exists.
2. `sets/ericsson.json` determines what is packaged.
3. Flow frontmatter determines source identity and product maturity.
4. Focused capability entries determine user education and demonstration guidance.
5. The generated compact catalog routes discovery and is never hand-edited.
6. Current runtime state determines readiness and overrides saved readiness.

Discovery loads the compact catalog. After selection, load one capability entry plus
only the chosen workflow, policy, and template. A contradiction between sources is a
validator failure, not permission to guess.

## Conversation routes

- **Discover/recommend:** start with role, goal, or outcome; ask one question; offer
  at most two matches and prefer `available` capabilities.
- **Explain:** describe the problem, example prompts, questions, reads, writes,
  approvals, dependencies, outputs, artifact locations, and common recovery.
- **Configure/readiness:** separate static secrets/settings, interactive sign-in,
  permission, software/platform, and workflow input. Guide one missing item at a
  time through protected interfaces.
- **Demonstrate:** label synthetic, simulated, read-only live, or approved live;
  preview expected output and a new destination, then compare actual with expected.
- **First real run:** route execution to the underlying capability only after scope,
  preview, and approval boundaries are clear.
- **Artifacts/troubleshooting:** explain destination, inspection, exclusions,
  warnings, and safe rerun; classify the failure before suggesting recovery.
- **Resume/summarize:** with consent, persist only a sanitized per-profile handoff,
  then recheck volatile facts on resume.

## Maturity and readiness

Product maturity is one of `available`, `partially-ported`,
`planned-not-implemented`, or `not-supported-no-port-planned`. Only available
entries receive runtime readiness checks. Readiness is `ready`, `missing`,
`needs-user-action`, `unavailable-on-platform`, `planned-not-implemented`, or
`unknown-needs-check`, supported by independent discovery, platform, dependency,
protected-setting, authentication, permission, and safe-probe facts.

Do not infer `ready` from an environment-variable name. Pseudonymization is an
unsupported historical tombstone with no port roadmap. Re-Identification is
non-runnable because its protected mapping dependency is unavailable.

## Selection cues

| User language | Candidate |
|---|---|
| “summarize my tickets,” “what should I work on” | Jira Assigned-Ticket Summary (available) |
| “read/digest my inbox” | Outlook inbox digest (available on Windows with classic Outlook) |
| “make an Ericsson opportunity progression visual” | Opportunity Visuals (available) |
| “show Teams and channels I can access” | Teams tools (available; device-code sign-in) |
| “search internal knowledge for this product” | Glean search (available when configured) |
| “build or run a repeatable workflow” | Workflow builder/orchestrator (available) |
| “fix this Jira defect and open an MR” | Jira-to-GitLab / Jira Defect Loop (partial, not runnable end to end) |
| “audit our GitLab CI” | CI File Auditor (planned, not implemented) |
| “turn requirements into test cases” | TOL Generation (planned, not implemented) |
| “remove PII with the old flow” | Pseudonymization (unsupported; no port planned) |

The legacy Image Generation outcome is provided by **Opportunity Visuals
(available)** for opportunity progression data. General illustrative image requests
remain with the ordinary image capability.

## Safety invariants

- Never accept, echo, print, fingerprint, log, or persist secret values in ordinary
  conversation.
- Never send email or Teams messages, add Jira comments, or create commits,
  branches, or merge requests merely to test configuration.
- Never describe partial, planned, or unsupported behavior as executable.
- Never retry a possibly completed side effect before inspection and fresh approval.
- Never use real confidential data in a showcase or overwrite an artifact without
  confirmation.

## Authoring contract

Every capability addition, removal, or material change follows the
[authoring and catalog maintenance procedure](onboarding/authoring.md). Update the
implementation, registration, user documentation, configuration, prompt examples,
demonstrations/tests, onboarding entry, generated catalog, and vendored Hermes
snapshot together. The catalog builder and validator are the primary enforcement
mechanism.
