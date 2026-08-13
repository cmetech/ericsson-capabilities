---
id: sharepoint-tools
display_name: Ericsson SharePoint Tools
aliases: [SharePoint connector, SharePoint files, SharePoint permission audit]
goals:
  - Resolve and inspect an Ericsson SharePoint link.
  - Download a bounded set of SharePoint files for separate document processing.
  - Collect bounded SharePoint permission evidence.
maturity: available
recommendation_eligible: true
source_flows: [docs/flows/sharepoint-document-intake.md]
implementation:
  skills: [skills/ericsson/sharepoint]
  plugins: [plugins/ericsson-sharepoint]
  mcp_servers: []
  workflows: [workflows/sharepoint-document-intake.yml]
  tools: [sharepoint_resolve_url, sharepoint_get_item, sharepoint_list_items, sharepoint_download, sharepoint_list_owned_sites, sharepoint_audit_permissions, sharepoint_upload, sharepoint_create_folder, sharepoint_move_item, sharepoint_copy_item, sharepoint_recycle_item]
platforms: [macos, linux, windows]
configuration:
  - name: SharePoint connector settings
    kind: local-software
    required: true
    guidance: Configure the exact tenant host, identity mode, limits, authorized roots, and browser profile through the plugin surface.
  - name: Microsoft Graph identity
    kind: interactive-sign-in
    required: true
    guidance: Use delegated MSAL, app-only protected credentials, or an existing Azure CLI identity; never paste tokens into chat.
  - name: Microsoft Graph and SharePoint permissions
    kind: permission
    required: true
    guidance: Obtain only the organization-approved Graph and SharePoint permissions needed for the selected operation.
  - name: Enrolled SharePoint browser
    kind: interactive-sign-in
    required: false
    guidance: Enroll the named core-owned browser profile only when permission auditing is requested.
  - name: sharepoint_url
    kind: workflow-input
    required: true
    guidance: Supply one permitted HTTPS URL on the configured tenant.
  - name: destination
    kind: workflow-input
    required: true
    guidance: Choose a destination beneath the configured download root.
reads: [normalized SharePoint item metadata, bounded folder listings, selected files, owned sites, bounded permission evidence]
writes: [authorized local download artifact, SharePoint mutation only after exact approval, workflow manifest]
artifacts: [workflow intake manifest, bounded files beneath the configured download root, optional redacted audit artifact]
demonstrations: [read-only-live]
troubleshooting: [connector disabled, configuration required, interactive authentication required, permission denied, browser enrollment required, bounded partial result, uncertain write result]
---

# Ericsson SharePoint Tools

## What it solves

Provides one bounded connector for SharePoint URL resolution, metadata,
listing, downloads, owned sites, permission evidence, and explicitly approved
file operations. The router remains visible while the plugin is disabled.

## Try saying

- “Resolve this SharePoint link and show me the item metadata.”
- “Download these selected files to my authorized intake folder.”
- “Audit permissions for these two sites with small limits.”

Follow up with file filters, request a preview, choose the manifest format and
destination, inspect exclusions or warnings, or start a fresh bounded rerun.

## Questions

Expect questions for the exact URL or site, desired breadth and bounds, local
destination, and any explicit write effect. Browser enrollment is asked only
for permission auditing.

## Reads and writes

Graph reads and bounded browser audit collection are non-mutating. Downloads
write only to an authorized local root. Upload, folder creation, move, copy,
and recycle require a backend approval for the exact operation. Permanent
delete is not implemented.

## Readiness

Confirm plugin enablement and a fresh conversation, connector settings, Graph
identity, required permissions, then a small read-only resolve/list. Audit
readiness separately requires the named enrolled browser. Missing browser
enrollment does not disable Graph file tools.

## Demonstration

Use a permitted small resolve/list or synthetic download. Do not perform a live
mutation for demonstration. Installed Windows browser and Conditional Access
behavior remains subject to the dedicated release checklist.

## Artifacts

Return only relative artifact paths, sizes, digests, normalized identities,
and explicit warnings. Document parsing, OCR, interpretation, conversion, and
generation are separate follow-on capabilities.

## Troubleshooting

Distinguish disabled plugin, missing configuration, interactive authentication,
permission denial, tenant mismatch, local boundary denial, truncation, browser
enrollment, and ambiguous write outcomes. Inspect uncertain writes before any
retry.
