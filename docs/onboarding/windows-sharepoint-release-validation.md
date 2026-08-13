# Windows SharePoint Release Validation

This installed-UAT checklist validates Ericsson SharePoint behavior that cannot
be claimed from the macOS source run: enterprise tenant authentication,
Conditional Access, enrolled Edge reuse, and native Windows file boundaries.

## Prerequisites

- Install the release containing the exact committed SharePoint source stamp.
- Use a dedicated test profile and a permitted non-production SharePoint site.
- Configure the tenant host and bounded local roots through plugin settings.
- Store app-only secrets only through protected plugin configuration.
- Use synthetic files containing no Ericsson or customer information.
- Do not use a live mutation merely as a readiness probe.

## Graph identity and file boundary

1. Enable `ericsson-sharepoint`, start a fresh conversation, and confirm its
   tools appear only there.
2. Exercise the approved identity mode: delegated MSAL, app-only, or Azure CLI.
   Capture only redacted readiness categories, never tokens or cache contents.
3. Resolve one permitted HTTPS tenant URL and list a folder with small bounds.
4. Download a synthetic file beneath the configured download root. Record its
   relative path, byte count, and digest.
5. Attempt traversal, a junction/reparse escape, and an unauthorized root.
   Each must fail closed without creating an outside file.

## Enrolled-browser authority

1. Before enrollment, confirm `sharepoint_audit_permissions` alone reports
   `browser_enrollment_required` while Graph file tools remain available.
2. Enroll the named profile through the core setup action and sign in visibly.
3. Audit one permitted site with small category/page/row/byte limits.
4. Confirm status distinguishes complete, partial, truncated, and unreachable
   categories and that evidence contains no cookies, headers, scripts, raw
   response bodies, debug URLs, profile paths, or credentials.
5. Release the acquired session and confirm unrelated browser sessions survive.

## Approved write smoke

In a disposable folder, preview and separately approve creation, small upload,
move or rename, asynchronous copy, and recycle. Confirm each operation rejects a
caller-authored approval claim, uses explicit conflict behavior, and reconciles
uncertain outcomes before any retry. Restore or remove test content through the
site's approved recovery process. Permanent delete must not be exposed.

## Evidence and result

Record the release version, full source stamp, Windows version, configured auth
mode, exact commands/prompts, sanitized results, and PASS/FAIL/PENDING for every
step. This checklist remains installed-UAT-only until run on the managed Windows
environment; source tests do not prove tenant policy or native Edge behavior.
