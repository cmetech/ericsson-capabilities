---
source_flow: utils/sp_files.py and custom_components/ericsson_parsers/sharepoint_files_fetcher.py
source_commit: fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6
source_sha256: behavior-frozen-in-docs-connector-porting-sharepoint-behavior-map
status: intent-ported
target_artifacts: [ericsson-sharepoint-plugin, sharepoint-document-intake-workflow]
supporting_capabilities: [sharepoint, document-processing]
platforms: [macos, linux, windows]
---

# SharePoint document intake

## What it does

Resolves an Ericsson SharePoint URL, optionally performs bounded folder
discovery, and downloads only the selected files to an authorized local root.
It writes `sharepoint-intake-manifest.json` with relative paths, sizes, digests,
remote identities, truncation, and warnings.

## When to use it

Use it when the user wants a bounded local acquisition step before another
capability works with documents. Ask whether a direct file URL may be broadened
to its parent folder; never broaden scope implicitly. Do not use this workflow
for uploads, permission changes, or tenant-wide collection.

## Original Loop24 behavior

The legacy utilities resolved SharePoint UI URLs, recursively discovered
documents, downloaded selected files, and handed them directly to embedded
Docling/basic parsers. The native port preserves URL identity, bounded
selection, safe download, partial-result warnings, and handoff while separating
transport from content work.

## Inputs and outputs

The required inputs are `sharepoint_url` and an authorized `destination`. The
single workflow node may call only `sharepoint_resolve_url`,
`sharepoint_list_items`, and `sharepoint_download`. It stops after artifact
acquisition. Document processing is a separate next step: PDF/Office extraction,
OCR, interpretation, conversion, and document generation are not connector
functions.

## Supporting capabilities and configuration

Enable `ericsson-sharepoint` and start a fresh conversation. Configure one
Graph identity mode, the tenant host, bounds, and authorized local roots as
described in [configuration](../configuration.md#sharepoint-connector). The
workflow does not require browser enrollment.

## Failure, safety, and privacy behavior

Traversal, unsafe links, special files, overwrite, boundary escape, untrusted
tenant URLs, and limit violations fail closed. Partial folder or download
results retain explicit warnings. Local evidence does not expose absolute
profile paths, credentials, raw remote bodies, or authorization headers.

## Independent permission-audit example

If a user separately requests permission evidence, use
`sharepoint_audit_permissions`. Without the configured core-owned session it
returns `browser_enrollment_required`; Graph file tools remain available when
Graph readiness is healthy. Browser enrollment does not authorize writes and
is not hidden inside this intake workflow.

## Hermes port status and target shape

Intent is ported through the standalone SharePoint plugin, its detailed skills,
the thin `sharepoint` router, and `sharepoint-document-intake`. Permanent delete,
embedded parsing, OCR, content generation, hidden LLM calls, and connector-owned
browser launching are deliberate exclusions.

## How Hermes should explain and configure it

Confirm the exact URL, requested breadth, file filters, bounds, and destination.
Validate with a small read-only resolve/list. Show the manifest and warnings,
then offer an explicitly separate document-processing capability if requested.
