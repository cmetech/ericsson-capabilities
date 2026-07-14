# Supporting capability configuration

This is the configuration source of truth for the documented flows and for a future Hermes setup-assistant skill. It covers static keys, interactive authentication, local software, permissions, and planned dependencies. It never contains secret values.

## Safety rules

1. Store static secrets through the OTTO/LOOP24 Keys interface or the product's protected environment file, never in workflow YAML, prompts, chat transcripts, source files, or this documentation.
2. A setup assistant may ask whether a value is configured, open the appropriate configuration surface, and run a non-destructive validation. It must not ask the user to paste a token into ordinary chat.
3. Redact tokens, authorization headers, cookies, certificate contents, email bodies, and document contents from diagnostics.
4. Prefer least privilege. Write-capable Jira, GitLab, Teams, and Outlook operations require explicit user intent; preview/draft or approval steps should precede consequential writes.
5. Treat source Langflow field names and planned Hermes keys as different contracts. A planned key is not available until it is added to the capability manifest and implementation.

## Quick readiness matrix

| Capability | Current configuration | Authentication form | Used by |
|---|---|---|---|
| Jira | `JIRA_BASE_URL`, `JIRA_PAT` | Static PAT/API token | Ticket summary; Jira→GitLab; defect loop |
| Glean | `GLEAN_MCP_URL`, `GLEAN_API_TOKEN` | Remote MCP URL and bearer token | Internal search when a workflow elects to use Glean |
| Teams | `teams_auth`; optional `ERICSSON_GRAPH_CLIENT_ID` | MSAL device-code sign-in | Teams list/read/send/reply and future notifications |
| Outlook | No API key | Logged-in desktop Outlook through PowerShell→COM | Email search/read/send and inbox digest |
| GitLab | Source flow uses a PAT; Hermes key names are not yet implemented | PAT with `api` scope; optional mTLS | CI audit; Jira→GitLab; defect loop |
| Document parsing/export | Local Python packages | No key | TOL generation; 3PP tracker |
| Branded visual rendering | Playwright/Chromium; active Hermes model | No flow-specific key | Image Generation |
| Privacy vault | Local NLP models and protected mapping database | No key | Pseudonymization and re-identification |
| Windows diagnostics | PowerShell and reviewed local script | No key; elevation only when justified | Windows Laptop Diagnostic |
| Workflow engine | Baked skills/workflows under the active `HERMES_HOME` | No key | All deterministic workflow ports |
| Hermes model | Product-level provider/model configuration | Provider-specific, outside this capability set | All prompt nodes |

## Jira

### Current keys

- `JIRA_BASE_URL`: Jira origin/base path used by REST API v2, without a trailing slash.
- `JIRA_PAT`: bearer personal access token or compatible Jira token. It is marked as a password in the capability manifest.

The current plugin exposes `jira_my_tickets`, `jira_get_issue`, and `jira_add_comment`. It is available only when both values are present. The PAT must be able to browse assigned issues; comment permission is additionally required for `jira_add_comment` and the future defect-fix flow.

### Configure and validate

1. Obtain a token through the organization's approved Jira token process. Do not reuse a browser cookie.
2. Add the base URL and token through Keys.
3. Validate with a read-only call such as `jira_my_tickets` with a small result limit.
4. If write behavior is needed, confirm the target issue and use a harmless test issue or explicit approval before validating comments.

Common errors: missing keys; `401` for an invalid/expired token; `403` for insufficient project permission; HTML/SSO responses when the base URL or token type is wrong; network/TLS restrictions on internal Jira.

## Glean MCP

### Current keys

- `GLEAN_MCP_URL`: organization-provided remote MCP endpoint.
- `GLEAN_API_TOKEN`: bearer token for that endpoint.

The seeded `glean` entry remains inert until both placeholders resolve. There is no Glean server code in Loop24 or this repository; the capability is an external service configuration.

Configure the values through Keys, then validate by connecting to the MCP server and listing tools before attempting a search. A future assistant should distinguish DNS/TLS/network failures, authentication failures, and a connected server that exposes no expected search tool. The endpoint and token acquisition process are organization-owned and must not be guessed.

## Teams and Microsoft Graph

The current plugin uses `teams_auth` and an MSAL public-client device-code flow. It caches refreshable authentication beneath the active `HERMES_HOME` in `ericsson/msal_token_cache.json`.

- No client secret is required.
- `ERICSSON_GRAPH_CLIENT_ID` optionally overrides the built-in public client ID when the organization supplies another app registration.
- The user starts `teams_auth`, opens the verification URL, enters the device code, completes sign-in, then calls `teams_auth` again with completion requested.
- `teams_list` and `teams_channels` are safe readiness checks. Read/send/reply permissions depend on tenant consent and Graph policy.

The original Langflow components sometimes used a short-lived Graph Explorer token file for `ChannelMessage.Read.All`. That is source-only behavior and should not be reproduced casually: raw bearer-token files expire quickly and increase exposure. The Hermes target should use approved delegated permissions and actionable consent guidance.

## Outlook MCP

Outlook needs no API key or Azure app registration. It automates the locally logged-in Outlook desktop session.

Requirements:

- Windows with classic desktop Outlook running, signed in, online, and able to access the intended mailbox;
- PowerShell available (`powershell.exe` is used by the ported server);
- Python can launch the bundled MCP server;
- when invoked through WSL, Windows interoperability and Windows paths must work.

Validate in increasing-risk order: start the MCP server/list its tools; list mailboxes; list a small number of messages; read one known message; only then test draft/send/calendar mutations with explicit approval. Distinguish “MCP server did not start,” “PowerShell unavailable,” “Outlook COM unavailable,” “Outlook closed/offline,” and “mailbox item not found.”

## GitLab (planned Hermes capability)

