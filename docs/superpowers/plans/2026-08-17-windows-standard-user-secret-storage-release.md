# Windows Standard-User Secret Storage and Branded v5.8.4 Release Plan

> **For Codex:** REQUIRED SKILLS DURING EXECUTION: use
> `superpowers:using-git-worktrees` before creating the Hermes integration
> checkout; use `superpowers:test-driven-development` for every code task;
> use `superpowers:systematic-debugging` for any unexpected failure; use
> `superpowers:requesting-code-review` at the two source-closure checkpoints;
> use `superpowers:verification-before-completion` before every completion or
> release claim; and use `superpowers:finishing-a-development-branch` for the
> Ericsson and Hermes integrations.

**Goal:** Make all descriptor-backed plugin secrets and the Ericsson Teams
MSAL cache persist securely for a standard, non-elevated Windows user, add an
explicit diagnostic write probe, and publish complete unsigned OTTO and
LOOP24 `v5.8.4` desktop releases.

**Architecture:** Replace the shared PowerShell ACL subprocess with a small
native, handle-based Win32 adapter that verifies current ownership and applies
only a protected current-user DACL. Keep the public ACL API unchanged so the
central keystore and all plugin descriptors inherit the fix. Ericsson Teams
lazily consumes that same host API around its separate atomic MSAL cache. Plain
`secrets doctor` remains read-only; `--write-probe` exercises only synthetic
profile-local directory/file ACLs and cleans them up.

**Technology:** Python 3.11-compatible `ctypes`, Win32 `kernel32`/`advapi32`,
pytest, PowerShell only as a CI launcher for a standard-user child process,
Node 22 brand/vendor scripts, Git/GitHub CLI, existing unsigned Electron
release workflows.

**Approved design:**
`docs/superpowers/specs/2026-08-17-windows-standard-user-secret-storage-release-design.md`

**Repository path variables:** Set these once in the execution shell before
running the commands below. They intentionally identify the checked-out release
repositories without depending on one developer's home directory.

```bash
WORKSPACE_ROOT=/path/to/otto_hermes
ERICSSON_REPO="$WORKSPACE_ROOT/ericsson-capabilities"
HERMES_REPO="$WORKSPACE_ROOT/hermes-agent"
HERMES_SECRET_STORAGE_REPO="$WORKSPACE_ROOT/hermes-agent-windows-secret-storage"
OTTO_RELEASES_REPO="$WORKSPACE_ROOT/otto-releases"
LOOP24_RELEASES_REPO="$WORKSPACE_ROOT/loop24-releases"
```

**Repositories:**

- Ericsson source: `$ERICSSON_REPO`
- Hermes source/brands: `$HERMES_REPO`
- OTTO release dispatcher: `$OTTO_RELEASES_REPO`
- LOOP24 release dispatcher: `$LOOP24_RELEASES_REPO`

**Release boundary:** Do not add a Python 3.13 migration to this patch. The
approved design changes credential security and publishes `v5.8.4`; Python
runtime/toolchain migration needs its own dependency and packaging audit.

---

## Global guardrails

- Never print, commit, fixture, or reuse the token exposed during diagnosis.
  The installed smoke test uses a newly generated disposable value, and the
  user must revoke the exposed token before testing.
- Do not require elevation, Administrator execution, `SeSecurityPrivilege`,
  SACL access, ownership takeover, PowerShell `Set-Acl`, or a plaintext
  fallback.
- Never weaken the exact current-user-only DACL policy to “current user is one
  of the allowed principals.” One protected allow ACE is the contract.
- Do not remove Hermes' authority registry, transaction lock, encrypted-file
  fallback, rollback, revocation, or OS-keyring tier.
- Plain `secrets doctor` must remain byte-for-byte read-only. Only the explicit
  `--write-probe` form may create its synthetic artifacts.
- Do not hand-edit generated onboarding `catalog.json`; use its builder.
- Ericsson source lands in `ericsson-capabilities/main` first. Vendor only the
  exact clean committed revision into neutral `hermes-agent/base`.
- Do not author shared runtime or vendored Ericsson content directly on
  `otto`, `loop24`, or any other brand branch.
- Discover brands from `brands/*.json`; do not hardcode the propagation loop.
- Literal Hermes `main` is upstream-sync-only and must remain untouched.
- Preserve unrelated untracked files in the existing Hermes checkout.
- Do not modify either release-dispatcher repository unless an existing
  workflow is demonstrably incapable of publishing the approved artifacts.
- Builds remain unsigned. Do not add certificates, secrets, notarization, or
  signing steps.
- Do not overwrite an existing tag or release. Re-read remote versions
  immediately before dispatch.

---

## Task 1: Freeze preconditions and establish isolated execution checkouts

**Files:**

- Read: `AGENTS.md` in both source repositories
- Read: `docs/superpowers/specs/2026-08-17-windows-standard-user-secret-storage-release-design.md`
- Read: `plugins/ericsson-teams/graph_auth.py`
- Read: `hermes_cli/windows_permissions.py`
- Read: `hermes_cli/secret_keystore.py`
- Read: `hermes_cli/secrets_repair.py`
- No source modifications

### Step 1: Verify Ericsson source state

Run:

```bash
cd "$ERICSSON_REPO"
git fetch origin
git status --short --branch
git branch --show-current
git log -3 --oneline
git diff --check
git merge-base --is-ancestor origin/main HEAD
```

Expected:

- current branch is `fix/windows-standard-user-secret-storage`;
- the design commit `06608d8` and this plan commit are present;
- no uncommitted tracked changes;
- the branch descends from current `origin/main`.

If `origin/main` advanced, rebase or merge it before code and rerun all
preconditions. Stop if tracked user changes overlap any task-owned file.

### Step 2: Verify Hermes base and preserve its dirty-untracked checkout

Run:

```bash
cd "$HERMES_REPO"
git fetch origin
git branch --show-current
git status --short --branch
git rev-parse base
git rev-parse origin/base
git diff --check
```

Expected: the primary checkout is on `base`; tracked files are clean; only the
previously observed unrelated untracked `.otto/` and `docs/...` paths may be
present. Do not delete, stage, move, or edit those paths.

### Step 3: Create the isolated Hermes worktree

Use `superpowers:using-git-worktrees`. Resolve a sibling path rather than
placing a worktree under the repository:

```bash
cd "$HERMES_REPO"
git worktree add \
  "$HERMES_SECRET_STORAGE_REPO" \
  -b fix/windows-standard-user-secret-storage origin/base
git -C "$HERMES_SECRET_STORAGE_REPO" status --short --branch
```

