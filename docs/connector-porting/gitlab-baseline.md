# GitLab connector source and vendor baseline

This document freezes the pre-port source/vendor state for the Ericsson GitLab
connector release. It is an inventory, not permission to silently prefer the
newer copy of a divergent file.

## Pinned repositories

| Repository | Branch/worktree | Frozen revision |
|---|---|---|
| `ericsson-capabilities` (source of truth) | `feat/ericsson-gitlab-connector` | `dae405ede7049b621e502d9259f97481c940a65b` |
| `hermes-agent` (vendored delivery) | `feat/ericsson-gitlab-connector` | `ebb0b33db1e15f816cb25bd5f863385771e46a00` |
| LOOP24 legacy evidence (read-only) | detached/pinned checkout | `fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6` |

The Hermes generated manifest currently records the same Ericsson source SHA,
`dae405ede7049b621e502d9259f97481c940a65b`, even though later Hermes-only
commits changed vendored files and manifest metadata. `vendoredFrom` therefore
does not by itself prove byte identity.

## Inventory method and result

The inventory used the complete output of these three commands:

```text
git -C <ericsson-worktree> ls-files
jq -r '.[]' <hermes-worktree>/capabilities/ericsson-vendored-paths.json
git -C <hermes-worktree> ls-files capabilities/ericsson.json \
  capabilities/ericsson-vendored-paths.json capabilities/mcp-servers.yaml \
  capabilities/workflow-packages/ericsson plugins/ericsson-* \
  plugins/outlook-mcp skills/ericsson
```

The source repository has 180 tracked files. The selected Hermes closure has
88 tracked files: 78 files beneath the seven inventory-ledger roots, the two
generated inventory/manifest files, and eight Hermes-only Confluence files.
For every ledger root, each tracked destination file was mapped back to its
source path and compared with `cmp`; generated paths were inspected separately.

| Ledger destination | Source mapping | Tracked files | Byte result |
|---|---|---:|---|
| `capabilities/mcp-servers.yaml` | `mcp/mcp-servers.yaml` | 1 | 1 equal |
| `capabilities/workflow-packages/ericsson` | no source root | 8 | generated/ported package; inspected, not byte-comparable |
| `plugins/ericsson-jira` | same path | 3 | 3 equal |
| `plugins/ericsson-teams` | same path | 4 | 3 equal, 1 divergent |
| `plugins/outlook-mcp` | `mcp/outlook-mcp` | 8 | 7 equal, 1 divergent |
| `skills/ericsson/onboard-ericsson-capabilities` | same path | 45 | 41 equal, 4 divergent |
| `skills/ericsson/opportunity-visuals` | same path | 9 | 9 equal |

Totals for the 70 directly comparable tracked files are 64 byte-equal and six
divergent. Local `__pycache__` directories are untracked and excluded from both
Git inventories. The source manifest also names eight tracked source-only files:
four under `skills/ericsson/workflow-orchestrator`, two under
`skills/ericsson/workflow-builder`, and the two legacy workflow YAML files.

## Manifest divergence and ownership decisions

| Field/path | Source at `0.4.1` | Hermes at `0.5.0` | Source-of-truth disposition |
|---|---|---|---|
| Manifest version | `0.4.1` | `0.5.0` | Do not copy either number as a snapshot assertion. Task 2 extends and validates the source manifest; the connector release bumps the source version intentionally, and Task 14 generates the vendored version from that exact source revision. |
| `skills` | Includes source-owned `workflow-orchestrator`, `workflow-builder`, `opportunity-visuals`, and onboarding. | Includes `opportunity-visuals`, onboarding, and Hermes-only `confluence-research`. | Task 2 removes the obsolete source workflow-router ownership in favor of Hermes' built-in workflow plugin/skills. Task 11 updates onboarding references. Confluence remains a documented Hermes compatibility overlay and is not changed by the GitLab release. |
| `plugins` | `ericsson-jira`, `ericsson-teams` | additionally includes Hermes-owned `plugins/workflow` | Task 2 makes the existing workflow backend explicit without treating it as a standalone connector or disabling it. Connector lifecycle authority, including later one-time migrations, belongs in `sets/ericsson.json`; Hermes must remain connector-id agnostic. |
| `workflows` / `workflowPackages` | Two legacy YAML entries: `my-tickets-summary.yml` and `inbox-digest.yml`; no package declaration. | No legacy `workflows`; one digest-bound package at `capabilities/workflow-packages/ericsson`. | The portable package is the accepted runtime shape. Before Task 14, bring that package under Ericsson source ownership, declare it in the source manifest, retain snapshot/read compatibility for historical workflows, and remove the obsolete delivery mapping only after parity tests pass. |
| `configDefaults` | absent | enrolled-browser defaults used by the Confluence skill | Preserve as a Hermes compatibility overlay until the Confluence release establishes source ownership. Task 14 must not delete or reinterpret it while vendoring GitLab. |
| `mcpServers` | `mcp/mcp-servers.yaml` | same | Ericsson source is authoritative; the copied bytes are currently equal. |
| `mcpServersFile` | absent | generated basename `mcp-servers.yaml` | Delivery-only generated compatibility metadata. Task 14 regenerates it; it is not authored in the source manifest. |
| `mcpLocal` | `mcp/outlook-mcp` | same logical source, delivered as `plugins/outlook-mcp` | Ericsson source is authoritative after the accepted Hermes subprocess fix is backported, then Task 14 re-vendors it. |
| `workflowCoreTools`, `personas`, `env` | present | logically equal | Ericsson source remains authoritative. New GitLab keys/settings follow the connector descriptor/secret-store design rather than ad hoc environment-only configuration. |
| `vendoredFrom` | absent | exact source SHA | Generated only. Task 14 must equal the full clean source SHA and must accompany complete byte/inventory checks. |
| `capabilities/ericsson-vendored-paths.json` | no source counterpart | seven managed destinations | Generated ledger only. Task 14 regenerates it from the reconciled source manifest and uses it for stale-path management. |

