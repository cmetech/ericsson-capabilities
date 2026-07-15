# Ericsson capability and flow handbook

This handbook explains the Loop24 Langflow automations that are being translated into native Hermes capabilities for OTTO and LOOP24. It is written for three readers: a user deciding which automation can help, a maintainer planning a port, and a future Hermes skill that explains and configures the capabilities interactively.

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
| [Pseudonymization](flows/pseudonymization.md) | Not ported | Local privacy-vault plugin/skill |
| [Re-Identification](flows/re-identification.md) | Not ported | Local privacy-vault plugin/skill |
| [Windows Laptop Diagnostic](flows/windows-laptop-diagnostic.md) | Not ported | Windows-only diagnostic skill with reviewed script |

Supporting foundations already exist independently of a complete flow port: Jira REST tools, Teams Graph/MSAL tools, the Outlook MCP server, Glean MCP configuration, and the workflow orchestrator/builder.

## Configuration and future skill context

- [Configuration guide](configuration.md) explains every current, planned, and source-only credential or machine prerequisite.
- [Skill design context](skill-design-context.md) defines how a future Hermes skill should explain flows, assess readiness, guide configuration, validate safely, and troubleshoot.
- [Flow template](flows/_template.md) is the required structure for documenting future source flows.
- [Ericsson Opportunity Visuals skill design](superpowers/specs/2026-07-14-ericsson-opportunity-visuals-design.md) specifies the approved deterministic port of the Loop24 Image Generation flow, including natural-language triggers, coworker interview behavior, and synthetic showcase/test artifacts.
- [Opportunity Visuals showcase](showcases/opportunity-visuals.md) provides cold-start prompts, exact synthetic commands, expected counts, artifact interpretation, PNG setup, troubleshooting, and visual verification.
- [Opportunity Visuals explained](opportunity-visuals-explained.md) gives a non-technical overview of what was delivered, how the coworker uses it, what the generated files mean, why the implementation is substantial, and how the shared skill reaches both OTTO and LOOP24.

## Status vocabulary

- **Intent ported:** a Hermes-native workflow achieves the source flow's user outcome, even if its internal steps differ.
- **Partially ported:** reusable foundations exist, but the end-to-end flow cannot yet run.
- **Not ported:** no supported end-to-end Hermes counterpart exists.
- **Planned:** a name or interface is proposed for port design and must not be presented to users as currently available.
- **Source-only:** configuration belonged to Langflow and should not automatically be carried into Hermes.

## Documentation maintenance

When the Loop24 source changes, re-inventory `flows/**/*.json`, review component code and README files, and update the affected page's source commit/hash and behavior. When a port lands, update its status, configuration, validation procedure, and manifest entry together. Never put tokens, passwords, cookies, certificate contents, or values copied from a local `.env` into this repository.