If the branch or worktree already exists, inspect and reuse it only when it is
clean and points at the intended work. Never delete an unknown worktree.

### Step 4: Record immutable baselines

Run and save the output in the execution notes:

```bash
git -C "$ERICSSON_REPO" rev-parse HEAD
git -C "$HERMES_REPO" rev-parse origin/base
git ls-remote --tags https://github.com/cmetech/otto.git 'refs/tags/v*' | tail -20
git ls-remote --tags https://github.com/cmetech/loop24.git 'refs/tags/v*' | tail -20
```

Expected at planning time: latest public tag for both brands is `v5.8.3`.
This is informational now; Task 12 repeats the check as a hard release gate.

### Step 5: Baseline focused tests

Run:

```bash
cd "$ERICSSON_REPO"
.venv/bin/pytest tests/test_teams_plugin.py -q

cd "$HERMES_SECRET_STORAGE_REPO"
uv sync --locked --python 3.11 --extra all --extra dev
uv run --no-sync bash scripts/run_tests.sh \
  tests/hermes_cli/test_windows_permissions.py \
  tests/hermes_cli/test_secret_keystore.py \
  tests/hermes_cli/test_secrets_repair.py -q
```

Expected: all baseline tests pass. Stop and report any pre-existing failure;
do not implement on a red baseline.

---

## Task 2: Replace the PowerShell ACL boundary with a native Win32 adapter

**Repository:** `hermes-agent-windows-secret-storage`

**Files:**

- Modify: `hermes_cli/windows_permissions.py`
- Replace/update: `tests/hermes_cli/test_windows_permissions.py`
- Reference only: `../ericsson-capabilities/skills/ericsson/onboard-ericsson-capabilities/scripts/onboarding_state_windows.py`

### Step 1: Write failing adapter-boundary tests

Delete assertions tied to PowerShell command text and add tests against an
injectable private Win32 adapter. Keep public API tests at the module boundary.
The test seam should be one private factory such as:

```python
def _native_api() -> _WindowsAclApi:
    return _WindowsAclApi()
```

Tests must prove:

1. files and directories are opened with `FILE_FLAG_OPEN_REPARSE_POINT` and,
   for directories, `FILE_FLAG_BACKUP_SEMANTICS`;
2. apply handles request `READ_CONTROL | WRITE_DAC` and no `ACCESS_SYSTEM_SECURITY`
   or `WRITE_OWNER`;
3. inspection requests only
   `OWNER_SECURITY_INFORMATION | DACL_SECURITY_INFORMATION`;
4. mutation passes exactly
   `DACL_SECURITY_INFORMATION | PROTECTED_DACL_SECURITY_INFORMATION` to
   `SetSecurityInfo`;
5. `OWNER_SECURITY_INFORMATION`, `SACL_SECURITY_INFORMATION`, and
   `UNPROTECTED_DACL_SECURITY_INFORMATION` are absent from mutation flags;
6. file policy is one explicit allow ACE for the current SID with mask
   `0x0012019F` and no inheritance flags;
7. directory policy is one explicit allow ACE for the current SID with mask
   `0x001201FF` and `OBJECT_INHERIT_ACE | CONTAINER_INHERIT_ACE`;
8. foreign owner, null DACL, unprotected DACL, inherited/deny/extra ACE,
   wrong SID, wrong type, reparse point, or identity change fails closed;
9. Win32 error text is normalized to `WindowsAclError` without path payload or
   environment values that could contain a secret;
10. all four existing public functions retain their signatures and
    `WindowsAclInspection` return shape.

Run:

```bash
uv run --no-sync python -m pytest tests/hermes_cli/test_windows_permissions.py -q
```

Expected: RED because the existing module still shells out to PowerShell and
has no native adapter.

### Step 2: Implement the minimal native API

Keep these public declarations unchanged:

```python
class WindowsAclError(RuntimeError): ...

@dataclass(frozen=True)
class WindowsAclInspection:
    secure: bool
    detail: str | None

def restrict_file_to_current_user(path: Path) -> None: ...
def restrict_directory_to_current_user(path: Path) -> None: ...
def inspect_file_acl(path: Path) -> WindowsAclInspection: ...
def inspect_directory_acl(path: Path) -> WindowsAclInspection: ...
```

Implement a focused `_WindowsAclApi` using `ctypes.WinDLL(..., use_last_error=True)`
and explicit `argtypes`/`restype`. It needs only:

- `CreateFileW`, `CloseHandle`, `GetFileInformationByHandle`, `LocalFree`;
- `OpenProcessToken`, `GetTokenInformation`, `ConvertSidToStringSidW`;
- `ConvertStringSecurityDescriptorToSecurityDescriptorW` and
  `GetSecurityDescriptorDacl` to construct the fixed DACL;
- `GetSecurityInfo` and `SetSecurityInfo` on the already-open handle;
- `GetSecurityDescriptorControl`, `GetAclInformation`, `GetAce`, `EqualSid`,
  and ACE structures to inspect the DACL structurally rather than trusting
  formatted SDDL text.

Use these load-bearing constants:

```python
OWNER_SECURITY_INFORMATION = 0x00000001
DACL_SECURITY_INFORMATION = 0x00000004
PROTECTED_DACL_SECURITY_INFORMATION = 0x80000000
SE_FILE_OBJECT = 1
READ_CONTROL = 0x00020000
WRITE_DAC = 0x00040000
FILE_PRIVATE_MASK = 0x0012019F
DIRECTORY_PRIVATE_MASK = 0x001201FF
```

Do not define or request a SACL mutation. It is acceptable to define the SACL
constant in tests solely to assert it is absent.

Build only the DACL, not an owner field:

```python
inheritance = "OICI" if directory else ""
mask = DIRECTORY_PRIVATE_MASK if directory else FILE_PRIVATE_MASK
sddl = f"D:P(A;{inheritance};0x{mask:08x};;;{current_sid})"
```

Before mutation, query the existing owner and require `EqualSid(owner,
current_user_sid)`. Never call `SetSecurityInfo` with an owner pointer or owner
flag. After mutation, inspect the same handle and require exact owner, protected
DACL, ACE count/type/flags/mask/SID, and stable handle identity.

Path handling must retain `_validated_direct_path()` as a pre-open rejection,
then treat the handle as authority. Open with reparse traversal disabled and
check the handle's file attributes and stable volume/file ID. Do not reopen by
name between apply and verify.

### Step 3: Run the focused GREEN test

```bash
uv run --no-sync python -m pytest tests/hermes_cli/test_windows_permissions.py -q
uv run --no-sync python scripts/check-windows-footguns.py \
  hermes_cli/windows_permissions.py tests/hermes_cli/test_windows_permissions.py
git diff --check
```

