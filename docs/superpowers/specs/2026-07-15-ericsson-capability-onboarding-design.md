# Ericsson Capability Onboarding Skill Design

**Date:** 2026-07-15

**Status:** Approved design; implementation not started

**Target repository:** `ericsson-capabilities`

**Delivery target:** Manifest-driven vendored snapshot in `hermes-agent`

## Summary

Create a bundled Ericsson skill named `onboard-ericsson-capabilities` that is the single conversational entry point for discovering, learning, configuring, validating, demonstrating, and safely beginning to use the Ericsson capabilities delivered with Co-Worker.

The skill will behave like a knowledgeable colleague rather than a documentation search engine. It will begin with the user's role, goal, or desired outcome; ask one question at a time; recommend at most one or two relevant capabilities; distinguish product maturity from live readiness; and progressively load only the guidance needed for the selected route. It will not duplicate or replace the underlying domain skills, plugins, MCP servers, or workflows.

The selected architecture is a catalog-driven router with runtime reconciliation. A generated, committed catalog will combine source-controlled product documentation with manifest and implementation facts. At runtime, the router will overlay the actual profile, platform, discovery, enablement, dependency, and authentication state. Deterministic validation will prevent catalog drift.

The skill will also support opt-in, redacted resume state under the active `$HERMES_HOME`, isolated per profile. Every Co-Worker profile will receive the bundled skill with no Ericsson-specific enablement gate.

## Goals

- Let a new pilot user begin with natural language such as “Please onboard me to the Co-Worker capabilities.”
- Translate a user's job or desired outcome into one or two relevant Ericsson capabilities without dumping the full catalog.
- Explain what each selected capability solves, how to invoke it, what it asks, what it reads or changes, which approvals occur, and which artifacts it produces.
- Report product maturity and current readiness honestly and separately.
- Guide configuration without requesting or exposing secrets in ordinary chat.
- Validate readiness in increasing-risk order and never use a real write merely as a test.
- Provide clearly labeled synthetic or read-only demonstrations where useful.
- Guide a first real run through the underlying capability with appropriate previews and approvals.
- Explain generated artifacts, their locations, and how to validate them.
- Resume an onboarding journey across conversations without saving sensitive source content.
- Make catalog maintenance part of the capability authoring contract and enforce it automatically.
- Remove obsolete Ericsson-specific `ERICSSON_ENV` and disabled-by-default declarations without removing the generic infrastructure that other capability sets may use.
- Deliver identical shared capability bytes through the neutral Hermes `base` branch and every discovered brand.

## Non-goals

- Reimplementing Jira, Teams, Outlook, Glean, Opportunity Visuals, workflow execution, or other domain logic inside the onboarding skill.
- Turning the skill into a static copy of all Ericsson documentation.
- Claiming that a documented, partially ported, planned, or unsupported flow can run.
- Building a new general secret store or authentication framework.
- Automatically installing software, opening sign-in flows, changing configuration, or performing writes without user approval.
- Proving configuration by printing credentials or sensitive diagnostics.
- Using real Ericsson customer, employee, email, ticket, opportunity, or project data in demonstrations.
- Removing the generic Hermes `requiresEnv`, `disabledByDefault`, brand-curation, or dormant capability-source mechanisms.
- General cleanup unrelated to the Ericsson capabilities and their onboarding contract.

## Chosen approach

### Decision

Build a thin router skill backed by focused onboarding entries, generated catalog data, reusable workflows, shared policy references, and deterministic validators. Runtime inspection will reconcile documented facts with the active Co-Worker profile.

### Alternatives considered

**Static onboarding handbook.** A large `SKILL.md` could describe every capability in one place. It would be initially straightforward but would consume excessive context, repeat documentation, and drift as capability registrations and configuration change. The existing bundled `hermes-agent` skill, shown to users as “Co-worker,” is useful as a platform reference but demonstrates why the Ericsson onboarding surface should not become another large static handbook.

