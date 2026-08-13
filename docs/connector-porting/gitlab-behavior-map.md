# GitLab legacy behavior map

This map is the test authority for the Ericsson GitLab connector port. Each
row names the exact legacy behavior, its disposition, and the implementation
task that owns the result. Production tasks must cite the row IDs in parity
tests.

## Frozen evidence

- LOOP24 repository commit: `fc3bf26d64e05cc3703ee39e323bbf3c1eaa4cd6`
- Accepted connector snapshot: `8ca26f882bc461d9aaa80a252685568c8749394a`
- Relationship: the accepted snapshot is the direct parent of the frozen
  commit. The sole intervening commit is `fc3bf26d` (`update document
  verification`). Its diff touches only `custom_components/ericsson_docgen/`
  (`__init__.py`, deleted `doc_editor.py`, and `doc_verify.py`). Every mapped
  GitLab and Jira file below is byte-identical between the two revisions.
- All cited code was inspected at the full frozen SHA, not at a moving branch.

### Files inspected in full

Every file under `custom_components/ericsson_gitlab/`:

- `README.md`
- `__init__.py`
- `code_review_runner.py`
- `gitlab_branch_creator.py`
- `gitlab_cicd_collector.py`
- `gitlab_code_context_builder.py`
- `gitlab_commit_pusher.py`
- `gitlab_file_fetcher.py`
- `gitlab_file_reader.py`
- `gitlab_mr_creator.py`
- `gitlab_project_resolver.py`

GitLab-touching Jira files inspected in full:

- `custom_components/ericsson_jira/fix_summary_composer.py`
- `custom_components/ericsson_jira/jira_assigned_tickets_fetcher.py`
- `custom_components/ericsson_jira/jira_ticket_context_builder.py`
- `custom_components/ericsson_jira/jira_ticket_selector.py`
- `custom_components/ericsson_jira/jira_ticket_triage.py`
- `custom_components/ericsson_jira/jira_ticket_updater.py`
- `custom_components/ericsson_jira/README.md`

## Disposition vocabulary

- **preserve**: retain the observable contract.
- **preserve with bounded normalization**: retain the outcome while adding
  explicit bounds, validation, redaction, stable errors, or a normalized JSON
  shape.
- **intentionally replace**: keep the user outcome through the approved Hermes
  architecture rather than the legacy mechanism.
- **defer**: do not implement the behavior in Release 1; the target still owns
  an explicit unsupported/warning contract so omission is not silent.

## Authentication, project identity, and common transport

