# Glean MCP Defaults Design

**Date:** 2026-07-16

**Status:** Approved design; implementation not started

**Source repository:** `ericsson-capabilities`

**Delivery target:** Manifest-driven vendored snapshot in `hermes-agent`

## Summary

Ship the Ericsson Glean MCP connection disabled by default and preconfigure its
shared, non-secret endpoint. The user's Glean API token remains unset and must
still be entered through the protected Keys surface.

New profiles receive a complete but disabled `glean` MCP entry. Existing
profiles retain every explicit user choice: an existing URL is never
overwritten, and an existing enabled or disabled state is never changed. An
existing Glean entry whose URL is missing or blank receives only the shared
default URL.

## Goals

- Prevent Glean from connecting automatically before the user has configured
  their credential and intentionally enabled it.
- Use
  `https://be.everyday-assistant.ericsson.net/mcp/EEA-KIRO-MCP` as the shared
  Ericsson endpoint.
- Keep `GLEAN_API_TOKEN` blank, secret, and user-specific.
- Remove the obsolete requirement for each user to configure
  `GLEAN_MCP_URL`.
- Upgrade existing profiles without overwriting a customized URL or changing
  an intentional enablement choice.
- Keep the Ericsson source, onboarding catalog, documentation, vendored
  Hermes snapshot, and both branded deliverables synchronized.

## Non-goals

- Supplying, discovering, validating, or migrating a user's Glean token.
- Enabling Glean automatically after a token is added.
- Testing the live Ericsson endpoint from development or CI.
- Overwriting an existing non-blank URL, even if it differs from the shared
  default.
- Re-disabling a server that a user intentionally enabled.
- Changing default behavior for any other MCP server.

## Chosen approach

The source MCP fragment will declare:

```yaml
mcp_servers:
  glean:
    enabled: false
    url: https://be.everyday-assistant.ericsson.net/mcp/EEA-KIRO-MCP
    headers:
      Authorization: "Bearer ${GLEAN_API_TOKEN}"
```

`GLEAN_MCP_URL` will be removed from the Ericsson manifest and onboarding
configuration entry. `GLEAN_API_TOKEN` remains a password-classified Keys
entry and the only user-specific Glean configuration requirement.

The Hermes baked-capability seeder will retain its existing missing-server
merge behavior and add one narrow managed-default rule derived from the
vendored fragment:

- when `mcp_servers.glean` is absent, copy the full fragment entry, including
  `enabled: false`;
- when the entry exists and `url` is missing, `null`, or an empty/whitespace
  string, copy only the fragment's non-empty URL;
- when the entry has a non-blank URL, leave it unchanged;
- when the entry already exists, never add, remove, or change `enabled`;
- never replace headers, tokens, commands, transports, or other user fields.

The same behavior will be applied to the generic bundle-staging path so the
source contract remains consistent if Ericsson capability-set staging is used
outside the current baked delivery model. The rule is structural rather than
hostname-hardcoded in Python: staging backfills a missing/blank URL only when
the source fragment supplies a non-empty URL. No token or secret value is
written by staging.

## Alternatives considered

### Seed only new profiles

Adding `enabled: false` and the URL only to the MCP fragment is the smallest
change. It does not satisfy the requirement to repair existing Glean entries
whose URL is blank.

### Prepopulate `GLEAN_MCP_URL` through Keys or `.env`

This preserves the old placeholder but treats a shared non-secret endpoint as
per-user environment configuration. It also makes ownership and upgrade
behavior ambiguous. Product configuration should live in `config.yaml`, while
the protected environment remains for the user-specific token.

### Narrow missing-field backfill — selected

The fragment remains the source of the default and staging fills only an
empty URL field. This supports new and existing profiles while preserving
customization and explicit enablement.

## Upgrade and ownership rules

| Existing state | Result |
|---|---|
| No `glean` entry | Add disabled entry with default URL and unresolved token placeholder |
| Entry with missing URL | Add only the default URL |
| Entry with blank URL | Replace only the blank URL with the default |
| Entry with customized URL | Preserve it byte-for-value |
| Entry with `enabled: true` | Preserve `true` |
| Entry with `enabled: false` | Preserve `false` |
| Entry without `enabled` | Preserve the absence; do not infer or write a new choice |
| Blank or missing token | Remain blank/missing; Glean is not ready |

The seeder must remain idempotent. Running it repeatedly after the first
backfill produces no further configuration changes.

## Documentation and onboarding

Update the configuration guide and Glean onboarding entry to explain that:

- the Ericsson endpoint is supplied by the product;
- Glean ships disabled until the user enables it;
- the user must configure only `GLEAN_API_TOKEN` through protected Keys;
- configured token presence alone does not prove readiness;
- readiness requires intentional enablement, connection/tool discovery,
  authentication, permissions, and a narrow read-only search.

Regenerate the onboarding catalog after changing the entry. Historical design
and implementation-plan records are not rewritten.

## Test strategy

Write the source expectation first and observe it fail. Coverage must assert:

- the source MCP fragment contains the exact URL and `enabled: false`;
- `GLEAN_MCP_URL` is absent from the manifest and generated onboarding
  catalog, while `GLEAN_API_TOKEN` remains required and secret;
- a new profile receives the disabled Glean entry with the default URL;
- an existing missing or blank URL is backfilled;
- an existing custom URL is preserved;
- existing `enabled: true`, `enabled: false`, and absent `enabled` states are
  preserved;
- headers and other existing fields are not overwritten;
- repeated seeding is idempotent;
- the vendored MCP fragment and manifest match the exact source revision;
- branding generation and relevant capability-staging tests pass on every
  discovered brand.

Tests use temporary homes and synthetic configuration only. They do not
connect to the live endpoint or contain a token value.

## Delivery

1. Implement and test in `ericsson-capabilities`.
2. Commit the source change.
3. Vendor that exact source commit onto neutral `hermes-agent/base`.
4. Run the staging, manifest, onboarding, and vendor consistency tests.
5. Discover brands from `brands/*.json`, merge `base` into each, and run each
   brand's generator write/check gates and relevant tests/builds.
6. Verify the shared manifest, MCP fragment, onboarding entry, and generated
   catalog bytes match across `base`, `otto`, and `loop24`.
7. Finish on `otto` without pushing or releasing unless separately approved.

## Acceptance criteria

- A fresh profile displays Glean as configured with the Ericsson endpoint but
  disabled.
- Enabling Glean remains an explicit user action.
- The API token remains blank until the user enters it through protected Keys.
- An upgrade fills an empty Glean URL but never changes a non-empty URL.
- An upgrade never changes an existing Glean enablement state.
- No other MCP server's seeding behavior changes.
- Source and both branded deliverables pass their required verification gates.
