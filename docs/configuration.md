# Supporting capability configuration

This is the configuration source of truth for the documented flows and the implemented `onboard-ericsson-capabilities` router. It separates static secrets, static settings, interactive authentication, permissions, local software/platform requirements, and ordinary workflow inputs. It never contains secret values. See the [onboarding safety policy](onboarding/safety-and-demonstrations.md) for the shared readiness and demonstration rules.

## Safety rules

1. Store static secrets through the OTTO/LOOP24 Keys interface or the product's protected environment file, never in workflow YAML, prompts, chat transcripts, source files, or this documentation.
2. A setup assistant may ask whether a value is configured, open the appropriate configuration surface, and run a non-destructive validation. It must not ask the user to paste a token into ordinary chat.
3. Redact tokens, authorization headers, cookies, certificate contents, email bodies, and document contents from diagnostics.
4. Prefer least privilege. Write-capable Jira, GitLab, Confluence, ARM, Teams,
   and Outlook operations require explicit user intent; preview/draft or approval
   steps should precede consequential writes.
5. Treat source Langflow field names and planned Hermes keys as different contracts. A planned key is not available until it is added to the capability manifest and implementation.

## Quick readiness matrix

| Capability | Current configuration | Authentication form | Used by |
|---|---|---|---|
| Jira | Standalone Tools settings plus protected PAT or API token | Bearer PAT or basic email/API-token | Ticket summary; Jira→GitLab; single-ticket triage |
| Glean | `GLEAN_API_TOKEN` | Bearer token for the supplied remote MCP endpoint | Internal search when a workflow elects to use Glean |
| Teams | `teams_auth`; optional `ERICSSON_GRAPH_CLIENT_ID` | MSAL device-code sign-in | Teams list/read/send/reply and future notifications |
| Outlook | No API key | Logged-in desktop Outlook through PowerShell→COM | Email search/read/send and inbox digest |
| GitLab | `origin`, protected `pat`; optional `client_certificate_path` and `client_key_path` | PAT with appropriate scope; optional mTLS | Repository research; CI inspection; Jira→GitLab |
| Confluence | `base_url`, protected `pat`; optional `api_base_override` | Bearer PAT | Bounded page research and authoring |
| ARM/Artifactory | `base_url`, `auth_mode`, protected `token`; optional mTLS paths and `deploy_root` | Bearer token or `X-JFrog-Art-Api`; optional mTLS | Repository/artifact research, deployment, and deletion |
| SharePoint | Profile-scoped connector settings and protected secret storage | Delegated MSAL, app-only, or existing Azure CLI identity; enrolled browser only for audits | Bounded files/folders, owned sites, and permission audits |
| Document parsing/export | Local Python packages | No key | TOL generation; 3PP tracker |
| Opportunity Visuals | Python/local files; optional openpyxl and Playwright/Chromium | No API key | Opportunity progression visual artifacts |
| Pseudonymization | No configuration; explicitly unsupported | None | Historical questions only; no port roadmap |
| Re-Identification | Required protected mapping capability is unavailable | None | Planned, not implemented; no runnable setup |
| Windows diagnostics | PowerShell and reviewed local script | No key; elevation only when justified | Windows Laptop Diagnostic |
| Workflow engine | Baked skills/workflows under the active `HERMES_HOME` | No key | All deterministic workflow ports |
| Hermes model | Product-level provider/model configuration | Provider-specific, outside this capability set | All prompt nodes |

## Plugin lifecycle and profile defaults

`sets/ericsson.json` distinguishes existing backend infrastructure from standalone
connectors without a capability-set toggle:

- a string in `plugins[]` is an existing enabled backend; the Teams entry retains its
  current behavior, `plugins/workflow` records Hermes' enabled built-in workflow
  backend, and `plugins/ericsson-connector-cli` is the always-loaded direct-command
  facade;
- a `{path, id, enabled: false}` object is a standalone connector bundled for explicit
  per-profile opt-in. Every new profile starts every such connector disabled; and
