# Ericsson Connector CLI and SuperCLI Migration Mapping Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` task by task. Use `superpowers:test-driven-development` for every behavior change and `superpowers:verification-before-completion` before reporting success.

**Goal:** Add model-free, domain-shaped Jira, GitLab, Confluence, and ARM commands to both OTTO and LOOP24, backed by the same connector application executors as model tools, with exact `--dry-run`/`--confirm` write intent and a complete generated SuperCLI 0.14.1 migration map.

**Architecture:** An always-loaded backend plugin, `ericsson-connector-cli`, owns four top-level argparse trees and all parsing/rendering. It has no HTTP client, configuration descriptor, credentials, or connector imports. Each enabled standalone connector registers its own existing tool operations with Hermes' owner-bound application-command port and executes them through a new connector-local `application.py`; its model-tool handler uses that same executor after model admission, while the direct CLI provider uses it after host command authority. Machine-readable curated descriptors bind public command paths to canonical operations and are checked against the live tool schemas. A versioned YAML inventory maps every extracted SuperCLI 0.14.1 service command to a supported replacement or explicit gap and generates the human migration guide.

**Tech Stack:** Python 3.11+, argparse through `ctx.register_cli_command`, Wave 4A `PluginContext.register_application_commands` / `invoke_application_command`, PyYAML already used by the repo, pytest through the source `.venv`.

**Spec:** `docs/superpowers/specs/2026-08-16-ericsson-connector-cli-design.md`

**Repo:** `ericsson-capabilities` (this repo), post-Wave-3 `main`.

## Reconciliation Note — 2026-08-18

The post-Wave-3 gate found 58 existing operation ids, but three approved public
signatures were stale: merge-request listing requires a project,
`gitlab_inspect_ci` has no pipeline id and is a broad CI inspection, and
`gitlab_create_branch` derives a ticket branch rather than accepting an
explicit branch name. Four existing dry-run-shaped admitted writes expose
`dry_run` but no connector-schema `confirm` field.

The approved resolution preserves all existing capability and adds two bounded
GitLab operations in Task 1A: `gitlab_read_pipeline` for one pipeline's
normalized metadata and `gitlab_create_named_branch` for an explicit branch and
ref. The existing CI inspection and ticket-derived branch creation receive
accurate public paths, and merge-request listing makes project positional. The
facade therefore starts in Task 1B against 60 operations: Jira 15, GitLab 30,
Confluence 9, and ARM 6.

Direct write intent remains exact and fail-closed at the CLI. The owning
provider validates a genuine Wave 4A invocation before translating host mode to
the connector's argument shape. Dry-run mode applies `dry_run=True`; confirmed
mode applies `confirm=True` where the schema supports it, or `dry_run=False` for
the reviewed dry-run-shaped writes. This avoids a broad connector-schema
retrofit while keeping model `PluginToolAdmission` and direct application
authority separate. Any schema drift beyond this documented reconciliation is
still a stop condition.

## Global Constraints

- **Wave gate:** do not start until Jira, GitLab, Confluence, and ARM Wave 2-3 work is merged to source `main`, its full test gate is green, Hermes credential storage is merged to neutral `base`, and Wave 4A's application-command port is merged and green on neutral `base`.
- **Source-first:** this plan stops at an `ericsson-capabilities` branch. Do not vendor, merge Hermes `base`, restamp brands, release, or merge this branch.
- **No Wave 1-3 edits:** branch from the post-Wave-3 `main`; do not reopen old feature branches or modify their plans/prompts.
- **Always-visible facade:** `ericsson-connector-cli` is a manifest string entry (`kind: backend`). Jira, GitLab, Confluence, and ARM remain standalone object entries with `enabled: false`.
- **No network in facade:** architectural tests must reject imports of connector packages, `httpx`, `requests`, `urllib`, shared transport, auth, clients, or operations under `plugins/ericsson-connector-cli/**`.
- **One application executor per connector:** model tools and direct CLI converge before configuration resolution and operation dispatch. No duplicated error translation, readiness, redaction, result normalization, client creation, or operation call.
- **Authority separation:** model writes still require genuine `PluginToolAdmission`; shell writes arrive only as genuine Wave 4A application-command invocations. Neither adapter may construct or accept the other's authority.
- **Fresh ownership:** the connector provider resolves `ctx.configuration()` inside every invocation. The facade never sees a configuration object, secret, client, or connector module.
- **Writes require exactly one intent:** every mutating leaf parser uses a required mutually exclusive group containing only `--dry-run` and `--confirm`. Omission and both-flags fail with exit 2 before file reads, configuration, provider lookup, or network activity.
- **No write without preview:** expose a write only when the connector has both a reviewed non-mutating preview and confirmed execution path. The CLI always requires exactly one intent. The provider validates the genuine host invocation before applying `dry_run=True`, `confirm=True`, or the documented dry-run-shaped confirmed normalization `dry_run=False`; no connector-level `confirm` retrofit is required for that bounded set.
- **Ambiguity survives:** `write_ambiguous` maps to exit 5 with reconciliation guidance. `--confirm` never enables retry of an uncertain write.
- **No secrets on argv:** do not accept tokens, passwords, certificate contents, or connector origins as command options. The active Hermes profile is authoritative. Bodies use bounded files or stdin; ARM deploy passes a local path to the connector without reading bytes in the facade.
- **Curated UX, schema-checked:** descriptors explicitly list every command path and binding. A test compares each descriptor's operation and target argument set against the final live `SCHEMAS`; stale/missing/extra bindings fail.
- **Stable output:** human output is bounded and terminal-sanitized. `--json` emits exactly one `ericsson.connector-cli/v1` envelope on stdout, no ANSI/log/banner/spinner text. Diagnostics go to stderr.
- **Pinned migration evidence:** mapping authority is SuperCLI 0.14.1, commit `6645cd0bb56cc54aa4f1d49095490832c9528dbb`, binary SHA-256 `72ce9d9ad14b451b53a7f0f06786d75336a302562a8ed6d0dbafc2cb7657cc6a`. Do not guess commands or flags.
- **Onboarding contract:** update implementation, manifest/runtime registration, user docs, natural-language coexistence, reads/writes/approvals/outputs, migration guidance, generated onboarding catalog, and tests in the same branch.

