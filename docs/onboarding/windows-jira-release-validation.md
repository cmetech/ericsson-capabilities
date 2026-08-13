# Windows Jira installed-release validation

This checklist is mandatory installed UAT for the Jira release candidate. It is not satisfied by source mocks and must run only against an authorized Jira test project/issue with non-production credentials stored through Tools.

## Profile and lifecycle

1. On a clean Windows profile, install the candidate and confirm `ericsson-jira` is present but disabled.
2. On an upgraded profile containing historical auto-seeded Jira enablement, confirm migration `ericsson-jira-backend-to-standalone-v1` removes only that automatic enablement, preserves settings/secrets, and records completion once.
3. Explicitly enable Jira, restart the conversation, restage/restart again, and confirm the explicit enable persists.
4. Confirm Desktop and CLI Tools show the same fields/defaults, project secrets as configured/write-only, and never infer enablement from credentials.

## Authentication and reads

1. Validate bearer PAT and basic email/API-token modes separately.
2. Exercise REST v3 and an authorized Server/DC v2 compatibility deployment; confirm auth/permission errors never trigger version fallback.
3. Run `jira_my_tickets`, bounded `jira_search_issues`, and `jira_get_issue`; inspect ADF/plain text, comments, GitLab URLs, filters, pagination, warnings, and truncation.
4. Confirm missing/invalid configuration, 401, 403, not-found, timeout, and cancellation categories reveal no credential or raw remote diagnostic.

## Transport compatibility

1. Prove native mode on the installed runtime.
2. Where required, prove explicit private curl mode with an approved Windows executable.
3. On the known Cloudflare deployment, prove `auto` changes transport only for the response carrying Cloudflare metadata and bounded error-1010 marker.
4. Confirm DNS, TLS, connection, timeout, generic 4xx/5xx, malformed response, and authentication/permission failures do not select curl.

## Comment and workflow

1. Run dry-run comment preview and confirm no Jira mutation.
2. Reject the single-ticket showcase approval and confirm no mutation.
3. Approve one exact comment, confirm its returned identity, rerun the same body, and confirm duplicate reconciliation without a second post.
4. Interrupt an authorized write only in the controlled test environment; reconcile read-only and confirm an unknown outcome is never blindly retried.
5. Confirm the summary and showcase compile/run with exact per-node tools and that no artifact claims multi-ticket parity.

Record installed version, source/vendor SHA, Windows build, Desktop build, Jira deployment/version, authentication/transport mode, issue key, timestamps, redacted evidence, and pass/fail for every row. Never record secrets or authorization headers.