## Exact divergent files

Every directly comparable divergence is listed here; all other comparable
tracked files are byte-identical as counted above.

| Source path -> vendored path | Observed difference | Disposition |
|---|---|---|
| `plugins/ericsson-teams/graph_auth.py` -> same | Hermes adds four comments documenting that `st_uid`/`geteuid` checks are on POSIX-only guarded paths; executable behavior is identical. | Retain the explanatory annotations by applying them in source during source closure (Task 13 at latest), then re-vendor in Task 14. Do not maintain a Hermes-only fork. |
| `mcp/outlook-mcp/src/outlook_cli/__init__.py` -> `plugins/outlook-mcp/src/outlook_cli/__init__.py` | Hermes passes `stdin=subprocess.DEVNULL` to the PowerShell subprocess; source does not. | The Hermes fix is accepted behavior. Backport it to source before source closure and re-vendor in Task 14. |
| `skills/ericsson/onboard-ericsson-capabilities/SKILL.md` -> same | Hermes resolves a brand-aware `PRODUCT_CLI` before commands. | Adopt in source in Task 11 so OTTO, LOOP24, and neutral Hermes examples remain correct; regenerate and re-vendor in Task 14. |
| `skills/ericsson/onboard-ericsson-capabilities/references/capabilities/workflow-builder.md` -> same | Hermes points to the built-in workflow skill/plugin and portable package/doctor contract; source points to the retired Ericsson builder. | Hermes semantics are authoritative because the runtime moved upstream. Reconcile the source reference in Task 11, without recreating a second workflow implementation. |
| `skills/ericsson/onboard-ericsson-capabilities/references/capabilities/workflow-orchestrator.md` -> same | Hermes points to `plugins/workflow`, RunStore, immutable inputs, and product CLI control; source describes the retired Ericsson controller/state files. | Hermes semantics are authoritative. Reconcile the source reference in Task 11 and keep old workflow snapshots readable. |
| `skills/ericsson/onboard-ericsson-capabilities/references/catalog.json` -> same | Content entries are otherwise equal; only `catalogVersion` differs (`0.4.1` vs `0.5.0`). | Generated file: never hand-edit. Task 11 regenerates it from the reconciled source version and validates it before Task 14. |

## Generated workflow-package closure

The eight Hermes package files were read in full:

- `commands/collect-inbox.md`
- `commands/fetch-tickets.md`
- `commands/summarize-inbox.md`
- `commands/summarize-tickets.md`
- `digests.json`
- `workflows/inbox-digest.yaml`
- `workflows/my-tickets-summary.yaml`
- `workflows/my-tickets-summary.hermes.yaml`

They are a deliberate portable replacement for the two source legacy workflow
YAML files, not byte-generated copies. The package separates bounded commands,
allowed tools, approval, outward-action policy, required services/secrets, and
digest identity. Its content must be copied/adapted source-first and validated;
the existing Hermes directory must not be silently treated as source merely
because it is newer. Historical workflow snapshots and run history remain
readable after the source contract changes.

## MCP and Outlook closure

`mcp/mcp-servers.yaml` and `capabilities/mcp-servers.yaml` are byte-identical.
All eight tracked Outlook files were compared using the source-to-destination
rename; seven are identical and the sole subprocess divergence is recorded
above. The eventual source copy is authoritative, with `${CAPABILITY_DIR}` and
the `mcpLocal` delivery mapping retained rather than hard-coding a checkout.

## Existing Confluence drift

Hermes contains the following source-absent tree, and the tree is not listed in
`ericsson-vendored-paths.json`:

- `skills/ericsson/confluence-research/SKILL.md`
- `skills/ericsson/confluence-research/references/rest-api-notes.md`
- `skills/ericsson/confluence-research/requirements.txt`
- `skills/ericsson/confluence-research/scripts/artifacts.py`
- `skills/ericsson/confluence-research/scripts/backends.py`
- `skills/ericsson/confluence-research/scripts/confluence.py`
- `skills/ericsson/confluence-research/scripts/confluence_api.py`
- `skills/ericsson/confluence-research/scripts/storage_to_md.py`

The GitLab phase preserves these bytes and their enrolled-browser defaults as a
compatibility overlay. It does not copy, refactor, delete, restamp, or otherwise
change Confluence behavior. Source-first reconciliation is deferred to the
approved Confluence release; Task 14's GitLab vendoring gate must assert this
unmanaged compatibility tree remains unchanged.

## Closure rule

Before Task 14, every adopted Hermes fix must exist in a clean Ericsson source
commit. Vendoring must use `ERICSSON_CAPABILITIES_DIR` pointed at that exact
worktree, regenerate both manifests, compare every managed byte and inventory
path, retain the explicitly deferred Confluence overlay, and record the full
source SHA. No later divergent edit is allowed directly in the vendored copy.
