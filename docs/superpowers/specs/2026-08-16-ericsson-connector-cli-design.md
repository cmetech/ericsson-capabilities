# Ericsson connector command-line interface

**Status:** Approved for Wave 4, reconciled with the live post-Wave-3 connector
contracts on 2026-08-18. No implementation work may start until the existing
connector waves have satisfied the gates in this document.

**Audience:** Engineers implementing or reviewing Ericsson connector command
surfaces in OTTO, LOOP24, and neutral Hermes Agent.

**Post-read action:** An engineer can implement a new direct connector command
without duplicating connector behavior, weakening write controls, or changing
the natural-language experience.

## 1. Context

The Ericsson connectors are model tools first. In CLI and TUI conversations, a
user describes an outcome and the active agent selects a bounded Jira, GitLab,
Confluence, or ARM operation. This is the right experience for exploration,
reasoning across systems, and workflows.

Users migrating from SuperCLI also need a deterministic, model-free command
surface. They already know the domain nouns and operations, use shell help for
discovery, and often need stable JSON for scripts. Requiring those users to
translate every familiar operation into natural language would discard useful
muscle memory and make simple automation less predictable.

The goal is familiarity with a documented migration mapping, not drop-in
SuperCLI compatibility. OTTO and LOOP24 keep their stronger bounds, safer input
shapes, profile-scoped configuration, explicit mutation intent, and ambiguous
write handling even when those differ from SuperCLI.

### 1.1 Post-Wave-3 reconciliation (2026-08-18)

The implementation gate found 58 live connector operations, but three approved
public signatures no longer matched their schemas: GitLab merge-request listing
requires a project, `gitlab_inspect_ci` is a broad CI inspection rather than a
single-pipeline lookup, and `gitlab_create_branch` creates a ticket-derived
branch rather than an explicitly named branch. Four existing dry-run-shaped
admitted writes also express confirmed execution as `dry_run=false` instead of
exposing a connector schema `confirm` field.

The approved resolution preserves all 58 operations and adds two localized
GitLab operations before facade scaffolding:

- `gitlab_read_pipeline`, exposed as
  `gitlab pipeline view <project> <pipeline-id>`, returns bounded normalized
  metadata for one pipeline. Its exact result contains `project` with a
  positive integer `id` and bounded string `path`; the exact positive integer
  `pipeline_id`; bounded string `status`, `ref`, `sha`, `source`, and
  same-origin `web_url`; and present-but-nullable bounded timestamp strings
  `created_at`, `updated_at`, `started_at`, and `finished_at`. Raw payloads,
  users, variables, and jobs are excluded;
- `gitlab_create_named_branch`, exposed as
  `gitlab branch create <project> <branch> <ref>`, reuses the connector's
  existing ref validation, project resolution, branch reconciliation, error
  classification, and ambiguous-write policy. It resolves the requested ref to
  an exact commit identity. A pre-existing named branch is reusable only when
  its commit matches that identity; a mismatch returns safe `conflict` without
  mutation. Creation sends the resolved commit identity, not a movable ref
  name. After a mutating dispatch or already-exists race, failure to prove that
  exact identity returns `write_ambiguous`;
- `gitlab_inspect_ci` is exposed accurately as
  `gitlab ci inspect <project>`; and
- the existing ticket-derived `gitlab_create_branch` is exposed as
  `gitlab branch create-ticket <project> <ticket-key> --summary <text>`.

The merge-request list path is corrected to require `<project>`. The resulting
surface contains 60 operations: Jira 15, GitLab 30, Confluence 9, and ARM 6.
This is an approved compatibility prerequisite, not schema drift that should
stop Wave 4B. Any other added, removed, or renamed operation remains a stop
condition.

## 2. Goals and non-goals

### Goals

- Provide the same domain command grammar under the `otto` and `loop24`
  executables.
- Make help and migration guidance available before a standalone connector is
  enabled.
- Support both reads and writes without involving a model.
- Require exactly one of `--dry-run` or `--confirm` for every write.
- Reuse the same connector application executor, configuration, secrets,
  transport, bounds, error taxonomy, and ambiguity policy used by model tools.
- Provide concise human output and a versioned JSON contract.
- Publish a complete, reviewed mapping from the pinned SuperCLI inventory to
  supported commands and explicit gaps.
