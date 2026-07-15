# Windows Resume Release Validation

This checklist is for the product owner validating an installed Co-Worker release on
a Windows machine. It proves that Ericsson onboarding resume selects the Windows
backend, persists only sanitized per-profile state, protects that state with native
Windows controls, and recovers safely under contention and interruption.

## Current verification status

On the macOS development host, the Windows test module collects 26 tests: 15
portable dispatch/API-boundary tests pass and 11 skipped Windows-native acceptance
tests remain. The shared state contract and macOS/Linux backend also pass locally.
Task 6 source is approved for native acceptance, but the Windows release result is
**pending**. Do not report native filesystem, ACL, junction, locking, or installed
release behavior as passed until this checklist is run and evidence is reviewed.

## Prerequisites and safety boundary

- Use a fresh Windows release installation under a dedicated Windows test account.
- Confirm the installed release's active profile home in product diagnostics. Do not
  assume a brand path and do not change the real user's global `HERMES_HOME`.
- Find the release-managed `hermes-agent` checkout beneath that profile and its
  `venv\Scripts\python.exe`; it contains the installed skill, not the source
  acceptance tests.
- Obtain a clean `ericsson-capabilities` source checkout at the exact full revision
  recorded by the release's `capabilities\ericsson.json` `vendoredFrom` field. The
  source checkout supplies `tests\test_onboarding_state_windows.py`. If that exact
  source is unavailable, run the installed-release smoke checks but report native
  pytest acceptance as `PENDING/INCOMPLETE`.
- **Task 9 delivery prerequisite:** the release must use a full `vendoredFrom` SHA
  and include `capabilities\ericsson-vendored-paths.json`. Those safeguards are
  verified after Task 9. Until both exist in the installed release, stop this
  checklist as `PENDING/INCOMPLETE`; do not accept a short or prefix SHA match.
- Create the source checkout's Windows venv with an approved Python 3.11+ and install
  `requirements-dev.txt` through the organization's approved package path. Do not
  replace the installed release's managed venv with the source test venv.
- Use only the fictional JSON below. Do not use real enterprise data, email, tickets,
  people, customers, opportunities, credentials, or authentication responses.
- Never paste secrets into chat or attach configuration files to the evidence.
- Run low-level tests against a new disposable directory under `%TEMP%`. Do not run
  destructive cases against the active release profile.
- Do not elevate merely to turn a fixture skip into a pass. Record the skip and its
  safe reason; the acceptance result remains incomplete until the required behavior
  can be exercised in an approved environment.

Open PowerShell as the normal test user and set these values. Replace
`$SourceRepo` with the exact source checkout and `$ReleaseHome` with the path shown
by the installed product:

```powershell
$SourceRepo = "C:\path\to\exact\ericsson-capabilities"
$ReleaseHome = "C:\path\reported\by\the\installed\release"
$ReleaseRepo = Join-Path $ReleaseHome "hermes-agent"
$SourcePython = Join-Path $SourceRepo ".venv\Scripts\python.exe"
$ReleasePython = Join-Path $ReleaseRepo "venv\Scripts\python.exe"
$InstalledSkill = Join-Path $ReleaseRepo "skills\ericsson\onboard-ericsson-capabilities"
$InstalledStateScript = Join-Path $InstalledSkill "scripts\onboarding_state.py"
$InstalledWindowsScript = Join-Path $InstalledSkill "scripts\onboarding_state_windows.py"
$VendorManifestPath = Join-Path $ReleaseRepo "capabilities\ericsson.json"
$VendorLedgerPath = Join-Path $ReleaseRepo "capabilities\ericsson-vendored-paths.json"
$TestRoot = Join-Path $env:TEMP ("coworker-resume-acceptance-" + [guid]::NewGuid())
$TestHomeA = Join-Path $TestRoot "profile-a"
$TestHomeB = Join-Path $TestRoot "profile-b"
New-Item -ItemType Directory -Path $TestRoot | Out-Null

if (-not (Test-Path $SourcePython)) {
  py -3.11 -m venv (Join-Path $SourceRepo ".venv")
}
& $SourcePython -m pip install -r (Join-Path $SourceRepo "requirements-dev.txt")

@($SourceRepo, $ReleaseRepo, $SourcePython, $ReleasePython,
  $InstalledStateScript, $InstalledWindowsScript, $VendorManifestPath,
  $VendorLedgerPath) | ForEach-Object {
  if (-not (Test-Path $_)) { throw "Required release path is missing: $_" }
}

$VendorManifest = Get-Content -Raw $VendorManifestPath | ConvertFrom-Json
$SourceRevision = (& git -C $SourceRepo rev-parse HEAD).Trim()
if ($SourceRevision -ne $VendorManifest.vendoredFrom) {
  throw "Source revision does not match the release vendoredFrom stamp."
}
```

