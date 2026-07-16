# Supporting capability configuration

This is the configuration source of truth for the documented flows and the implemented `onboard-ericsson-capabilities` router. It separates static secrets, static settings, interactive authentication, permissions, local software/platform requirements, and ordinary workflow inputs. It never contains secret values. See the [onboarding safety policy](onboarding/safety-and-demonstrations.md) for the shared readiness and demonstration rules.

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
| Glean | `GLEAN_API_TOKEN` | Bearer token for the supplied remote MCP endpoint | Internal search when a workflow elects to use Glean |
| Teams | `teams_auth`; optional `ERICSSON_GRAPH_CLIENT_ID` | MSAL device-code sign-in | Teams list/read/send/reply and future notifications |
| Outlook | No API key | Logged-in desktop Outlook through PowerShell→COM | Email search/read/send and inbox digest |
| GitLab | Source flow uses a PAT; Hermes key names are not yet implemented | PAT with `api` scope; optional mTLS | CI audit; Jira→GitLab; defect loop |
| Document parsing/export | Local Python packages | No key | TOL generation; 3PP tracker |
| Opportunity Visuals | Python/local files; optional openpyxl and Playwright/Chromium | No API key | Opportunity progression visual artifacts |
| Pseudonymization | No configuration; explicitly unsupported | None | Historical questions only; no port roadmap |
| Re-Identification | Required protected mapping capability is unavailable | None | Planned, not implemented; no runnable setup |
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
4. If a real comment is later needed, preview the exact issue and text and obtain explicit approval. Never post a comment merely to validate configuration.

Common errors: missing keys; `401` for an invalid/expired token; `403` for insufficient project permission; HTML/SSO responses when the base URL or token type is wrong; network/TLS restrictions on internal Jira.

## Glean MCP

### Current keys

- `GLEAN_API_TOKEN`: bearer token for the supplied endpoint,
  `https://be.everyday-assistant.ericsson.net/mcp/EEA-KIRO-MCP`.

The supplied endpoint is preconfigured in the seeded `glean` entry. The server ships
with `enabled: false` and remains inert until the user configures the token and
intentionally enables it. There is no Glean server code in Loop24 or this repository;
the capability is an external service configuration.

Readiness requires, in order: the token configured, the server intentionally enabled,
a connection established, tools discovered, and then a narrow read-only search. The
onboarding router distinguishes DNS/TLS/network failures, authentication failures, and
a connected server that exposes no expected search tool. The token acquisition process
is organization-owned and must not be guessed.

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

The onboarding router resolves the active brand home instead of assuming `~/.hermes`, confirms the orchestrator skill and selected workflow are installed, runs structural validation, and uses a scratch/read-only lifecycle check before a real run. `report.kanban: auto` is optional and must degrade safely when the Kanban toolset is unavailable. Never edit `state.json` directly to “fix” a run.

## Document parsing and spreadsheet output

TOL Generation and the 3PP tracker require local file access and artifact-writing permission.

- Docling parses PDF, DOCX, PPTX, XLSX, HTML, images, and audio; OCR/table recovery can increase runtime and dependency size.
- `openpyxl>=3.1.5` reads/writes XLSX.
- `python-docx>=1.1.0` supports DOCX-oriented generation components.
- The 3PP source flow uses a sheet name, 1-based column mapping, skip marker, reference URL field, and output filename. Those are workflow inputs/configuration, not secrets.

Before porting, decide whether these packages ship in the main Hermes environment or in an isolated helper/plugin. Validate with synthetic documents that contain no Ericsson data, confirm output paths remain under approved artifact directories, and cap file size/record count.

## Opportunity Visuals

No API key is required for Opportunity Visuals. Python 3.11+ and local file
access provide CSV/JSON plus SVG/HTML. XLSX requires `openpyxl>=3.1.5`. PNG
requires `playwright>=1.52` and a locally installed Chromium browser; when
unavailable, the skill succeeds with SVG/HTML and reports PNG as unavailable.

The local helpers (`inspect`, `analyze`, `prepare`, and `render`) are
deterministic and make no model, network, `image_generate`, web-search, or
remote-renderer calls. Their HTML is generated from escaped data, contains no
scripts or remote resources, and the PNG path denies external requests. The
source CSV/JSON/XLSX remains unchanged.

The model-backed coworker that orchestrates those helpers may receive source
metadata, mapping labels, and minimal stage labels and diagnostics selected
from analyze output. Do not paste confidential rows into chat unless the
configured model and organizational privacy policy permit it. A local helper
guarantee is not a guarantee that pasted or chat-visible content avoids a
hosted model.

### Preflight

Select Python 3.11+ before creating the repository venv. `bootstrap.sh` uses
`python3` and does not enforce its version:

```bash
python3 -c 'import sys; assert sys.version_info >= (3, 11), sys.version'
./bootstrap.sh
.venv/bin/python --version
```