- Preserve natural-language CLI, TUI, gateway, and workflow behavior.

### Non-goals

- Existing SuperCLI scripts do not run unchanged.
- SuperCLI's raw vendor payloads, unsafe passthroughs, flag spellings, and exit
  codes are not compatibility contracts.
- The direct CLI does not perform agent reasoning or implicit multi-step
  orchestration.
- The first release does not add connector widgets, keybindings, or a second
  TUI command parser.
- The facade does not implement REST clients, authentication, retries,
  pagination, or connector business logic.
- The facade does not expose an arbitrary `invoke TOOL JSON` escape hatch.

## 3. Wave placement and delivery gates

The command surface is an adapter over completed connector contracts. It must
not become a dependency of connector implementation.

```text
Wave 1: shared transport
          |
Wave 2: shared amendment, Jira canary, Confluence/ARM registration
          |
Wave 3: GitLab coverage + Confluence operations + ARM operations
          |
Wave 4A: neutral Hermes owner-bound plugin command port
          |
Wave 4B: Ericsson direct connector CLI + SuperCLI migration mapping
          |
Separate delivery: source verification -> Hermes base -> every brand -> clean OTTO
```

Wave 4A starts only after all of the following are true:

1. The shared transport branch is merged to the Ericsson capability source.
2. Wave 2 is merged and Jira has validated the shared connector foundation.
3. All three Wave 3 branches are merged and their full source test gate passes.
4. The generic Hermes credential-storage work is merged to neutral Hermes
   `base`, so direct commands resolve protected connector secrets through the
   approved profile authority.
5. The public connector tool names and input schemas for Jira, GitLab,
   Confluence, and ARM are stable for the release.

Wave 4B starts only after the Wave 4A host port is reviewed, merged to neutral
Hermes `base`, and its full Hermes test gate is green. This makes the Ericsson
facade a consumer of a settled public host contract instead of a co-author of
private admission behavior.

Wave 4 changes no Wave 1-3 branch or task. Wave 4A branches from neutral Hermes
`base`; Wave 4B branches from the post-Wave-3 Ericsson source `main`. Neither
session merges its own work.

Vendoring is not part of the Wave 4 source implementation session. After the
source branch is reviewed and merged, a separately authorized delivery step
vendors that exact source revision onto neutral Hermes `base`, discovers every
brand, merges `base` into each brand, regenerates and checks each overlay,
verifies shared bytes, and finishes clean on OTTO.

## 4. User-facing command grammar

The brand executable is the only branded token. Everything after it is
identical:

```text
<brand> <domain> <resource> <verb> [identifiers] [options]
```

The initial top-level domains are:

```text
otto jira ...          loop24 jira ...
otto gitlab ...        loop24 gitlab ...
otto confluence ...    loop24 confluence ...
otto arm ...           loop24 arm ...
```

Domain nouns and verbs are curated for humans. They are not mechanically
exposed Python names. Reads consistently prefer `get`, `list`, `search`, and
`show`. Writes use the domain action: `comment`, `transition`, `assign`,
`create`, `update`, `approve`, `merge`, `retry`, `deploy`, or `delete`.

Representative commands are:

```bash
otto jira issue get ERIC-123
otto jira issue search --jql 'project = ERIC AND status != Done' --limit 20 --json

otto jira issue comment ERIC-123 --body-file comment.md --dry-run
otto jira issue comment ERIC-123 --body-file comment.md --confirm

loop24 gitlab mr show group/project 42
loop24 gitlab pipeline view group/project 918
loop24 gitlab ci inspect group/project --branch-spec RECENT
loop24 gitlab branch create-ticket group/project ERIC-123 --summary 'repair login' --dry-run
loop24 gitlab branch create group/project release/1.2 main --dry-run
loop24 gitlab pipeline retry group/project 918 --confirm

otto confluence page update 12345 --body-file page.md --dry-run
otto arm artifact deploy release-local/team/app.tgz --file app.tgz --confirm
```

Common flags are deliberately small:

- `--json` selects the stable machine envelope.
- `--dry-run` requests a non-mutating preview of a write.
- `--confirm` authorizes one exact write invocation.
- `--body-file`, `--file`, and stdin carry large or structured content without
  placing it in process listings or shell history.