Record the release version, brand, Windows edition/build, both Python versions,
source commit/vendor stamp, and whether PowerShell is elevated. Do not include usernames or
full local paths in a shared report; replace them with `<TEST_USER>` and
`<RELEASE_HOME>`.

## 1. Collection and OS dispatch proof

Run collection first so an outdated release cannot silently omit native cases:

```powershell
Push-Location $SourceRepo
& $SourcePython -m pytest tests/test_onboarding_state_windows.py --collect-only -q
Pop-Location
```

Expected: 26 tests collected, including 11 marked for Windows native resume
acceptance. Then prove explicit OS dispatch:

```powershell
& $ReleasePython -c "import importlib.util,json,os,sys; p=sys.argv[1]; s=importlib.util.spec_from_file_location('state_dispatch',p); m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; s.loader.exec_module(m); print(json.dumps({'os_name':os.name,'backend':m._backend_kind()},sort_keys=True))" $InstalledStateScript
```

Expected JSON:

```json
{"backend": "windows", "os_name": "nt"}
```

Any other backend is a failure. The implementation performs OS detection with
`os.name` and dispatches `nt` to the native Windows module; it does not attempt the
POSIX implementation or silently fall back to pathname-only writes.

## 2. Full native pytest acceptance

```powershell
Push-Location $SourceRepo
& $SourcePython -m pytest tests/test_onboarding_state_windows.py -q
Pop-Location
```

Expected: all 15 portable cases and all 11 native cases pass. Save the complete
terminal output. A native `skipped` result is not a pass; record its test name and
reason. The suite covers default-profile usability, private ACLs, reparse/junction
rejection, atomic replacement, history collision, clear behavior, two-process lock
timeout/recovery, concurrent save/complete/clear, profile isolation, and injected
post-commit failure reporting.

## 3. Manual save, show, resume, complete, and clear

Create a schema-valid, sanitized checkpoint:

```powershell
$InputA = Join-Path $TestRoot "state-a.json"
$StateJson = @'
{
  "schemaVersion": "1.0",
  "catalogVersion": "0.4.0",
  "selectedCapabilities": ["jira-tools"],
  "maturity": {"jira-tools": "available"},
  "readinessFacts": {
    "jira-tools": {
      "state": "unknown-needs-check",
      "discoverable": true,
      "enabled": true,
      "platformSupported": true,
      "requiredSettingsConfigured": null,
      "permissionAdequate": null,
      "dependencyAvailable": true,
      "authenticationValidated": null,
      "safeProbeSucceeded": null
    }
  },
  "completedSteps": ["Read the Jira tools overview."],
  "pendingActions": ["Check protected Jira settings without printing values."],
  "artifactPointers": [],
  "nextPrompt": "Check Jira readiness without a write.",
  "createdAt": "2026-07-15T15:00:00Z",
  "updatedAt": "2026-07-15T15:00:00Z"
}
'@
[System.IO.File]::WriteAllText(
  $InputA, $StateJson, [System.Text.UTF8Encoding]::new($false)
)

& $ReleasePython $InstalledStateScript --home $TestHomeA save --input $InputA
& $ReleasePython $InstalledStateScript --home $TestHomeA show
```

Expected output is one JSON object per command. `save` returns `ok: true` and a path
ending in `onboarding\ericsson\current.json`. `show` returns `ok: true` and the exact
sanitized state. It must not add a credential or reveal another profile.

Close PowerShell, open a new normal-user PowerShell, restore the variables, and run
the `show` command again. This fresh-process `show` is the low-level resume proof.
Then complete and clear:

```powershell
& $ReleasePython $InstalledStateScript --home $TestHomeA complete
& $ReleasePython $InstalledStateScript --home $TestHomeA show
& $ReleasePython $InstalledStateScript --home $TestHomeA save --input $InputA
& $ReleasePython $InstalledStateScript --home $TestHomeA clear
& $ReleasePython $InstalledStateScript --home $TestHomeA show
```

Expected:

- `complete` returns `ok: true` and a new UTC-timestamped JSON path under `history`;
- the following `show` returns `{"ok": true, "state": null}`;
- the second `save` succeeds;
- `clear` returns `{"cleared": true, "ok": true}`;
- the final `show` again has `state: null`.

Keep the archived history for later collision inspection. Do not edit a persisted
JSON file manually.

## 4. Private ACL and protected inheritance

Save once more, then inspect the state root, `history`, and `current.json`:

