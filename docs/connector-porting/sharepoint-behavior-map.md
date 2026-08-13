# SharePoint Connector Behavior Map

This map freezes the SharePoint behavior inspected before the Ericsson
connector port. It is the source for the named behavior tests in Tasks 2-9;
an omission from a tool list does not silently discard a legacy behavior.

## Source identity

- Legacy repository: `sd-americas-css/sd-americas-ai/loop_24`
- Inspected commit: `fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6`
- Accepted connector snapshot: `8ca26f882bc461d9aaa80a252685568c8749394a`
- Relationship: the accepted snapshot is an ancestor of the inspected commit.
- The three inspected SharePoint files are byte-identical between those two
  commits. Their blobs at the inspected commit are:
  - `utils/sp_files.py`: `4aac0bbcb5ba60a524538a6520b0c01b8f410f78`
  - `utils/sp_audit.py`: `b47bea87e975bcfc487fb6d926a3657f303c1803`
  - `custom_components/ericsson_parsers/sharepoint_files_fetcher.py`:
    `c119eee6af9ddc3f67024be7eb6bc4b698212c73`
- Current Hermes baseline: `da59906aaad8f9cb023fb66426c6f60ff5afa04a`
- Current Ericsson baseline: `dae405ede7049b621e502d9259f97481c940a65b`

The legacy files were read with `git show <commit>:<path>`; the LOOP24
checkout was not changed or checked out at another revision.

## Decision vocabulary

- **Preserve** means the connector must retain the user-visible contract.
- **Adapt** means the outcome is retained through Hermes-native Graph,
  browser, approval, or artifact infrastructure.
- **Exclude** means the behavior is intentionally outside this release and is
  named here so it cannot disappear accidentally.

## Existing Hermes Graph and Teams baseline

| ID | Current symbol | Frozen behavior | Disposition and target |
|---|---|---|---|
| G-01 | `GraphCredentials.from_env` | Normalizes `MSGRAPH_TENANT_ID`, `MSGRAPH_CLIENT_ID`, `MSGRAPH_CLIENT_SECRET`, optional scope, and authority; missing required values raise a configuration error. | **Preserve** exactly for Teams and other app-only callers in Task 2. |
| G-02 | `MicrosoftGraphTokenProvider` | Uses the OAuth client-credentials grant, caches until refresh skew, serializes acquisition with an async lock, and exposes credential-free token-health metadata. | **Preserve** as the app-only implementation of the generic token-provider protocol in Task 2. |
| G-03 | `MicrosoftGraphClient._request` | Adds bearer auth, refreshes after 401, retries transport errors, 429, and 5xx with bounded exponential/`Retry-After` delay, and supports GET/POST/PATCH/DELETE JSON operations. | **Preserve** and invariant-test in Tasks 2-3. |
| G-04 | `iterate_pages` / `collect_paginated` | Follows `@odata.nextLink` and does not reapply first-page query params. Absolute next links are currently accepted without a host check. | **Adapt** in Task 3: keep opaque next links but constrain them to the configured Graph origin and add caller bounds. |
| G-05 | `download_to_file` | Streams to `<destination>.part`, renames atomically on success, retries classified failures, and removes the partial file on `httpx` errors. It has no aggregate byte limit, cancellation contract, or cleanup guarantee for every exception path. | **Adapt** in Task 3 with aggregate bounds, cancellation/deadline, and universal partial cleanup. |
| G-06 | `MicrosoftGraphAPIError` / `_build_api_error` | Error objects retain parsed payloads and messages derived from response bodies. | **Adapt** in Task 3 so public/request projections omit authorization and raw response bodies while internal classification remains useful. |
| G-07 | `agent.azure_identity_adapter` | Reuses `azure-identity` credentials and bearer-provider construction without copying Azure CLI/SDK token stores into Hermes auth state. | **Reuse unchanged** from the new Azure CLI delegated identity path in Task 2. |
| G-08 | Ericsson Teams `graph_auth.py` | Uses a profile-scoped MSAL cache with bounded reads, POSIX no-follow opens, private modes, atomic persistence, symlink rejection, silent refresh, and explicit device-flow completion. | **Reference, do not copy.** Generic reusable cache safety moves into Task 2; Teams' public tool behavior remains unchanged. |
| G-09 | Existing Graph/Teams tests | The pinned baseline passes the existing Graph auth/client and Teams gateway/plugin/identity suites (67 tests). | **Mandatory invariant** after Tasks 2-3 and at source closure. |

