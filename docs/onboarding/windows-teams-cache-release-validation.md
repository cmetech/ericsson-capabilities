# Windows Teams Cache Release Validation

This installed-release checklist validates that an Ericsson Teams sign-in cache can
be created and used by a normal Windows user without exposing its contents. It is
not satisfied by source mocks or by a successful core secret-store check.

## Contract under test

The Teams plugin stores its MSAL cache at
`$HERMES_HOME/ericsson/msal_token_cache.json`. On Windows, the cache directory, any
publication temporary, and the final file must use the Hermes generic protected
current-user ACL. The validation runs unelevated and does not require
`SeSecurityPrivilege`.

This cache is an interactive Teams session artifact. It is separate from plugin
descriptor secrets and from `hermes secrets doctor --write-probe`; do not treat a
doctor write-probe result as a Teams cache result.

## Prerequisites and evidence boundary

- Use the installed release under a dedicated, non-administrator Windows test
  account and a disposable Microsoft test account/session. Do not use a production
  account or another user's profile.
- Start from a clean test profile or a deliberately cleared Teams session. Record
  the product brand, installed version, full Ericsson source/vendor commit, Windows
  version, and the result of each step. Redact usernames and absolute profile paths.
- Run every command in an ordinary PowerShell window. Do not elevate PowerShell,
  change ACLs manually, enable privileges, or request `SeSecurityPrivilege`.
- Never paste or capture a device code, token, browser response, cache byte,
  authentication response, environment dump, or full local path. Evidence may name
  the cache only as `<HERMES_HOME>\\ericsson\\msal_token_cache.json`.

Set only redacted inspection variables; these commands do not print cache bytes:

```powershell
$HermesHome = if ([string]::IsNullOrWhiteSpace($env:HERMES_HOME)) {
  Join-Path $HOME ".hermes"
} else {
  $env:HERMES_HOME
}
$Cache = Join-Path $HermesHome "ericsson\\msal_token_cache.json"
$CacheParent = Split-Path -Parent $Cache
$CacheLeaf = Split-Path -Leaf $Cache
$TempPattern = ".${CacheLeaf}.*.tmp"
```

Expected precondition state: the test is running as the dedicated standard user,
and there is no persistent Teams session from a previous test run.

## Authenticate and inspect the protected artifacts

1. In a fresh product conversation, invoke `teams_auth` with no arguments. Open the
   verification URL only in the disposable account's browser session and enter the
   displayed device code there. Record only `teams_auth started`—never the code or
   URL parameters.
2. Invoke `teams_auth` with `complete=true`. Expected redacted state: `ok: true`.
   A pending state may be retried only after the browser sign-in completes. Use
   `teams_list` with its normal bounded read-only behavior as the readiness check;
   do not send or reply to a channel for this validation.
3. Confirm the final cache exists without reading it:

   ```powershell
   Test-Path -LiteralPath $Cache
   Get-Item -LiteralPath $Cache | Select-Object Name, Length, LastWriteTime
   Get-ChildItem -LiteralPath $CacheParent -Filter $TempPattern |
     Select-Object Name, Length, LastWriteTime
   ```

   Expected redacted state: the final cache exists; no publication temporary remains
   after the completed operation. Record only the final file name, metadata, and
   temporary count—never bytes or a content-derived value.
4. Inspect ownership and DACL metadata for the cache directory and final file. These
   commands must not be replaced with `Get-Content`, `type`, `more`, `Select-String`,
   archive, copy, hash, or any command that reads cache bytes:

   ```powershell
   Get-Acl -LiteralPath $CacheParent |
     Select-Object Owner, AreAccessRulesProtected, AccessToString
   Get-Acl -LiteralPath $Cache |
     Select-Object Owner, AreAccessRulesProtected, AccessToString
   ```

   Expected redacted state for both artifacts: owner is the dedicated current user,
   inheritance is protected, and the effective explicit access is restricted to that
   current user under the generic protected current-user rule. Do not record a SID,
   username, or full path. An ACL read failure is a failed check, not a reason to
   elevate.
5. Repeat one bounded `teams_list` call in the same disposable session. Expected
   redacted state: the cache remains usable and the cache inspection still reports
   the protected current-user state. Record only the tool outcome category and ACL
   state.

## Failure handling and cleanup

If `teams_auth` or a later Teams read reports that the cache could not be read or
stored securely, treat it as fail-closed. Do not relax ACLs, move/copy the cache,
inspect its contents, or work around the result with a descriptor secret or
`hermes secrets doctor --write-probe`. Record the redacted failure category, correct
the local filesystem condition through the approved support process, clear the
disposable session, and start again with `teams_auth`.

At the end of every run, clear the disposable Teams session by closing the product
conversation and removing only the test profile's cache artifacts through the
approved release cleanup process. With the product stopped, verify metadata only:

```powershell
Remove-Item -LiteralPath $Cache -Force -ErrorAction Stop
$RemainingTemps = @(Get-ChildItem -LiteralPath $CacheParent -Filter $TempPattern -ErrorAction Stop)
if ($RemainingTemps.Count -ne 0) {
  throw "Teams cache cleanup left temporary artifacts"
}
if (Test-Path -LiteralPath $Cache) {
  throw "Teams cache cleanup left the final cache"
}
```

Expected final redacted state: the command completes without error, the final cache
is absent, and the temporary re-list contains zero entries. Do not remove another
profile's cache or a shared `HERMES_HOME`; retain no device code, token, cache file,
browser session, or captured authentication output.

## Result

Mark the checklist `PASS` only when the disposable standard-user session completes
the bounded read-only flow, the parent and final file show the protected
current-user ACL state, no temporary remains after publication, and cleanup leaves
no test cache. Mark it `FAIL` for any ACL, ownership, path, reparse-point,
authentication, or cleanup failure; mark it `PENDING/INCOMPLETE` when the installed
release, disposable account, or required evidence is unavailable. Include the
brand, version, commit, redacted commands, expected/actual redacted states, and
PASS/FAIL/PENDING result in the release record.
