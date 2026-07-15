# Configuration Safety and Demonstrations

This policy lets a facilitator or maintainer guide readiness and demonstrations
without exposing credentials, overstating status, or creating test side effects.

## Classify every requirement

- **Static secret:** token, password, cookie, certificate, or private key. Detect
  only configured/not configured and direct entry to protected Tools & Keys.
- **Static setting:** endpoint, tenant, or public client identifier. It is not a
  credential but may still belong in protected configuration.
- **Interactive sign-in:** device code, browser, desktop application, or other
  approved authentication flow. Ask before opening it and never request the code or
  response in ordinary chat.
- **Permission:** access to a project, mailbox, team, channel, knowledge source, or
  file. Authentication success is not permission proof.
- **Local software/platform:** operating system, desktop application, package,
  executable, server, or network/TLS path. Ask before installing or launching.
- **Workflow input:** scope, filters, issue IDs, dates, limits, local files, formats,
  and destinations. Do not store these as credentials.

Never ask a user to paste a password, token, cookie, certificate contents, or private
key into chat. Never print, echo, mask, hash, fingerprint, or otherwise derive a
secret to prove it exists. Explain only the documented general source of a
credential; do not invent an organization-specific owner or approval process.

## Readiness in increasing-risk order

1. Confirm packaged and discoverable.
2. Confirm current profile discoverability and platform support. If a generic profile/runtime suppression
   exists, report it separately; it is not an Ericsson
   capability-set toggle or disabled-by-default delivery rule.
3. Confirm dependency or server availability.
4. Validate authentication without exposing values.
5. Perform a bounded read-only list/get when authorized.
6. Produce a draft, preview, or synthetic result.
7. Perform a write only through the domain capability after explicit, scoped user
   approval.

A configured setting name is not proof of readiness. Report independent facts and
use `unknown-needs-check` when evidence is absent. Email, Teams messages, Jira
comments, commits, branches, and merge requests are never setup tests.

## Demonstration modes

- `synthetic/offline`: deterministic fictional input with no live connection.
- `simulated`: a labeled explanation or mock that does not claim integration
  success.
- `read-only live`: an authorized bounded read with no mutation.
- `approved live`: a real operation through the underlying capability after preview
  and explicit approval; it is not a configuration test.

Before a demonstration, state the mode, fixture, expected result, actions, and new
artifact destination. Resolve ambiguity and confirm that existing output will not be
overwritten. Afterward, compare actual with expected output, report discrepancies,
and show how to inspect the result.

Use only fictional, clearly labeled data. Never use real Ericsson customer,
employee, ticket, email, opportunity, project, or knowledge content in a showcase.
Reusable fixtures stay separate from generated output. Do not fake a successful
live integration when only simulation or synthetic execution occurred.

## Available showcase patterns

The [Ericsson onboarding facilitator showcase](../showcases/ericsson-capability-onboarding.md)
provides an end-to-end Jira route using `SYNTH-JIRA-DIGEST-001`, expected Markdown,
and a golden personalized summary. The
[Opportunity Visuals showcase](../showcases/opportunity-visuals.md) supplies richer
synthetic fixtures, audit manifests, golden visual artifacts, and visual inspection.
Reuse its principles, not its image-specific mechanics, for unrelated capabilities.

If an operation is interrupted or may have partially completed, inspect the target
before retrying and obtain a fresh approval for any remaining write. Record only a
sanitized checkpoint; never store source payloads or unredacted diagnostics.