**Runtime-introspection-first router.** Deriving the experience entirely from the live installation would accurately identify many installed components. Runtime registrations do not contain enough product purpose, porting status, trigger education, artifact guidance, safe-demonstration policy, or troubleshooting context. This approach would also make planned and historical flows difficult to explain accurately.

**Catalog-driven router with runtime reconciliation — selected.** Source-controlled onboarding entries provide the educational contract; generated validation binds them to manifests, flow metadata, plugins, MCP configuration, workflows, and skill registrations; runtime checks provide current readiness. This gives the strongest combination of progressive disclosure, status honesty, maintainability, and testability.

## Product boundary

The new skill is the Ericsson training and onboarding entry point. It owns:

- initial intake and goal discovery;
- capability recommendation and selection;
- product-maturity explanation;
- readiness orchestration;
- safe configuration guidance;
- synthetic demonstration routing;
- first-run preparation;
- artifact education;
- troubleshooting routing;
- pause, summary, and resume state.

It may inspect state, run deterministic non-secret checks, and write onboarding summaries after consent. Domain reads and writes remain owned by the selected skill, plugin, MCP server, or workflow.

The existing `hermes-agent` skill remains the general Co-Worker platform guide. The Ericsson router may direct a user to a focused native surface or platform instruction, including Skills, Tools & Keys, MCP configuration, authentication, and general diagnostics. It must not reproduce that skill's command handbook or inherit its upstream-facing product language.

## User experience

### Trigger boundary

The skill should activate for direct onboarding requests and Ericsson capability discovery, education, configuration, readiness, demonstration, artifact, and troubleshooting goals. Representative triggers include:

- “Please onboard me to the Co-Worker capabilities.”
- “I'm new to Co-Worker—where should I start?”
- “What Ericsson capabilities can help me?”
- “Teach me how to use the Jira skills.”
- “Show me how Opportunity Visuals works.”
- “What do I need to configure for Outlook?”
- “Help me test the inbox digest.”
- “Which capabilities are ready for me to use?”
- “Resume my Ericsson onboarding.”

It should not take over an already clear domain request merely to force training. A user who directly requests an ordinary Jira summary may proceed through the Jira capability; the onboarding skill is appropriate when the user asks to learn, choose, configure, validate, demonstrate, interpret, troubleshoot, or resume.

### Conversation lifecycle

1. Welcome the user briefly and state the kinds of help available.
2. Ask one role-, goal-, or outcome-oriented question.
3. Reuse prior answers and observable environment state instead of asking for known information.
4. Recommend at most one or two capabilities, with concise reasons and honest status.
5. Let the user choose a depth: overview, readiness check, synthetic demonstration, guided real run, artifact walkthrough, or troubleshooting.
6. Progressively load the selected workflow, capability entry, and only the shared references that route requires.
7. Explain expected inputs, questions, reads, writes, approvals, dependencies, outputs, and artifacts before execution.
8. Route domain operations to the underlying capability after readiness and approval boundaries are clear.
9. End, pause, or resume with a concise personalized handoff.

The interview is conditional, not a fixed wizard. It asks exactly one question per turn and skips decisions already present in the request, environment, or saved state. It must never begin by listing the entire catalog.

### Unavailable capabilities

An unavailable capability may be mentioned when it directly matches the user's goal, but it must not be recommended as runnable. The skill should explain the current maturity, what is missing, and any available alternative. It must refuse attempts to execute planned, partial, historical, or unsupported flows.

Pseudonymization is explicitly not planned for porting. It will have only a minimal `not-supported-no-port-planned` tombstone so a user asking about the legacy flow receives an accurate answer. It must not appear in ordinary recommendations or roadmap language.

## Architecture

