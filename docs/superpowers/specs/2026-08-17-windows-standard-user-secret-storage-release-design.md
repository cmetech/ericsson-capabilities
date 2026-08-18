# Windows Standard-User Secret Storage and Branded Release Design

**Date:** 2026-08-17

**Ericsson source branch:** `fix/windows-standard-user-secret-storage`

**Hermes integration branch:** `fix/windows-standard-user-secret-storage`

**Release versions:** OTTO `v5.8.4` and LOOP24 `v5.8.4`

## Context

On a standard managed Windows account, saving an Artifactory token through the
LOOP24 plugin configuration surface fails with the stable public error
`plugin configuration could not be persisted`. The same process emits this
more specific startup warning:

```text
Windows ACL drift remains ... PowerShell ACL operation failed:
Set-Acl ... SeSecurityPrivilege ... PrivilegeNotHeldException
```

The reproduction proves the request passes schema validation and reaches the
secure secret prompt. `loop24 secrets doctor` reports no findings because its
default inspection is read-only and the empty store has no artifact whose ACL
can be inspected. The write then fails before Windows Credential Manager is
reached: `secret_keystore.set_secrets()` creates the profile transaction root,
and `_ensure_private_permissions()` calls the shared PowerShell ACL helper as a
hard persistence boundary.

This is not a JFrog token, plugin-enable, or general Windows standard-user
limitation. The installed super-cli uses Windows Credential Manager through
`go-keyring` successfully under the same class of non-administrator account.
Hermes adds a filesystem authority registry and transaction lock to provide
durable per-key authority, revocation, recovery, and cross-process
transactions. That additional filesystem layer exposes the failing ACL path.

The same shared ACL helper protects every descriptor-backed plugin secret, so
the defect affects Artifactory, Jira, Confluence, and any present or future
plugin using the central configuration keystore. Ericsson Teams has a separate
MSAL refresh-token cache at
`$HERMES_HOME/ericsson/msal_token_cache.json`; its Windows path atomically
replaces the cache but does not apply or verify a private ACL. This release
closes both paths.

## Goals

1. Allow a standard, non-elevated Windows user to write, read, replace, and
   clear centrally managed plugin secrets.
2. Preserve Hermes' durable authority registry, encrypted-file fallback,
   transaction locking, rollback, and revocation semantics.
3. Replace the PowerShell ACL mutation with a native Win32 boundary that never
   requests SACL access or `SeSecurityPrivilege`.
4. Make the shared boundary cover all central plugin secrets without
   connector-specific exceptions.
5. Apply and verify the same boundary for the separate Ericsson Teams MSAL
   cache on Windows.
6. Keep default `secrets doctor` byte-for-byte read-only while adding an
   explicit synthetic write probe that can diagnose write-time ACL failures.
7. Deliver the verified source through neutral Hermes `base`, regenerate both
   brands, and publish unsigned OTTO and LOOP24 `v5.8.4` releases.

## Non-goals

- Running LOOP24, OTTO, PowerShell, or Python as Administrator.
- Granting `SeSecurityPrivilege`, weakening ACL checks, or treating `chmod` as
  a Windows security boundary.
- Removing the authority registry to imitate super-cli's simpler persistence
  model.
- Replacing Windows Credential Manager or Python `keyring`.
- Migrating the Teams MSAL cache into the central plugin keystore.
- Adding Windows or macOS code signing. The existing release workflows
  deliberately publish unsigned artifacts.
- Holding publication for manual installed-UAT. The owner has accepted
  immediate publication after automated gates because there are currently no
  other active users; installed smoke testing follows publication and any
  failure produces a later patch release.

## Decisions

### D1. Use a native handle-based Win32 ACL boundary

`hermes_cli/windows_permissions.py` keeps its public functions:

```python
def restrict_file_to_current_user(path: Path) -> None: ...
def restrict_directory_to_current_user(path: Path) -> None: ...
def inspect_file_acl(path: Path) -> WindowsAclInspection: ...
def inspect_directory_acl(path: Path) -> WindowsAclInspection: ...
```

Their Windows implementation moves from PowerShell `Get-Acl`/`Set-Acl` to a
small `ctypes` adapter over Win32 security APIs. The implementation follows the
native handle and validation pattern already used by
`onboarding_state_windows.py`, but the generic helper remains focused on ACL
application and inspection rather than absorbing onboarding persistence.