Expected: all pass; no `subprocess`, `powershell`, `Get-Acl`, `Set-Acl`,
`SetOwner`, or `SeSecurityPrivilege` remains in the production module.

### Step 4: Commit the native boundary

```bash
git add hermes_cli/windows_permissions.py tests/hermes_cli/test_windows_permissions.py
git diff --cached --check
git commit -m "fix(secrets): use native Windows ACL boundary"
```

---

## Task 3: Prove the generic central plugin-secret path

**Repository:** `hermes-agent-windows-secret-storage`

**Files:**

- Modify only if required: `hermes_cli/secret_keystore.py`
- Modify: `tests/hermes_cli/test_secret_keystore.py`
- Modify: `tests/hermes_cli/test_plugin_configuration_storage.py`
- Modify: `tests/hermes_cli/test_ericsson_connector_surfaces.py`

### Step 1: Write failing service-level regressions

Add a parametrized test over real vendored descriptors:

```python
@pytest.mark.parametrize(
    ("plugin_id", "field_id"),
    [
        ("ericsson-arm", "token"),
        ("ericsson-jira", "pat"),
        ("ericsson-confluence", "token"),
    ],
)
def test_disabled_descriptor_plugin_secret_round_trip_on_windows(...): ...
```

For each case:

- copy the real plugin into a fresh profile;
- keep the standalone connector disabled where its manifest says disabled;
- use a fake OS keyring but the real `PluginConfigurationService.update()`;
- make `_is_windows()` true and inject the native ACL adapter seam;
- store a unique synthetic value;
- assert `detail(...)["fields"]` reports `is_set: true` without returning the
  value;
- resolve the secret through the normal keystore authority path;
- replace it, then clear it through `clear_secret()`;
- assert the authority entry is created, updated without duplication, and
  removed on clear;
- assert plugin enablement was never required;
- assert no synthetic value occurs in status JSON or exception strings.

Add separate forced-file-mode coverage proving the root, lock, key,
ciphertext, authority registry, and atomic temporary files all call the same
private ACL boundary and retain rollback semantics on an injected failure.

Run:

```bash
uv run --no-sync python -m pytest \
  tests/hermes_cli/test_secret_keystore.py \
  tests/hermes_cli/test_plugin_configuration_storage.py \
  tests/hermes_cli/test_ericsson_connector_surfaces.py -q
```

Expected: RED on at least the new Windows service integration until its fake
native boundary and transaction expectations are wired correctly.

### Step 2: Make the smallest core adjustment, if any

The expected implementation is no connector-specific production change:
`secret_keystore._ensure_private_permissions()` should continue importing the
same four public helper functions. Modify `secret_keystore.py` only if required
to normalize a native typed failure without changing the stable external
`KeystoreError`/plugin persistence envelope.

Do not bypass `_ensure_transaction_root()` for the OS-keyring tier. The
authority registry and lock remain mandatory.

### Step 3: Run focused and invariant suites

```bash
uv run --no-sync bash scripts/run_tests.sh \
  tests/hermes_cli/test_windows_permissions.py \
  tests/hermes_cli/test_secret_keystore.py \
  tests/hermes_cli/test_plugin_configuration_storage.py \
  tests/hermes_cli/test_ericsson_connector_surfaces.py \
  tests/hermes_cli/test_secret_authority.py -q
git diff --check
```

Expected: all pass.

### Step 4: Commit generic service coverage

```bash
git add hermes_cli/secret_keystore.py \
  tests/hermes_cli/test_secret_keystore.py \
  tests/hermes_cli/test_plugin_configuration_storage.py \
  tests/hermes_cli/test_ericsson_connector_surfaces.py
git diff --cached --check
git commit -m "test(secrets): cover Windows plugin secret persistence"
```

If `secret_keystore.py` did not change, omit it from `git add`.

---

## Task 4: Add the explicit doctor write probe without weakening default doctor

**Repository:** `hermes-agent-windows-secret-storage`

**Files:**

- Modify: `hermes_cli/secrets_repair.py`
- Modify: `tests/hermes_cli/test_secrets_repair.py`

### Step 1: Write RED tests for CLI parsing and mutation boundaries

Add parser coverage for exactly:

```text
hermes secrets doctor
hermes secrets doctor --write-probe
```

Reject abbreviated `--write-*` forms by setting `allow_abbrev=False` on the
doctor parser.

Retain and strengthen the existing real-console test so plain doctor:

- does not create an absent profile;
- produces the same tree snapshot before and after;
- never calls OS keyring set/delete;
- never calls the write-probe helper.

Add write-probe tests that prove:

- exactly one unique directory directly below active `HERMES_HOME` is made;
- it contains one fixed noncredential sentinel file;
- production directory and file restrict/inspect functions are called;
- successful probe leaves no directory or file;
- ACL application or inspection failure reports `WRITE_PROBE_FAILED` and
  returns nonzero without leaking exception payloads;
- cleanup failure reports `WRITE_PROBE_CLEANUP_FAILED`, returns nonzero, and
  reports the exact synthetic artifact path for manual removal;
- keyring, authority registry, master key, encrypted data, and
  `secret_keystore.set_secret()` are never called;
- an existing collision is never reused;
- a symlink/reparse/wrong-type probe component fails closed.

Run:

```bash
uv run --no-sync python -m pytest tests/hermes_cli/test_secrets_repair.py -q
```

Expected: RED because `--write-probe` is not registered.

### Step 2: Implement one bounded probe function

Add and export:

```python
def run_write_probe(profile_root: Path | None = None) -> tuple[SecretFinding, ...]:
    """Exercise only profile-local file/directory ACL writes with synthetic data."""
```

Use `profile_root` when injected by tests; otherwise resolve the active
profile through the same canonical helper used by the keystore. Name the
directory with `secrets.token_hex(16)` and a fixed prefix such as
`.secret-write-probe-`. Create with `exist_ok=False`; create the file with
`O_CREAT | O_EXCL`; write only `b"hermes-secret-write-probe\n"`; flush and
close it; restrict and inspect directory and file; then unlink and `rmdir` in a
`finally` path.

Stable findings:

```text
WRITE_PROBE_OK              info
WRITE_PROBE_FAILED          error
WRITE_PROBE_CLEANUP_FAILED  error
```

The success message may say the synthetic ACL write passed. Failure messages
may name the exception type, never its raw message, because a platform error
can contain profile or environment data.