## URL, site, drive, and item identity

| ID | Legacy symbol | Legacy input/output and edge behavior | Disposition and target |
|---|---|---|---|
| U-01 | `parse_sp_url` | Accepts ordinary SharePoint paths and UI prefixes such as `/:x:/r/` and `/:w:/s/`; removes a colon-wrapped app token and one recognized single-letter mode. | **Preserve** with table-driven URL tests in Task 5. |
| U-02 | `parse_sp_url` | Splits identity into host, optional `sites/<name>` or `teams/<name>`, first post-site segment as library, and remaining segments as item path. Root sites produce an empty site path. | **Preserve** in `url_parser.py`, including encoded spaces and root/library/folder/file distinctions. |
| U-03 | `parse_sp_url` | Ignores query strings. It accepts arbitrary schemes, userinfo, fragments, malformed escaping, and arbitrary hosts because no authority validation exists. | **Adapt** in Task 5: require HTTPS, configured tenant hosts, valid percent encoding, no userinfo, no unsafe fragment, and no redirect escape. |
| U-04 | `resolve` | Resolves the site through `/sites/{host}:/{site_path}` (or root host) and returns site id/name/web URL plus drive and item path. | **Preserve** as `sharepoint_resolve_url`, with bounded normalized identity rather than the mutable `Target` container. |
| U-05 | `_resolve_drive` | Treats no library, `Shared Documents`, `Documents`, and underscore-prefixed SharePoint internal paths as the default drive. Otherwise lists drives and matches case-insensitive display name or decoded final `webUrl` segment. | **Preserve**, but reject ambiguous matches and bound enumeration in Task 5. Internal `_layouts`/`_api` paths never become a library name. |
| U-06 | `_item_url` / `_folder_item_id` | Addresses the drive root or encodes each path segment independently; resolves folder ids for parent references. | **Preserve** for safe path fallback. Prefer drive/item ids when available. |
| U-07 | batch download identity | `_driveId` and `_driveItemId` avoid path-encoding failures for commas, apostrophes, and viewer URLs; URL resolution is the fallback. | **Preserve** as explicit drive/item identity in Tasks 5-6. |
| U-08 | `_is_file_url` / `_parent_folder_url` | Uses a known-extension heuristic for file URLs and can expand a file URL to its containing folder while preserving UI-prefix path syntax and dropping file-specific query/fragment data. | **Adapt** into skill/workflow selection in Task 9; the low-level resolver uses remote item identity rather than extension heuristics. |

## Listing, filtering, and discovery

