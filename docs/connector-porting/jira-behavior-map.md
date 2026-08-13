# Jira connector behavior map

This map freezes the Jira behavior that Release 2 must preserve, adapt, or
deliberately exclude before the connector is refactored. It is the traceability
source for Jira Tasks 2–7 and the installed Windows UAT packet.

## Source identity

- Legacy repository: `sd-americas-css/sd-americas-ai/loop_24`
- Legacy commit inspected: `fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6`
- Accepted connector snapshot: `8ca26f882bc461d9aaa80a252685568c8749394a`
- Verification: `8ca26f8..fc3bf26` contains one commit,
  `fc3bf26 update document verification`, and changes only
  `custom_components/ericsson_docgen/**`. No Jira component changed.
- Current Ericsson source baseline:
  `dae405ede7049b621e502d9259f97481c940a65b`
- Current source plugin:
  `plugins/ericsson-jira/{plugin.yaml,__init__.py,jira_tools.py}`

The legacy Jira package contains `JiraAssignedTicketsFetcher`,
`JiraTicketContextBuilder`, `JiraTicketSelector`, `JiraTicketTriage`,
`JiraTicketUpdater`, and `FixSummaryComposer`. The current source plugin
already exposes three direct Jira operations, but is an always-loaded backend
plugin using process-global environment variables and REST v2 only.

## Public compatibility contract

| Behavior | Legacy/current source | Disposition | Target task and acceptance evidence |
|---|---|---|---|
| List the authenticated user's tickets | Legacy `JiraAssignedTicketsFetcher._search_issues`; current `jira_tools.my_tickets` | Preserve the public tool name `jira_my_tickets`. Preserve assigned-ticket discovery while making JQL, filters, bounds, and fields explicit. | Tasks 3 and 5; source read tests and Windows native/curl reads. |
| Read one ticket | Current `jira_tools.get_issue` | Preserve `jira_get_issue`, including normalized description, status, priority, comments, and GitLab links. | Task 5; v2/v3 and ADF/plain-text fixtures. |
| Add a comment | Legacy `JiraTicketUpdater.update_ticket`, `JiraTicketTriage._post_triage_comment`; current `jira_tools.add_comment` | Preserve `jira_add_comment` and its existing `{ok, id}` compatibility fields. Add host-authored approval, preview, bounds, reconciliation, and version-correct request bodies. | Task 6; approval and ambiguous-write tests. |
| General JQL search | Legacy search logic is fixed to the authenticated user's issues; current plugin has no general search tool. | Add bounded `jira_search_issues` with explicit JQL, result limit, and an allowlisted field projection. | Task 5; search/pagination/truncation tests. |
| Toolset identity | Current `plugin.yaml` and registration use `ericsson-jira`. | Preserve `ericsson-jira`; do not add Jira tools to Hermes core. | Tasks 2 and 9; distribution and fresh-session tests. |
| Availability lifecycle | Current `kind: backend` auto-loads whenever base URL and PAT are present. | Replace with `kind: standalone`, bundled but disabled until explicitly enabled. Apply manifest transition `ericsson-jira-backend-to-standalone-v1` once to historical auto-seeded configuration without inferring a user from credentials. | Tasks 2 and 9; fresh/upgraded profile fixtures. |

## Authentication and endpoint identity

| Legacy behavior and symbol | Exact contract/default | Disposition | Target task |
|---|---|---|---|
| `JiraAssignedTicketsFetcher._normalize_base_url` | Trims whitespace/trailing slash and prepends `https://` when no HTTP scheme is present. | Adapt: normalize to one configured HTTP(S) origin, reject userinfo/fragments and cross-origin targets/redirects, and never let operation arguments replace the configured origin. | Task 3 |
| `JiraAssignedTicketsFetcher._auth_header_value` | `bearer` PAT by default; `basic` requires email and sends base64 `email:token`. SecretStr wrappers are unwrapped. | Preserve bearer PAT and basic email/API-token selection through resolved profile configuration. Reject missing, unknown, and ambiguous combinations. Secrets must not appear in representation, errors, logs, or results. | Tasks 2–4 |
| `JiraTicketUpdater._auth_header` and `JiraTicketTriage._jira_auth_header` | Duplicate bearer/basic construction; updater does not validate an empty basic email/token. | Replace with the single typed auth implementation and common validation. | Task 3 |
| Current `jira_tools._client` | Reads `JIRA_BASE_URL` and `JIRA_PAT` directly; fixed bearer header; 30-second client timeout. | Replace process-global reads with plugin-resolved settings/secrets. Retain legacy environment detection only as migration diagnostics, never as enablement or the documented setup path. | Tasks 2–3 |
| REST search compatibility | Legacy `_search_endpoint_candidates` tries `/rest/api/3/search`, then `/rest/api/2/search`; current plugin calls v2 only. | Preserve v3 preference, but fall back to v2 only for a classified unsupported/missing endpoint response. Never fall back on authentication, permission, timeout, TLS/DNS, malformed payload, or generic server failures. | Task 3 |
| Comment REST version | Legacy and current comment writes use v2 plain text. | Adapt: v3 uses ADF comment bodies and v2 uses plain text. Version selection follows the same classified compatibility policy. | Task 6 |