`_handle_secrets_doctor(args)` first runs and prints the unchanged read-only
report. Only when `args.write_probe` is true does it print a clear mutation
notice, invoke the probe, print its findings, and combine error status. The
plain-doctor “No secret storage findings.” line remains accurate for the
read-only report and must not imply the probe was run.

### Step 3: Run focused GREEN and real-entrypoint checks

```bash
uv run --no-sync python -m pytest tests/hermes_cli/test_secrets_repair.py -q
tmp_profile="$(mktemp -d)"
HERMES_HOME="$tmp_profile/profile" uv run --no-sync hermes secrets doctor
test ! -e "$tmp_profile/profile"
HERMES_HOME="$tmp_profile/profile" uv run --no-sync hermes secrets doctor --write-probe
test -d "$tmp_profile/profile"
test -z "$(find "$tmp_profile/profile" -maxdepth 1 -name '.secret-write-probe-*' -print -quit)"
git diff --check
```

Expected: all pass. The explicit probe may create the profile root, but it
must leave no probe child. Remove only the `mktemp` directory created by this
step after checking the resolved path.

### Step 4: Commit the diagnostic

```bash
git add hermes_cli/secrets_repair.py tests/hermes_cli/test_secrets_repair.py
git diff --cached --check
git commit -m "feat(secrets): add explicit ACL write probe"
```

---

## Task 5: Harden the Ericsson Teams MSAL cache on Windows

**Repository:** `ericsson-capabilities`

**Files:**

- Modify: `plugins/ericsson-teams/graph_auth.py`
- Modify: `tests/test_teams_plugin.py`

### Step 1: Write portable RED tests against an injectable host adapter

Add a small fake with call recording for:

```python
restrict_directory_to_current_user(path)
inspect_directory_acl(path) -> object(secure=True, detail=None)
restrict_file_to_current_user(path)
inspect_file_acl(path) -> object(secure=True, detail=None)
```

Patch only a lazy `_windows_acl_api()` factory in source-side tests; do not
require the Hermes package in this repository.

Test Windows branches by patching the module's platform predicate rather than
changing global `os.name`. Required cases:

1. persist creates parent, restricts and verifies it before creating a temp;
2. temp file is restricted and verified before the first serialized-cache
   byte is written;
3. final destination is restricted and verified after `os.replace()`;
4. read restricts/verifies parent and file before reading/deserializing;
5. read retains the 16 MiB bound;
6. insecure inspection, missing host API, wrong type, reparse point, replace
   failure, and final-ACL failure become the existing redacted `AuthRequired`;
7. unpublished temporary files are removed on every failure;
8. no serialized cache bytes or injected exception text occurs in errors;
9. existing POSIX tests and four Windows-footgun annotations remain unchanged.

Run:

```bash
.venv/bin/pytest tests/test_teams_plugin.py -q
```

Expected: RED because the portable Windows path has no ACL adapter.

### Step 2: Add a lazy, generic host ACL adapter

Add a private immutable adapter or named tuple and lazy resolver. The import
must occur only on the Windows branch:

```python
def _windows_acl_api():
    from hermes_cli.windows_permissions import (
        inspect_directory_acl,
        inspect_file_acl,
        restrict_directory_to_current_user,
        restrict_file_to_current_user,
    )
    return ...
```

Normalize all adapter import/call failures to `OSError` inside the private
Windows cache helpers so `_read_cache_text()` and `_persist()` continue to emit
only their current safe `AuthRequired("could not ... securely")` messages.
Never fall back to the current unprotected portable write.

Split platform routing explicitly:

```python
if os.name == "posix":
    ...
elif os.name == "nt":
    ...
else:
    ...  # existing portable atomic behavior only for non-Windows ports
```

The Windows helper must lstat and reject reparse points/wrong types before
calling the host API. Keep unique `O_EXCL` temp creation, bounded writes,
`fsync`, close-before-replace, atomic `os.replace`, and cleanup.

### Step 3: Run focused GREEN and secret-redaction checks

```bash
.venv/bin/pytest tests/test_teams_plugin.py -q
rg -n "secret-refresh-token|must-not-leak" plugins/ericsson-teams tests/test_teams_plugin.py
git diff --check
```

Expected: tests pass. Synthetic sentinel text may exist only in tests, never
production logs or errors.

### Step 4: Commit the Teams source change

```bash
git add plugins/ericsson-teams/graph_auth.py tests/test_teams_plugin.py
git diff --cached --check
git commit -m "fix(teams): protect Windows MSAL cache ACLs"
```

---

## Task 6: Document Teams' standard-user cache contract and close Ericsson source

**Repository:** `ericsson-capabilities`

**Files:**

- Modify: `docs/configuration.md`
- Modify: `skills/ericsson/onboard-ericsson-capabilities/references/capabilities/teams-tools.md`
- Create: `docs/onboarding/windows-teams-cache-release-validation.md`
- Regenerate if changed: `skills/ericsson/onboard-ericsson-capabilities/references/catalog.json`

### Step 1: Update user-facing guidance

Document all of the following without exposing cache contents:

- the cache location remains `$HERMES_HOME/ericsson/msal_token_cache.json`;
- on Windows its parent, temporary, and final files use the generic protected
  current-user ACL;
- standard users do not need elevation or `SeSecurityPrivilege`;
- device codes and tokens must never be pasted into chat or diagnostics;
- an ACL failure fails closed and requires `teams_auth` after remediation;
- the cache is separate from plugin descriptor secrets and from
  `secrets doctor --write-probe`.

The installed checklist must use only a disposable account/session, list
exact redacted commands/expected states, inspect ACL ownership without printing
cache bytes, clear the session, and record brand/version/commit.

### Step 2: Regenerate and validate onboarding catalog

Run:

```bash
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py --check
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/validate_catalog.py
```

Expected: validator prints an `ok` result. If the generated catalog is
byte-identical, do not force a change.

### Step 3: Run Ericsson focused, parity, invariant, shared-sync, and full gates

```bash
.venv/bin/pytest tests/test_teams_plugin.py -q
.venv/bin/pytest \
  tests/test_onboarding_skill.py \
  tests/test_onboarding_docs.py \
  tests/test_onboarding_catalog.py \
  tests/test_onboarding_baselines.py -q
.venv/bin/pytest tests/test_shared_sync.py -q
.venv/bin/pytest tests/test_manifest.py tests/test_onboarding_catalog.py -q
.venv/bin/pytest -q
git diff --check
git status --short
```

If exact test filenames differ, resolve them with `rg --files tests | rg
'(onboard|catalog|manifest|shared_sync)'` and record the actual commands. Do
not silently omit a named class of gate.

Expected: all pass.

