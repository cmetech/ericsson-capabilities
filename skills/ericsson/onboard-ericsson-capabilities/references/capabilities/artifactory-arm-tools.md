---
id: artifactory-arm-tools
display_name: Ericsson Artifactory/ARM Tools (Planned)
aliases: [Ericsson ARM, Ericsson Artifactory, Artifactory connector scaffold]
goals:
  - Explain the current status of the Ericsson Artifactory/ARM connector scaffold.
  - Review the configuration that a future Artifactory connector will require.
  - Tell me whether Artifactory tools, reads, writes, or demonstrations are runnable today.
maturity: planned-not-implemented
recommendation_eligible: false
source_flows: []
implementation:
  skills: []
  plugins: [plugins/ericsson-arm]
  mcp_servers: []
  workflows: []
  tools: []
platforms: [macos, linux, windows]
configuration:
  - name: base_url
    kind: static-setting
    required: true
    guidance: A future implementation will require the exact Artifactory HTTP(S) origin.
  - name: auth_mode
    kind: static-setting
    required: true
    guidance: A future implementation will require an explicit bearer or API-key header mode.
  - name: token
    kind: static-secret
    required: true
    guidance: A future implementation will store the Artifactory token only through the protected secret field.
  - name: client_cert_path
    kind: static-setting
    required: false
    guidance: A future implementation may use an optional bounded mTLS certificate path together with its key.
  - name: client_key_path
    kind: static-setting
    required: false
    guidance: A future implementation may use an optional bounded mTLS key path together with its certificate.
  - name: deploy_root
    kind: static-setting
    required: false
    guidance: A future implementation may use an optional local source boundary for approved deployments.
  - name: max_deploy_megabytes
    kind: static-setting
    required: false
    guidance: A future implementation may use this optional bounded upload-size setting.
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
troubleshooting: [planned scaffold mistaken for a runnable connector, premature configuration request, unsupported artifact operation or demonstration claim]
---

# Ericsson Artifactory/ARM Tools (Planned)

## What it solves

This status entry explains the registered, disabled-by-default Artifactory/ARM
plugin scaffold. It has configuration metadata and shared foundations, but no
runnable tools, reads, writes, skills, workflows, or demonstrations yet.

## Try saying

- “Is the Ericsson Artifactory/ARM connector runnable yet?”
- “What configuration fields are represented by the ARM scaffold?”
- “Can you search, download, deploy, or delete an artifact today?”

There is no runnable repository filter, deployment preview, output format,
artifact destination, exclusion, warning-processing, or rerun flow yet. Treat
those requests as status questions, not permission to invent an operation.

## Questions

Ask only whether the user wants current status or future configuration explained.
Do not request an origin, token, certificate, key, or local deploy path while the
capability is not implemented.

## Reads and writes

There are no Artifactory reads or writes. The plugin exposes no tools and its
write collections are empty; enabling the scaffold does not create artifact
operations.

## Readiness

`planned-not-implemented` and recommendation-ineligible. Do not claim readiness,
run authentication, or ask the user to configure secrets for a non-runnable port.

## Demonstration

No synthetic, simulated, read-only, approved-live, or other demonstration exists.

## Artifacts

No repository result, preview, uploaded or downloaded artifact, or local output is
created.

## Troubleshooting

Correct any claim that manifest registration means tools are available. Preserve
the planned status and do not fabricate setup steps, reads, writes, warnings, or a
safe rerun path.
