# Ericsson Capability Onboarding

This documentation supports three concrete jobs:

- a capability maintainer can add, change, or remove an onboarding entry and
  regenerate, validate, and vendor it;
- a pilot facilitator can demonstrate onboarding without credentials, live writes,
  or confidential data;
- a product owner can validate Windows resume behavior from a release installation
  and return precise, secret-free evidence.

The bundled `onboard-ericsson-capabilities` skill is the single training and
onboarding entry point for the Ericsson capabilities delivered with Co-Worker. It
starts from a user's goal, recommends at most two relevant capabilities, separates
product maturity from current profile readiness, and loads detailed guidance only
after a route is selected. Domain work remains with the selected skill, plugin, MCP
server, or workflow.

The router is available in every profile. There is no Ericsson-specific runtime
toggle or disabled-by-default delivery contract. Platform requirements, protected
settings, interactive sign-in, permissions, and dependencies still determine
whether an individual capability is ready.

## Architecture and source precedence

The source-controlled capability entries are the education contract. A deterministic
builder compiles their small routing fields into the committed `catalog.json`; the
router loads that compact catalog for discovery and then one focused entry plus only
the policies needed for the selected route. The catalog is generated, never edited
by hand.

When facts disagree, use this order:

1. Implementation and runtime registration determine whether behavior exists.
2. The Ericsson manifest determines what is packaged.
3. Flow metadata determines porting maturity and historical coverage.
4. Capability entries determine user-facing education and demonstration guidance.
5. The generated catalog compiles those facts.
6. Current runtime inspection determines readiness and supersedes saved readiness.

A contradiction is a validation failure. Do not resolve it by guessing in the
conversation.

## Documentation map

- [Authoring and catalog maintenance](authoring.md) — add, change, remove,
  regenerate, validate, and deliver an entry.
- [Safety and demonstrations](safety-and-demonstrations.md) — configuration
  categories, secret handling, readiness order, and synthetic showcase policy.
- [Artifacts and troubleshooting](artifacts-and-troubleshooting.md) — destinations,
  inspection, failure classification, partial effects, and resume records.
- [Mock sessions](mock-sessions.md) — representative conversations and facilitator
  pass criteria.
- [Test strategy and results](test-strategy-and-results.md) — baseline pressure
  behavior, completed model evidence, deterministic checks, and known limitations.
- [Windows resume release validation](windows-resume-release-validation.md) —
  product-owner acceptance steps for the Windows-specific persistence backend.
- [Pilot facilitator showcase](../showcases/ericsson-capability-onboarding.md) — the
  end-to-end fictional Jira demonstration plus shorter Opportunity Visuals and
  unsupported-platform paths.

## Scope and limitations

The skill teaches, checks, demonstrates, summarizes, and resumes. It does not
reimplement the underlying capability, obtain credentials, invent access-request
procedures, install software without approval, or use a live write as a readiness
test. Pseudonymization is retained only as a
`not-supported-no-port-planned` historical tombstone. Re-Identification has no
runnable implementation because its required protected mapping capability is not
available.

Resume state is opt-in, sanitized, and isolated beneath the active profile home.
Portable schema/dispatch tests and the macOS/Linux backend are locally verified. The
Windows backend source and portable boundary are approved for native acceptance;
the product owner's Windows release result remains pending until the Windows
checklist is completed. A pending native result is never reported as a pass.

## Delivery path

Shared capability work is authored and verified here first. After explicit delivery
approval, commit the source, vendor that exact source revision into neutral Hermes
`base`, discover every brand from `brands/*.json`, merge `base` into each brand,
regenerate and check each branding overlay, and verify byte identity. Never author a
shared Ericsson capability directly on a brand branch.