### Step 4: Request Ericsson source review

Use `superpowers:requesting-code-review` on the diff from `origin/main` through
HEAD. The review must specifically inspect:

- Windows reparse/type and publication ordering;
- failure cleanup and redaction;
- lazy dependency direction (Teams -> generic host API only);
- POSIX behavior preservation;
- documentation/catalog parity;
- no changes to unrelated Jira, GitLab, Confluence, ARM, or shared transport.

Resolve every Critical/Important finding with RED/GREEN tests and atomic fix
commits. Rerun Step 3 after any code change.

### Step 5: Commit documentation and source closure

```bash
git add docs/configuration.md \
  docs/onboarding/windows-teams-cache-release-validation.md \
  skills/ericsson/onboard-ericsson-capabilities/references/capabilities/teams-tools.md \
  skills/ericsson/onboard-ericsson-capabilities/references/catalog.json
git diff --cached --check
git commit -m "docs(teams): describe private Windows cache validation"
git status --short --branch
```

Omit unchanged generated files.

### Step 6: Merge and push Ericsson main

Use `superpowers:finishing-a-development-branch`. Because the user authorized
source integration, fast-forward or create a normal merge commit into current
`origin/main`; never rewrite public main.

```bash
git fetch origin
git merge-base --is-ancestor origin/main HEAD
git push origin fix/windows-standard-user-secret-storage
git switch main
git pull --ff-only origin main
git merge --no-ff fix/windows-standard-user-secret-storage \
  -m "merge: Windows standard-user secret storage source"
.venv/bin/pytest tests/test_teams_plugin.py -q
.venv/bin/pytest -q
git push origin main
git status --short --branch
```

Stop if `origin/main` advanced incompatibly. Record the exact merge commit as
`ERICSSON_SOURCE_REVISION`; this is the only revision Task 7 may vendor.

---

## Task 7: Vendor the exact Ericsson revision into neutral Hermes

**Repository:** `hermes-agent-windows-secret-storage`

**Files:**

- Regenerate: manifest-owned Ericsson vendor destinations
- Modify generated: `capabilities/ericsson.json`
- Modify generated: `capabilities/ericsson-vendored-paths.json`
- Modify vendored: `plugins/ericsson-teams/graph_auth.py`
- Modify vendored: Teams documentation/catalog paths selected by the manifest
- No handwritten edits to vendored files

### Step 1: Verify the source revision is clean and exact

```bash
git -C "$ERICSSON_REPO" status --porcelain
git -C "$ERICSSON_REPO" rev-parse HEAD
git -C "$ERICSSON_REPO" rev-parse origin/main
```

Expected: no output from status and identical HEAD/origin-main revisions.

### Step 2: Run vendor tests before mutation

```bash
node --test scripts/__tests__/vendor-ericsson.test.mjs
```

Expected: pass.

### Step 3: Vendor only through the manifest-driven script

```bash
ERICSSON_CAPABILITIES_DIR="$ERICSSON_REPO" node scripts/vendor-ericsson.mjs
```

Expected: output names the exact `ERICSSON_SOURCE_REVISION`, and
`capabilities/ericsson.json` records it as `vendoredFrom`.

Do not copy files manually.

### Step 4: Prove exact byte identity and inventory parity

Run:

```bash
node --test scripts/__tests__/vendor-ericsson.test.mjs
uv run --no-sync bash scripts/run_tests.sh \
  tests/hermes_cli/test_ericsson_connector_distribution.py \
  tests/hermes_cli/test_ericsson_connector_surfaces.py \
  tests/plugins/workflow/test_ericsson_connector_toolsets.py -q
git diff --check
```

Additionally compare each path named by the manifest/vendor inventory against
`git archive "$ERICSSON_SOURCE_REVISION"`; use the existing vendor test helper
rather than a partial hand-written file list. Expected: no drift, no extra
unowned paths, and `vendoredFrom` equals the source merge SHA.

### Step 5: Commit the vendor snapshot

```bash
git add capabilities plugins skills mcp workflows
git diff --cached --check
git commit -m "feat(ericsson): vendor Windows Teams cache hardening"
```

Review `git diff --cached --name-only` before committing. It may include only
manifest-owned vendor outputs; abort if unrelated connector bytes changed.

---

## Task 8: Add a native standard-user Windows acceptance gate

**Repository:** `hermes-agent-windows-secret-storage`

**Files:**

- Create: `scripts/ci/windows_standard_user_secret_gate.py`
- Create: `scripts/ci/run_windows_standard_user_secret_gate.ps1`
- Modify: `.github/workflows/ci.yml`
- Create/update: `tests/hermes_cli/test_windows_standard_user_secret_gate_contract.py`

### Step 1: Write portable contract tests for the gate scripts

Test that the Python harness:

- refuses non-Windows execution unless an explicit unit-test adapter is
  injected;
- verifies token elevation and `SeSecurityPrivilege` state before testing;
- creates a fresh profile and only synthetic values;
- invokes plain doctor and snapshots the tree to prove read-only behavior;
- invokes explicit write probe and requires zero leftovers;
- exercises real `PluginManager` + `PluginConfigurationService` using vendored
  `ericsson-arm` while it remains disabled;
- performs create/read/replace/clear in both `auto` OS-keyring and forced
  `file` modes;
- validates the exact ACL on every durable transaction artifact;
- exercises the vendored Teams cache write/read/replace/cleanup path;
- injects an extra current-profile ACE and proves the next operation repairs
  it;
- rejects a junction/reparse fixture without altering its target;
- scrubs all synthetic values from output, including on injected failure;
- always clears keyring entries, cache, and temporary profile in `finally`.

Test that the PowerShell launcher:

- creates a uniquely named local standard user only in CI;
- does not add it to Administrators or grant privileges;
- grants that user read/execute access only to the checkout and a private temp
  workspace;
- starts the checked-in Python harness with a loaded user profile;
- captures exit code and redacted output;
- deletes the local user and its temporary profile in `finally`;
- fails rather than skips if standard-user creation or launch fails.

Run:

```bash
uv run --no-sync python -m pytest \
  tests/hermes_cli/test_windows_standard_user_secret_gate_contract.py -q
```

Expected: RED because the scripts do not exist.

### Step 2: Implement the Python native harness

Make it an executable script with `main() -> int`, no pytest dependency, and
no production credential inputs. Use a random synthetic secret held only in
memory. It must call production public APIs, not duplicate their ACL logic.

For the originally failing path, load the real disabled `ericsson-arm`
descriptor and call the same `PluginConfigurationService.update(
"ericsson-arm", secrets={"token": synthetic})` service used by CLI/desktop.
Assert the projected field reports `is_set: true`, then clear it.