The active product profile is authoritative. Users switch profiles through the
existing profile commands; connector commands do not add a second profile
selector or cross-profile lookup.

## 5. Architecture

### 5.1 Always-visible facade

One bundled Ericsson backend plugin owns the four top-level command trees. It
is runtime infrastructure, performs no network requests, and is available in
every branded profile. It uses the existing plugin CLI registration API to
create real argparse subcommands.

The facade owns only:

- public command names and help;
- parsing and local input acquisition;
- command-to-operation descriptors;
- read/write classification;
- human and JSON rendering;
- stable exit-code selection; and
- SuperCLI migration metadata.

The facade is always loaded so `otto jira --help` works before Jira is enabled.
It never imports a disabled connector's client or operation modules. An
execution attempt against a disabled connector returns bounded enablement and
configuration guidance instead of an argparse `invalid choice` error.

The facade reserves `jira`, `gitlab`, `confluence`, and `arm` as one owned
command family. Registration collisions fail closed; a connector or unrelated
plugin cannot partially replace one of these trees.

### 5.2 Curated command descriptors

Each leaf command has a declarative descriptor containing:

- public command path;
- connector and canonical operation identity;
- read or write classification;
- positional and optional argument bindings;
- file/stdin bindings;
- human rendering hint;
- migration-map identity; and
- support status.

Canonical operation identities are public connector tool names
(`jira_get_issue`, `gitlab_read_merge_request`, `gitlab_read_pipeline`, and so
on). Task 1A adds the two reconciled GitLab names to the connector before the
facade descriptors are created. This avoids a second internal namespace and
lets descriptor/schema drift fail mechanically.

Descriptors are curated because a good domain CLI cannot be generated blindly
from JSON Schema. Source validators nevertheless compare descriptors with the
canonical tool schemas. A removed operation, missing required input, unhandled
write, or stale migration row fails the source test gate.

### 5.3 One application executor

Every connector exposes one application-level executor used by both adapters:

```text
natural-language/model-tool adapter --+
                                     +--> connector executor --> bounded result
direct command adapter --------------+
```

The executor owns schema validation, profile configuration resolution, opaque
secret access, readiness, connector operations, shared transport policy,
result normalization, error translation, and write-ambiguity behavior.

The logical port is:

```text
execute ConnectorCommandRequest -> ConnectorCommandResult

ConnectorCommandRequest:
  connector identity
  canonical operation identity
  validated arguments
  read | dry-run | confirmed authority
  active profile generation
  unique invocation identity

ConnectorCommandResult:
  success or connector-local error category
  bounded normalized data
  warnings and truncation metadata
  remediation
  write outcome: not-applicable | previewed | completed | ambiguous
```

An enabled connector registers its executor under its connector identity. The
registration stores a callable and immutable metadata only; it never caches a
configuration accessor, resolved secret, client, or profile generation. The
executor resolves fresh profile configuration inside each invocation. Runtime
lookup is order-independent: if no enabled executor is registered, the facade
reports the connector as disabled or unavailable.

The model-tool adapter proves host approval where required. The direct command
adapter proves explicit local CLI intent through a genuine active Wave 4A
invocation. Neither adapter can supply a plain JSON field that impersonates the
other's authority. The direct CLI must not manufacture or reuse a model-tool
admission token, and the model adapter must not construct or accept an
application-command invocation.

Planning evidence confirmed that the existing plugin CLI registration surface
can build the argparse trees but cannot preserve these cross-plugin authority
boundaries by itself. Wave 4A therefore adds a small generic, owner-bound local
application-command port on neutral Hermes `base`. The port binds caller,
provider, operation, canonical arguments, active connector-configuration
fingerprint, invocation identity, and single-use command mode. It is separate
from model-tool admission and does not make that private token constructible.
Wave 4B consumes only this public port. Connector-specific code must not reach
into private Hermes admission internals as a shortcut.