| ID | Legacy symbol | Legacy contract and limits | Disposition and target |
|---|---|---|---|
| L-01 | `_list_children` | Requests id, name, size, folder/file facets, web URL, and modified time with `$top=200`, following every OData page. | **Preserve** as bounded `sharepoint_list_items` metadata in Task 6. |
| L-02 | `_walk` | Depth-first recursive listing has no depth, item, page, byte, cycle, or deadline limit. | **Adapt** in Task 6: optional recursion with explicit depth/item/page/byte/deadline bounds and truncation warnings. |
| L-03 | `cmd_list --json` | Adds `_relativePath`, `_driveId`, and `_driveItemId`; relative paths are based on the listed folder rather than the drive root. | **Preserve** using normalized non-underscore fields and stable relative paths. |
| L-04 | `_name_patterns` / `_matches_name_filter` | Comma-separated, case-insensitive globs match the basename unless the pattern contains `/`, in which case they match the relative path. Name filters replace extension filters. | **Adapt** into bounded list filtering and the navigation skill in Tasks 6 and 9. Patterns cannot expand the fetch beyond the authorized listed scope. |
| L-05 | extension selection | Default `.pdf`/`.docx`; optional Office and text formats; folders are skipped; `max_files` truncates after filtering. | **Adapt**: connector listing exposes metadata and bounds without claiming content support. Skills/workflows may select artifacts by extension; parsing is excluded below. |
| L-06 | anchor discovery | Recursive scan identifies folders directly containing a case-insensitive marker glob. Marker inclusion is configurable; sibling files become URL-only records with drive/item fallbacks. | **Adapt** in Task 9 as a navigation/document-intake skill recipe over bounded recursive listing. It is not a second transport or a hidden parser. |
| L-07 | file-to-folder expansion | A direct file URL can be broadened to its parent so the named file and matching siblings are processed. | **Adapt** in Task 9 with an explicit user-visible scope choice. Never broaden unattended scope implicitly. |

## Reads and local artifacts

| ID | Legacy symbol | Legacy contract and failure behavior | Disposition and target |
|---|---|---|---|
| R-01 | `cmd_stat` | Returns raw DriveItem metadata or a human projection including type, size, child count, dates, actors, id, and web URL. | **Preserve** as bounded normalized `sharepoint_get_item` in Task 5; no raw payload by default. |
| R-02 | `_download_to` | Uses authenticated `/content`; intercepts redirects and follows the preauthorized CDN `Location` without forwarding the Graph bearer. It streams 1 MiB chunks and retries 429/503. | **Preserve** the no-cross-origin-bearer invariant and streaming behavior in Tasks 3 and 6. Constrain redirect hosts/semantics and total bytes. |
| R-03 | `cmd_download` | Rejects roots and folders, derives the remote name, creates parent directories, and downloads to any caller-supplied path. | **Adapt** in Task 6: only authorized work/artifact roots, safe names, traversal/symlink/device rejection, one-operation interactive expansion, relative public paths, digest and size. |
| R-04 | `cmd_batch_download` | Reuses one auth, accepts URL or drive/item ids, isolates per-file errors, and returns URL/path/error rows. It has no aggregate limits and returns absolute paths/errors verbatim. | **Adapt** into bounded list/download operations with safe normalized warnings and relative artifact evidence. |
| R-05 | fetcher temp lifecycle | Uses a temporary directory for downloaded files and per-file subdirectories to avoid name collisions. Failed files are skipped while successful items continue. | **Preserve** cleanup and partial-result semantics, but use connector-authorized roots and explicit warnings in Task 6. |
| R-06 | parser handoff | Docling/basic parsers extract PDF, Office, JSON, text, HTML, and structured content, with optional rich metadata. | **Exclude from connector** by approved design. Task 9 stops after artifact acquisition and hands files to separate document capabilities. |

## Upload and mutation behavior