```text
skills/ericsson/onboard-ericsson-capabilities/
├── SKILL.md
├── workflows/
│   ├── discover-and-recommend.md
│   ├── explain-capability.md
│   ├── configure-and-check-readiness.md
│   ├── run-synthetic-demonstration.md
│   ├── guide-first-real-run.md
│   ├── interpret-artifacts.md
│   ├── troubleshoot-capability.md
│   └── resume-or-summarize.md
├── references/
│   ├── catalog.json
│   ├── capabilities/
│   │   └── *.md
│   ├── configuration-and-authentication.md
│   ├── safety-and-approvals.md
│   ├── demonstration-policy.md
│   ├── artifact-interpretation.md
│   └── troubleshooting-taxonomy.md
├── templates/
│   ├── onboarding-summary.md
│   ├── readiness-checklist.md
│   ├── first-run-checklist.md
│   └── session-handoff.md
└── scripts/
    ├── build_catalog.py
    ├── validate_catalog.py
    └── onboarding_state.py
```

The implementation plan may adjust filenames when repository conventions or tests show a clearer boundary, but it must preserve the thin-router, focused-entry, generated-catalog, deterministic-validation, and profile-scoped-state responsibilities.

### `SKILL.md`

- Uses the Hermes Markdown skill convention and valid frontmatter.
- Uses the directory-matching name `onboard-ericsson-capabilities` and the concise description `Onboard users to Ericsson Co-Worker capabilities.`
- Defines positive and negative trigger boundaries.
- Contains essential safety, honesty, one-question-at-a-time, and progressive-disclosure rules.
- Performs initial intake and routes to focused workflows.
- Does not embed the capability handbook or load the complete catalog into conversation context.

### Workflows

Each workflow is a reusable conversational procedure. It specifies entry conditions, allowed checks and actions, one-question behavior, required approvals, references to load, expected outputs, resumable checkpoints, and exit conditions. A workflow may route to another workflow, but it must not duplicate a domain implementation.

### Capability onboarding entries

Each capability has one focused Markdown entry with machine-readable metadata and plain-language guidance. The entry is the user-education contract and contains:

- stable capability ID, display name, and aliases;
- product maturity and recommendation eligibility;
- related skill, plugin, MCP server, and workflow registrations;
- supported platforms and local dependencies;
- static secrets, interactive sign-in, permissions, and ordinary workflow inputs;
- at least three realistic natural-language goal examples plus follow-up language for scope, filters, preview versus execution, output format, destination, exclusions, warnings, and safe reruns;
- information the Co-Worker will ask for;
- systems and data read;
- possible writes or changes and their approvals;
- outputs, artifact locations, and inspection guidance;
- readiness checks in risk order;
- supported demonstration modes and fixtures;
- common failures and recovery guidance;
- authoritative implementation and flow-document links.

Most capability changes should require editing only the implementation, its ordinary documentation, its onboarding entry, and generated artifacts—not the router.

### Generated runtime catalog

`references/catalog.json` is a deterministic, committed, compact routing index. It contains only the identifiers, aliases, goal-oriented search cues, maturity, recommendation eligibility, and pointers required for initial routing. Detailed configuration, safety, demonstration, artifact, and troubleshooting material remains in the focused capability entries and shared references, which are loaded only after selection. The index is generated from the capability entries and checked against:

- `sets/ericsson.json` for packaged content;
- skill frontmatter and referenced files;
- plugin manifests and relevant runtime tool registrations;
- MCP server definitions;
- workflow definitions and requirements;
- flow-document metadata for porting maturity;
- configuration metadata used by Hermes and the Keys surface.

The committed catalog lets the vendored skill operate without the full source documentation tree. Generated output must be stable for identical inputs and must be checked in CI for freshness.

### Source-of-truth precedence

Conflicts are resolved explicitly:

1. Current implementation and runtime registration determine whether executable behavior exists.
2. The Ericsson manifest determines what is packaged.
3. Flow-document metadata determines porting maturity and historical coverage.
4. Capability onboarding entries determine user-facing education and demonstration guidance.
5. The generated catalog compiles these facts but is never edited by hand.
6. Runtime state determines the active user's current readiness and overrides stale saved readiness.

A contradiction between these sources is a validation failure, not a reason to guess at runtime.

## Capability and readiness status

The design keeps product maturity separate from live readiness.

### Product maturity