| ID | Legacy public behavior and contract | Disposition | Target |
|---|---|---|---|
| GL-AUTH-01 | All GitLab components send `PRIVATE-TOKEN` and `Accept: application/json` using a `requests.Session`. Citation: `gitlab_project_resolver.py:GitLabProjectResolver._get_session` and sibling `_get_session` methods. | **preserve with bounded normalization**: one direct REST client, write-only secret resolution, redacted diagnostics, deadlines/cancellation, and no raw token projection. | Task 8 auth/client tests and implementation. |
| GL-AUTH-02 | Client certificate defaults are `~/.config/edpctl/auth/client.pem` and `client-key.pem`; mTLS is enabled only when both files exist, with explicit path overrides accepted. Citation: `gitlab_project_resolver.py:GitLabProjectResolver._get_session` and every GitLab component session helper. | **preserve with bounded normalization**: retain the accepted `edpctl` defaults and pair requirement, expose them through the profile connector descriptor, and classify unusable/partial pairs without revealing paths in public evidence. | Task 8. |
| GL-AUTH-03 | GitLab uses direct REST and never needs a local checkout. Citation: `ericsson_gitlab/README.md:Requirements` and all component request methods. | **preserve**: no `glab`, Git executable, clone, or subprocess transport. | Task 8 plugin invariant tests. |
| GL-ID-01 | Project URLs produce origin plus a nested `path_with_namespace`; `/-/` endpoint suffixes are removed and a trailing `.git` is stripped. Citation: `gitlab_project_resolver.py:GitLabProjectResolver._parse_gitlab_url`; `gitlab_cicd_collector.py:GitLabCICDCollector._parse_gitlab_url`. | **preserve with bounded normalization**: require configured/allowed HTTP(S) origin, preserve arbitrarily nested groups within length bounds, reject empty/group-only ambiguity, and URL-encode the full slug. | Task 8. |
| GL-ID-02 | Project resolver consumes the first extracted Jira `gitlab_urls` entry, permits a base-URL override, and returns project id/path/name/default branch/web URL/base URL/ticket key. Citation: `gitlab_project_resolver.py:GitLabProjectResolver.resolve_project`. | **preserve with bounded normalization**: `gitlab_resolve_project` additionally accepts canonical URL, namespace/project slug, or numeric id and returns stable bounded identity; ticket selection remains skill/workflow work. | Task 8 reads; Task 11 ticket-to-fix skill. |
| GL-ID-03 | CI collector accepts a plain URL, Data/Message/dict-like wrapper, and recognized URL keys; group URLs are rejected distinctly from missing projects. Citation: `gitlab_cicd_collector.py:_extract_url_input`, `_resolve_project_url`, `_resolve_project`. | **preserve with bounded normalization**: keep bounded structured URL coercion and clear group-vs-project errors. | Task 9. |
| GL-ID-04 | Project metadata's `default_branch` is authoritative, with literal `main` only as a missing-field fallback. Citation: `gitlab_project_resolver.py:resolve_project`, `gitlab_file_reader.py:read_files`, `gitlab_cicd_collector.py:_collect_all`. | **preserve with bounded normalization**: never coerce a returned nonempty default branch; validate an explicit caller ref; use `main` only when the API omits/empties the field and report that fallback. | Task 8; write use in Task 10; CI use in Task 9. |
| GL-ID-05 | A legacy advanced input may override the CI project URL with the first nonblank, noncomment line of arbitrary text from a file component. Citation: `gitlab_cicd_collector.py:_collect_all` (`project_url_from_file`). | **defer** the file override and return an unsupported-input diagnostic; the native tool accepts a validated structured project reference. | Task 9. |

## Repository navigation and file reads