## Transport behavior

| Legacy behavior and symbol | Exact contract/default | Disposition | Target task and UAT impact |
|---|---|---|---|
| Curl deployment reason | `JiraAssignedTicketsFetcher._request_json` documents Python TLS/JA3 requests being rejected by Cloudflare error 1010. README requires curl for those deployments. | Preserve this proven compatibility reason. Native HTTP is primary. In `auto`, curl is eligible only after a normal native HTTP response has Cloudflare response metadata and a bounded error-1010 marker. Other deployments select `curl` explicitly. | Tasks 3–4; installed Cloudflare deployment UAT. |
| Legacy curl command | `--silent --show-error`, GET/POST method, authorization and JSON body placed directly in argv, 30/60-second max-time, status appended to stdout; updater follows redirects. | Replace with the approved safer transport. Use a fixed validated executable, method allowlist, exact configured origin, private config/input material, bounded output, deadline/cancellation, no shell, and no token/body in argv. Redirects remain origin-bound and bounded. | Task 4; fake-executable argv, permissions, cleanup, timeout, cancellation, and redaction tests. |
| Curl response parsing | Final stdout line is parsed as status; JSON object required for reads. Legacy classifies 3xx as SSO auth failure and reports body snippets on error. | Adapt to bounded status/header/body parsing and the common safe error taxonomy. Sanitize before logging/persistence; never expose raw auth or an unbounded Jira/Cloudflare body. | Tasks 3–4 |
| Native retries | Current source has no retry policy. | Add bounded Retry-After/transient retry with deadline and cancellation. Never retry auth, permission, validation, conflict, approval, or ambiguous writes. Retry identity/body/authority remains unchanged. | Task 3 |

## Ticket discovery, fields, and filters

| Legacy behavior and symbol | Exact contract/default | Disposition | Target task |
|---|---|---|---|
| Assigned-ticket ordering | Legacy JQL: `assignee = currentUser() ORDER BY updated DESC`. Current JQL adds `resolution = Unresolved ORDER BY priority DESC, updated DESC`. | Preserve the current public `jira_my_tickets` unresolved/priority behavior for compatibility. Make status/category/priority/age/threshold filters explicit and deterministic instead of hiding policy inside transport. | Task 5 |
| Pagination | Legacy `page_size=100`, clamped to 1–100; `max_issues=0` means all. Current source performs one request with default `max_results=25`. | Adapt to bounded pagination with a finite configured default/ceiling and explicit truncation warnings. `jira_my_tickets` retains default 25. General search requires an explicit bounded maximum. | Tasks 2 and 5 |
| Requested fields | Current list requests summary/status/priority/updated/description; detail adds last comments. Legacy accepts all returned fields and can include 12,000 bytes of compact raw fields. | Preserve needed normalized fields. Reject arbitrary field expansion and remove raw-field projection from model results; it unnecessarily exposes payloads. | Task 5 |
| Issue type filter | `JiraTicketTriage.filter_issue_types`, default `Bug`; empty means all. | Move to triage skill/workflow selection and supported search/my-ticket filters. No hidden LLM-side filtering in the plugin. | Tasks 5 and 7 |
| Priority filter | `filter_priorities`; empty means all. | Preserve as deterministic read filter; skills explain triage policy. | Tasks 5 and 7 |
| Label allowlist | `filter_labels`; case-insensitive intersection, empty means ignored. | Preserve as deterministic category/label filtering where the bounded field projection includes labels. | Task 5 |
| Confidence thresholds | `auto_fix_threshold=70`; `manual_review_threshold=40`; below 40 becomes `needs-info`, and low-confidence auto-fix becomes `manual-review`. | Move to the defect-triage skill as guidance for active-agent reasoning. It cannot grant write authority. | Task 7 |
| Include manual review | `include_manual_review=False`; only `auto-fix` enters the loop unless enabled. | Move to conversational triage guidance. Release 2 may research one selected ticket; it does not implement the multi-ticket loop. | Task 7 |

## Normalization and result projection