- `available`: implemented and eligible for runtime readiness checks.
- `partially-ported`: some supporting behavior exists, but the documented flow cannot run end to end.
- `planned-not-implemented`: documented future or source-only capability with no runnable port.
- `not-supported-no-port-planned`: retained only to answer historical requests accurately.

### Runtime facts

For an available capability, the skill gathers independent facts when relevant:

- packaged and discoverable;
- enabled or disabled;
- supported on the active platform;
- dependency or server available;
- credential name configured without exposing its value;
- authentication validated;
- safe read-only probe succeeded;
- preview or draft available;
- write path available only after approval.

### Readiness result

The user-facing readiness result uses:

- `ready`;
- `missing`;
- `needs-user-action`;
- `unavailable-on-platform`;
- `planned-not-implemented`;
- `unknown-needs-check`.

`partially-ported` and `not-supported-no-port-planned` entries are not candidates for runtime readiness checks; their product maturity is shown directly. `planned-not-implemented` is used as a readiness result only for documented planned or source-only entries. This preserves the distinction between incomplete, planned, and explicitly unsupported capabilities.

The summary must retain supporting facts so “installed but disabled,” “installed but needing configuration,” and “configured but not authenticated” are not collapsed into the same label. A present environment-variable name is evidence only that a value may be configured; it is never sufficient evidence for `ready`.

## Initial capability coverage

The generator and validator, rather than this prose list, define final coverage. At minimum, the initial implementation must accurately cover:

- Opportunity Visuals;
- Jira assigned-ticket summary;
- Ericsson Jira tools;
- Ericsson Teams tools and device-code authentication;
- Outlook MCP and inbox digest;
- Glean MCP configuration;
- workflow orchestrator;
- workflow builder;
- every additional capability packaged by the Ericsson manifest or registered in the relevant runtime.

Documented Loop24 flows must be represented according to current flow metadata. Known non-available coverage includes:

- partially ported Jira to GitLab;
- partially ported Jira Defect Loop;
- CI File Auditor;
- TOL Generation;
- 3PP Support and LCM Tracker;
- Re-Identification;
- Windows Laptop Diagnostic;
- other source-only or future flows discovered by validation;
- Pseudonymization only as `not-supported-no-port-planned`.

The implementation must not preserve a hard-coded list that can silently drift. This section is an acceptance floor, not the runtime catalog.

## Configuration and secret safety

Every requirement is classified as one of:

- static secret;
- interactive authentication;
- permission or organizational access;
- local software, server, or platform requirement;
- ordinary workflow input.

The skill must never ask a user to paste passwords, tokens, cookies, certificate contents, or private keys into ordinary chat. It may check whether a key appears configured without printing its value, then direct the user to Tools & Keys or another approved protected entry mechanism. It may explain where a credential generally comes from but must not invent Ericsson-specific ownership or approval processes.

The skill asks before installing packages, starting dependency servers, opening sign-in flows, or changing configuration. Readiness validation proceeds in this order:

1. Packaged and discoverable.
2. Enabled and supported on the current platform.
3. Dependency or server startup.
4. Authentication.
5. Read-only list or retrieval.
6. Draft, preview, or synthetic execution.
7. Explicitly approved write through the underlying capability.

Email, Teams messages, Jira comments, commits, branches, and merge requests are never used merely to test configuration. Diagnostics, saved state, and summaries exclude or redact sensitive values and payloads.

Configuration metadata must account for required and optional implementation values, including optional overrides such as the Teams client ID. The catalog validator must detect relevant configuration names in implementation or manifests that have no corresponding onboarding guidance.

## Demonstration policy

Demonstrations identify their mode explicitly:

- synthetic/offline;
- simulated;
- read-only live;
- approved live.

Simulation must never be presented as successful live integration. Synthetic fixtures are fictional, clearly labeled, deterministic, and separated from generated demonstration output. Existing showcase fixtures are reused when appropriate; Opportunity Visuals supplies patterns for expected results, golden artifacts, audit manifests, and artifact interpretation, but capabilities adopt only the patterns suited to their outputs.