| ID | Legacy public behavior and contract | Disposition | Target |
|---|---|---|---|
| GL-READ-01 | `GitLabFileFetcher` recursively enumerates repository-tree blobs on a selected branch/path, filters by a default source-extension list, and truncates to `max_files` (default 20, minimum 1). Citation: `gitlab_file_fetcher.py:GitLabFileFetcher._get_tree`, `_allowed_extensions`, `fetch_files`. | **preserve with bounded normalization**: expose tree listing independently, bound page count/item count/deadline, validate path/ref, and return structured entries rather than one unbounded prompt block. | Task 8. |
| GL-READ-02 | Tree pagination requests 100 entries until a short page; legacy has no total page ceiling. Citation: `gitlab_file_fetcher.py:_get_tree`; `gitlab_file_reader.py:_get_tree`. | **preserve with bounded normalization**: follow GitLab pagination headers/short pages with configured hard page and result ceilings and a truncation warning. | Task 8. |
| GL-READ-03 | File API content is base64-decoded after newline removal; 404 means absent, oversized files return a skip marker (80 KiB fetcher, 100 KiB link reader), and UTF-8 uses replacement characters. Citation: `gitlab_file_fetcher.py:_get_file`; `gitlab_file_reader.py:_get_file`. | **intentionally replace** the lossy text assumption: validate encoding/base64, enforce byte limits before projection, return decoded UTF-8 only when text-safe, and otherwise return binary/base64 metadata plus an explicit binary/undecodable diagnostic. Never place binary bytes in model context. | Task 8. |
| GL-READ-04 | Fetcher branch selection prefers created `branch_name`, then `ref_branch`, then project default/main. Citation: `gitlab_file_fetcher.py:fetch_files`. | **preserve with bounded normalization**: one explicit resolved ref identity, with the same precedence represented by the Task 11 workflow rather than implicit mixed dictionaries. | Task 8 ref resolution; Task 11 orchestration. |
| GL-READ-05 | Link reader accepts repository root, `/-/tree/<ref>/<path>`, or `/-/blob/<ref>/<path>` URLs; other `/-/` endpoints are treated as repository root. Citation: `gitlab_file_reader.py:GitLabLinkReader._parse_url`, `read_files`. | **preserve with bounded normalization**: support root/tree/blob, reject unsupported endpoint kinds explicitly, and preserve nested project slugs. | Task 8. |
| GL-READ-06 | Slashed branch/tag names are resolved by listing up to ten 100-item pages of both branches and tags and taking the longest prefix; fallback treats the first segment as an unlisted ref/SHA. Citation: `gitlab_file_reader.py:_list_refs`, `_resolve_ref`. | **preserve with bounded normalization**: correctly encode slash-containing refs, retain longest-match semantics within explicit ref-page limits, and verify fallback refs through the API before file access. | Task 8. |
| GL-READ-07 | Link-reader directory mode optionally recurses, optionally filters extensions, limits files (default 50), and returns formatted contents, paths, ref, subpath, project identity, and base URL. Citation: `gitlab_file_reader.py:read_files`. | **preserve with bounded normalization** through `gitlab_list_repository_tree` plus `gitlab_read_file`; skills may format bounded prompt text. | Task 8 tools; Task 11 repository-research skill. |
| GL-READ-08 | File fetch/read outputs embed full contents in Markdown fences and duplicate them in a `text` field. Citation: `gitlab_file_fetcher.py:fetch_files`; `gitlab_file_reader.py:read_files`. | **intentionally replace** with bounded structured JSON and content metadata; human formatting belongs in the active-agent skill. | Task 8 and Task 11. |

## Branch, commit, merge-request, and review behavior