## Decisions Taken

| # | Decision | Rationale |
|---|---|---|
| D1 | One backend facade owns all four top-level names | Help remains visible while standalone connectors are disabled, and command collisions fail atomically. |
| D2 | Add connector-local `application.py` modules | Pulls common execution/error behavior behind both adapters without moving domain code into the facade or Hermes core. |
| D3 | Canonical operation ids remain connector tool names | Task 1A adds the two approved missing GitLab names before facade work; schemas, provider registration, model handlers, CLI descriptors, and mapping rows then reconcile mechanically without a second internal namespace. |
| D4 | Public command paths retain SuperCLI's domain nouns where safe | Migration muscle memory matters. Differences are documented rather than hidden behind an artificial compatibility claim. |
| D5 | Positional identifiers, options for filters/settings | `issue get ERIC-123` and `mr show group/project 42` are concise; optional filters remain explicit and shell-discoverable. |
| D6 | No `--profile` flag | Existing brand profile selection is the single authority; adding another selector creates cross-profile secret and freshness risks. |
| D7 | No literal body option for write prose | `--body-file PATH` and `--body-file -` avoid quoting damage and keep large prose out of process listings/history. |
| D8 | JSON error envelopes are emitted even on nonzero exit | Scripts receive stable category/remediation while the exit code remains useful to shell control flow. |
| D9 | Migration mapping covers the complete pinned inventory, not only implemented commands | A migration document is trustworthy only when absence is explicit. |

## Reconciled Public Command Map

Each row is a curated descriptor. Identifiers shown in angle brackets are positional. All remaining final schema properties are explicit long options with hyphens replacing underscores; required schema properties remain required. `--json` is output selection and never enters connector arguments. Writes also add the required intent group.

The table has exactly 60 rows: Jira 15, GitLab 30, Confluence 9, and ARM 6.

| Public path | Canonical operation |
|---|---|
| `jira issue mine` | `jira_my_tickets` |
| `jira issue search` | `jira_search_issues` |
| `jira issue get <key>` | `jira_get_issue` |
| `jira issue comment <key> --body-file <path|->` | `jira_add_comment` |
| `jira field list` | `jira_list_fields` |
| `jira project get <project>` | `jira_get_project` |
| `jira transition list <key>` | `jira_list_transitions` |
| `jira user search-assignable <project>` | `jira_search_assignable_users` |
| `jira issue transition <key> <transition-id>` | `jira_transition_issue` |
| `jira issue assign <key> <assignee>` | `jira_assign_issue` |
| `jira issue update <key>` | `jira_update_fields` |
| `jira issue label <key> <add|remove> <label>...` | `jira_manage_labels` |
| `jira issue create <project> <issue-type> --summary <text>` | `jira_create_issue` |
| `jira link-type list` | `jira_list_link_types` |
| `jira issue link <inward-key> <outward-key> <link-type>` | `jira_link_issues` |
| `gitlab project resolve <project>` | `gitlab_resolve_project` |
| `gitlab group project-list <group>` | `gitlab_list_group_projects` |
| `gitlab commit list <project>` | `gitlab_list_commits` |
| `gitlab commit show <project> <sha>` | `gitlab_read_commit` |
| `gitlab commit comment-list <project> <sha>` | `gitlab_list_commit_comments` |
| `gitlab commit discussion-list <project> <sha>` | `gitlab_list_commit_discussions` |
| `gitlab mr list <project>` | `gitlab_list_merge_requests` |
| `gitlab mr commit-list <project> <iid>` | `gitlab_list_merge_request_commits` |
| `gitlab mr discussion-list <project> <iid>` | `gitlab_list_merge_request_discussions` |
| `gitlab repository tree <project>` | `gitlab_list_repository_tree` |
| `gitlab file show <project> <path>` | `gitlab_read_file` |
| `gitlab mr show <project> <iid>` | `gitlab_read_merge_request` |
| `gitlab pipeline list <project>` | `gitlab_list_pipelines` |
| `gitlab pipeline view <project> <pipeline-id>` | `gitlab_read_pipeline` |
| `gitlab ci inspect <project>` | `gitlab_inspect_ci` |
| `gitlab branch create <project> <branch> <ref>` | `gitlab_create_named_branch` |
| `gitlab branch create-ticket <project> <ticket-key> --summary <text>` | `gitlab_create_branch` |
| `gitlab commit create <project> <branch>` | `gitlab_commit_changes` |
| `gitlab mr create <project> <source-branch> <target-branch> --title <text>` | `gitlab_create_merge_request` |
| `gitlab job log <project> <job-id>` | `gitlab_job_log` |
| `gitlab mr note <project> <iid> --body-file <path|->` | `gitlab_create_mr_note` |
| `gitlab mr discussion-reply <project> <iid> <discussion-id> --body-file <path|->` | `gitlab_reply_to_discussion` |
| `gitlab mr discussion-resolve <project> <iid> <discussion-id>` | `gitlab_resolve_discussion` |
| `gitlab mr approval-show <project> <iid>` | `gitlab_merge_request_approvals` |
| `gitlab mr approve <project> <iid>` | `gitlab_approve_merge_request` |
| `gitlab mr merge <project> <iid>` | `gitlab_merge_merge_request` |
| `gitlab mr update <project> <iid>` | `gitlab_update_merge_request` |
| `gitlab job play <project> <job-id>` | `gitlab_play_job` |
| `gitlab job retry <project> <job-id>` | `gitlab_retry_job` |
| `gitlab pipeline retry <project> <pipeline-id>` | `gitlab_retry_pipeline` |
| `confluence space list` | `confluence_list_spaces` |
| `confluence page search --cql <query>` | `confluence_search` |
| `confluence page get <content-id>` | `confluence_get_page` |
| `confluence page body <content-id>` | `confluence_get_page_body` |
| `confluence page child-list <content-id>` | `confluence_list_children` |
| `confluence page comment-list <content-id>` | `confluence_list_comments` |
| `confluence page create <space-key> --title <text> --body-file <path|->` | `confluence_create_page` |
| `confluence page update <content-id> --body-file <path|->` | `confluence_update_page` |
| `confluence page comment <content-id> --body-file <path|->` | `confluence_add_comment` |
| `arm repository list` | `arm_list_repositories` |
| `arm artifact info <repo> <path>` | `arm_artifact_info` |
| `arm artifact properties <repo> <path>` | `arm_get_properties` |
| `arm artifact search --query <aql>` | `arm_search_artifacts` |
| `arm artifact deploy <repo> <path> --file <local-path>` | `arm_deploy` |
| `arm artifact delete <repo> <path>` | `arm_delete` |