```powershell
& $ReleasePython $InstalledStateScript --home $TestHomeA save --input $InputA
$StateRoot = Join-Path $TestHomeA "onboarding\ericsson"
$Current = Join-Path $StateRoot "current.json"

Get-Acl $StateRoot | Select-Object Owner,AreAccessRulesProtected
Get-Acl (Join-Path $StateRoot "history") | Select-Object Owner,AreAccessRulesProtected
Get-Acl $Current | Select-Object Owner,AreAccessRulesProtected
icacls $StateRoot
icacls (Join-Path $StateRoot "history")
icacls $Current

& $ReleasePython -c "import importlib.util,json,sys; p=sys.argv[1]; paths=sys.argv[2:]; s=importlib.util.spec_from_file_location('state_windows_acl',p); m=importlib.util.module_from_spec(s); sys.modules[s.name]=m; s.loader.exec_module(m); print(json.dumps({x:m.native_acl_is_private(x) for x in paths},sort_keys=True))" $InstalledWindowsScript $StateRoot (Join-Path $StateRoot "history") $Current
```

Expected: each object is owned by the current test user, inheritance is protected
(`AreAccessRulesProtected` is `True`), and its allow ACL contains exactly the owner
and local SYSTEM (`S-1-5-18`) with full access. There must be no inherited `(I)` ACE,
Everyone, Users, or other principal. The Python result must map all three paths to
`true`. Localized Windows may display a localized name for SYSTEM; retain the SID in
evidence when available.

## 5. Reparse point and junction rejection

The full suite exercises symbolic-link/reparse and junction rejection. Run the
focused cases and keep their output:

```powershell
Push-Location $SourceRepo
& $SourcePython -m pytest `
  tests/test_onboarding_state_windows.py::test_native_reparse_component_is_rejected `
  tests/test_onboarding_state_windows.py::test_native_junction_component_is_rejected -q
Pop-Location
```

For an additional release-level junction check inside the disposable root:

```powershell
$Target = Join-Path $TestRoot "junction-target"
$Junction = Join-Path $TestRoot "profile-junction"
New-Item -ItemType Directory -Path $Target | Out-Null
$JunctionOutput = & cmd.exe /c "mklink /J `"$Junction`" `"$Target`""
$JunctionExit = $LASTEXITCODE
if ($JunctionExit -ne 0) {
  throw "PENDING/INCOMPLETE: junction fixture setup failed before backend testing. $JunctionOutput"
}
if (-not (Test-Path -LiteralPath $Junction)) {
  throw "PENDING/INCOMPLETE: mklink reported success but the junction fixture is absent."
}
$JunctionItem = Get-Item -LiteralPath $Junction -Force
$IsReparse = [bool]($JunctionItem.Attributes -band [IO.FileAttributes]::ReparsePoint)
if (-not $IsReparse -or $JunctionItem.LinkType -ne "Junction") {
  throw "PENDING/INCOMPLETE: fixture exists but is not a verified junction/reparse point."
}

$StateLines = & $ReleasePython $InstalledStateScript --home $Junction save --input $InputA
$StateExit = $LASTEXITCODE
$StateOutput = $StateLines -join "`n"
$StateOutput
$StateResult = $StateOutput | ConvertFrom-Json
if (($StateExit -ne 1) -or ($StateResult.ok -ne $false) -or ($StateResult.error -notmatch "reparse|symbolic link")) {
  throw "FAIL: installed backend did not reject the verified junction fixture."
}
$TargetState = Join-Path $Target "onboarding\ericsson\current.json"
if (Test-Path -LiteralPath $TargetState) {
  throw "FAIL: junction test redirected onboarding state into the target."
}
```

Fixture setup failure is a separate `PENDING/INCOMPLETE` result and the backend must
not be invoked. With a verified junction, expected backend behavior is exit code 1
and one safe JSON object with `ok: false` and an error that mentions a symbolic link
or reparse point. No target-side `current.json` may exist. Do not weaken ACLs to make
this case run.

## 6. Lock timeout, recovery, atomicity, and concurrency

Run the focused native cases:

```powershell
Push-Location $SourceRepo
& $SourcePython -m pytest `
  tests/test_onboarding_state_windows.py::test_native_lock_timeout_and_recovery `
  tests/test_onboarding_state_windows.py::test_native_atomic_replacement_and_no_replace_history `
  tests/test_onboarding_state_windows.py::test_native_clear_and_generation_conflict `
  tests/test_onboarding_state_windows.py::test_native_concurrent_save_complete_clear_remain_consistent -q
Pop-Location
```

Expected behavior:

- while a second process holds the profile lock, another operation stops after the
  bounded timeout with a safe `busy; retry` error;
- after the holder exits, the next operation succeeds without deleting the lock or
  corrupting state;
- a newer save atomically replaces the prior current record;
- completion never replaces an existing timestamped history entry and reports a
  history collision;
- concurrent save/complete/clear serializes to either no current state or the full
  newest record—never truncated JSON, mixed generations, or another profile's data.

## 7. Interrupted write and partial-effect recovery

```powershell
Push-Location $SourceRepo
& $SourcePython -m pytest `
  tests/test_onboarding_state_windows.py::test_native_injected_post_commit_failure_reports_partial_effect -q
Pop-Location
```