- optional `lifecycleMigration` metadata is reserved for a disabled standalone connector
  that had previously been auto-seeded. Its stable id and exact
  `from: auto_seeded_backend` transition live only in the manifest.

Do not use connector metadata to disable source skills or workflows, add a set-wide
`disabledByDefault` switch, or infer that a declared connector is implemented. Jira,
GitLab, Confluence, and ARM have standalone lifecycle objects with `enabled: false`.
Jira declares the one-time
`ericsson-jira-backend-to-standalone-v1` transition that removes only historical
automatic enablement and records its completion. Existing Jira settings or credentials
never imply consent to enable the connector. Every standalone connector remains disabled
until explicit per-profile opt-in. SharePoint has its own standalone lifecycle contract.

## Direct connector CLI

`ericsson-connector-cli` is an always-loaded backend string entry, not a
standalone connector. It owns the `jira`, `gitlab`, `confluence`, and `arm`
command trees for OTTO and LOOP24, so help remains available while a standalone
connector is disabled. Do not enable `ericsson-connector-cli`; it has no
credentials or configuration of its own. Execution resolves the active profile
and requires the selected standalone connector to be enabled, configured, and
ready.

Natural-language CLI/TUI use and direct shell use coexist. The agent-facing tool
adapter and direct adapter use the same connector application executor after
their separate authority checks. Direct commands are model-free and deterministic;
they do not add a second configuration path. Replace `<brand>` with `otto` or
`loop24`:

```bash
<brand> jira issue get ERIC-123
<brand> gitlab pipeline view group/project 918 --json
<brand> confluence page update 12345 --body-file page.md --dry-run
<brand> arm artifact deploy release-local team/app.tgz --file app.tgz --confirm
```

Connector credentials, origins, certificate paths, or profile selection on argv
are forbidden. Store those values in the active profile's protected Tools
configuration and switch profiles with the existing product commands. Large or
structured content uses bounded file/stdin inputs rather than secrets or content
embedded in process listings. Every write requires exactly one of `--dry-run`
and `--confirm`: omission or conflict is rejected before file reads,
configuration, provider lookup, or network activity.

With `--json`, stdout contains exactly one `ericsson.connector-cli/v1` envelope.
The exact success shape is:

```json
{"schema_version":"ericsson.connector-cli/v1","ok":true,"connector":"jira","operation":"jira_get_issue","mode":"read","data":{},"warnings":[],"meta":{}}
```

The exact error shape replaces `data`, `warnings`, and `meta` with
`"error":{"category":"...","message":"..."}` and may add one bounded
`remediation` string inside `error`:

```json
{"schema_version":"ericsson.connector-cli/v1","ok":false,"connector":"gitlab","operation":"gitlab_retry_pipeline","mode":"confirm","error":{"category":"write_ambiguous","message":"The write outcome is unknown.","remediation":"Reconcile remote state before another write."}}
```

Human output is terminal-sanitized and bounded; JSON output is also structurally
and size bounded. The stable exit codes are `0` for success,
`2` for usage/schema/local-input/intent failure, `3` for disabled or unready
configuration, `4` for a classified connector failure, and `5` for
`write_ambiguous`. Exit code `5` means the remote write outcome is unknown:
reconcile remote state with a safe read and never blindly retry it.

The reviewed source-command mapping and all supported gaps are in
`docs/cli-migration/supercli-0.14.1.md`. Existing SuperCLI scripts are not
drop-in compatible.

## Jira

### Standalone Tools configuration

Enable `ericsson-jira` explicitly for each intended profile, then configure it through
the product's Tools UI or `hermes tools`. Set the Jira base URL, authentication mode,
REST preference, transport, timeout, and finite result default as ordinary settings.
Enter either a bearer PAT or a basic-auth API token through the protected secret editor;
basic auth also requires the Jira account email. Secret values are write-only and are
never projected back into the UI, CLI output, logs, or tool results. Do not put Jira
credentials in `.env`, workflow YAML, prompts, or chat.