At the direct adapter boundary, the host mode is normalized into the owning
connector's existing argument contract only after the genuine invocation has
been validated. Reads add no write intent. Dry-run mode sets `dry_run=true`.
Confirmed mode sets `confirm=true` when the connector schema owns both intent
fields. For the existing dry-run-shaped admitted writes `jira_add_comment`,
`gitlab_create_branch`, `gitlab_commit_changes`, and
`gitlab_create_merge_request`, and for the new compatible dry-run-shaped
`gitlab_create_named_branch`, confirmed mode sets `dry_run=false` only after
the owner-bound, caller/provider/operation/arguments/profile-bound, single-use
host confirmation authority has been proved. This normalization does not alias
the two Hermes authority types or weaken the CLI's exactly-one-intent rule.
Both adapters converge on the connector application executor only after their
separate checks.

### 5.4 TUI extension hooks are complementary

Hermes' wrapper-CLI hooks support extra widgets, keybindings, layout changes,
styles, and wrapper-owned slash commands. They are not the terminal subcommand
boundary for this feature. Wave 4 uses plugin CLI registration and leaves the
TUI natural-language-first. A later command palette may consume the same
descriptors, but it is not required for migration.

## 6. Write authority and ambiguity

Every write parser contains a required mutually exclusive intent group.
Supplying neither flag or both flags is a local usage error. Rejection happens
before connector configuration, secret resolution, file upload, or network
activity.

`--dry-run`:

- executes the connector's reviewed preview path;
- cannot issue a mutating request;
- may perform bounded reads needed to render a truthful preview; and
- exits successfully only when the preview is complete.

For named-branch preview, those bounded reads include project resolution,
requested-ref-to-commit resolution, and target-branch lookup. The preview must
distinguish create, exact-identity reuse, and pre-existing identity conflict
without issuing a mutating request.

`--confirm`:

- authorizes exactly one connector, operation, active profile generation, and
  canonical argument digest;
- is single-use and cannot become a saved default;
- does not authorize different arguments after parsing;
- does not turn an uncertain write into a retryable write; and
- does not bypass connector permission, capacity, or validation checks.

There is no `--yes` alias, environment-variable confirmation, configuration
default, or interactive fallback after omission. A CLI-exposed write must
support both reviewed dry-run and confirmed execution paths. This does not
require retrofitting a connector-level `confirm` field where a dry-run-shaped
write represents those paths as `dry_run=true` and `dry_run=false`:
the genuine Wave 4A mode is the confirmation authority, and only the provider
adapter performs that normalization. A write without both behavioral paths is
listed in the migration map as not yet supported.

The direct CLI preserves `write_ambiguous` as a distinct terminal outcome. It
reports reconciliation guidance and never silently retries the write.

## 7. Output and exit-code contract

Human output is the default. It is bounded, strips unsafe terminal control
sequences, distinguishes warnings from results, and includes remediation.

`--json` writes one versioned envelope to stdout and nothing decorative:

```json
{
  "schema_version": "ericsson.connector-cli/v1",
  "ok": true,
  "connector": "jira",
  "operation": "jira_get_issue",
  "mode": "read",
  "data": {},
  "warnings": [],
  "meta": {}
}
```

Diagnostics and logs go to stderr. JSON mode emits no ANSI color, spinner,
banner, approval prompt, or model prose. The stable contract is the bounded
connector envelope, not raw Jira, GitLab, Confluence, or Artifactory payloads.

Exit codes are:

- `0`: successful read, preview, or confirmed write;
- `2`: command usage, schema, input, or mutation-intent error;
- `3`: connector disabled, unsupported, unavailable, or not configured;
- `4`: classified remote or connector operation failure; and
- `5`: ambiguous write outcome requiring reconciliation.

The JSON error object retains the more specific connector category and
remediation. Signal termination follows the operating system convention rather
than this table.

## 8. Disabled connectors and readiness

Help is side-effect free and available for every shipped connector regardless
of enablement. It does not load credentials or probe a remote service.

Execution resolves readiness in this order:

1. connector shipped and supported;
2. connector enabled for the active profile;
3. required settings and protected secrets present;
4. authentication accepted;
5. permission adequate for the requested operation; and
6. bounded operation execution.

Failure reports the first unproved requirement with an exact branded command
or settings action. Saved credentials never imply enablement. A direct command
starts a fresh process, so it sees the current profile generation immediately;
existing natural-language conversations still require a new conversation after
plugin enablement changes.

## 9. SuperCLI migration mapping

One versioned, machine-readable mapping is the authority. Human migration docs
are generated from it and checked for drift.