Expected: the injected directory-flush failure produces an error naming only the
safe relative `current.json` recovery location. The committed full record remains
inspectable. For completion failures, safe errors may name
`history/<timestamp>.json` and a generated `history/.history.<id>.tmp`; they must
explain whether `current.json` remains active. Inspect before retrying. Never paste
the persisted JSON into a shared failure report.

Unexpected real interruption procedure:

1. Stop and preserve terminal output.
2. Run `show` once; do not immediately save, complete, or clear.
3. List only filenames and sizes in the state root and history; redact the profile
   prefix.
4. If a safe error names a temporary or history file, record that relative name.
5. Report whether `current.json` is absent, valid and complete, or unreadable. Do not
   manually combine records or rerun a possible write.

## 8. Profile isolation and default-profile usability

```powershell
Push-Location $SourceRepo
& $SourcePython -m pytest `
  tests/test_onboarding_state_windows.py::test_native_round_trip_and_profile_isolation `
  tests/test_onboarding_state_windows.py::test_native_round_trip_beneath_default_user_profile -q
Pop-Location
```

For manual isolation, copy `$InputA` to a second file, change only `nextPrompt` to
`"Profile B checkpoint."`, save it with `--home $TestHomeB`, and show both homes.
Expected: each home returns only its own full record. Clearing A must not change B.

The default-profile native test creates and removes its own temporary directory
beneath `%USERPROFILE%`; it does not write the installed Co-Worker profile.

## 9. Minimal installed-release conversation

Perform this only on the fresh release test account after the disposable checks
pass. First use the low-level `show` command against `$ReleaseHome`. If it returns a
non-null state, stop rather than overwrite an existing journey.

```powershell
& $ReleasePython $InstalledStateScript --home $ReleaseHome show
```

1. Open Co-Worker and say, **“Please onboard me to the Co-Worker capabilities.”**
2. Choose a fictional learning-only route and consent to saving a checkpoint. Do not
   configure an integration, sign in, or use a live write.
3. Close Co-Worker completely and reopen the same installed release/profile.
4. Say, **“Resume my Ericsson onboarding.”**
5. Expect the sanitized completed step and next action, plus a statement that
   volatile readiness will be rechecked. No prior transcript or fictional payload
   should be reproduced.
6. Ask to complete the journey. Verify a history record exists and no current record
   remains. Start one final empty learning checkpoint and ask Co-Worker to forget it;
   verify `show` returns null.

If the release is upgraded or reinstalled as part of acceptance, a normal
upgrade/reinstall is expected to preserve profile resume data. Record a redacted
`Get-FileHash` of `current.json` before and after. If the uninstaller offers an
explicit remove-profile-data choice, do not select it for preservation testing; a
deliberate data-removal path may delete the checkpoint and is a separate test.

## Cleanup

Close Co-Worker and all test PowerShell processes. Remove the junction itself with
`cmd /c rmdir "$Junction"` before removing its target. Then remove only the GUID
disposable root after verifying `$TestRoot` begins with the expected `%TEMP%`
prefix:

```powershell
if ($TestRoot.StartsWith($env:TEMP) -and
    (Split-Path $TestRoot -Leaf).StartsWith("coworker-resume-acceptance-")) {
  if (Test-Path $Junction) { cmd /c rmdir "$Junction" }
  Remove-Item -LiteralPath $TestRoot -Recurse -Force
} else {
  throw "Refusing cleanup outside the disposable acceptance root."
}
```

Remove the release-profile conversational checkpoint only through the Co-Worker
forget/complete action used above. Do not delete the real profile tree manually.

## Evidence and pass/fail report

Return one secret-free evidence bundle containing:

- release version, brand, Windows build, Python version, source commit/vendor stamp;
- collection count and the OS dispatch JSON;
- full pytest summary with every skipped/failed native test named;
- manual save/show/complete/clear JSON with profile prefixes redacted;
- `Get-Acl` protected-inheritance result, `icacls` principal/SID summary, and the
  `native_acl_is_private` JSON;
- focused reparse/junction, lock, atomic/history collision, concurrency,
  interrupted-write, isolation, and default-profile results;
- installed-release resume/complete/forget observations and optional
  upgrade/reinstall hash comparison;
- cleanup result.

Report each section as `PASS`, `FAIL`, or `PENDING/INCOMPLETE`. Include the exact
test name, exit code, safe error text, and redacted relative artifact name for a
failure. Do not include tokens, environment dumps, configuration files, checkpoint
contents, usernames, email/ticket data, or full local paths. A failure report should
be sufficient to reproduce the boundary without exposing user data.