The plugin exposes 15 operations: eight bounded reads for assigned work, JQL
search, issue details, fields, project metadata, transitions, assignable users,
and link types; plus seven writes for comments, transitions, assignment, bounded
field or label changes, issue creation, and issue links. Qualified
`ericsson-jira:ticket-research` and `ericsson-jira:defect-triage` guidance appears
only while the plugin is enabled. Reads require the corresponding Jira permission;
writes additionally require exact direct-command intent or model admission.

### Configure and validate

1. Obtain a token through the organization's approved Jira token process. Do not reuse a browser cookie.
2. Enable the connector and save settings and secrets through Tools.
3. Validate with a read-only call such as `jira_my_tickets` with a small result limit.
4. If a real comment is later needed, preview the exact issue and text and obtain explicit approval. Never post a comment merely to validate configuration.

Common errors: missing keys; `401` for an invalid/expired token; `403` for insufficient project permission; HTML/SSO responses when the base URL or token type is wrong; network/TLS restrictions on internal Jira.

The native transport is the default. `auto` selects the private curl compatibility
path only for the bounded proven Cloudflare error-1010 response; other deployments
that require it must explicitly select `curl` and an approved executable. Transport
selection never weakens origin, timeout, output, cancellation, or secret boundaries.

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

The current plugin uses `teams_auth` and an MSAL public-client device-code flow. It
caches refreshable authentication at
`$HERMES_HOME/ericsson/msal_token_cache.json`.

- No client secret is required.
- `ERICSSON_GRAPH_CLIENT_ID` optionally overrides the built-in public client ID when the organization supplies another app registration.
- The user starts `teams_auth`, opens the verification URL, enters the device code, completes sign-in, then calls `teams_auth` again with completion requested.
- `teams_list` and `teams_channels` are safe readiness checks. Read/send/reply permissions depend on tenant consent and Graph policy.

### Windows cache boundary

On Windows, the cache parent directory, each publication temporary, and the final
cache file use the Hermes generic protected current-user ACL. The rule is applied
and verified while the artifact is handled: the current user owns it, inheritance
is protected, and access is restricted to the current user. A normal standard-user
session is the supported environment; neither elevation nor `SeSecurityPrivilege`
is required.

The cache is an interactive-session artifact, not a plugin descriptor secret and
not a substitute for protected Tools & Keys configuration. It is also independent
of `hermes secrets doctor --write-probe`, which exercises the core secret-store
write probe rather than the Teams MSAL cache. Do not use that probe as evidence
that Teams sign-in storage is healthy, and do not copy, edit, or inspect cache
contents to troubleshoot sign-in.

Never paste a device code, token, cache content, or authentication response into
chat, logs, or diagnostics. An ACL, ownership, path-type, or reparse-point failure
fails closed: the plugin does not use an unprotected cache. Correct the local
filesystem condition through the approved support process, remove the disposable
test session when appropriate, and run `teams_auth` again to create a fresh
session. The installed-release procedure is documented in
[Windows Teams cache release validation](onboarding/windows-teams-cache-release-validation.md).

The original Langflow components sometimes used a short-lived Graph Explorer token file for `ChannelMessage.Read.All`. That is source-only behavior and should not be reproduced casually: raw bearer-token files expire quickly and increase exposure. The Hermes target should use approved delegated permissions and actionable consent guidance.

## SharePoint connector

`ericsson-sharepoint` is a standalone connector and is disabled by default.
Enable it explicitly, then configure it through the plugin configuration
surface. Non-secret settings include the exact `*.sharepoint.com` tenant host,
authentication mode, tenant/client identifiers, Graph scopes, authority,
operation limits, authorized local roots, and the name of a Hermes enrolled
browser profile. An app-only client secret is write-only protected storage; it
does not belong in `.env`, chat, workflow YAML, or diagnostics.

Delegated MSAL is the normal interactive mode. `authenticate` is an explicit
interactive setup action and writes its bounded private cache beneath the
active Hermes profile. `test_connection` is silent and never starts sign-in.
App-only mode requires a complete tenant/client/secret plus one `.default`
scope. Azure CLI mode reuses Hermes' existing Azure identity adapter and does
not copy or invoke a second token store.