The Loop24 flows accept a GitLab personal access token in each component and require `api` scope for project discovery, repository reads, branch/commit creation, merge requests, CI variables, and review data. Some internal deployments also use an mTLS client certificate and key beneath `~/.config/edpctl/auth/`.

No GitLab capability or manifest keys currently exist in `ericsson-capabilities`. The port design must choose stable names—likely a base URL plus secret PAT—and add them to the manifest before a setup skill presents them as available. It must also decide whether certificates are file paths, environment configuration, or delegated to an existing GitLab client.

Validation should be staged: identify the current user; resolve a permitted project; read its default branch; list repository files; inspect CI metadata; then, only with approval and a test project, create a branch/MR. Never test by pushing to a production default branch. Expected permission for the full write path is GitLab `api`; a read-only auditor should use a narrower token if the server supports it.

## Model and embedded Langflow LLM settings

Loop24 flows contain ACP/Ollama base URLs and sometimes expose `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` at the Langflow platform level. These are source-only flow-runtime settings. In Hermes, prompt nodes use the user's active model/provider and must not introduce a second per-flow LLM key. A flow may document model-quality or context-size needs, but configuration stays with the product's normal model setup.

## Workflow engine and artifact locations

The workflow orchestrator and builder require no API key. Baked startup seeding copies reference workflow YAML into the active brand's `$HERMES_HOME/workflows/`; run state and node artifacts live below that workflow area. `workflow_ctl.py` requires Python plus PyYAML and is the only supported writer of workflow run state.

A setup assistant should resolve the active brand home instead of assuming `~/.hermes`, confirm the orchestrator skill and selected workflow are installed/enabled, run structural validation, and use a scratch/read-only lifecycle check before a real run. `report.kanban: auto` is optional and must degrade safely when the Kanban toolset is unavailable. Never edit `state.json` directly to “fix” a run.

## Document parsing and spreadsheet output

TOL Generation and the 3PP tracker require local file access and artifact-writing permission.

- Docling parses PDF, DOCX, PPTX, XLSX, HTML, images, and audio; OCR/table recovery can increase runtime and dependency size.
- `openpyxl>=3.1.5` reads/writes XLSX.
- `python-docx>=1.1.0` supports DOCX-oriented generation components.
- The 3PP source flow uses a sheet name, 1-based column mapping, skip marker, reference URL field, and output filename. Those are workflow inputs/configuration, not secrets.

Before porting, decide whether these packages ship in the main Hermes environment or in an isolated helper/plugin. Validate with synthetic documents that contain no Ericsson data, confirm output paths remain under approved artifact directories, and cap file size/record count.

## Branded visual rendering

The source Image Generation flow has the active LLM produce HTML and uses Playwright with headless Chromium to screenshot it as PNG/JPEG. Requirements are `playwright` plus `playwright install chromium`, writable temporary/output directories, and a trusted HTML-rendering boundary.

The port must decide whether the requested result is a data-driven branded infographic (HTML renderer remains relevant) or an illustrative image (Hermes native image generation may be a better fit). Do not render untrusted HTML with network/file access enabled without sandboxing.

## Privacy vault

No API key is required. The source implementation uses Presidio, spaCy `en_core_web_lg`, optional `en_core_web_sm` plus `dslim/bert-base-NER`, SQLite, and document/PDF libraries. The transformer model may download from Hugging Face on first use; enterprise/offline packaging must account for that.

The mapping database contains the original sensitive values and is more sensitive than the anonymized output. The port must store it beneath a protected per-brand home, restrict permissions, avoid syncing it, define retention/deletion, and bind every mapping to a session key. Re-identification must fail closed when the mapping is missing or ambiguous. Use synthetic PII for validation.

## Windows diagnostics and PowerShell

The source flow runs `utils/system_diagnostic.ps1` without elevation and with a 300-second timeout, then asks an LLM to interpret the report. A port should bundle and hash/review the exact script rather than expose a generic arbitrary-PowerShell tool. Any future elevation must explain why and require a visible user confirmation.

Validation should run read-only collection, confirm timeout/cancellation, redact usernames/paths/network identifiers from shared diagnostics, and save reports to the user's artifact area. PowerShell missing, execution-policy restrictions, UAC cancellation, timeout, and partial report generation need distinct guidance.

## Additional Loop24 source capabilities

Loop24 also contains SharePoint and Confluence utilities/components that are not directly wired into the eleven JSON flows in this inventory. They are future capability inputs, not current requirements:

- SharePoint utilities use Microsoft Graph with cached Azure/MSAL identity, Azure CLI fallback, or interactive browser login. A Hermes port should reuse an approved Graph identity surface rather than create another token cache.
- Confluence retrieval can use Playwright and an interactive SSO browser session. A port must not export cookies or ask users to paste session cookies; it needs a separately approved auth and sandbox design.
- Document-generation components use `python-docx` and the active model to extract structure, generate changed sections, assemble a DOCX, and report a diff. No cataloged flow currently wires that entire pipeline.

Document these as their own flow/capability pages when a concrete port is selected. Do not imply they are installed merely because their source components exist.

## Known configuration inconsistency

The approved delivery design says Ericsson content is baked into OTTO/LOOP24 with no `ERICSSON_ENV` toggle. Current Jira and Teams runtime checks follow that design, but the source/vendored manifest, plugin metadata, README, and both reference workflows still contain stale `ERICSSON_ENV` or disabled-by-default declarations. Baked seeding does not use the manifest gate, but workflow validation can still treat `ERICSSON_ENV` as required.

Until corrected, a setup assistant must describe this as compatibility debt—not as the desired architecture. It may explain a temporary environment workaround when a shipped workflow is blocked, but the durable fix is to remove stale declarations, re-vendor, test, and release consistently.