Before Task 1A, the live post-Wave-3 schemas must contain the 58 existing
operations in this table and must not contain either approved prerequisite
operation yet. Task 1A adds `gitlab_read_pipeline` and
`gitlab_create_named_branch`; after it commits, all 60 rows must match the live
schemas exactly. Any difference other than those two documented additions is a
stop condition: do not silently expose, remove, or rename another operation.

## Stable Output and Exit Contract

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

Errors replace `data` with:

```json
{
  "error": {
    "category": "invalid_configuration",
    "message": "Jira configuration is invalid",
    "remediation": "Enable and configure ericsson-jira for the active profile."
  }
}
```

Exit codes: `0` success/preview/completed write; `2` CLI, schema, input, file, or intent error; `3` connector disabled/unavailable/unsupported/not configured; `4` classified connector/remote failure; `5` `write_ambiguous`.

## File Structure

| File | Responsibility |
|---|---|
| **Create** `plugins/ericsson-connector-cli/plugin.yaml` | Always-loaded backend identity, no tools/configuration. |
| **Create** `plugins/ericsson-connector-cli/__init__.py` | Register four top-level CLI trees and bind handlers to the host port. |
| **Create** `plugins/ericsson-connector-cli/descriptors.py` | Curated command table and argument/file bindings. |
| **Create** `plugins/ericsson-connector-cli/parser.py` | Argparse tree construction and exact mutation intent groups. |
| **Create** `plugins/ericsson-connector-cli/io.py` | Bounded body-file/stdin acquisition and terminal sanitization. |
| **Create** `plugins/ericsson-connector-cli/render.py` | Human/JSON envelopes and exit-code mapping. |
| **Create** `plugins/ericsson-connector-cli/mappings/supercli-0.14.1.yaml` | Complete machine-readable migration authority with provenance. |
| **Create** `plugins/ericsson-connector-cli/scripts/build_migration_docs.py` | Deterministic human guide generator/checker. |
| **Create** `docs/cli-migration/supercli-0.14.1.md` | Generated migration guide. |
| **Modify** `plugins/ericsson-gitlab/{tools.py,operations.py,__init__.py,plugin.yaml}` | Add the reconciled pipeline-read and explicit named-branch operations before facade descriptors. |
| **Create** `plugins/ericsson-{jira,gitlab,confluence,arm}/application.py` | Connector-local shared application execution/error envelope. |
| **Modify** each connector `__init__.py` | Model adapter calls application executor; register application-command provider. |
| **Modify** `sets/ericsson.json` | Add backend facade string, preserve standalone lifecycle objects. |
| **Modify** source docs/onboarding catalog | Discovery, migration, CLI/TUI coexistence, safe writes, output use. |
| **Create** `tests/test_connector_cli_*.py` | Manifest, descriptors, parser, authority, parity, rendering, mapping, docs, architecture. |

---

### Task 1: Complete GitLab compatibility, then scaffold the facade

Task 1 has two ordered TDD commits. Task 1A completes the owning connector's
public contract; Task 1B builds facade descriptors only after the live schemas
contain all 60 approved operations.