The permission audit has a separate browser readiness facet. Configure a named
core-owned enrolled browser profile whose trusted origins include the tenant,
then invoke `enroll_browser` interactively. Graph file and owned-site operations
may remain ready while audit readiness reports `browser_enrollment_required`.
The connector does not own a CDP port, browser executable, profile directory,
or browser launcher, and `clear_session` releases only a session the connector
acquired through the core browser manager.

The source-owned `sharepoint` router remains discoverable while the connector
is disabled and directs an enabled fresh conversation to qualified plugin
skills. `sharepoint-document-intake` uses a flat
`requires: [ericsson-sharepoint]` admission declaration and exact node tool
allowlist. It stops at bounded artifact acquisition; parsing, OCR,
interpretation, conversion, and generation belong to a separate document
capability.

## Outlook MCP

Outlook needs no API key or Azure app registration. It automates the locally logged-in Outlook desktop session.

Requirements:

- Windows with classic desktop Outlook running, signed in, online, and able to access the intended mailbox;
- PowerShell available (`powershell.exe` is used by the ported server);
- Python can launch the bundled MCP server;
- when invoked through WSL, Windows interoperability and Windows paths must work.

Validate in increasing-risk order: start the MCP server/list its tools; list mailboxes; list a small number of messages; read one known message; only then test draft/send/calendar mutations with explicit approval. Distinguish “MCP server did not start,” “PowerShell unavailable,” “Outlook COM unavailable,” “Outlook closed/offline,” and “mailbox item not found.”

## GitLab

The Loop24 flows accept a GitLab personal access token in each component and require `api` scope for project discovery, repository reads, branch/commit creation, merge requests, CI variables, and review data. Some internal deployments also use an mTLS client certificate and key beneath `~/.config/edpctl/auth/`.

The manifest bundles `ericsson-gitlab` at `plugins/ericsson-gitlab` with `enabled: false` and no migration from an older auto-seeded backend. Enable it explicitly, configure the exact HTTP(S) `origin` and protected `pat`, and optionally configure both `client_certificate_path` and `client_key_path`. The optional pair must identify bounded regular files and load as a matching certificate/key pair; certificate contents never enter diagnostics.

After enablement start a fresh conversation, then validate by resolving a permitted project and reading its default branch before bounded repository or CI inspection. Only with explicit intent, a dry-run preview, and host approval should a test project receive a branch, atomic commit, or merge request. Never validate by pushing to a production default branch. Use least privilege supported by the server; the full write path commonly requires GitLab `api`.

The 30-operation surface contains 18 bounded reads and 12 writes. Reads cover
project/group discovery, repository files and trees, commits and feedback, merge
requests and discussions, exact pipeline metadata, job-log tails, approval state,
and CI structure without variable values. Writes cover ticket-derived and explicitly
named branches, atomic commits, merge-request creation/review/approval/SHA-pinned
merge/update, and one-shot CI recovery. A named branch resolves its ref to an exact
commit identity; a conflicting existing branch is not reused. Enabled profiles also
receive the qualified `ericsson-gitlab:repository-research`,
`ericsson-gitlab:merge-request-review`, and
`ericsson-gitlab:ci-investigation` skills, plus the qualified
`ericsson-gitlab:gitlab-activity-digest` skill. The reviewed cross-connector
workflow is `jira-to-gitlab`.

## Confluence

`ericsson-confluence` is a standalone connector and is disabled by default. Enable
it for the intended profile, configure the exact HTTP(S) `base_url`, and store the
bearer `pat` through the protected write-only Tools field. Confluence Cloud normally
includes `/wiki` in the configured origin. Use `api_base_override` only for a
deployment whose REST route cannot be derived, and keep timeout/result defaults
inside their documented finite ranges.

The nine-operation surface provides six bounded reads for CQL search, spaces,
pages, page bodies, direct children, and comments, plus three writes for page create,
optimistic-concurrency update, and comments. Remote page/comment content remains
untrusted data. Markdown writes escape raw HTML and macro markup before storage.
Every write requires a dry-run or confirmation and preserves version conflicts and
ambiguous outcomes.