| Legacy/current behavior | Exact contract | Disposition | Target task |
|---|---|---|---|
| ADF flattening | Legacy `_extract_text` recursively collects text/content plus selected display fields and deduplicates exact strings. Current `_text` serializes dictionaries as JSON. | Replace with deterministic ADF-to-text normalization for paragraphs, lists, code, links, mentions, tables, unknown nodes, and malformed content. Preserve plain-text Server/DC bodies. | Task 5 |
| Brief problem | Legacy `_brief_problem` chooses description, environment, or summary; returns first sentence capped at 260 characters. | Preserve the intent as a bounded normalized summary field; never silently substitute an error for an empty workload. | Task 5 |
| GitLab URL discovery | Legacy `_extract_gitlab_urls` walks every returned string, accepts URLs whose host or path contains `gitlab`, strips `).,;]}>\"'`, and deduplicates in discovery order. Current extraction is description-only and strips `.,;:!?`. | Preserve punctuation cleanup, stable deduplication, and discovery from normalized description/comments/context. Do not scan or return arbitrary raw fields. | Task 5 |
| Ticket list projection | Legacy returns key, summary, status, problem summary, GitLab URLs, browse URL, and display text. Current returns key, summary, status, priority, updated, GitLab URLs. | Produce a bounded stable union required by current callers and skills. Include safe issue URL/identity and truncation warnings. | Task 5 |
| Ticket detail projection | Current returns key, summary, status, priority, description, five most recent comments, and description GitLab URLs. | Preserve existing fields. Normalize bounded comments with safe author/time projection and collect deduplicated GitLab links from normalized context. | Task 5 |
| Comment result | Current returns `{ok: true, id}`. Legacy updater additionally builds ticket/MR/confidence summary status for loop aggregation. | Preserve `{ok, id}` and add bounded preview/reconciliation metadata without requiring legacy Langflow feedback shapes. Aggregate summaries belong to the agent/workflow. | Task 6 |
| Error handling | Current `_check` distinguishes 401 then includes up to 300 raw response characters for all other errors. | Replace with stable categories: configuration/authentication/permission/not-found/conflict/rate-limit/remote/limit/approval/cancelled/internal. Redact and bound every message. | Tasks 3–6 |

## Reasoning, skills, and workflow ownership

| Legacy behavior and symbol | Disposition | Target task and release boundary |
|---|---|---|
| `JiraTicketContextBuilder.build_context` combines every ticket without loss for an LLM summary. | Move to `my-tickets-summary` workflow and active-agent instructions. Keep ticket count and truncation explicit. | Task 7 |
| `JiraTicketSelector.select_ticket` passes a loop item through or selects a key case-insensitively, falling back to the first item when missing. | Replace unsafe fallback with an exact single-ticket input/selection contract. Missing or unknown keys fail explicitly. | Task 7 showcase |
| `JiraTicketTriage._call_triage_llm` embeds a system prompt and calls an Ollama-compatible model. | Exclude from plugin. The active Hermes agent loads `defect-triage` and owns classification/reasoning; no connector-local LLM, model list, temperature, or hidden prompt ships. | Task 7 |
| `JiraTicketTriage._fetch_file_tree` directly reads GitLab for repository evidence. | Move to the accepted `ericsson-gitlab` plugin and cross-connector Jira-to-GitLab guidance. Jira contains no duplicate GitLab client. | Task 7 and existing GitLab capability |
| Optional skipped-ticket comments | Preserve only as an explicitly approved `jira_add_comment` operation after the agent presents the proposed text. Classification cannot authorize the write. | Tasks 6–7 |
| `FixSummaryComposer` aggregates success/failure/MR/confidence text for email. | Move to workflow/agent reasoning and Outlook delivery. Preserve visibility of every skipped/failed item; email remains separately approved. | Task 7; exact multi-ticket composition deferred |
| Jira assigned-ticket digest | Preserve through the existing `my-tickets-summary` workflow using flat `requires: [ericsson-jira]` and exact allowed tools. | Task 7 |
| Single-ticket research/triage/comment | Add an explicitly named `jira-single-ticket-showcase` that accepts exactly one key, reads normalized context, and optionally posts one approved/preauthorized comment. | Task 7 |
| Exact Jira defect loop | Intentionally defer multi-ticket iteration, per-ticket isolation, aggregate summary, and unattended batch-write parity until workflow Phase 6 `loop_group`. Release 2 artifacts must not claim parity. | Task 7 docs and negative assertions |
| Jira-to-GitLab automated fix | Keep as cross-connector guidance. Release 2 does not add issue mutation or recreate hidden LLM/review steps inside Jira. | Task 7 |

## Deliberate exclusions

Release 2 does not add issue creation, transition, assignment, arbitrary field
editing, attachment mutation, permanent batch autonomy, connector-local model
calls, raw payload projection, browser-cookie authentication, or a new Hermes
core tool. It also does not preserve the legacy practice of putting
authorization headers or request bodies in process arguments.

## Installed UAT implications

Installed Windows validation must exercise bearer and basic configuration,
native v3 reads, classified v2 fallback, explicit curl and the proven
Cloudflare-1010 automatic fallback, ADF/plain-text normalization, bounded
search and comments, process/log redaction, approval or admitted workflow
authority, disable/re-enable and one-time lifecycle migration, and the
single-ticket showcase. It must also confirm that unsupported issue mutations
are absent and that no artifact claims exact multi-ticket defect-loop parity.