| ID | Legacy public behavior and contract | Disposition | Target |
|---|---|---|---|
| GL-WRITE-01 | Branch name is `<prefix>/<ticket-key>-<slug>`; prefix defaults to `fix`, strips trailing `/`; summary is lowercased, nonalphanumerics collapse to `-`, edges trim, and the slug is cut to 30 characters without a trailing `-`. Citation: `gitlab_branch_creator.py:GitLabBranchCreator._slugify`, `create_branch`. | **preserve with bounded normalization**: retain these slug rules and default prefix, validate ticket/prefix/path length, and reject a resulting empty or ambiguous branch. | Task 10. |
| GL-WRITE-02 | Branch source ref is the explicit `ref` when nonblank, otherwise the resolved project default branch/main. Citation: `gitlab_branch_creator.py:create_branch`. | **preserve** with exact project/ref identity checks. | Task 10. |
| GL-WRITE-03 | Existing branch GET 200 is reused; every non-200 response currently attempts creation. Citation: `gitlab_branch_creator.py:create_branch`. | **intentionally replace** with classified recovery: reuse only verified 200 identity, create only after 404, surface auth/permission/transient errors, and return dry-run/idempotency details. | Task 10. |
| GL-WRITE-04 | Code-context builder combines ticket fields and fetched files and instructs an LLM to return complete-file JSON actions (`update`, `create`, `delete`) with commit message and summary. Citation: `gitlab_code_context_builder.py:_FIX_FORMAT_INSTRUCTIONS`, `GitLabCodeContextBuilder.build_context`. | **intentionally replace**: the active Hermes agent and Task 11 ticket-to-fix skill gather context and produce validated arguments; no hidden connector prompt or model call. Full-file content remains an accepted commit action input. | Task 11 skill/workflow; Task 10 validates tool arguments. |
| GL-WRITE-05 | Commit pusher extracts a bare or fenced JSON object, requires nonempty `files`, defaults action to update, omits content on delete, and submits one atomic GitLab commits API call. Citation: `gitlab_commit_pusher.py:_extract_json`, `push_commit`. | **preserve with bounded normalization**: tool accepts structured actions directly, validates the allowlisted action schema/path/content/aggregate size, rejects empty actions, and creates one atomic commit after approval. | Task 10. |
| GL-WRITE-06 | Before commit, HEAD checks convert update-to-create on 404 and create-to-update on 200. Citation: `gitlab_commit_pusher.py:push_commit`. | **preserve with bounded normalization**: retain deterministic create/update reconciliation only when explicitly requested/previewed, add optimistic last-commit checks, and return `conflict` for changed identity. Delete-missing and ambiguous writes are not retried. | Task 10. |
| GL-WRITE-07 | Commit errors currently expose raw response body and payload paths. Citation: `gitlab_commit_pusher.py:push_commit`. | **intentionally replace** with redacted stable error categories, safe known remote identity, and no raw body/token/content. | Task 10. |
| GL-WRITE-08 | MR title is `fix: <ticket> — <summary>` capped at 255; description carries Jira link, summary, fix summary, changed paths, and automated-review notice. Target defaults to project default/main; remove-source defaults true and squash false. Citation: `gitlab_mr_creator.py:GitLabMRCreator.create_mr`. | **preserve with bounded normalization**: retain defaults/templates as skill-supplied values, bound all text, validate source/target identity, and require approval/admission. | Task 10 and Task 11. |
| GL-WRITE-09 | Duplicate MR recovery triggers only on HTTP 409, then lists opened MRs by source branch and reuses the first. Citation: `gitlab_mr_creator.py:create_mr`. | **intentionally replace**: classify both proven GitLab 409 and duplicate-open-MR 400 response classes; query opened MRs with source and target/project identity; reuse only one unambiguous match, otherwise return conflict. | Task 10 named parity tests. |
| GL-WRITE-10 | Branch and MR creation are described as idempotent; commit creation has no idempotency/last-SHA guard. Citation: `ericsson_jira/README.md:Notes`; branch/MR/commit methods above. | **preserve with bounded normalization** for existing-resource recovery; commit ambiguity is separately replaced by the GL-WRITE-06 conflict contract. | Task 10. |
| GL-REVIEW-01 | Review runner fetches MR diffs, formats file sections, and truncates combined diff text to 30,000 characters. Citation: `code_review_runner.py:CodeReviewRunner._fetch_diff`. | **preserve with bounded normalization** in `gitlab_read_merge_request`: bound diff count/bytes and return structured truncation warnings. | Task 8. |
| GL-REVIEW-02 | `CodeReviewRunner` calls a local Ollama-compatible model twice with embedded security/adversarial prompts, parses permissive JSON, averages scores, caps confidence at 40 when the ticket is not fixed, and renders a summary. Citation: `code_review_runner.py:_call_llm`, `_parse_json`, `_confidence`, `run_reviews`. | **intentionally replace**: do not port the LLM client, prompts, scoring algorithm, model discovery, or hidden second model authority. The active Hermes agent uses the Task 11 merge-request-review skill over bounded Task 8 MR data. | Task 11 (explicit no-hidden-LLM tests). |
| GL-REVIEW-03 | Package exports `CodeReviewRunner` alongside eight operational Langflow components. Citation: `ericsson_gitlab/__init__.py:__all__`; `ericsson_gitlab/README.md:Components`. | **intentionally replace** with a standalone plugin registering the nine approved deterministic tools only; review/reasoning are qualified plugin skills. | Tasks 8–11. |

## CI/CD inspection