Before a demonstration, the skill explains expected results, planned actions, and artifact destination. Afterward, it compares actual and expected results, identifies discrepancies, and explains how to inspect the output. It prefers offline and read-only modes, avoids live credentials where a useful synthetic mode exists, never overwrites existing artifacts without confirmation, and never accepts real confidential data as showcase input.

An interrupted or partially successful operation is reported honestly. The skill records only a sanitized checkpoint and routes recovery through the underlying capability or troubleshooting workflow.

## Artifact guidance

Every available capability entry explains, where applicable:

- the expected output type;
- default or selected destination;
- whether the artifact is generated, draft, preview, or live-system state;
- how to inspect it safely;
- what success, exclusion, warning, or partial completion looks like;
- which manifest, log, metadata, or supporting file explains the result;
- how to rerun without overwriting prior work.

The skill must resolve an ambiguous artifact destination before writing. Summary state may store a safe local artifact pointer after consent, but not artifact contents or sensitive diagnostic material.

## Resume-state design

The skill is bundled for every profile. Progress is isolated to the active profile through `$HERMES_HOME`:

```text
$HERMES_HOME/onboarding/ericsson/
├── current.json
└── history/
    └── YYYYMMDDTHHMMSSZ.json
```

There is one active journey per profile. A journey may cover several capabilities. Completed summaries are retained as local history; multiple named active journeys are not part of the first release.

The skill asks once before persisting the first journey. After consent, it may update state at meaningful checkpoints. Users can inspect, summarize, restart, complete, or forget saved onboarding state. Writes are atomic and use restrictive local permissions where supported.

The state API detects the host operating system and dispatches to a secure,
platform-specific persistence backend. macOS and Linux use descriptor-relative
POSIX operations. Windows uses native Windows handles, reparse-point checks,
bounded interprocess locking, atomic same-volume replacement, and profile-private
ACLs. Both backends expose the same JSON schema and user behavior; neither may
silently fall back to weaker pathname-only checks.

Development-host tests cover the shared contract and the injectable Windows API
boundary. Windows-only tests remain collectable but skipped off Windows. Because
development occurs on macOS, final Windows filesystem, ACL, junction, locking,
and release-install behavior is an explicit pilot release acceptance gate run by
the product owner from the documented checklist. A pending native run is reported
as pending, never as verified.

Saved state contains only:

- schema and catalog version;
- selected capability IDs;
- product maturity and last-known readiness facts;
- completed learning, checks, and demonstrations;
- sanitized outcomes;
- pending user actions;
- safe artifact pointers when appropriate;
- recommended next prompt;
- creation and update timestamps.

It never stores credentials, authentication responses, raw email or Jira content, customer or employee data, pasted files, full transcripts, or unredacted diagnostics. Sensitive-looking values are omitted rather than reproduced.

Native Co-Worker session resume may preserve conversational context but is not required. When a journey resumes, the skill compares the saved catalog version with the current one and rechecks volatile installation, enablement, dependency, authentication, and availability facts.

## Personalized summary

Pause and completion use one stable handoff shape:

- selected capabilities;
- current readiness with supporting facts;
- completed learning or demonstration;
- missing user actions;
- safe artifact locations and inspection guidance, when applicable;
- one suggested next prompt.

The summary is concise, excludes secrets and sensitive content, and can be rendered from saved structured state without loading the full prior conversation.

## Obsolete Ericsson-declaration cleanup

The implementation will remove the obsolete Ericsson-specific delivery contract from source and synchronized delivery surfaces:

- `requiresEnv: {"ERICSSON_ENV": "1"}` in the Ericsson manifest;
- Ericsson manifest `disabledByDefault` declarations;
- brand-level `capabilityRequiresEnv` declarations for Ericsson;
- Jira and Teams plugin `requires_env` entries and “Gated on ERICSSON_ENV” descriptions;
- `ERICSSON_ENV` workflow requirements;
- documentation and compatibility-debt notes that preserve the stale model;
- source and Hermes tests that assert the obsolete Ericsson behavior;
- the regenerated vendored manifest, plugins, workflows, and documentation-derived catalog.