| ID | Legacy symbol | Legacy contract and limits | Disposition and target |
|---|---|---|---|
| W-01 | `_upload_small` | PUTs file bytes to `/content`; legacy selection uses simple upload through 4 MiB. | **Preserve** request semantics in Tasks 3 and 8 with caller-supplied size bounds, approval, and conflict policy. |
| W-02 | `_upload_large` | Creates an upload session with `replace`, holds the entire file in memory, uploads 10 MiB chunks (aligned to 320 KiB), and accepts each response without validating resume offsets or ambiguous completion. | **Adapt** in Tasks 3 and 8: streaming chunks, aligned ranges, returned resume offsets, chunk/session bounds, expiration/cancellation, and no blind restart. |
| W-03 | `cmd_upload` | Destination is a resolved folder plus caller name or local basename; overwrite is implicit. | **Adapt** to explicit overwrite/rename/fail policy, exact local boundary, and approval/admitted authority in Task 8. |
| W-04 | `cmd_mkdir` | POSTs a folder child and maps `exist_ok` to Graph `replace`; otherwise `fail`. | **Preserve** the user intent, but define idempotent existing-folder recovery and conflict projection in Task 8. |
| W-05 | `cmd_mv` | PATCH can rename, move to a resolved destination parent, or both; a source root and empty mutation are rejected. Parent reference may name another drive. | **Preserve** with explicit source/destination tenant and drive validation, optimistic conflict handling, and approval in Task 8. |
| W-06 | `cmd_cp` | POSTs `/copy` with destination drive/folder and optional name. A 202 `Location` is reported but never polled. | **Adapt** in Tasks 3 and 8: host-constrained async polling, `Retry-After`, deadline/cancel, terminal failures, and reconciliation of ambiguous acceptance. |
| W-07 | `cmd_rm` | Requires `--yes`, rejects library root, DELETEs the DriveItem, and describes recovery through the site recycle bin. | **Preserve as recycle only** via `sharepoint_recycle_item` with approval/admitted authority. **Permanent deletion is excluded.** |
| W-08 | all writes | Legacy writes have CLI confirmation only for delete; upload/mkdir/move/copy have no shared approval or unattended authority contract. | **Adapt** in Task 8: every write requires backend approval or sealed admitted authority; caller-authored approval claims are rejected. |

## Graph authentication branches

| ID | Legacy/current branch | Frozen selection behavior | Disposition and target |
|---|---|---|---|
| A-01 | `SharedCacheCredential(allow_interactive=False)` | Reads the shared MSAL cache, chooses the first account, attempts silent acquisition/refresh, persists changes, and fails with next-step guidance when unavailable. | **Preserve generically** as `delegated_msal`, with explicit account identity, scopes, bounded private profile cache, corruption handling, and no secret-bearing errors in Task 2. |
| A-02 | `AzureCliCredential` | Falls back after silent MSAL and uses Azure CLI identity without duplicating that token store. | **Preserve** as `azure_cli` via the existing Hermes Azure identity adapter in Task 2. |
| A-03 | interactive shared-cache credential | When interactive use is allowed, opens browser sign-in using the same public client/cache so later processes refresh silently. | **Preserve** as an explicit setup action only. Unattended operations never initiate it. |
| A-04 | `SP_NONINTERACTIVE` | Removes the interactive credential branch and fails fast for agent/automation runs. | **Preserve as execution context**, not as a new user-facing env variable: unattended context is supplied by plugin/setup APIs. |
| A-05 | current Hermes app-only credentials | Fully configured tenant/client/secret uses client credentials and `.default` scope. | **Preserve** as `app_only`; existing `GraphCredentials.from_env()` callers remain compatible. SharePoint settings/secrets come from plugin configuration rather than new env documentation. |
| A-06 | new `auto` mode | No legacy equivalent. | **Add in Task 2**: deterministic selection only among fully configured supported modes; partial configuration is a readiness error, never a guess or interactive fallback. |
| A-07 | readiness | Legacy auth errors conflate missing config, stale interactive state, and unavailable CLI. | **Adapt** into `configuration_required`, `interactive_auth_required`, and `ready` without token/cache disclosure. |

## Owned-site discovery

| ID | Legacy symbol | Legacy output and failure behavior | Disposition and target |
|---|---|---|---|
| O-01 | `cmd_collect_my_sites.run` | Reads `/me`, enumerates owned M365 group objects across opaque pages, resolves each group root site, and returns title, URL, description, created time, group id, and group name. | **Preserve** as bounded `sharepoint_list_owned_sites` in Task 7 using generic Graph identity/client. |
| O-02 | per-group `ODataError` | An inaccessible/unresolvable group site is logged and skipped while remaining groups continue. | **Adapt** to per-site/group warnings and partial status rather than silent omission. |
| O-03 | `--update-sites-csv` | Optionally replaces a local `name,url` selection file from owned sites. | **Adapt**: selected-site inputs are explicit bounded operation arguments; optional structured export may be written atomically under the artifact root. No implicit project CSV mutation. |

## Browser authority and permission audit

