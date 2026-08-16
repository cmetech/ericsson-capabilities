---
id: confluence-tools
display_name: Ericsson Confluence Tools (Planned)
aliases: [Ericsson Confluence, Confluence connector scaffold, Confluence tools]
goals:
  - Explain the current status of the Ericsson Confluence connector scaffold.
  - Review the configuration that a future Confluence connector will require.
  - Tell me whether Confluence tools, reads, writes, or demonstrations are runnable today.
maturity: planned-not-implemented
recommendation_eligible: false
source_flows: []
implementation:
  skills: []
  plugins: [plugins/ericsson-confluence]
  mcp_servers: []
  workflows: []
  tools: []
platforms: [macos, linux, windows]
configuration:
  - name: base_url
    kind: static-setting
    required: true
    guidance: A future implementation will require the exact Confluence HTTP(S) origin, including the Cloud wiki path where applicable.
  - name: pat
    kind: static-secret
    required: true
    guidance: A future implementation will store the Confluence personal access token only through the protected secret field.
  - name: api_base_override
    kind: static-setting
    required: false
    guidance: A future implementation may use this optional REST API base-path override for a nonstandard deployment.
  - name: request_timeout_seconds
    kind: static-setting
    required: false
    guidance: A future implementation may use this optional bounded request deadline.
  - name: default_max_results
    kind: static-setting
    required: false
    guidance: A future implementation may use this optional bounded default result count.
reads: []
writes: []
artifacts: []
demonstrations: []
troubleshooting: [planned scaffold mistaken for a runnable connector, premature configuration request, unsupported tool or demonstration claim]
---

# Ericsson Confluence Tools (Planned)

## What it solves

This status entry explains the registered, disabled-by-default Confluence plugin
scaffold. It has configuration metadata and shared connector foundations, but no
runnable tools, reads, writes, skills, workflows, or demonstrations yet.

## Try saying

- “Is the Ericsson Confluence connector runnable yet?”
- “What configuration fields are represented by the Confluence scaffold?”
- “Can you search, read, comment on, or author Confluence pages today?”

There is no runnable filter, preview, output format, artifact destination,
exclusion, warning-processing, or rerun flow yet. Treat requests for those as
status questions, not permission to invent a connector operation.

## Questions

Ask only whether the user wants current status or future configuration explained.
Do not request the base URL or PAT while the capability is not implemented.

## Reads and writes

There are no Confluence reads or writes. The plugin exposes no tools and its write
collections are empty; enabling the scaffold does not make page operations exist.

## Readiness

`planned-not-implemented` and recommendation-ineligible. Do not claim readiness,
run authentication, or ask the user to configure secrets for a non-runnable port.

## Demonstration

No synthetic, simulated, read-only, approved-live, or other demonstration exists.

## Artifacts

No Confluence result, preview, page, comment, or local artifact is produced.

## Troubleshooting

Correct any claim that manifest registration means tools are available. Preserve
the planned status and do not fabricate setup steps, reads, writes, warnings, or a
safe rerun path.