Every pinned SuperCLI command receives one disposition:

- `equivalent`: same user outcome within the bounded connector contract;
- `renamed`: supported with a different command or flag name;
- `safer-different`: supported with deliberate safety or data-shape changes;
- `not-yet-supported`: planned but unavailable in this release; or
- `no-equivalent`: deliberately excluded, with rationale and alternative.

Each row records the SuperCLI command, branded replacement template, flag
translations, output differences, write behavior, connector wave, and notes.
Examples in documentation are generated from verified rows. Guessed SuperCLI
syntax is forbidden.

Unsafe differences remain explicit. Examples include bounded Jira field maps
instead of arbitrary raw field JSON, Markdown-to-storage conversion instead of
unescaped Confluence storage passthrough, and confirmed writes that preserve
ambiguous-outcome refusal.

## 10. Security invariants

1. The facade contains no HTTP client or connector endpoint implementation.
2. Secrets never appear in command arguments, output, migration files, logs,
   descriptors, or error text.
3. All protected values come from the active profile's opaque secret authority.
4. Help, local validation, and missing-intent failures perform no network I/O.
5. Every write requires exactly one explicit intent flag.
6. CLI authority is genuine, active, single-use, and argument-bound; it cannot
   impersonate model-tool approval or be serialized into arguments/results.
7. Dry-run cannot mutate; confirm cannot retry an ambiguous write.
8. Large content is bounded and acquired from reviewed file/stdin inputs.
9. Human rendering removes terminal control sequences; JSON stdout remains
   machine-clean.
10. Disabled connectors remain disabled. The facade provides guidance, not an
    enablement bypass.
11. Connector-local errors remain connector-local at the public boundary.
12. Natural-language, direct CLI, and workflow adapters cannot diverge in
    transport, validation, or operation semantics.

## 11. Verification strategy

Wave 4 must include:

- parser and help snapshots for OTTO and LOOP24;
- help and remediation tests while each connector is disabled;
- descriptor-to-tool-schema and write-coverage drift tests;
- parity tests proving equivalent CLI and model-tool inputs reach the same
  normalized application request and result after separate authority checks;
- tests that neither/both write flags fail before configuration and network
  access;
- dry-run no-mutation tests, argument-bound single-use confirm tests, and
  dry-run-shaped `dry_run=false` normalization tests that require genuine host
  mode;
- ambiguous-write, cancellation, deadline, retry, and capacity regressions;
- JSON schema snapshots, stdout/stderr separation, exit-code mapping, and
  terminal-control sanitization;
- profile-generation and secret-redaction tests;
- complete SuperCLI inventory disposition and generated-doc drift tests;
- architecture tests proving the facade has no connector client or HTTP
  implementation; and
- the complete Ericsson source test gate before merge.

After source merge, delivery verification additionally proves the exact source
revision is vendored on neutral Hermes `base`, every declared brand inherits
it, brand generation/check gates pass, shared bytes match, and the final OTTO
worktree is clean.

## 12. Alternatives considered

### One generic connector command

`<brand> connector <service> <operation>` is compact and largely
schema-generatable, but it exposes tool-oriented names and gives migrating
users a weaker domain experience.

### Commands registered only by each standalone connector

This gives excellent ownership and domain grammar, but disabled plugins do not
load. A new user cannot discover `jira --help` until after completing the setup
that help should explain.

### Wrapper-TUI customization

The wrapper hooks are appropriate for visual panels, keybindings, layout, and
slash commands. They do not provide the model-free shell command contract,
stable JSON, exit codes, or pre-enablement discoverability required here.

The selected design combines domain-shaped commands with an always-visible,
no-network facade and one shared connector application executor.

## 13. Reference extension contracts

- Hermes **Extending the CLI** documents wrapper-TUI widgets, keybindings,
  layout, styles, and wrapper-owned slash commands. Those hooks are
  complementary and are not the Wave 4 terminal subcommand seam:
  <https://hermes-agent.nousresearch.com/docs/developer-guide/extending-the-cli>
- The Hermes plugin developer guide documents plugin CLI command registration,
  which creates real top-level argparse commands and is the selected command
  registration seam:
  <https://hermes-agent.nousresearch.com/docs/developer-guide/plugins>