The bootstrap reuses an existing `.venv`. If that environment reports Python
older than 3.11, stop. After preserving anything needed, manually remove or
rename the stale venv, recreate it with a selected Python 3.11+ interpreter
(for example, `/path/to/python3.11 -m venv .venv`), and rerun bootstrap. The
coworker must not remove an environment automatically.

Run preflight with the intended destination before preparing data:

```bash
.venv/bin/python skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py \
  --preflight --output-dir /path/to/new-run
```

The JSON result reports `csv_json`, `xlsx`, `svg_html`, `png_package`,
`chromium`, and `output_directory` independently. A missing optional component
must not be described as failure of another component.

The destination or its nearest existing parent must be writable. Choose a new,
user-approved local directory, especially for confidential data. Preparation
will not overwrite a non-empty run directory, and the renderer will not
overwrite an existing target artifact. If preflight reports `Output directory
is not writable`, ask for another destination or have the user correct its
permissions; do not silently redirect output.

### User-approved installation

Neither the skill nor its renderer installs packages or browsers. After the
user approves local installation, install only the missing capability:

```bash
.venv/bin/python -m pip install 'openpyxl>=3.1.5'
.venv/bin/python -m pip install 'playwright>=1.52'
.venv/bin/python -m playwright install chromium
```

The first command enables XLSX parsing. The second installs the Python
Playwright package; it does not by itself guarantee a Chromium binary. The
third installs Chromium for that Python environment. Re-run preflight after
each relevant change. Enterprise-managed or offline machines should use their
approved package/browser distribution instead of these public installers.
For native Windows, use the complete PowerShell venv, `$Python`, `$RunRoot`,
analyze, and render sequence in the [reproducible
showcase](showcases/opportunity-visuals.md#native-windows-powershell). Do not
paste POSIX continuations or `RUN_ROOT=...` syntax into PowerShell.

### Independent failure guidance

- `openpyxl is unavailable`: CSV/JSON and SVG/HTML still work. Install
  `openpyxl>=3.1.5` with approval or provide CSV/JSON instead of XLSX.
- `Playwright package is unavailable`: SVG/HTML still work and `--png auto`
  reports PNG unavailable. Install `playwright>=1.52` with approval if PNG is
  needed.
- `Chromium is unavailable`: Playwright is importable but cannot launch its
  local Chromium. Use the approved `.venv/bin/python -m playwright install chromium`
  path or the organization's managed browser setup, then rerun preflight.
- `Output directory is not writable`: choose a writable, approved local
  destination or correct permissions. Do not retry in a shared directory.

With `--png auto`, either Playwright or Chromium failure preserves successful
SVG/HTML and records the reason in `render-manifest.json`. With `--png
required`, the same condition returns `png_unavailable`. See the
[reproducible showcase](showcases/opportunity-visuals.md) for commands and
visual verification.

## Pseudonymization and Re-Identification

Pseudonymization is `not-supported-no-port-planned`. It has no Co-Worker
configuration, runnable implementation, demonstration, or setup recipe. The legacy
dependency list is historical context only and must not be presented as an
installation path.

Re-Identification remains `planned-not-implemented` and non-runnable. It requires a
protected token-to-original mapping produced by a corresponding pseudonymization
implementation; that mapping dependency is unavailable. Do not request an
anonymized file, session identifier, original values, or configuration. This fact
does not create or imply a new roadmap decision.

## Windows diagnostics and PowerShell

The source flow runs `utils/system_diagnostic.ps1` without elevation and with a 300-second timeout, then asks an LLM to interpret the report. A port should bundle and hash/review the exact script rather than expose a generic arbitrary-PowerShell tool. Any future elevation must explain why and require a visible user confirmation.

Validation should run read-only collection, confirm timeout/cancellation, redact usernames/paths/network identifiers from shared diagnostics, and save reports to the user's artifact area. PowerShell missing, execution-policy restrictions, UAC cancellation, timeout, and partial report generation need distinct guidance.

## Additional Loop24 source capabilities

Loop24 also contains SharePoint and Confluence utilities/components that are not directly wired into the eleven JSON flows in this inventory. They are future capability inputs, not current requirements:

- SharePoint utilities use Microsoft Graph with cached Azure/MSAL identity, Azure CLI fallback, or interactive browser login. A Hermes port should reuse an approved Graph identity surface rather than create another token cache.
- Confluence retrieval can use Playwright and an interactive SSO browser session. A port must not export cookies or ask users to paste session cookies; it needs a separately approved auth and sandbox design.
- Document-generation components use `python-docx` and the active model to extract structure, generate changed sections, assemble a DOCX, and report a diff. No cataloged flow currently wires that entire pipeline.

Document these as their own flow/capability pages when a concrete port is selected. Do not imply they are installed merely because their source components exist.

## Delivery and readiness contract

Ericsson capabilities are baked into every profile. There is no Ericsson-specific
toggle or disabled-by-default delivery declaration. Readiness still depends on the
selected capability's current platform, protected settings, authentication,
permissions, dependencies, and safe probe. The router never treats a configured
name as proof that its value is valid or authorized.