| ID | Legacy public behavior and contract | Disposition | Target |
|---|---|---|---|
| GL-CI-01 | Branch spec is `ALL`, `RECENT` (default, lookback default 10 days), or exact branch. ALL/RECENT pipeline refs are intersected with live branches; ordering follows first-seen newest pipelines. Citation: `gitlab_cicd_collector.py:_discover_branches`, `_fetch_*pipeline_branches`, `_fetch_live_branch_set`. | **preserve with bounded normalization**: retain selection semantics and ordering with hard pages/items/lookback bounds and warnings. | Task 9. |
| GL-CI-02 | Pipeline stats return `X-Total` in the lookback window plus latest pipeline status and UTC start/end times. Citation: `gitlab_cicd_collector.py:_fetch_pipeline_stats`. | **preserve with bounded normalization** through bounded pipeline listing/inspection; normalize absent/malformed totals. | Task 9. |
| GL-CI-03 | For each selected branch, `.gitlab-ci.yml` is fetched through the file API, base64-decoded, SHA-256 hashed, sized, timestamped, and a 404 becomes a visible not-found record; other exceptions become per-file errors. Citation: `gitlab_cicd_collector.py:_fetch_ci_file`. | **preserve with bounded normalization**: reuse Task 8 safe file decoding, retain hash/size/status metadata, and emit stable warnings without raw errors. | Task 9. |
| GL-CI-04 | Include parsing is one level only. A local include uses the current project/current branch; a project include uses its project/file and `ref` defaulting to `main`. Nested includes are not traversed. Citation: `gitlab_cicd_collector.py:_parse_includes`, `_resolve_includes_shallow`. | **preserve with bounded normalization**: retain one-level local/project traversal, explicit max include count/bytes/deadline/cycle identity, and never evaluate included YAML. | Task 9. |
| GL-CI-05 | A project include whose ref is empty or begins with `$` is coerced to literal `main`; no CI variable interpolation occurs. Citation: `gitlab_cicd_collector.py:_resolve_includes_shallow`. | **preserve with bounded normalization**: keep the recorded `$ref`-to-`main` coercion for parity, attach a warning that interpolation was not performed, and never fetch an interpolated caller-controlled ref. | Task 9. |
| GL-CI-06 | GitLab `include:remote` is silently ignored by the legacy parser. Citation: `gitlab_cicd_collector.py:_parse_includes` (only local/project branches). | **defer** remote retrieval: Task 9 recognizes it and returns an explicit `unsupported_include` warning/metadata. It must not make an unauthenticated cross-origin request in Release 1. | Task 9. |
| GL-CI-07 | GitLab `include:template` is silently ignored by the legacy parser. Citation: `gitlab_cicd_collector.py:_parse_includes`. | **defer** template materialization: Task 9 recognizes it and returns explicit unsupported metadata; later support requires a separately tested GitLab API contract. | Task 9. |
| GL-CI-08 | Include fetch distinguishes success, not-found, permission-denied, other HTTP, and exception; successful raw text is hashed. Citation: `gitlab_cicd_collector.py:_fetch_include_file`. | **preserve with bounded normalization** using stable error categories and byte caps. | Task 9. |
| GL-CI-09 | Project variables and every ancestor group’s variables are paginated at 100 and return only key/type/protected/masked/hidden/raw/environment scope/description/scope/source metadata; 403 becomes a visible permission record. Citation: `gitlab_cicd_collector.py:_fetch_project_variables`, `_fetch_group_variables`. | **preserve with bounded normalization**: never request/project variable values, bound groups/pages/results, deduplicate identity, and retain permission warnings. | Task 9. |
| GL-CI-10 | Branch, tag, pipeline, project-variable, group-variable, and tree lists paginate by incrementing `page` until a short page; most loops are unbounded, while link-reader refs stop at ten pages. Citation: corresponding `_fetch_*` and `_get_tree` methods. | **preserve with bounded normalization**: all list operations use explicit maximum pages/items and return continuation/truncation facts; no unbounded loop remains. | Tasks 8 and 9. |
| GL-CI-11 | Collector caches one complete collection per component instance and projects project info, branches, CI files, variables, combined output, and per-branch context; errors become Data records instead of raising. Citation: `gitlab_cicd_collector.py:_collect_all`, `get_project_info`, `get_branches`, `get_ci_files`, `get_variables`, `get_combined`, `get_branches_with_context`. | **intentionally replace** six Langflow output ports/cache with one bounded `gitlab_inspect_ci` normalized JSON result and stable partial warnings. No cross-call mutable cache is required. | Task 9. |
| GL-CI-12 | `entity` and `applicable_policies` are echoed only and do not filter collection. Citation: `gitlab_cicd_collector.py:inputs`, `get_project_info`. | **defer** connector-level echo fields; Task 11 workflow/skills may attach business context without sending it to GitLab. | Task 11. |