| ID | Legacy symbol | Legacy contract and failure behavior | Disposition and target |
|---|---|---|---|
| B-01 | `_ensure_edge` | Reuses anything responding on fixed localhost port 9222; otherwise launches fixed-path Edge with a fixed profile under legacy output and records only the spawned pid. | **Replace in Task 7** with a named core-owned enrolled-browser profile, registry, manager acquisition, trusted origins, and core collision/ownership controls. No raw CDP setting or duplicate launcher. |
| B-02 | `_browser_connect` | Attaches Playwright over CDP, selects the first SharePoint tab or creates one, and navigates to the first selected site. | **Adapt** through the core browser authority; connector code receives an acquired session rather than claiming a port/profile. |
| B-03 | `_authenticated` / `_wait_for_signin` | Probes same-origin REST. Visible runs can wait up to 300 seconds for sign-in; headless missing sessions return instructions. | **Adapt** into `enroll_browser`, `clear_session`, readiness, and bounded setup actions in Task 4. Audit calls never initiate sign-in. |
| B-04 | `_navigate_if_needed` | Uses `domcontentloaded`, retries navigation twice, and may continue after timeout only when the current page has the same origin. | **Preserve** the same-origin continuation principle with explicit configured tenant origin, deadline, cancellation, and bounded retries in Task 7. |
| B-05 | `_shutdown_edge` | A run leaves a reused browser alive. A browser it launched receives CDP `Browser.close`, a five-second liveness wait, then Windows tree-kill fallback. `--keep-browser` leaves an owned browser alive. | **Preserve ownership semantics** through core release/teardown: reused/parallel user sessions survive; operation-owned sessions are released by the manager. Connector code does not kill processes. |
| B-06 | `_SITE_USERS_JS` | Paginates site users and returns id, title, login, email, site-admin flag, and principal type. | **Preserve bounded** in `sharepoint_audit_permissions`. |
| B-07 | `_ROLE_ASSIGNMENTS_JS` | Expands member and role-definition bindings, emits one row per principal/role, and discovers SharePoint groups (`PrincipalType == 8`). | **Preserve bounded**, with normalized site-scope role rows. |
| B-08 | `_SP_GROUP_MEMBERS_JS` | Fetches each discovered SharePoint group's users, suppresses inaccessible-group errors, and emits group/member identity rows. | **Preserve**, but expose per-group partial warnings instead of silent suppression. |
| B-09 | `_SITE_METADATA_JS` | Returns title, description, URL, created/modified times, web template, and language. | **Preserve bounded** per selected site. |
| B-10 | `_LISTS_JS` | Enumerates non-hidden lists with id, title, description, base type, item count from the remote response, created, and modified data. | **Preserve bounded**; normalize all retained fields and report truncation. |
| B-11 | `_SUBSITES_JS` | Enumerates immediate webs with title, URL, created time, and source web template (legacy projection omits template). | **Preserve** title/URL/created and retain normalized template where returned. |
| B-12 | site selection | `sites.csv` supports case-insensitive substring filters over name/URL, repeated filters, then a numeric limit. | **Adapt** to exact bounded names/URLs plus a hard site limit to prevent accidental broad audits. |
| B-13 | category helper failures | Most collection helpers catch an exception and return an empty list/`None`; the enclosing site is still marked `collected`. Navigation failure alone marks `unreachable`. | **Fix in Task 7**: category and site status must distinguish complete, partial, truncated, and unreachable. Empty data cannot imply successful completeness after a failed request. |
| B-14 | pagination/limits | Browser `_getAll` follows every `odata.nextLink`; audit has no category row, aggregate row, page, byte, or deadline bounds. | **Adapt** with per-category and aggregate row/byte/page limits, deadline/cancel, and truncation warnings. |
| B-15 | audit readiness | Browser auth is required for `collect-users`; Graph auth independently powers `collect-my-sites`. | **Preserve as two readiness facets**: missing enrollment blocks only `sharepoint_audit_permissions`; Graph file operations and `sharepoint_list_owned_sites` retain Graph readiness. |