The Teams case imports the vendored `plugins/ericsson-teams/graph_auth.py`
through the plugin's normal isolated loader or an importlib spec with its
plugin directory, never the Ericsson source checkout. Use a minimal changed
cache object containing synthetic bytes; do not initiate Microsoft auth.

Every output line is a stable case name plus PASS/FAIL. Never print absolute
profile paths except a cleanup-failure path, and never print exception
messages, secret values, MSAL bytes, keyring accounts, or authority keys.

### Step 3: Implement the standard-user PowerShell launcher

The GitHub Windows runner may be administrative, so the launcher must create
and run a distinct local non-admin user. Generate a CI-only password in memory,
use `New-LocalUser`, confirm group membership excludes `Administrators`, and
launch the venv Python with `Start-Process -Credential ... -LoadUserProfile
-Wait -PassThru` and redirected output. Confirm from inside the child that its
token is not elevated and `SeSecurityPrivilege` is absent or disabled.

Do not use `Set-Acl` in the product or harness. The launcher may use `icacls`
only to grant the disposable child read/execute access to the checkout/temp
bootstrap; that is fixture setup under the runner's administrative account,
not product behavior. The actual product assertions must run entirely inside
the standard-user child.

### Step 4: Add a dedicated Windows CI job

Add a `windows-secret-storage` job to `.github/workflows/ci.yml` gated by the
Python affected-area output, on `windows-latest`, with Python 3.11 and the
locked `all,dev` environment. Run:

```yaml
- name: Run standard-user secret storage gate
  shell: powershell
  run: ./scripts/ci/run_windows_standard_user_secret_gate.ps1
```

Include this job in the final aggregate `all-checks-pass` dependency/result
logic. Do not bury it in the slow workflow portability slices.

### Step 5: Run portable checks locally

```bash
uv run --no-sync python -m pytest \
  tests/hermes_cli/test_windows_standard_user_secret_gate_contract.py \
  tests/hermes_cli/test_windows_permissions.py \
  tests/hermes_cli/test_secret_keystore.py \
  tests/hermes_cli/test_secrets_repair.py -q
uv run --no-sync python scripts/check-windows-footguns.py \
  hermes_cli/windows_permissions.py \
  scripts/ci/windows_standard_user_secret_gate.py
git diff --check
```

Expected: pass locally. The native PowerShell launcher is verified by GitHub
Actions in Task 10; do not claim native success from macOS.

### Step 6: Commit the native gate

```bash
git add .github/workflows/ci.yml scripts/ci/windows_standard_user_secret_gate.py \
  scripts/ci/run_windows_standard_user_secret_gate.ps1 \
  tests/hermes_cli/test_windows_standard_user_secret_gate_contract.py
git diff --cached --check
git commit -m "test(secrets): gate standard-user Windows persistence"
```

---

## Task 9: Close the Hermes feature branch with full verification and review

**Repository:** `hermes-agent-windows-secret-storage`

**Files:** No new planned files; fixes only in previously owned files.

### Step 1: Run focused security and regression suites

```bash
uv run --no-sync bash scripts/run_tests.sh \
  tests/hermes_cli/test_windows_permissions.py \
  tests/hermes_cli/test_windows_standard_user_secret_gate_contract.py \
  tests/hermes_cli/test_secret_authority.py \
  tests/hermes_cli/test_secret_keystore.py \
  tests/hermes_cli/test_secrets_repair.py \
  tests/hermes_cli/test_plugin_configuration_storage.py \
  tests/hermes_cli/test_ericsson_connector_distribution.py \
  tests/hermes_cli/test_ericsson_connector_surfaces.py \
  tests/plugins/workflow/test_ericsson_connector_toolsets.py -q
node --test scripts/__tests__/vendor-ericsson.test.mjs
```

Expected: all pass.

### Step 2: Run repository invariant gates

Resolve the exact supported invocations from repository scripts, then run:

```bash
uv run --no-sync python scripts/check-windows-footguns.py --diff origin/base
uv lock --check
npm ci
npm run typecheck
npm run lint
npm test
node scripts/brand/generate.mjs _fixture-quote --check
git diff --check
```

If a command name differs, use `npm run`/script help to select the repository's
documented equivalent and record it. Do not auto-fix unrelated formatting or
lockfiles.

### Step 3: Run the complete Python suite

```bash
uv run --no-sync bash scripts/run_tests.sh
```

Expected: exit 0. Platform-gated skips are acceptable only when already
documented; the new native acceptance gate is not considered covered by a
macOS skip.

### Step 4: Request security-focused code review

Use `superpowers:requesting-code-review` over `origin/base..HEAD`. Require the
reviewer to inspect:

- SID acquisition and ctypes lifetime/`LocalFree` correctness;
- exact handle access and security-information masks;
- no SACL or ownership mutation;
- ACE parsing, null-DACL handling, and protected inheritance;
- reparse/identity race handling;
- keystore rollback/authority invariants;
- doctor default-read-only proof and probe cleanup;
- Teams pre-write/final ACL ordering and redaction;
- CI child really being standard/non-elevated;
- vendor provenance and brand neutrality.

Resolve Critical/Important findings with a new failing regression first, then
rerun Steps 1-3. Commit each logical fix separately.

### Step 5: Confirm branch cleanliness

```bash
git status --short --branch
git log --oneline origin/base..HEAD
git diff origin/base...HEAD --check
```

Expected: clean branch with an intentional task-by-task commit list.

---

## Task 10: Open the Hermes integration PR, run native CI, and integrate neutral base

**Repository:** `hermes-agent-windows-secret-storage` plus primary Hermes checkout

### Step 1: Push the feature branch and open a base-targeted PR

```bash
git push -u origin fix/windows-standard-user-secret-storage
gh pr create --repo cmetech/hermes-agent \
  --base base \
  --head fix/windows-standard-user-secret-storage \
  --title "fix: support Windows standard-user secret storage" \
  --body "Implements the approved native Windows ACL boundary, explicit doctor write probe, generic descriptor-secret regression coverage, vendored Teams MSAL cache hardening, and a standard-user Windows CI gate. Builds remain unsigned; release dispatch is a later gated task."
```

The body summarizes the approved design and explicit unsigned-release note;
do not add tokens or local absolute paths. The repository CI listens to
`pull_request`, not arbitrary feature pushes, so the PR is required to
exercise the native gate before base integration.

Capture the PR number and its CI run. Use `gh run watch <run-id>
--repo cmetech/hermes-agent --exit-status` and inspect failures with
`gh run view <run-id> --log-failed`.