After configuration, start a fresh conversation and validate with a small read-only
space list or CQL search. Do not use a page/comment write to test readiness. The
qualified `ericsson-confluence:page-research` skill is available only while the
connector is enabled. Browser-based research is a read-only fallback for deployments
whose PAT route is blocked by interactive SSO; it does not replace connector writes.

## ARM/Artifactory

`ericsson-arm` is a standalone connector and is disabled by default. Configure the
exact Artifactory origin as `base_url`, choose `bearer` or `api_key` authentication,
and store the token in protected write-only storage. When the edge requires mTLS,
configure both `client_cert_path` and `client_key_path`; certificate expiry and
edge-authentication failure are checked and classified separately from token
authentication.

The six-operation surface provides bounded repository listing, artifact/folder
metadata, build properties, and AQL search, plus checksum-first deployment and exact
path deletion. AQL input cannot include its own `.limit()` clause. Deployment reads
one bounded regular file, attempts checksum publication first, and falls back to a
full upload only when necessary. An optional `deploy_root` confines upload sources
with POSIX descriptor traversal and fails closed on Windows and unsupported
platforms. Configure `max_deploy_megabytes`, request timeout, and result defaults
only within their schema bounds.

Start a fresh conversation after enablement/configuration and validate with a
read-only repository or artifact lookup. Never deploy or delete merely to prove
readiness. The qualified `ericsson-arm:artifact-research` skill appears only while
the connector is enabled. Any uncertain deployment or deletion remains
`write_ambiguous` and must not be blindly retried.

## Model and embedded Langflow LLM settings

Loop24 flows contain ACP/Ollama base URLs and sometimes expose `ANTHROPIC_API_KEY` or `OPENAI_API_KEY` at the Langflow platform level. These are source-only flow-runtime settings. In Hermes, prompt nodes use the user's active model/provider and must not introduce a second per-flow LLM key. A flow may document model-quality or context-size needs, but configuration stays with the product's normal model setup.

## Workflow engine and artifact locations

Hermes' built-in workflow backend and skills require no API key. The manifest records that backend as the enabled string entry `plugins/workflow`; it is not a standalone connector. Baked startup seeding copies reference workflow YAML into the active brand's `$HERMES_HOME/workflows/`; run state and node artifacts live below that workflow area. Historical source workflows remain validation/read-compatibility inputs while the portable workflow package becomes the accepted runtime shape.

The onboarding router resolves the active brand home instead of assuming `~/.hermes`, confirms the built-in workflow capability and selected workflow are installed, runs structural validation, and uses a scratch/read-only lifecycle check before a real run. `report.kanban: auto` is optional and must degrade safely when the Kanban toolset is unavailable. Never edit workflow state directly to “fix” a run.

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

Loop24 also contains utilities/components that are not directly wired into the
eleven JSON flows in this inventory. Their source presence is context, not proof
that an unrelated end-to-end flow is implemented:

- SharePoint utilities use Microsoft Graph with cached Azure/MSAL identity, Azure CLI fallback, or interactive browser login. A Hermes port should reuse an approved Graph identity surface rather than create another token cache.
- Historical Confluence retrieval can use Playwright and an interactive SSO browser
  session. The implemented connector now owns bounded PAT-backed reads and writes;
  the enrolled-browser path remains a separately bounded read-only fallback and
  must never export cookies or ask users to paste session cookies.
- Document-generation components use `python-docx` and the active model to extract structure, generate changed sections, assemble a DOCX, and report a diff. No cataloged flow currently wires that entire pipeline.

Document these as their own flow/capability pages when a concrete port is selected. Do not imply they are installed merely because their source components exist.

## Delivery and readiness contract

Ericsson capabilities are baked into every profile. There is no Ericsson-specific
toggle or disabled-by-default delivery declaration. Readiness still depends on the
selected capability's current platform, protected settings, authentication,
permissions, dependencies, and safe probe. The router never treats a configured
name as proof that its value is valid or authorized.