## Audit result, artifacts, and redaction

| ID | Legacy symbol | Legacy contract | Disposition and target |
|---|---|---|---|
| E-01 | `RESULT` / combined JSON | Produces one combined object with status, error, times, counts, skipped sites, owned sites, and nested per-site metadata, users, permissions, members, lists, and subsites. | **Preserve normalized structure** as bounded tool data and optional structured artifact in Task 7. Avoid process-global mutable run state. |
| E-02 | optional CSVs | `--csv` writes per-type metadata, users, permissions, members, lists, and subsites CSVs; combined JSON remains primary. | **Adapt** to optional structured export only under the authorized artifact root. Legacy CSV filenames/layout are not the primary API. |
| E-03 | logs/file manifest | Legacy output includes absolute output/log/JSON paths and a manifest of absolute paths and byte counts. | **Adapt** to safe paths relative to the authorized root plus digest/size metadata. Absolute temp/profile paths are excluded from public results. |
| E-04 | public evidence | Browser JavaScript errors, raw URL/status text, subprocess errors, and provider details may flow into logs/results; no comprehensive secret/body redaction exists. | **Fix** before persistence/logging/return: exclude cookies, bearer tokens, cache content, scripts, CDP URLs, profile paths, raw browser/Graph bodies, authorization headers, and absolute temporary paths. |
| E-05 | partial collection | Unreachable sites are listed separately; individual file/audit failures generally allow the run to continue. | **Preserve** partial progress, but make every partial category and truncation explicit and never report false completeness. |

## Deliberate exclusions and handoffs

| ID | Behavior | Decision |
|---|---|---|
| X-01 | Permanent deletion | **Excluded.** Initial deletion is DriveItem recycle-bin behavior only. |
| X-02 | Document parsing, OCR, conversion, semantic interpretation, and generation | **Excluded from SharePoint connector.** Separate document capabilities consume authorized downloaded artifacts. |
| X-03 | Legacy Langflow component and subprocess architecture | **Excluded.** The active Hermes agent calls registered plugin tools backed by importable operations and the generic Graph client. |
| X-04 | Fixed Edge executable, port 9222, legacy profile directory, PowerShell/Azure helper subprocesses | **Excluded.** Core Graph identity and enrolled-browser authority own these concerns. |
| X-05 | Unbounded recursive or tenant-wide collection | **Excluded.** Every operation has caller-supplied and hard safety limits. |
| X-06 | Hidden connector-local LLM prompts/calls | **Excluded.** Reasoning and interpretation remain with the active Hermes agent and skills. |

## Target tool coverage

| Target tool | Required behavior-map rows |
|---|---|
| `sharepoint_resolve_url` | U-01 through U-07 |
| `sharepoint_get_item` | U-04 through U-07, R-01 |
| `sharepoint_list_items` | L-01 through L-05, G-04 |
| `sharepoint_download` | R-02 through R-05, G-05, E-03 through E-05 |
| `sharepoint_upload` | W-01 through W-03, G-05 |
| `sharepoint_create_folder` | W-04, W-08 |
| `sharepoint_move_item` | W-05, W-08 |
| `sharepoint_copy_item` | W-06, W-08 |
| `sharepoint_recycle_item` | W-07, W-08, X-01 |
| `sharepoint_list_owned_sites` | O-01 through O-03, A-01 through A-07 |
| `sharepoint_audit_permissions` | B-01 through B-15, E-01 through E-05 |

## Verification implications

- Tasks 2-3 must prove G-01 through G-09 and A-01 through A-07 without
  moving Teams-specific code into core.
- Tasks 5-8 tests cite the relevant row ids in their test names or docstrings
  when translating legacy cases.
- Task 9 keeps the thin router discoverable while the standalone plugin is
  disabled, describes L-04 through L-07, and makes X-02 explicit.
- Task 10 source closure includes the unchanged Teams plugin suite and checks
  that no connector-specific id appears in generic Graph production code.