#### Task 1A: Add the two reconciled GitLab capabilities

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`
- Modify: `plugins/ericsson-gitlab/operations.py`
- Modify: `plugins/ericsson-gitlab/__init__.py`
- Modify: `plugins/ericsson-gitlab/plugin.yaml`
- Modify: `tests/test_gitlab_reads.py`
- Modify: `tests/test_gitlab_writes.py`
- Modify: `tests/test_gitlab_plugin.py`
- Modify: `tests/test_gitlab_approval.py`

**Interfaces:**
- read operation `gitlab_read_pipeline(project, pipeline_id)`;
- write operation `gitlab_create_named_branch(project, branch, ref, dry_run=False)`;
- both operations are declared in `SCHEMAS` and `plugin.yaml`;
- the named-branch operation joins `_WRITE_TOOLS` and `WRITE_APPROVALS` and
  continues to require genuine model admission on the model-tool surface.

- [ ] **Step 1: Write failing focused GitLab tests**

For `gitlab_read_pipeline`, test schema bounds, tool dispatch, exact project
resolution and pipeline endpoint, and this exact bounded normalized result:

- `project`: canonical mapping with required positive integer `id` and required
  bounded string `path`;
- `pipeline_id`: required positive integer exactly equal to the requested id;
- `status`, `ref`, `sha`, and `source`: required bounded strings;
- `web_url`: required bounded same-origin string; and
- `created_at`, `updated_at`, `started_at`, and `finished_at`: required keys
  whose values are either null or bounded timestamp strings.

Reject missing, wrongly typed, over-bounded, cross-origin, or inconsistent
remote data. Do not expose the raw payload, user objects, variables, jobs, or
unlisted fields.

For `gitlab_create_named_branch`, test schema bounds, ref/branch validation,
project resolution, requested-ref resolution to an exact commit identity, and
a truthful dry-run that may perform those bounded reads plus target-branch
lookup but issues no mutating request. Pin exact-identity existing-branch reuse;
pre-existing identity mismatch as safe `conflict` with no mutation; successful
creation; already-exists/post-dispatch reconciliation that succeeds only when
the target branch is proved to match the resolved requested identity; and
`write_ambiguous` whenever that exact identity cannot be proved after dispatch.
Also pin safe classified errors and uncertain-write preservation. Assert the
approval text identifies project, branch, and ref; the operation is in
`_WRITE_TOOLS`; and an admitted model write still cannot bypass genuine
`PluginToolAdmission`.

- [ ] **Step 2: Confirm the expected RED state**

```bash
. .venv/bin/activate
pytest \
  tests/test_gitlab_reads.py \
  tests/test_gitlab_writes.py \
  tests/test_gitlab_plugin.py \
  tests/test_gitlab_approval.py -q
```

Expected: FAIL only because `gitlab_read_pipeline` and
`gitlab_create_named_branch` are absent.

- [ ] **Step 3: Implement the minimum connector capability**

Add both canonical schemas and bounded `tools.invoke` dispatch. Implement the
single-pipeline read with the existing client, project resolution, deadline,
remote-shape validation, canonical URL handling, and result bounds.

Extract or reuse the current branch validation and reconciliation path so the
new named-branch write does not duplicate transport, ambiguity, or error
policy. It accepts an explicit validated `branch` and `ref`, resolves the ref to
an exact commit identity, and may perform bounded project/ref/target-branch
reads during dry-run while issuing no mutating request. Reuse a pre-existing
branch only when its commit matches the resolved identity; return safe
`conflict` without mutation on a pre-existing mismatch. Its confirmed path
passes the resolved commit identity—not the potentially movable ref name—as the
creation ref. After a mutating dispatch or already-exists race, return
success/reuse only when a bounded read proves the target branch has the exact
requested commit; otherwise return `write_ambiguous`. Keep the new operation's
compatible dry-run-shaped connector arguments; Wave 4A host confirmation is
normalized by the direct provider only after genuine invocation validation.

Register the read/write in `plugin.yaml`, add the write to `_WRITE_TOOLS`, and
add bounded approval rendering. Do not add SuperCLI-derived behavior or
credentials/options to either domain operation.

- [ ] **Step 4: Run focused and complete GitLab parity tests**

```bash
pytest \
  tests/test_gitlab_reads.py \
  tests/test_gitlab_writes.py \
  tests/test_gitlab_plugin.py \
  tests/test_gitlab_approval.py -q
pytest tests/test_gitlab_*.py -q
```

Expected: PASS. Confirm `SCHEMAS` now contains exactly 30 GitLab operations and
the repository contains exactly 60 operations across the four connectors.

- [ ] **Step 5: Commit**

```bash
git add \
  plugins/ericsson-gitlab/tools.py \
  plugins/ericsson-gitlab/operations.py \
  plugins/ericsson-gitlab/__init__.py \
  plugins/ericsson-gitlab/plugin.yaml \
  tests/test_gitlab_reads.py \
  tests/test_gitlab_writes.py \
  tests/test_gitlab_plugin.py \
  tests/test_gitlab_approval.py
