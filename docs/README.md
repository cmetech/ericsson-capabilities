# Ericsson capability and flow handbook

This handbook explains the Loop24 Langflow automations translated into native Co-Worker capabilities for OTTO and LOOP24. It serves users choosing an outcome, maintainers implementing or changing a capability, and the implemented `onboard-ericsson-capabilities` router that explains and configures them interactively.

## Source and translation rule

- Source checkout: Loop24 repository `loop_24` (location varies by environment)
- Git remote: `git@git.rosetta.ericssondevops.com:sd-americas-css/sd-americas-ai/loop_24.git`
- Inventory snapshot: commit `3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e`
- Source areas: `flows/`, `custom_components/`, `mcp/`, and supporting scripts under `utils/`

The goal is to port each flow's intent, controls, and user outcome—not reproduce the Langflow graph node for node. In Hermes:

- deterministic ordering, approvals, and recovery belong in workflow YAML;
- reusable external operations belong in tools, plugins, or MCP servers;
- instructions and interactive guidance belong in skills;
- an embedded Langflow LLM node becomes work performed by the active Hermes agent;
- secrets stay in Hermes configuration, never in workflows or these documents.

## Flow inventory

| Original flow | Current status | Hermes counterpart or likely target |
|---|---|---|
| [CI File Auditor](flows/ci-file-auditor.md) | Not ported | GitLab tools plus audit workflow |
| [Search and Read E-Mails](flows/search-and-read-emails.md) | Intent ported | Outlook MCP plus `inbox-digest` workflow |
| [TOL Generation](flows/tol-generation.md) | Not ported | Document parser, prompt workflow, spreadsheet artifact |
| [Image Generation](flows/image-generation.md) | Intent ported | [`opportunity-visuals` skill](../skills/ericsson/opportunity-visuals/SKILL.md); [reproducible showcase](showcases/opportunity-visuals.md) |
| [Jira to GitLab](flows/jira-to-gitlab.md) | Partially ported | Jira tools exist; GitLab write path and workflow are missing |
| [Jira Assigned Tickets Summary](flows/jira-assigned-tickets-summary.md) | Intent ported | Jira tools plus `my-tickets-summary` workflow |
| [Jira Defect Loop](flows/jira-defect-loop.md) | Partially ported | Jira tools exist; triage, GitLab tools, loop, reviews, and summary remain |
| [3PP Support and LCM Tracker](flows/third-party-support-lcm-tracker.md) | Not ported | Spreadsheet tools plus lifecycle-research workflow |
| [Pseudonymization](flows/pseudonymization.md) | Not supported; no port planned | Historical tombstone only |
| [Re-Identification](flows/re-identification.md) | Planned, not implemented | No runnable mapping capability is available |
| [Windows Laptop Diagnostic](flows/windows-laptop-diagnostic.md) | Not ported | Windows-only diagnostic skill with reviewed script |

Supporting foundations already exist independently of a complete flow port: Jira REST tools, Teams Graph/MSAL tools, the Outlook MCP server, Glean MCP configuration, and the workflow orchestrator/builder.

## Onboarding, configuration, and maintenance

- [Configuration guide](configuration.md) explains every current, planned, and source-only credential or machine prerequisite.
- [Onboarding guide](onboarding/README.md) explains the implemented router, architecture, scope, resume status, and documentation map.
- [Onboarding authoring contract](onboarding/authoring.md) gives the exact add/change/remove, catalog generation, validation, and source-first delivery procedure.
- [Safety and demonstrations](onboarding/safety-and-demonstrations.md) defines configuration classes, secret handling, the readiness ladder, and synthetic showcase rules.
- [Artifacts and troubleshooting](onboarding/artifacts-and-troubleshooting.md) defines artifact inspection, failure taxonomy, partial-effect recovery, and saved-state behavior.
- [Mock sessions](onboarding/mock-sessions.md) provides cold-reader conversation examples.
- [Test strategy and results](onboarding/test-strategy-and-results.md) separates deterministic evidence, model evidence, and limitations.
- [Windows resume release validation](onboarding/windows-resume-release-validation.md) is the product-owner checklist for the pending native Windows acceptance run.
- [Skill design context](skill-design-context.md) defines the implemented router's runtime and authoring contract.
- [Flow template](flows/_template.md) is the required structure for documenting future source flows.
- [Ericsson Opportunity Visuals skill design](superpowers/specs/2026-07-14-ericsson-opportunity-visuals-design.md) specifies the approved deterministic port of the Loop24 Image Generation flow, including natural-language triggers, coworker interview behavior, and synthetic showcase/test artifacts.
- [Opportunity Visuals showcase](showcases/opportunity-visuals.md) provides cold-start prompts, exact synthetic commands, expected counts, artifact interpretation, PNG setup, troubleshooting, and visual verification.
- [Opportunity Visuals explained](opportunity-visuals-explained.md) gives a non-technical overview of what was delivered, how the coworker uses it, what the generated files mean, why the implementation is substantial, and how the shared skill reaches both OTTO and LOOP24.
- [Ericsson onboarding facilitator showcase](showcases/ericsson-capability-onboarding.md) demonstrates a fictional Jira journey, resume, Opportunity Visuals routing, and honest unsupported-platform handling.

## Status vocabulary

- **Intent ported:** a Hermes-native workflow achieves the source flow's user outcome, even if its internal steps differ.
- **Partially ported:** reusable foundations exist, but the end-to-end flow cannot yet run.
- **Not ported:** no supported end-to-end Hermes counterpart exists.
- **Planned:** a name or interface is proposed for port design and must not be presented to users as currently available.
- **Source-only:** configuration belonged to Langflow and should not automatically be carried into Hermes.
- **Not supported; no port planned:** retained only to answer historical requests accurately and never recommended as runnable.

## Documentation maintenance

When the Loop24 source changes, re-inventory `flows/**/*.json`, review component code and README files, and update the affected page's source commit/hash and behavior. When a capability is added, removed, or materially changed, follow the [complete maintenance checklist](onboarding/authoring.md): update implementation, registration, user guidance, configuration, natural-language examples, demonstrations/tests, onboarding entry, generated catalog, and the vendored Hermes snapshot together. Never put tokens, passwords, cookies, certificate contents, or values copied from a local `.env` into this repository.