The helper opens the exact file or directory with reparse traversal disabled,
captures its stable identity, obtains the current process token SID, reads the
owner and DACL with `GetSecurityInfo`, and requires the existing owner to equal
the current user. It constructs a protected DACL containing exactly the
current-user ACE required by the existing Hermes policy. It applies only
`DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION` through
`SetSecurityInfo`; it does not set or query the SACL and does not attempt to
take ownership.

Avoiding `SACL_SECURITY_INFORMATION` is load-bearing: Windows requires
`SeSecurityPrivilege` for SACL access. Requiring current ownership and changing
only the DACL uses the ordinary owner's `WRITE_DAC` authority. A foreign owner
is a typed failure with remediation guidance, not an invitation to elevate or
seize ownership.

After application, the same open handle is re-inspected. Success requires:

- unchanged file identity;
- current-user ownership;
- protected inheritance;
- exactly one explicit allow ACE for the current user;
- the exact file or directory rights already defined by Hermes; and
- no inherited, deny, broad, unknown, or additional ACE.

Every Win32 error is normalized to `WindowsAclError` without including a
credential value. Callers retain their existing stable error envelopes.

### D2. Do not use the narrower alternatives

A freshly constructed PowerShell `FileSecurity` object would be a smaller
patch, but it would retain the failing subprocess/tooling boundary and managed
PowerShell variability. Removing the filesystem authority registry for OS-tier
secrets would resemble super-cli but would discard Hermes' stronger durable
authority and revocation design and would not fix encrypted fallback or Teams.

### D3. One core helper serves all central plugin secrets

The central plugin configuration service remains connector-neutral. No Jira,
Confluence, ARM, or future connector receives a private Windows workaround.
Tests exercise multiple real descriptor-backed plugin fields through
`PluginConfigurationService.update()` and `clear_secret()` so a green
low-level ACL unit test cannot conceal a broken service-level path.

### D4. Teams consumes the generic Hermes ACL contract lazily

`plugins/ericsson-teams/graph_auth.py` remains the Ericsson source of truth.
Its Windows branch lazily imports the four public ACL functions from
`hermes_cli.windows_permissions` only when running inside Hermes on Windows.
This is a dependency on a generic host security service, not a Teams-specific
core exception.

Source-side tests inject a fake ACL adapter and remain runnable without a
Hermes source checkout. Vendored integration tests use the real host module.
Missing or incompatible host ACL support fails with the existing redacted
`AuthRequired("could not ... securely")` contract; it never falls back to an
unprotected cache.

### D5. Teams protects reads and every publication boundary

On Windows, Teams:

1. creates or opens the cache parent as a direct directory;
2. rejects symlink, junction, reparse-point, and wrong-type components;
3. applies and verifies the private directory ACL;
4. creates a unique temporary file without replacing an existing entry;
5. applies and verifies the private file ACL before writing token state;
6. writes, flushes, and closes the temporary;
7. atomically replaces the destination;
8. applies and verifies the final destination ACL; and
9. removes an unpublished temporary on failure.

Before deserializing an existing cache, the read path validates the parent and
cache types, applies and verifies their ACLs, enforces the existing 16 MiB
bound, and returns only redacted failures. POSIX descriptor-relative behavior
is unchanged.

### D6. Default doctor remains read-only; write probing is explicit

`secrets doctor` preserves its strict read-only contract. A new explicit flag,
`secrets doctor --write-probe`, performs a synthetic ACL write test without
storing a credential or touching the authority registry, OS keyring, master
key, or ciphertext.

The probe creates a uniquely named temporary directory below the active
profile, creates one synthetic file, applies and verifies both ACLs through the
production helper, deletes both artifacts, and reports stable finding codes.
Cleanup failure is an error and reports the artifact path for manual review.
The probe payload is a fixed noncredential sentinel. It never accepts or logs a
token. The option is documented as mutating and is never implied by plain
`doctor`.

## Architecture and Data Flow

### Central plugin secret write

```text
Desktop or CLI configuration request
  -> PluginConfigurationService.update()
  -> secret_keystore.set_secrets()
  -> create/open profile transaction root and lock
  -> native current-user DACL apply + verify
  -> Windows Credential Manager or encrypted file transaction
  -> atomic authority-registry publication
  -> configuration detail reports is_set=true
```

ACL failure aborts before authority publication, compensates any staged
transaction, and returns the existing stable plugin persistence error. No
plaintext fallback is introduced.

### Teams MSAL cache write

```text
MSAL cache has_state_changed
  -> graph_auth._persist()
  -> Windows secure cache adapter
  -> native private parent/temp ACL apply + verify
  -> bounded write + flush
  -> atomic replace
  -> native final ACL apply + verify
  -> return to MSAL flow
```