git commit -m "feat: add missing GitLab CLI capabilities"
```

#### Task 1B: Scaffold the always-visible facade and descriptor contract

**Files:**
- Create: `plugins/ericsson-connector-cli/{plugin.yaml,__init__.py,descriptors.py}`
- Modify: `sets/ericsson.json`
- Create: `tests/test_connector_cli_manifest.py`
- Create: `tests/test_connector_cli_descriptors.py`

**Interfaces:**
- plugin id `ericsson-connector-cli`, `kind: backend`, `provides_tools: []`
- manifest entry is the string `plugins/ericsson-connector-cli`
- immutable `CommandDescriptor` and `ArgumentBinding` values
- `DESCRIPTORS` contains exactly the 60 rows in **Reconciled Public Command Map**

- [ ] **Step 1: Write failing manifest and descriptor tests**

Tests must assert:

- the plugin is a backend with no config schema, required env, tools, hooks, or network metadata;
- `sets/ericsson.json` contains the facade exactly once as a string and leaves each connector an `enabled: false` object;
- command paths and canonical operations are globally unique;
- top-level domains are exactly `jira`, `gitlab`, `confluence`, `arm`;
- every descriptor declares connector id, path tokens, operation, read/write, positional bindings, option bindings, file bindings, and human render hint;
- every one of the 60 operations in the approved table appears exactly once,
  with family counts Jira 15, GitLab 30, Confluence 9, and ARM 6;
- descriptor arguments target exactly the live final schema properties after removing `dry_run` and `confirm` from writes;
- descriptor read/write classification exactly matches the connector `_WRITE_TOOLS` set;
- facade source imports no connector, transport, client, auth, operations, `httpx`, `requests`, or `urllib` module.
- loading the facade against one preoccupied top-level domain fails the plugin load and leaves none of the other three facade domains registered; the pre-existing owner is preserved.

- [ ] **Step 2: Confirm failure**

```bash
. .venv/bin/activate
pytest tests/test_connector_cli_manifest.py tests/test_connector_cli_descriptors.py -q
```

Expected: FAIL because the plugin does not exist.

- [ ] **Step 3: Add the plugin and descriptors**

Use frozen dataclasses. Each argument binding records source (`positional`, `option`, `body_file`, `local_file`), public name, target schema property, requiredness, repeatability, value type, and optional choices. Do not store handlers or import schemas in `descriptors.py`; tests load connector schemas independently.

For simple optional schema fields, use exact kebab-case flags such as `max_results -> --max-results`. For structured maps/lists, add explicit repeatable bindings and deterministic parsing rather than accepting raw connector JSON. The minimum special bindings are:

- body-bearing writes: `--body-file PATH`, with `-` meaning stdin;
- Jira update fields: repeatable `--field NAME=JSON_VALUE`;
- GitLab commit changes: repeatable `--change-file PATH` containing one bounded change object per file;
- GitLab list-valued labels/reviewers/assignees/actions: repeatable singular flags;
- ARM deploy: `--file PATH`, passed as a path without reading bytes in the facade;
- AQL: `--query TEXT` or bounded `--query-file PATH`, mutually exclusive and required.

If the final schema requires a different structured type, add a named binding and a test; never fall back to arbitrary full-operation JSON.

- [ ] **Step 4: Run focused tests and full manifest tests**

```bash
pytest tests/test_connector_cli_manifest.py tests/test_connector_cli_descriptors.py tests/test_manifest.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/ericsson-connector-cli sets/ericsson.json tests/test_connector_cli_manifest.py tests/test_connector_cli_descriptors.py
git commit -m "feat: scaffold Ericsson connector CLI descriptors"
```

---

### Task 2: Extract Jira's shared application executor and register the provider

**Files:**
- Create: `plugins/ericsson-jira/application.py`
- Modify: `plugins/ericsson-jira/__init__.py`
- Create: `tests/test_connector_cli_jira_port.py`
- Modify: existing Jira contract/write tests only where imports move

**Produces:** model and local adapters return the same safe envelope for identical Jira operation requests.

- [ ] **Step 1: Write failing Jira parity and authority tests**

Cover a representative read, dry-run write, confirmed write, invalid input, configuration failure, connector-local failure, unexpected exception, and `write_ambiguous`. Assert:

- the model handler still refuses a write without genuine `PluginToolAdmission`;
- a provider callback accepts only a genuine host application invocation;
- direct dry-run applies `dry_run=True` only after genuine invocation
  validation; direct confirmation applies `confirm=True` where the schema owns
  that field, while existing dry-run-shaped `jira_add_comment` applies
  `dry_run=False` only after genuine confirmed host mode;
- neither adapter constructs, accepts, aliases, or serializes the other's
  authority, and both converge on `application.execute` only after their
  separate checks;
- application execution resolves `ctx.configuration()` once per call, not registration;
- both adapters call the same `application.execute(...)` spy and return byte-equivalent JSON-decoded envelopes;
- no configuration object or admission/invocation object appears in results.

- [ ] **Step 2: Confirm failure**

```bash
pytest tests/test_connector_cli_jira_port.py -q
```

Expected: FAIL because Jira has no application executor/provider.

- [ ] **Step 3: Implement `application.py` and thin adapters**

Move the current expected execution block from Jira's registered tool handler into:

```python
def execute(name, arguments, configuration, *, cancel_check=None) -> dict:
    """Return {'success': True, 'result': ...} or one safe classified error."""