The implementation will also audit every ported Ericsson capability for stale configuration names, natural-language triggers, platform claims, dependency guidance, artifact locations, and compatibility instructions. An item is removed only when current implementation and runtime evidence show it is obsolete. General Hermes infrastructure and unrelated refactoring remain out of scope.

Generic `requiresEnv`, `disabledByDefault`, brand-curation, and dormant capability-source support remain available for other or future capability sets.

## Maintenance contract

Adding, removing, or materially changing an Ericsson capability must update, as applicable:

- its implementation;
- manifest and runtime registration;
- user-facing capability and flow documentation;
- configuration, authentication, permissions, dependencies, and platforms;
- natural-language trigger and follow-up examples;
- reads, writes, approvals, outputs, and artifact guidance;
- demonstrations, fixtures, expected results, and troubleshooting;
- its onboarding entry and generated catalog;
- the vendored Hermes snapshot.

The generator and validator enforce this contract. Validation fails when:

- a packaged or relevant runtime capability has no onboarding entry;
- a removed implementation remains advertised;
- a previously managed path remains as stale vendored content after its source entry is removed;
- product maturity disagrees with flow metadata or runnable registrations;
- a planned, partial, or unsupported capability is marked available;
- configuration names disagree across manifest, implementation, and onboarding guidance;
- a required education or safety field is absent;
- an entry references a missing file or unknown component;
- generated catalog output is stale;
- a vendored Hermes snapshot does not match its stamped source commit.

Resume records store the catalog version so older journeys are reconciled when capability contracts change.

## Test-driven skill development

Implementation begins with behavioral pressure scenarios before the final skill guidance exists. Baseline transcripts and outcomes record how an agent behaves without the new skill. The completed skill is accepted only when it corrects the identified failures.

Development follows red-green-refactor cycles and the Superpowers skill-authoring workflow. Subagent-driven development may be used after plan approval for independent test and implementation tasks, but no Git worktrees may be created.

### Structural validation

- Valid frontmatter and directory-matching skill name.
- Concise, discoverable description.
- Hermes Markdown section convention.
- Progressive disclosure and bounded `SKILL.md` size.
- Every referenced workflow, reference, template, and script exists.
- No broken relative paths.
- Manifest lint and packaging validation.
- Deterministic catalog generation with no uncommitted diff.

### Catalog consistency

- Every manifest-listed and relevant runtime Ericsson capability is represented.
- Every catalog implementation reference resolves.
- Planned, partial, and unsupported entries are not marked runnable.
- Pseudonymization is `not-supported-no-port-planned` and recommendation-ineligible.
- Removed capabilities do not remain advertised.
- Configuration names match manifests and implementation.
- Flow-document status matches catalog maturity.
- Vendored content matches the stamped source commit.

### Conversation scenarios

- Completely new user.
- User who names the desired capability.
- User with a vague business goal.
- User interested in several capabilities.
- Returning user resuming saved progress.
- Unsupported-platform user.
- Installed but disabled capability.
- Installed but unconfigured capability.
- Documented but partially ported capability.
- Planned or explicitly unsupported capability.

Scenarios verify one question per turn, reuse of known information, at-most-two initial recommendations, and a concise final handoff.

### Safety pressure tests

- User pastes or offers a token in chat.
- User asks to prove a key by printing it.
- User requests an email, Jira, Teams, commit, branch, or merge-request write as a test.
- User requests execution of an unported or unsupported capability.
- An operation has a partial side effect or interruption.
- Artifact destination is missing or ambiguous.
- User offers real confidential data for a showcase.
- Environment-variable name exists but authentication is invalid or unchecked.

### Demonstration artifacts

- Small fictional fixtures.
- Expected outputs and structured comparisons.
- Mock onboarding transcripts.
- Golden readiness summaries where stable.
- Pilot-facilitator showcase instructions.
- At least one end-to-end onboarding demonstration from vague goal through summary.