Any failure becomes a redacted `AuthRequired` result. Device codes, access
tokens, refresh tokens, and serialized cache bytes never appear in exceptions,
logs, subprocess environments, or command arguments.

## Files and Ownership

### `ericsson-capabilities`

- Modify `plugins/ericsson-teams/graph_auth.py` for the Windows secure-cache
  adapter and lazy host ACL integration.
- Modify `tests/test_teams_plugin.py` for portable adapter contracts, redaction,
  failure cleanup, atomic replacement, and Windows-native acceptance cases.
- Modify `docs/configuration.md` and Teams onboarding/troubleshooting material
  to state the private Windows-cache and standard-user contract.
- Regenerate the onboarding catalog only if its generated inputs materially
  change.
- Add an installed Windows Teams credential-cache validation checklist or
  extend the existing Windows release documentation with exact redacted steps.

### `hermes-agent`

- Modify `hermes_cli/windows_permissions.py` to replace PowerShell mutation and
  inspection with the native handle-based adapter.
- Modify `hermes_cli/secrets_repair.py` to parse and report the explicit
  `--write-probe` result while keeping default doctor read-only.
- Modify `hermes_cli/secret_keystore.py` only if the native helper requires a
  more precise typed-error or stable-handle integration seam.
- Modify `tests/hermes_cli/test_windows_permissions.py` for Win32 boundary and
  invariant tests.
- Modify `tests/hermes_cli/test_secret_keystore.py`,
  `tests/hermes_cli/test_secrets_repair.py`, and
  `tests/hermes_cli/test_plugin_configuration_storage.py` for real write-path
  coverage.
- Vendor the exact committed Ericsson source revision, including the Teams
  changes and generated catalog/docs.
- Add or update installed Windows release validation documentation.

No brand branch owns a handwritten copy of these changes. The neutral runtime
fix and vendored Ericsson bytes land on Hermes `base`, then flow through the
brand generator.

## Test Strategy

Every code slice uses RED/GREEN TDD and atomic commits.

### Portable and mocked-host tests

- Native API signatures, requested access masks, and security-information
  flags exclude SACL access and owner mutation.
- Current SID and paths are passed as data, never interpolated into executable
  PowerShell or shell source.
- File and directory ACLs have the exact protected current-user ACE and rights.
- Foreign ownership, reparse points, identity changes, extra ACEs, inherited
  ACEs, missing DACLs, wrong types, and Win32 errors fail closed.
- Plain doctor performs no writes; `--write-probe` creates only its synthetic
  artifacts and removes them on success.
- Plugin secret write/read/clear works for at least ARM, Jira, and Confluence
  descriptors through the real service and a temporary profile.
- File fallback and OS-keyring authority paths both retain correct registry and
  rollback behavior.
- Teams Windows cache tests prove private ACL calls before write and after
  replacement, secure read validation, cleanup after injected failures, and
  secret-free errors.
- Existing POSIX permission, keyring, migration, repair, and Teams tests remain
  green.

### Native Windows automated gate

On a non-administrator Windows runner or standard-user child process:

- assert the token is not elevated and the process does not have
  `SeSecurityPrivilege` enabled;
- create a fresh temporary `HERMES_HOME`;
- run `secrets doctor` and prove it is read-only;
- run `secrets doctor --write-probe` and require success plus zero leftovers;
- store, resolve, replace, and clear synthetic central plugin secrets;
- exercise both OS-keyring and forced encrypted-file modes;
- inspect every transaction artifact and require the exact private DACL;
- persist, read, replace, and clear a synthetic Teams MSAL cache;
- inject an extra ACE and prove the next authorized operation repairs it;
- reject a reparse/junction path without touching its target; and
- rerun the originally failing `loop24 tools configure ericsson-arm --secret
  token` flow with a disposable synthetic value, then confirm `is_set=true` and
  clear it.

Tests never use a production token. Any native case that cannot establish its
fixture must fail the automated gate rather than skip, except a specifically
documented foreign-owner fixture whose creation itself requires elevation.

### Repository and delivery gates

- Focused Ericsson Teams and onboarding tests.
- Ericsson full suite and onboarding catalog build/check/validation.
- Focused Hermes ACL, keystore, repair, plugin configuration, and vendored
  Ericsson tests.
- Hermes Windows-footgun, dependency, brand-neutral, and full Python suites.
- Exact source-to-vendor byte comparison and vendor inventory validation.
- Brand discovery from `brands/*.json` rather than a hardcoded two-item list.
- Merge `base` into every discovered brand and run each generator with
  `--write` and `--check`.