```

It validates the operation through existing `tools.invoke`, translates `JiraError` using `SAFE_ERROR_MESSAGES` and remediation, maps input exceptions to `invalid_input`, and maps unexpected exceptions to safe `transient` without raw text.

Keep model admission in the model adapter before `application.execute`. Register all Jira `SCHEMAS` through:

```python
ctx.register_application_commands(
    operations={name: "write" if name in _WRITE_TOOLS else "read" for name in jira_tools.SCHEMAS},
    allowed_callers={"ericsson-connector-cli"},
    handler=local_command_handler,
)
```

The local handler verifies provider/operation identity by relying on the genuine invocation, copies arguments, applies mode, resolves fresh configuration, and calls `application.execute`.

- [ ] **Step 4: Run Jira and shared parity tests**

```bash
pytest tests/test_connector_cli_jira_port.py tests/test_jira_*.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/ericsson-jira tests/test_connector_cli_jira_port.py tests/test_jira_*.py
git commit -m "refactor: share Jira execution across model and CLI adapters"
```

---

### Task 3: Extract GitLab's shared application executor and register the provider

**Files:**
- Create: `plugins/ericsson-gitlab/application.py`
- Modify: `plugins/ericsson-gitlab/__init__.py`
- Create: `tests/test_connector_cli_gitlab_port.py`

Repeat Task 2's red-green cycle for GitLab. The error boundary must remain connector-local: `GitLabError` is translated in `application.execute`; `ConnectorError` never escapes or appears in the public envelope. Pin representative read, dry-run, confirmed write, approval refusal, configuration failure, `write_ambiguous`, and unexpected error cases.

GitLab parity must cover both connector intent shapes. Operations with
`dry_run` and `confirm` receive the matching field only after a genuine Wave 4A
invocation is validated. The existing dry-run-shaped writes
`gitlab_create_branch`, `gitlab_commit_changes`, and
`gitlab_create_merge_request`, plus the new compatible dry-run-shaped
`gitlab_create_named_branch`, receive `dry_run=True` for host dry-run and
`dry_run=False` for genuine host confirm.
The confirmed false value is never accepted as standalone direct authority;
the provider owns this normalization. Model writes still require genuine
`PluginToolAdmission`, and neither adapter accepts or constructs the other's
authority.

Run:

```bash
pytest tests/test_connector_cli_gitlab_port.py tests/test_gitlab_*.py -q
```

Expected after implementation: PASS.

Commit:

```bash
git add plugins/ericsson-gitlab tests/test_connector_cli_gitlab_port.py
git commit -m "refactor: share GitLab execution across model and CLI adapters"
```

---

### Task 4: Extract Confluence and ARM application executors

**Files:**
- Create: `plugins/ericsson-confluence/application.py`
- Modify: `plugins/ericsson-confluence/__init__.py`
- Create: `plugins/ericsson-arm/application.py`
- Modify: `plugins/ericsson-arm/__init__.py`
- Create: `tests/test_connector_cli_confluence_port.py`
- Create: `tests/test_connector_cli_arm_port.py`

Use the same contract as Tasks 2-3 in two sequential red-green substeps, committing only after both are green. Preserve:

- Confluence body warning and Markdown/storage escaping;
- Confluence version-conflict and ambiguity categories;
- ARM file confinement and checksum-first deploy behavior;
- ARM dry-run deploy performs no request;
- ARM delete dry-run performs its reviewed GET;
- connector-local `ConfluenceError`/`ArmError` translation with no `ConnectorError` escape.

Run:

```bash
pytest tests/test_connector_cli_confluence_port.py tests/test_confluence_*.py -q
pytest tests/test_connector_cli_arm_port.py tests/test_arm_*.py -q
```

Expected: PASS.

Commit:

```bash
git add plugins/ericsson-confluence plugins/ericsson-arm tests/test_connector_cli_confluence_port.py tests/test_connector_cli_arm_port.py
git commit -m "refactor: share Confluence and ARM application execution"
```

---

### Task 5: Build parsers, bounded local input, and pre-dispatch write gates

**Files:**
- Create: `plugins/ericsson-connector-cli/parser.py`
- Create: `plugins/ericsson-connector-cli/io.py`
- Modify: `plugins/ericsson-connector-cli/__init__.py`
- Create: `tests/test_connector_cli_parser.py`
- Create: `tests/test_connector_cli_input.py`

**Produces:** all four top-level command trees, canonical argument mappings, and local failures before provider dispatch.

- [ ] **Step 1: Write golden parser tests**

For every descriptor, test `--help` and one minimum valid parse. For every write, parameterize omission, both flags, `--dry-run`, and `--confirm`. Patch file read, stdin read, and `ctx.invoke_application_command`; assert omission/both call none of them. Test unknown commands/flags, missing required values, repeated structured flags, enum choices, integer bounds, and `--json` stripping.

Test both branded program names by setting parser `prog` to `otto` and `loop24`; parsed connector arguments and help below the executable token must be identical.

- [ ] **Step 2: Confirm failure**

```bash
pytest tests/test_connector_cli_parser.py tests/test_connector_cli_input.py -q
```

Expected: FAIL because parser/input modules do not exist.

- [ ] **Step 3: Implement parser and bounded input**

Build argparse trees only from curated descriptors. Set leaf handlers through the existing plugin CLI setup/handler seam. The leaf handler returns an integer exit code and never calls `sys.exit` itself.

Input rules:

- body/query/change files: regular file or stdin, UTF-8, maximum 256 KiB each;
- stdin may be consumed once per invocation;
- reject symlinks for body/change inputs to avoid surprising file substitution;
- ARM `--file`: resolve and pass the path only; the connector's existing confinement/size checks remain authoritative;
- repeatable `NAME=VALUE`: bound item count to 64, name length to 128, decoded value to 16 KiB, reject duplicate names unless the schema is list-valued;
- strip `dry_run`, `confirm`, `json`, descriptor identity, and argparse handler objects from connector arguments;
- create a UUID invocation id inside the leaf handler immediately before host dispatch.

- [ ] **Step 4: Run focused tests**

```bash
pytest tests/test_connector_cli_parser.py tests/test_connector_cli_input.py tests/test_connector_cli_descriptors.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/ericsson-connector-cli tests/test_connector_cli_parser.py tests/test_connector_cli_input.py tests/test_connector_cli_descriptors.py
git commit -m "feat: add bounded connector CLI parsing and write intent"
```

---

### Task 6: Dispatch through the host port and render stable output

**Files:**
- Create: `plugins/ericsson-connector-cli/render.py`
- Modify: `plugins/ericsson-connector-cli/__init__.py`
- Create: `tests/test_connector_cli_dispatch.py`
- Create: `tests/test_connector_cli_output.py`

**Produces:** provider resolution, stable JSON/human output, stdout/stderr separation, and exit codes 0/2/3/4/5.

- [ ] **Step 1: Write failing dispatch/output tests**

Use fake contexts/providers, not network. Cover:

- read, dry-run, and confirm pass the expected Wave 4A mode and canonical args;
- missing provider/disabled connector returns exit 3 with an exact active-profile enablement remediation;
- application-port invalid/denied errors return exit 2 without provider details;
- connector `invalid_configuration`/authentication/readiness return exit 3;
- ordinary classified errors return exit 4;
- `write_ambiguous` returns exit 5 and preserves remediation;
- human output removes CSI/OSC control sequences, respects row/text bounds, and sends warnings/diagnostics to stderr;
- JSON success and every error contain exactly one envelope, no ANSI, and no object representations;
- JSON output contains no credential/configuration/admission/invocation values;
- the handler writes no banner/spinner/model prose;
- identical normalized provider results produce the same `data`, `warnings`, and `meta` under both brands.

- [ ] **Step 2: Confirm failure**

```bash
pytest tests/test_connector_cli_dispatch.py tests/test_connector_cli_output.py -q
```

Expected: FAIL because rendering/dispatch is incomplete.

- [ ] **Step 3: Implement dispatch and rendering**

The facade calls only `ctx.invoke_application_command(provider_id, operation, arguments, mode=..., invocation_id=...)`. Translate Wave 4A stable exceptions without inspecting private manager state. For disabled remediation, render the current executable token and the existing plugin-enable command documented by Hermes; do not hardcode `otto` when running `loop24`.

Normalize provider envelopes:

- success: unwrap `result` into `data`, preserve connector envelope warnings/meta;
- expected error: copy only category, safe message, and remediation;
- malformed result: stable `transient` error, exit 4;
- never print the raw malformed object or exception.

JSON uses `json.dumps(... sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)` followed by one newline.

- [ ] **Step 4: Run focused and cross-surface tests**

```bash
pytest tests/test_connector_cli_dispatch.py tests/test_connector_cli_output.py tests/test_connector_cli_*_port.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/ericsson-connector-cli tests/test_connector_cli_dispatch.py tests/test_connector_cli_output.py
git commit -m "feat: dispatch connector commands with stable output contracts"
```

---

### Task 7: Build the complete SuperCLI 0.14.1 migration authority

**Files:**
- Create: `plugins/ericsson-connector-cli/mappings/supercli-0.14.1.yaml`
- Create: `plugins/ericsson-connector-cli/scripts/build_migration_docs.py`
- Create: `docs/cli-migration/supercli-0.14.1.md`
- Create: `tests/test_connector_cli_migration.py`

**Evidence input:** locate the analysis workspace by the filenames `SUPER-CLI-ARCHITECTURE.md`, `PLUGIN-GAP-ANALYSIS.md`, and `out/func-strings.txt`. These inputs are required for this task but are not copied wholesale into the shipped repo.

- [ ] **Step 1: Write failing mapping tests**

Assert the YAML contains:

- schema version `ericsson.supercli-migration/v1`;
- exact pinned version/commit/binary SHA-256 from Global Constraints;
- one unique row for every service command (`jira`, `gitlab`, `confluence`, `arm`) extracted from the quoted command strings in `func-strings.txt`;
- dispositions limited to `equivalent`, `renamed`, `safer-different`, `not-yet-supported`, `no-equivalent`;
- replacement template using `{brand}` only for supported rows;
- flag mapping, output difference, write behavior, earliest wave, rationale, and evidence reference on every row;
- every supported replacement resolves to a real descriptor;
- every descriptor has at least one mapping row or an explicit `new-capability` note;
- no supported row claims `--url`, credential flags, `--raw`, `--no-throttle`, arbitrary raw JSON mutation, or unsupported operations are equivalent;
- writes mention required dry-run/confirm and ambiguity behavior;
- generator output is byte-stable and `--check` detects drift.

- [ ] **Step 2: Confirm failure**

```bash
pytest tests/test_connector_cli_migration.py -q
```

Expected: FAIL because mapping files do not exist.

- [ ] **Step 3: Extract and review the inventory**

Write a bounded one-off extraction inside the test or generator that recognizes only exact single-quoted `super-cli (jira|gitlab|confluence|arm) ...` command strings and deduplicates them. Compare the count and rows manually against the architecture report's per-service method/command discussion. Do not parse fused adjacent strings as commands and do not infer missing flags.

Populate every row. Important deliberate differences include:

- SuperCLI `--url` and credential flags -> active Hermes profile configuration (`safer-different`);
- SuperCLI raw Jira field JSON -> repeatable bounded `--field` allowlist (`safer-different`);
- Confluence raw storage writes -> escaped Markdown input (`safer-different`);
- ARM deploy -> checksum-first with full-upload fallback (`safer-different`);
- ARM download -> no equivalent; use metadata/checksum and explain why;
- unimplemented boards/sprints, GitLab releases/tags/webhooks/variables/todos/code search, Confluence labels/attachments/versions/move/delete/append, ARM properties writes/copy/move/Xray/storage/permissions -> explicit unsupported/no-equivalent dispositions according to approved connector plans;
- `write_ambiguous` is an added safety difference on every write.
- the pinned SuperCLI `gitlab pipeline view` row maps to
  `{brand} gitlab pipeline view <project> <pipeline-id>` and
  `gitlab_read_pipeline`, with only the evidenced project/pipeline inputs and
  bounded normalized output;
- `gitlab_create_named_branch` is marked as a new capability unless an exact
  pinned evidence row exists; do not infer or invent a SuperCLI command for it.

- [ ] **Step 4: Generate and verify the human guide**

The generated Markdown groups rows by service and disposition, includes a quick-start section, read and write examples for both `{brand}` substitutions, exit codes, JSON schema, profile/enablement instructions, and a prominent statement that existing scripts are not drop-in compatible.

```bash
.venv/bin/python plugins/ericsson-connector-cli/scripts/build_migration_docs.py
.venv/bin/python plugins/ericsson-connector-cli/scripts/build_migration_docs.py --check
pytest tests/test_connector_cli_migration.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add plugins/ericsson-connector-cli/mappings plugins/ericsson-connector-cli/scripts docs/cli-migration tests/test_connector_cli_migration.py
git commit -m "docs: add verified SuperCLI connector migration map"
```

---

### Task 8: Integrate source docs and onboarding catalog

**Files:**
- Modify: `docs/README.md`
- Modify: `docs/configuration.md`
- Modify: relevant Jira/GitLab/Confluence/ARM capability and flow docs
- Modify: onboarding capability references as generated/input conventions require
- Regenerate: `skills/ericsson/onboard-ericsson-capabilities/references/catalog.json`
- Create or modify: `tests/test_connector_cli_docs.py`

- [ ] **Step 1: Write failing docs/catalog tests**

Assert user-facing docs explain:

- direct shell commands and natural-language CLI/TUI coexist;
- help works while connector is disabled;
- execution requires standalone connector enablement/configuration;
- no connector credentials belong on argv;
- all writes require exactly one dry-run/confirm;
- JSON contract and exit code 5 ambiguity;
- migration guide location;
- examples use a neutral `<brand>`/`{brand}` token or show both brands, never imply OTTO-only behavior;
- onboarding catalog references the facade and domain CLI paths without misclassifying the backend as a connector that needs enablement.

- [ ] **Step 2: Confirm failure, update docs, regenerate catalog**

```bash
pytest tests/test_connector_cli_docs.py -q
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py --check
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/validate_catalog.py
```

After doc updates and regeneration, all commands must pass.

- [ ] **Step 3: Run shipped-doc security hygiene**

```bash
pytest tests/test_opportunity_visuals_skill.py::test_shipped_docs_do_not_embed_developer_home_paths -q
git diff --check
```

Expected: PASS. Refer to the analysis workspace only by file/repository name, never a developer home path.

- [ ] **Step 4: Commit**

```bash
git add docs skills/ericsson/onboard-ericsson-capabilities tests/test_connector_cli_docs.py
git commit -m "docs: integrate connector CLI with onboarding and configuration"
```

---

### Task 9: End-to-end contract gates and source handoff

**Files:** no planned production changes.

- [ ] **Step 1: Run the complete connector CLI suite**

```bash
. .venv/bin/activate
pytest tests/test_connector_cli_*.py -q
```

Expected: PASS.

- [ ] **Step 2: Run connector and manifest regressions**

```bash
pytest \
  tests/test_jira_*.py \
  tests/test_gitlab_*.py \
  tests/test_confluence_*.py \
  tests/test_arm_*.py \
  tests/test_manifest.py \
  tests/test_shared_sync.py -q