Reusable fixtures remain separate from generated output, and tests prove existing artifacts are not overwritten by default.

### Model behavior

Run the target models and configurations available in Hermes against the baseline and completed pressure scenarios. Verify that the completed skill:

- asks one question at a time;
- does not load or recite the full handbook;
- loads only the selected capability entry and required shared references;
- does not request secrets in chat;
- distinguishes documented status from runtime readiness;
- routes domain work instead of duplicating it;
- produces the required resumable summary.

Deterministic repository tests remain the merge gate. Model evaluations are recorded with model/configuration identity and clearly separated from deterministic assertions.

## Documentation deliverables

Implementation will produce or update durable documentation for:

- product purpose and scope;
- architecture and source-of-truth rules;
- catalog generation and maintenance;
- authoring a new capability onboarding entry;
- configuration and secret-handling policy;
- synthetic demonstration policy;
- artifact interpretation;
- troubleshooting;
- pilot-facilitator showcase;
- mock user sessions;
- test strategy and results.

`docs/README.md`, relevant configuration and flow documentation, and synchronized `CLAUDE.md`/`AGENTS.md` memory will be updated where durable repository guidance changes.

## Packaging and branch delivery

The source skill is created in `ericsson-capabilities` and added to `sets/ericsson.json`. Shared content is never authored directly on a Hermes brand branch.

After implementation, source verification, review, and explicit approval to deliver:

1. Commit the final source in `ericsson-capabilities`.
2. Run the manifest-driven Hermes vendor command using that exact source commit.
3. Commit the shared vendored snapshot on `hermes-agent/base`.
4. Discover brands from `hermes-agent/brands/*.json` rather than relying on a fixed list.
5. Merge `base` into every discovered brand.
6. Regenerate and check each branding overlay independently.
7. Run shared vendor and capability tests.
8. Run provider and brand-runtime tests on every brand.
9. Run `test_skin_engine.py` only on `otto`, where OTTO-literal assertions belong.
10. Verify the onboarding skill and manifest bytes match across `base`, `otto`, and `loop24`.
11. Finish on a clean `otto` checkout unless directed otherwise.

No worktrees, pushes, releases, or pull requests are permitted without explicit approval. Source commit and implementation delivery are also held for the requested approval gate.

## Acceptance criteria

The design is successfully implemented when a pilot user can begin with “Please onboard me to the Co-Worker capabilities” and, without a facilitator:

- identify capabilities relevant to their goal;
- understand which capabilities are available, partial, planned, unsupported, installed, disabled, configured, or not yet checked;
- select a capability and learn realistic natural-language invocation;
- understand required inputs, questions, systems, reads, writes, approvals, and outputs;
- configure dependencies and authentication without exposing secrets;
- validate readiness through the required increasing-risk sequence;
- complete a clearly labeled synthetic demonstration when supported;
- prepare and approve a first real run through the underlying capability;
- inspect and understand resulting artifacts;
- pause and resume onboarding across conversations within the active profile;
- receive a concise personalized next-step summary.

Repository acceptance additionally requires:

- stale Ericsson-specific gating and disabled-by-default declarations are removed everywhere in source and vendored content;
- generic capability infrastructure remains intact;
- catalog generation and consistency tests pass;
- pressure scenarios demonstrate improvement over baseline behavior;
- source, vendored, provider, brand-runtime, branding, and byte-equivalence checks pass on their required branches;
- documentation and maintenance guidance agree with implementation;
- all repositories and brand branches finish in the required clean state.

## Deferred extensions

The following require separate design approval:

- Multiple named active onboarding journeys within one profile.
- Organization-wide or cross-profile onboarding progress synchronization.
- Central telemetry or analytics for onboarding completion.
- Automatic credential acquisition or organization-specific access-request workflows.
- Automatic software installation or configuration repair without per-action approval.
- General Co-Worker onboarding outside the Ericsson capability ecosystem.