- Verify neutral runtime and vendored Ericsson bytes are identical across
  `base`, `otto`, and `loop24`, apart from declared generated overlays.
- Run desktop typecheck, lint, unit, Electron, build, and brand checks.
- Verify clean checkouts and push source, base, and brand refs before release.

## Delivery and Release

1. Implement and commit the Teams source fix on the Ericsson feature branch.
2. Pass Ericsson focused, onboarding, catalog, shared-sync, and full-suite
   gates; merge and push it to `ericsson-capabilities/main`.
3. Implement and commit the generic native ACL and doctor-probe fix on a Hermes
   feature branch created from `base`.
4. Vendor the exact Ericsson `main` revision into that Hermes feature branch
   and verify byte identity.
5. Pass focused, native Windows, full-suite, desktop, vendor, and security
   review gates.
6. Merge the Hermes feature branch into `base` and push `base`. Literal
   `main` remains untouched.
7. Discover every brand from `brands/*.json`; merge `base`, regenerate, check,
   commit, and push each brand. Finish the working checkout clean on `base`.
8. Confirm remote OTTO and LOOP24 latest versions remain `v5.8.3`; abort rather
   than overwrite if either has advanced. If both remain unchanged, dispatch
   the existing unsigned release workflow for `v5.8.4` from `otto` and
   `loop24`, with each brand tracking its own branch.
9. Monitor both release workflows through artifact upload and GitHub release
   publication. Require Windows NSIS/MSI and macOS DMG/ZIP assets for both
   brands and verify each install stamp references the expected brand commit.
10. Perform post-publication Windows smoke tests on the standard account that
    reproduced the failure: central ARM/Jira/Confluence secret persistence,
    explicit doctor write probe, and Teams MSAL cache persistence. Record any
    failure as a blocker for the next patch release, not as retroactive evidence
    that the published release passed.

Release publication is authorized without a pre-publication installed-UAT
checkpoint. It is still conditional on all automated gates and successful
artifact construction. No workflow may overwrite an existing tag or release.

## Success Criteria

- A non-admin Windows user can save an ARM token and status reports
  `"is_set": true`.
- The same central path works for Jira, Confluence, and future descriptor-backed
  plugin secrets without connector-specific code.
- Standard-user writes do not require `SeSecurityPrivilege`, elevation, or
  PowerShell ACL mutation.
- The authority registry, lock, key, ciphertext, `.env`, and relevant temporary
  artifacts retain exact private ACLs.
- Plain doctor stays read-only; the explicit write probe accurately detects the
  production ACL path and leaves no artifacts on success.
- Teams' Windows MSAL cache is private before any serialized token state can be
  consumed or published.
- Both source repositories and all Hermes brand branches are clean, committed,
  and pushed with exact provenance.
- Unsigned OTTO and LOOP24 `v5.8.4` releases are publicly published with all
  expected platform assets and correct source stamps.

## Risks and Mitigations

- **Win32 API complexity:** keep the adapter small, derive it from the existing
  native onboarding pattern, and test every requested mask and failure code.
- **TOCTOU or reparse traversal:** operate on verified handles, compare stable
  identity before and after mutation, and fail closed.
- **Over-broad ACL:** build a protected DACL from a fixed policy and verify the
  exact ACE set after application.
- **Teams/core coupling:** consume only the generic host ACL API lazily and keep
  a source-side injectable adapter contract.
- **Doctor mutation surprise:** default remains read-only; mutation requires
  the explicit `--write-probe` flag and uses only synthetic data.
- **Immediate-publication risk:** the owner accepts post-release installed UAT;
  automated native Windows tests remain mandatory before dispatch.
- **Version race:** re-read remote tags immediately before dispatch and abort
  if either brand has advanced beyond `v5.8.3`.

## References

- Microsoft, [Security Descriptor Operations](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-operations).
- Microsoft, [GetNamedSecurityInfoW](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-getnamedsecurityinfow).
- Microsoft, [SetNamedSecurityInfo](https://learn.microsoft.com/en-us/windows/win32/api/aclapi/nf-aclapi-setnamedsecurityinfoa).
- Microsoft, [Security Descriptor String Format](https://learn.microsoft.com/en-us/windows/win32/secauthz/security-descriptor-string-format).
- Existing native reference implementation:
  `skills/ericsson/onboard-ericsson-capabilities/scripts/onboarding_state_windows.py`.
- Existing Hermes authority and recovery contract:
  `hermes-agent/docs/superpowers/specs/2026-08-16-credential-storage-parity-remediation-design.md`.