## Jira-to-GitLab flow behaviors

| ID | Legacy public behavior and contract | Disposition | Target |
|---|---|---|---|
| GL-JIRA-01 | Assigned-ticket fetch uses JQL `assignee = currentUser() ORDER BY updated DESC`, clamps page size to 1..100, supports optional total cap, tries REST v3 then v2, and emits one normalized ticket per result. Citation: `jira_assigned_tickets_fetcher.py:_search_issues`, `fetch_tickets`. | **preserve** through the existing `jira_my_tickets` public contract for Release 1; transport mechanics are separately deferred by GL-JIRA-12. | Task 11 integration tests. |
| GL-JIRA-02 | Jira description/environment/ADF and arbitrary nested fields are flattened; the first problem sentence is capped at 260 characters. Citation: `jira_assigned_tickets_fetcher.py:_extract_text`, `_brief_problem`. | **preserve with bounded normalization** in the Jira result consumed by the cross-connector skill; do not duplicate this logic in GitLab. | Task 11 integration; Jira Release 2 behavior map. |
| GL-JIRA-03 | GitLab-looking HTTP(S) URLs are collected recursively from all returned issue fields, punctuation-trimmed, insertion-ordered, and deduplicated when host or path contains `gitlab`. Citation: `jira_assigned_tickets_fetcher.py:_collect_strings`, `_extract_gitlab_urls`. | **preserve with bounded normalization**: cap scanned input/results, accept only configured GitLab origin during resolution, and retain ordered deduplication. | Task 11 workflow/skill tests plus Task 8 resolver validation. |
| GL-JIRA-04 | Ticket context normalizes GitLab URL string/list values and emits key, summary, status, problem, URLs, Jira URL, ticket count, and a human text block; coroutine values are skipped. Citation: `jira_ticket_context_builder.py:_ticket_dict`, `build_context`. | **intentionally replace** Langflow prompt aggregation with structured active-agent skill context; retain all listed fields and zero-ticket outcome. | Task 11. |
| GL-JIRA-05 | Selector passes a single loop item, or case-insensitively selects a key from a list; a missing requested key falls back to the first ticket. Citation: `jira_ticket_selector.py:select_ticket`. | **intentionally replace** with explicit workflow input/agent selection. Missing explicit keys must return `not_found`, not silently choose a different ticket. | Task 11. |
| GL-JIRA-06 | Triage fetches at most one 100-entry page of source-file paths from the linked project default branch, filters source extensions, and caps prompt paths to 200; failures become context text. Citation: `jira_ticket_triage.py:_fetch_file_tree`. | **intentionally replace** with bounded Task 8 tree reads, including full pagination bounds and structured warnings. | Task 8 read tools; Task 11 triage guidance. |
| GL-JIRA-07 | Triage prefilters issue type (Bug default), optional priority and label allowlist, then calls an embedded LLM with repository context; thresholds downgrade low-confidence categories and optional manual-review inclusion controls selection. Citation: `jira_ticket_triage.py:_should_triage`, `_call_triage_llm`, `_apply_thresholds`, `_run_triage`. | **intentionally replace**: no connector-local LLM/prompt/model discovery. The active agent follows the Task 11 skill; deterministic filters remain guidance/workflow inputs. | Task 11. |
| GL-JIRA-08 | Triage may post comments for skipped tickets and converts per-ticket failures into visible manual-review/zero-confidence results. Citation: `jira_ticket_triage.py:_post_triage_comment`, `_run_triage`. | **preserve with bounded normalization** for visible per-ticket failure and approved optional comment via existing Jira tools; no token/body appears in process arguments. | Task 11; Jira Release 2 safe-transport task. |
| GL-JIRA-09 | Jira updater posts MR URL, confidence, and review summary as a Jira v2 comment; it never raises, and emits a nonempty structured success/failure Message so the next loop item can run. Citation: `jira_ticket_updater.py:update_ticket`, `_feedback`. | **intentionally replace** with an approval-aware workflow Jira comment and structured node result. Preserve visible per-ticket status; do not preserve unsafe curl arguments or the hidden confidence authority. | Task 11; Jira Release 2 safe transport. |
| GL-JIRA-10 | Fix summary accepts DataFrame/Table/Data/Message shapes, prefers updater text markers, counts successes/failures, and emits an email-ready aggregate including the zero-ticket case. Citation: `fix_summary_composer.py:_rows`, `_get`, `compose_summary`. | **intentionally replace** with active-agent/workflow summarization over structured results; preserve zero-ticket, success/failure, MR-link, and attention-needed outcomes. | Task 11. |
| GL-JIRA-11 | Legacy documentation promises an end-to-end 12-component flow from assigned tickets through triage, branch/files/fix/commit/MR/review, Jira comment, and summary, with `fix/<ticket>-<slug>`, default-branch, atomic commit, and idempotent branch/MR behavior. Citation: `ericsson_jira/README.md:How It Works`, `Components`, `Notes`; `ericsson_gitlab/README.md:Pipeline Flow`. | **intentionally replace** the Langflow topology with native tools, qualified skills, and one admitted Archon workflow while preserving the user outcome and explicit approval. The active agent owns all reasoning. | Task 11 documentation/workflow tests. |
| GL-JIRA-12 | Jira fetch/update/comment use curl to work around a proven Cloudflare/TLS fingerprint case and support bearer PAT or basic email/token. Citation: `jira_assigned_tickets_fetcher.py:_request_json`, `jira_ticket_updater.py:_curl_api`, `ericsson_jira/README.md:Prerequisites/Notes`. | **defer** transport changes to Jira Release 2. Release 1 reuses the existing Jira plugin; the future port must use the approved bounded classifier and keep secrets/bodies out of arguments. | Jira Release 2 behavior-map and safe-transport tasks; Task 11 only asserts the existing Jira service is required/ready. |
| GL-JIRA-13 | The legacy DataFrame/Loop processes every selected defect and uses updater Messages as feedback so one failure does not abort later tickets. Citation: `jira_ticket_triage.py:triage_defects`, `jira_ticket_selector.py:select_ticket`, `jira_ticket_updater.py:_feedback`, `fix_summary_composer.py:compose_summary`. | **defer** exact multi-ticket loop parity to Phase 6 `loop_group`; Release 1 ships only the admitted workflow shape authorized by Task 11 and must not claim exact loop parity. | Task 11 documentation guard; Phase 6 `loop_group` task. |

## Implementation gate

Tasks 8–11 must translate every applicable `preserve` and `preserve with
bounded normalization` row into named tests before production code. Rows marked
`intentionally replace` require tests proving the replacement outcome and the
absence of the rejected mechanism. Rows marked `defer` require a truthful
unsupported/warning result in their named target; they may not disappear
silently. In particular:

- Task 10 must test duplicate open-MR recovery for both 409 and classified 400;
- Task 9 must test one-level local/project behavior, explicit remote/template
  disposition, and `$ref`-to-`main` warning semantics;
- Task 8 must test nested project slugs, default branches, `edpctl` mTLS,
  binary/base64 projection, and pagination ceilings;
- Task 10 must test branch/commit conflicts and ambiguous-write non-retry; and
- Task 11 must prove no `CodeReviewRunner`, connector-local model client, or
  hidden prompt is ported.