Hard gate: the dedicated `windows-secret-storage` job must pass in the
standard-user child. A skipped, cancelled, timed-out, or fixture-creation
failure blocks integration and release.

### Step 2: Re-run local focused tests after any CI fix

Any fix follows RED/GREEN TDD, gets its own commit, and reruns Task 9. Push and
wait for a fresh green run; do not rely on rerunning stale code.

### Step 3: Integrate the reviewed PR into neutral `base`

Use `superpowers:finishing-a-development-branch`. In the primary Hermes
checkout, preserve unrelated untracked user files and first prove none collide
with incoming paths:

```bash
gh pr view "$PR_NUMBER" --repo cmetech/hermes-agent \
  --json mergeable,reviewDecision,statusCheckRollup,headRefOid,baseRefName
gh pr merge "$PR_NUMBER" --repo cmetech/hermes-agent --merge --delete-branch=false

cd "$HERMES_REPO"
git fetch origin
git status --short --branch
git diff --quiet
git diff --cached --quiet
git merge --ff-only origin/base
```

If an untracked path would be overwritten, stop and ask the user rather than
moving/deleting it. Confirm the remote PR merge commit's first parent is the
prior base tip and its second parent is the reviewed feature head. Do not
create a second local merge commit.

### Step 4: Verify and push base

```bash
uv run --no-sync bash scripts/run_tests.sh \
  tests/hermes_cli/test_windows_permissions.py \
  tests/hermes_cli/test_secret_keystore.py \
  tests/hermes_cli/test_secrets_repair.py \
  tests/hermes_cli/test_ericsson_connector_surfaces.py -q
node --test scripts/__tests__/vendor-ericsson.test.mjs
git status --short --branch
git push origin base
```

Record the merge SHA as `HERMES_BASE_REVISION`. Literal `main` remains
unchanged.

### Step 5: Observe post-base CI

Wait for the `base` run and require the dedicated Windows standard-user job,
all Python slices, Windows portability slices, lint, vendor/JS gates, and the
aggregate result to finish successfully. Since CI is advisory in repository
policy, this task makes it a release gate explicitly.

---

## Task 11: Discover, regenerate, verify, and push every brand

**Repository:** `hermes-agent`

**Files:** Generated brand overlays only, if generator output changes.

### Step 1: Discover real brand descriptors

Run:

```bash
cd "$HERMES_REPO"
for descriptor in brands/*.json; do
  brand="$(basename "$descriptor" .json)"
  case "$brand" in
    schema|_fixture-*) continue ;;
  esac
  printf '%s\n' "$brand"
done
```

Expected now: `loop24` and `otto`. The loop, not this expectation, is
authoritative.

### Step 2: Create one isolated worktree per real brand

For each discovered brand, fetch its remote branch and create/reuse a clean
sibling worktree. Example shape:

```bash
git worktree add "$WORKSPACE_ROOT/hermes-agent-brand-$brand" \
  "$brand"
```

Stop if a brand checkout has unknown changes.

### Step 3: Merge neutral base and regenerate each overlay

For every brand:

```bash
brand_root="$WORKSPACE_ROOT/hermes-agent-brand-$brand"
git -C "$brand_root" fetch origin
git -C "$brand_root" pull --ff-only origin "$brand"
git -C "$brand_root" merge --no-ff origin/base \
  -m "merge: base into $brand for v5.8.4"
cd "$brand_root"
node scripts/brand/generate.mjs "$brand" --write
node scripts/brand/generate.mjs "$brand" --check
node --test scripts/__tests__/vendor-ericsson.test.mjs
git diff --check
```

Commit generated overlay changes only when present:

```bash
git add -u
git diff --cached --check
if ! git diff --cached --quiet; then
  git commit -m "chore(brand): regenerate $brand for v5.8.4"
fi
```

Do not use `|| true` around tests, generators, or commits.

### Step 4: Prove neutral-byte parity

For every brand, compare these paths at `origin/base` and brand HEAD:

- `hermes_cli/windows_permissions.py`
- `hermes_cli/secret_keystore.py`
- `hermes_cli/secrets_repair.py`
- `plugins/ericsson-teams/graph_auth.py`
- `capabilities/ericsson.json` and vendor inventory
- all manifest-owned vendored Ericsson paths

Use `git show <ref>:<path> | shasum -a 256`; expected hashes are identical.
Only declared generator-owned branding overlays may differ.

### Step 5: Run brand and desktop verification

In each brand worktree:

```bash
node scripts/brand/generate.mjs "$brand" --check
npm ci
npm run typecheck
npm run lint
npm test
npm run build
uv run --no-sync bash scripts/run_tests.sh \
  tests/hermes_cli/test_brand_runtime.py \
  tests/hermes_cli/test_brand_channels.py \
  tests/hermes_cli/test_brand_curation.py \
  tests/hermes_cli/test_windows_permissions.py \
  tests/hermes_cli/test_ericsson_connector_surfaces.py -q
git status --short --branch
```

Use the repository's exact desktop-specific test/build scripts if `npm run`
shows a more precise command. Record every actual command and result.

### Step 6: Push every brand

```bash
git -C "$brand_root" push origin "$brand"
```

Record each pushed brand SHA. After both are pushed, verify remote ancestry:

```bash
git fetch origin
git merge-base --is-ancestor origin/base origin/otto
git merge-base --is-ancestor origin/base origin/loop24
```

Expected: both exit 0.

Leave the brand-restamp checkout for `otto` clean to satisfy the Ericsson
delivery invariant. Leave the separate primary Hermes development checkout on
clean `base` as required by Hermes' repo-local release instructions. Untracked
user docs in the primary checkout remain untouched and are not described as
release changes.

---

## Task 12: Recheck versions and dispatch both unsigned v5.8.4 releases

**Repositories:** `otto-releases`, `loop24-releases`; no planned file changes.

### Step 1: Verify dispatcher workflows and GitHub authentication

```bash
gh auth status
git -C "$OTTO_RELEASES_REPO" status --short --branch
git -C "$LOOP24_RELEASES_REPO" status --short --branch
```

Expected: both dispatcher repos clean on `main`; workflow text still explicitly
sets `CSC_IDENTITY_AUTO_DISCOVERY=false` and publishes `OTTO-*`/`LOOP24-*`.

### Step 2: Perform the hard version-race gate