```

Expected: PASS.

- [ ] **Step 3: Run the repository gate**

```bash
./bootstrap.sh
```

Expected: PASS. If it fails, prove any claimed baseline failure in a separate,
untouched worktree checked out at the exact current `origin/main` commit, using
the same environment and test command. Never use `main~1` or a dirty/current
feature checkout as baseline evidence. Do not classify a recently introduced
regression as pre-existing without that exact-commit reproduction.

- [ ] **Step 4: Re-run generated and architecture checks**

```bash
.venv/bin/python plugins/ericsson-connector-cli/scripts/build_migration_docs.py --check
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py --check
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/validate_catalog.py
git diff main...HEAD --check
git status --short
git log --oneline main..HEAD
```

Expected: generated artifacts current, no whitespace errors, clean worktree, focused task commits.

- [ ] **Step 5: Push and report; do not deliver**

Push `feat/ericsson-connector-cli`. Report:

- command families and supported operation counts (Jira 15, GitLab 30,
  Confluence 9, ARM 6; total 60);
- focused/full test results;
- exact JSON schema and exit codes;
- SuperCLI inventory row counts by disposition;
- deviations and plan defects;
- confirmation that Wave 1-3 branches were untouched;
- confirmation that no vendoring, base/brand merge, regeneration, release, or delivery occurred.

Do not vendor or merge. The AGENTS.md source-first delivery sequence is a separately authorized session after this branch is reviewed and merged to source `main`.

## Self-Review

- The facade is discoverable before connector opt-in because it is a backend; execution remains impossible until the standalone provider is enabled and loaded.
- Direct commands and model tools share the same connector-local executor, but preserve different host authorities at their adapters.
- The plan does not generate a human CLI blindly from JSON Schema. The approved command list is explicit; schemas are a drift detector.
- The facade never imports connector code. Cross-plugin dispatch goes only through the public Wave 4A host port.
- Parser rejection precedes file reads as well as network/configuration, which keeps missing intent truly side-effect free.
- ARM deploy remains special: the facade passes a local path, while the owning connector retains file confinement, bounds, hashing, and upload behavior.
- Mapping completeness is based on pinned extracted evidence, not on current connector coverage or memory.
- Existing SuperCLI scripts are not promised compatibility. The generated guide is a migration map with named safety differences.
- Natural-language CLI/TUI remains the reasoning surface; direct commands are deterministic leaves over the same operations.