```bash
gh release view v5.8.3 --repo cmetech/otto --json tagName,isDraft,isPrerelease,publishedAt
gh release view v5.8.3 --repo cmetech/loop24 --json tagName,isDraft,isPrerelease,publishedAt
if gh release view v5.8.4 --repo cmetech/otto --json tagName >/dev/null 2>&1; then
  echo "cmetech/otto v5.8.4 already exists" >&2
  exit 1
fi
if gh release view v5.8.4 --repo cmetech/loop24 --json tagName >/dev/null 2>&1; then
  echo "cmetech/loop24 v5.8.4 already exists" >&2
  exit 1
fi
test -z "$(git ls-remote --tags https://github.com/cmetech/otto.git refs/tags/v5.8.4)"
test -z "$(git ls-remote --tags https://github.com/cmetech/loop24.git refs/tags/v5.8.4)"
```

Expected: `v5.8.3` exists and is the latest public release; no `v5.8.4` release
or tag exists. If either remote advanced or partially contains `v5.8.4`, stop
and report; do not overwrite or guess the next version.

### Step 3: Verify source branches at their recorded SHAs

```bash
git -C "$HERMES_REPO" fetch origin
git -C "$HERMES_REPO" rev-parse origin/otto
git -C "$HERMES_REPO" rev-parse origin/loop24
```

Expected: exact equality with Task 11's recorded SHAs.

### Step 4: Dispatch OTTO

```bash
gh workflow run release.yml --repo cmetech/otto \
  -f ref=otto \
  -f version=5.8.4 \
  -f stamp_branch=otto \
  -f prerelease=false
```

Capture the new run ID with a timestamp-bounded `gh run list`; do not assume
the first historical row belongs to this dispatch.

### Step 5: Dispatch LOOP24

```bash
gh workflow run release.yml --repo cmetech/loop24 \
  -f ref=loop24 \
  -f version=5.8.4 \
  -f stamp_branch=loop24 \
  -f prerelease=false
```

Capture its run ID the same way.

### Step 6: Monitor both runs to terminal success

```bash
gh run watch "$OTTO_RUN_ID" --repo cmetech/otto --exit-status
gh run watch "$LOOP24_RUN_ID" --repo cmetech/loop24 --exit-status
```

If either fails, inspect with `gh run view ... --log-failed`. Do not redispatch
the same version while a partial tag/release may exist. Reconcile remote state
first and, if necessary, publish a later patch as the user authorized.

---

## Task 13: Verify published assets, stamps, and post-release smoke evidence

**Repositories:** Read-only verification unless a separate follow-up is needed.

### Step 1: Verify both public releases

```bash
gh release view v5.8.4 --repo cmetech/otto \
  --json tagName,name,isDraft,isPrerelease,publishedAt,assets,url
gh release view v5.8.4 --repo cmetech/loop24 \
  --json tagName,name,isDraft,isPrerelease,publishedAt,assets,url
```

Expected for each:

- tag `v5.8.4`;
- not draft, not prerelease;
- Windows NSIS `.exe` and MSI `.msi` assets;
- macOS `.dmg` and `.zip` assets;
- filenames begin with the correct `OTTO-5.8.4-` or `LOOP24-5.8.4-` brand;
- release body states unsigned build.

Download assets or workflow artifacts to a fresh `mktemp -d`, never a broad
workspace path. Inspect packaged `install-stamp.json` and require:

- correct product version `5.8.4`;
- correct tracking branch (`otto` or `loop24`);
- exact Task 11 source commit for that brand.

Record SHA-256 checksums of every published asset.

### Step 2: Perform the authorized post-publication Windows smoke test

On the same standard account that reproduced the defect, after installing the
new LOOP24 build:

```powershell
loop24 --version
loop24 secrets doctor
loop24 secrets doctor --write-probe
loop24 tools status ericsson-arm
loop24 tools configure ericsson-arm --secret token
loop24 tools status ericsson-arm
```

Use a newly generated disposable Artifactory/reference token entered only at
the secure prompt. Never put it on the command line or in the report. Expected:

- no `SeSecurityPrivilege`/`Set-Acl` warning;
- plain doctor remains read-only;
- explicit probe reports `WRITE_PROBE_OK` and leaves no probe artifact;
- ARM token field moves from `is_set: false` to `is_set: true` while the plugin
  may remain disabled;
- clearing the token returns it to `is_set: false`.

Repeat descriptor-backed save/status/clear with Jira and Confluence using
disposable synthetic/test credentials, without making network calls. Then run
`teams_auth` only with an approved test identity, verify the cache owner/DACL
without reading its bytes, exercise silent reuse, and clear the session/cache.

Perform an OTTO smoke of the same doctor probe and one descriptor-backed
secret to prove brand parity.

Because the user explicitly authorized publication before installed UAT, a
smoke failure does not rewrite release history. Capture redacted evidence,
open the next patch task, and do not claim installed validation passed.

### Step 3: Final verification-before-completion report

Use `superpowers:verification-before-completion` and report:

1. Ericsson feature/source commits and pushed `main` merge SHA;
2. Hermes feature commits, pushed `base` merge SHA, and confirmation literal
   `main` was untouched;
3. every discovered brand, merge/regeneration commit, pushed SHA, and byte
   parity result;
4. exact focused, full-suite, catalog, vendor, native Windows, brand, desktop,
   and CI commands with pass/fail counts;
5. OTTO and LOOP24 workflow run URLs/IDs;
6. release URLs, asset names, sizes, SHA-256 values, and install-stamp SHAs;
7. confirmation that both releases are unsigned full `v5.8.4` releases;
8. post-release smoke results, clearly separating automated prepublication
   evidence from installed postpublication evidence;
9. deviations, remaining concerns, or blockers;
10. confirmation that all intended refs were pushed and no unintended merge
    to literal Hermes `main` occurred.

---

## Expected atomic commit sequence

The exact SHAs are produced during execution, but the intended history is:

### Ericsson source

```text
docs: design Windows standard-user secret storage release       (existing 06608d8)
docs: plan Windows standard-user secret storage release         (this plan)
fix(teams): protect Windows MSAL cache ACLs
docs(teams): describe private Windows cache validation
[review-fix commits only when justified]
merge: Windows standard-user secret storage source              (main)
```

### Hermes neutral source

```text
fix(secrets): use native Windows ACL boundary
test(secrets): cover Windows plugin secret persistence
feat(secrets): add explicit ACL write probe
feat(ericsson): vendor Windows Teams cache hardening
test(secrets): gate standard-user Windows persistence
[review/CI-fix commits only when justified]
merge: support Windows standard-user secret storage             (base)
```

### Each discovered brand

```text
merge: base into <brand> for v5.8.4
chore(brand): regenerate <brand> for v5.8.4                     (only if needed)
```

No commit is planned in either release-dispatcher repository.
