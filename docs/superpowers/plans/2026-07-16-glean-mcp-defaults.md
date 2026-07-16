# Glean MCP Defaults Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship Glean disabled by default with the Ericsson endpoint preconfigured, while preserving existing URLs and enablement choices and leaving the user token blank.

**Architecture:** `ericsson-capabilities` remains the source of the MCP entry, manifest, onboarding contract, and documentation. Hermes staging copies a missing server in full but applies one narrow structural backfill to an existing server: copy a non-empty source URL only when the current URL is missing or blank. The source commit is then vendored onto neutral `hermes-agent/base` and merged into every discovered brand.

**Tech Stack:** JSON and YAML manifests, Python 3.11+, PyYAML, pytest, Hermes capability staging, Node.js Ericsson vendor and brand generators, npm/Vite desktop builds.

## Global Constraints

- Use `https://be.everyday-assistant.ericsson.net/mcp/EEA-KIRO-MCP` exactly.
- New Glean entries set `enabled: false`.
- Existing Glean entries never have `enabled` added, removed, or changed.
- Existing non-blank URLs are never overwritten; missing, `null`, empty, or whitespace-only URLs receive the default.
- `GLEAN_API_TOKEN` remains blank, secret, user-specific, and represented only by `${GLEAN_API_TOKEN}` in the authorization header.
- Remove `GLEAN_MCP_URL` from the manifest, protected Keys inventory, onboarding requirement, and generated catalog.
- Do not connect to the live Ericsson endpoint in tests.
- Do not change another MCP server's values except that the generic structural URL-backfill behavior may apply when a managed fragment supplies a non-empty URL and the current URL is blank.
- Preserve all unrelated dirty worktree changes in `hermes-agent`; never stage, revert, or overwrite them.
- Author shared Hermes behavior on `base`, merge `base` into every brand in `brands/*.json`, and finish on `otto`.
- Do not create a worktree, push, release, or open a PR.

---

### Task 1: Change the Ericsson source contract with TDD

**Files:**
- Modify: `tests/test_outlook_mcp.py`
- Modify: `tests/test_manifest.py`
- Modify: `tests/test_onboarding_catalog.py`
- Modify: `mcp/mcp-servers.yaml`
- Modify: `sets/ericsson.json`
- Modify: `skills/ericsson/onboard-ericsson-capabilities/references/capabilities/glean-search.md`
- Regenerate: `skills/ericsson/onboard-ericsson-capabilities/references/catalog.json`
- Modify: `docs/configuration.md`
- Modify: `AGENTS.md`
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Ericsson manifest schema, MCP fragment schema, onboarding entry frontmatter, `build_catalog.py`.
- Produces: version `0.4.1` source manifest; a disabled static-URL Glean MCP entry; token-only onboarding configuration; regenerated compact catalog.

- [ ] **Step 1: Invert the source tests before changing source data**

In `tests/test_outlook_mcp.py`, replace the Glean URL assertion and add the default-off assertion:

```python
    assert servers["glean"]["enabled"] is False
    assert servers["glean"]["url"] == (
        "https://be.everyday-assistant.ericsson.net/mcp/EEA-KIRO-MCP"
    )
    assert servers["glean"]["headers"]["Authorization"] == (
        "Bearer ${GLEAN_API_TOKEN}"
    )
```

In `tests/test_manifest.py`, require the token but reject the obsolete URL key and bump the expected set version:

```python
    keys = {entry["key"] for entry in doc["env"]}
    assert keys == {
        "JIRA_BASE_URL",
        "JIRA_PAT",
        "GLEAN_API_TOKEN",
        "ERICSSON_GRAPH_CLIENT_ID",
    }
    assert "GLEAN_MCP_URL" not in keys
    assert doc["version"] == "0.4.1"
```

In `tests/test_onboarding_catalog.py`, change `EXPECTED_CONFIGURATION["glean-search"]` to:

```python
    "glean-search": {
        ("GLEAN_API_TOKEN", "static-secret", True),
    },
```

- [ ] **Step 2: Run the three focused source tests and verify RED**

Run:

```bash
.venv/bin/pytest tests/test_outlook_mcp.py tests/test_manifest.py tests/test_onboarding_catalog.py -q
```

Expected: failures report the current `${GLEAN_MCP_URL}`, missing `enabled: false`, manifest version `0.4.0`, and the still-present URL configuration requirement.

- [ ] **Step 3: Apply the minimal source configuration change**

Change `mcp/mcp-servers.yaml` to:

```yaml
# mcp_servers entries for the `ericsson` capability set.
# The staging seam merges these into the brand's config.yaml, resolving
# ${CAPABILITY_DIR} to where mcpLocal content was staged. Remote entries may
# retain unresolved secret placeholders and remain unusable until configured.
mcp_servers:
  outlook:
    # Windows-only: PowerShell -> COM against the logged-in Outlook desktop.
    command: python
    args: ["${CAPABILITY_DIR}/outlook-mcp/run_server.py"]
    env: {}
    timeout: 120
  glean:
    # Shared Ericsson endpoint; the user supplies only the protected token.
    enabled: false
    url: https://be.everyday-assistant.ericsson.net/mcp/EEA-KIRO-MCP
    headers:
      Authorization: "Bearer ${GLEAN_API_TOKEN}"
```

In `sets/ericsson.json`, set `"version": "0.4.1"` and remove only the `GLEAN_MCP_URL` object from `env[]`. Keep the `GLEAN_API_TOKEN` entry unchanged.

- [ ] **Step 4: Update the onboarding entry and durable documentation**

In the Glean entry frontmatter, keep only:

```yaml
configuration:
  - {name: GLEAN_API_TOKEN, kind: static-secret, required: true, guidance: Enter the token only in protected Tools & Keys and never in chat.}
```

Update its readiness prose to state that the endpoint is preconfigured, the MCP server ships disabled, and the user must intentionally enable it after adding the token.

Update `docs/configuration.md` so the matrix lists only `GLEAN_API_TOKEN`, the Glean section names the supplied endpoint, and readiness is described as: token configured, server intentionally enabled, connection established, tools discovered, then a narrow read-only search.

Update both `AGENTS.md` and `CLAUDE.md` identically:

```markdown
Ericsson has no capability-set toggle or set-level `disabledByDefault`
declaration. The remote Glean MCP entry is a deliberate server-level exception:
it is seeded with `enabled: false` until the user supplies their token and opts in.
```

Keep the existing statement about generic staging infrastructure and do not introduce a manifest `disabledByDefault` block.

- [ ] **Step 5: Regenerate and validate the onboarding catalog**

Run:

```bash
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py --check
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/validate_catalog.py
```

Expected: both commands exit 0; the generated `glean-search` catalog entry contains no `GLEAN_MCP_URL` configuration requirement.

- [ ] **Step 6: Run the focused source suite and verify GREEN**

Run:

```bash
.venv/bin/pytest tests/test_outlook_mcp.py tests/test_manifest.py tests/test_onboarding_catalog.py tests/test_claude_md.py -q
```

Expected: all tests pass.

- [ ] **Step 7: Run the complete Ericsson source test gate**

Run:

```bash
./bootstrap.sh
```

Expected: dependency/bootstrap validation and the complete source pytest suite pass without a live Glean connection.

- [ ] **Step 8: Commit the source contract**

Run:

```bash
git add AGENTS.md CLAUDE.md docs/configuration.md mcp/mcp-servers.yaml \
  sets/ericsson.json \
  skills/ericsson/onboard-ericsson-capabilities/references/capabilities/glean-search.md \
  skills/ericsson/onboard-ericsson-capabilities/references/catalog.json \
  tests/test_outlook_mcp.py tests/test_manifest.py tests/test_onboarding_catalog.py
git commit -m "fix: seed Glean disabled with Ericsson endpoint"
```

Record the resulting source commit SHA for the vendor step.

---

### Task 2: Add preservation-safe MCP URL backfill in Hermes with TDD

**Files:**
- Modify: `hermes-agent/tests/hermes_cli/test_baked_seed.py`
- Modify: `hermes-agent/tests/hermes_cli/test_capability_staging.py`
- Modify: `hermes-agent/hermes_cli/capability_staging.py`

**Interfaces:**
- Consumes: `_resolve_placeholders(value, capability_dir)`, config dictionaries loaded by `stage_bundle` and `seed_baked_capabilities`.
- Produces: `_merge_mcp_server_defaults(existing: dict, entries: dict, capability_dir: str) -> bool`, used by both staging paths.

- [ ] **Step 1: Switch to neutral Hermes `base` without disturbing unrelated changes**

Run:

```bash
git -C ../hermes-agent status --short --branch
git -C ../hermes-agent switch base
```

Expected: branch is `base`; the pre-existing portable-workflow documentation changes remain visible and untouched.

- [ ] **Step 2: Extend baked-seed fixtures and write failing preservation tests**

Make the fake MCP fragment in `tests/hermes_cli/test_baked_seed.py` include:

```yaml
mcp_servers:
  outlook:
    command: python
    args: ["${CAPABILITY_DIR}/outlook-mcp/run_server.py"]
  glean:
    enabled: false
    url: https://default.example.test/mcp
    headers:
      Authorization: "Bearer ${GLEAN_API_TOKEN}"
```

Add a parametrized behavioral test:

```python
@pytest.mark.parametrize("enabled", [True, False])
@pytest.mark.parametrize("current_url", [None, "", "   "])
def test_seed_backfills_only_missing_or_blank_mcp_url(
    tmp_path, fake_repo, fake_config, current_url, enabled
):
    glean = {"enabled": enabled, "headers": {"X-User": "preserve"}}
    if current_url is not None:
        glean["url"] = current_url
    fake_config["cfg"] = {"mcp_servers": {"glean": glean}}

    cs.seed_baked_capabilities(tmp_path / "home")

    saved = fake_config["cfg"]["mcp_servers"]["glean"]
    assert saved["url"] == "https://default.example.test/mcp"
    assert saved["enabled"] is enabled
    assert saved["headers"] == {"X-User": "preserve"}
```

Add custom-URL, absent-`enabled`, and idempotency coverage:

```python
def test_seed_preserves_custom_mcp_url_and_absent_enabled(
    tmp_path, fake_repo, fake_config
):
    fake_config["cfg"] = {
        "mcp_servers": {
            "glean": {
                "url": "https://custom.example.test/mcp",
                "headers": {"X-User": "preserve"},
            }
        }
    }

    cs.seed_baked_capabilities(tmp_path / "home")
    first = json.loads(json.dumps(fake_config["cfg"]))
    cs.seed_baked_capabilities(tmp_path / "home")

    saved = fake_config["cfg"]["mcp_servers"]["glean"]
    assert saved["url"] == "https://custom.example.test/mcp"
    assert "enabled" not in saved
    assert saved["headers"] == {"X-User": "preserve"}
    assert fake_config["cfg"] == first
```

Also assert the fresh-profile path receives the fragment's full Glean entry with `enabled is False` and the source URL.

- [ ] **Step 3: Add equivalent failing bundle-staging coverage**

Extend `make_bundle()` in `tests/hermes_cli/test_capability_staging.py` with the same Glean fragment. Add a test that begins with `enabled: true`, a blank URL, and custom headers, calls `stage_bundle`, and asserts only the URL changes. Add another test that uses a custom URL and asserts the entire existing entry is unchanged.

- [ ] **Step 4: Run both staging test files and verify RED**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py -q
```

Expected: missing/blank existing URLs remain blank under the current whole-entry `continue` behavior, while the pre-existing non-clobber tests still pass.

- [ ] **Step 5: Implement one structural merge helper**

Add this helper near `_resolve_placeholders` in `hermes_cli/capability_staging.py`:

```python
def _merge_mcp_server_defaults(
    existing: dict,
    entries: dict,
    capability_dir: str,
) -> bool:
    """Merge missing servers and fill only missing/blank managed URLs."""
    changed = False
    for name, entry in entries.items():
        resolved = _resolve_placeholders(entry, capability_dir)
        if name not in existing:
            existing[name] = resolved
            changed = True
            continue

        current = existing.get(name)
        if not isinstance(current, dict) or not isinstance(resolved, dict):
            continue
        current_url = current.get("url")
        default_url = resolved.get("url")
        current_url_is_blank = current_url is None or (
            isinstance(current_url, str) and not current_url.strip()
        )
        if (
            current_url_is_blank
            and isinstance(default_url, str)
            and default_url.strip()
        ):
            current["url"] = default_url
            changed = True
    return changed
```

Replace the per-entry loops in both `stage_bundle` and `seed_baked_capabilities` with calls to `_merge_mcp_server_defaults`. Do not add any special case for `glean`, Ericsson, or the production hostname.

- [ ] **Step 6: Run the staging tests and verify GREEN**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py -q
```

Expected: all new and existing tests pass, including the original never-clobber test.

- [ ] **Step 7: Run adjacent MCP and configuration suites**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py \
  tests/hermes_cli/test_mcp_config.py \
  tests/hermes_cli/test_mcp_startup.py \
  tests/hermes_cli/test_mcp_tools_config.py \
  tests/hermes_cli/test_tools_config.py -q
```

Expected: all pass; disabled servers remain excluded by runtime tool selection.

- [ ] **Step 8: Commit the staging behavior on `base`**

Run:

```bash
git add hermes_cli/capability_staging.py \
  tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py
git commit -m "fix(capabilities): backfill blank managed MCP URLs"
```

---

### Task 3: Vendor the exact Ericsson source commit onto Hermes `base`

**Files:**
- Modify: `hermes-agent/capabilities/ericsson.json`
- Modify: `hermes-agent/capabilities/mcp-servers.yaml`
- Modify: `hermes-agent/capabilities/ericsson-vendored-paths.json` only if generated inventory changes
- Modify: `hermes-agent/skills/ericsson/onboard-ericsson-capabilities/references/capabilities/glean-search.md`
- Modify: `hermes-agent/skills/ericsson/onboard-ericsson-capabilities/references/catalog.json`
- Modify: `hermes-agent/tests/hermes_cli/test_capability_env_vars.py`

**Interfaces:**
- Consumes: exact committed Ericsson source tree and `scripts/vendor-ericsson.mjs`.
- Produces: a manifest-stamped, transactional vendored snapshot whose `vendoredFrom` matches the Task 1 source commit.

- [ ] **Step 1: Update the vendored Keys regression test before vendoring**

In `tests/hermes_cli/test_capability_env_vars.py`, require the remaining four keys and reject the removed URL key:

```python
    for key in (
        "JIRA_BASE_URL",
        "JIRA_PAT",
        "GLEAN_API_TOKEN",
        "ERICSSON_GRAPH_CLIENT_ID",
    ):
        assert key in ov
        assert ov[key]["category"] == "tool"
    assert "GLEAN_MCP_URL" not in ov
```

- [ ] **Step 2: Run the focused test and verify RED against the old snapshot**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_capability_env_vars.py -q
```

Expected: FAIL because the current vendored manifest still registers `GLEAN_MCP_URL`.

- [ ] **Step 3: Run the manifest-driven vendor command**

From `hermes-agent/base`, run:

```bash
node scripts/vendor-ericsson.mjs
```

Expected: the script reports the exact Task 1 Ericsson commit; the vendored manifest version is `0.4.1`; the vendored MCP fragment has the exact static URL and `enabled: false`; the generated onboarding files match source.

- [ ] **Step 4: Verify vendored provenance and managed bytes**

Run:

```bash
git -C ../ericsson-capabilities rev-parse HEAD
python - <<'PY'
import json
from pathlib import Path

manifest = json.loads(Path("capabilities/ericsson.json").read_text())
print(manifest["vendoredFrom"])
assert manifest["version"] == "0.4.1"
assert "GLEAN_MCP_URL" not in {entry["key"] for entry in manifest["env"]}
PY
```

Expected: the printed source and vendored SHAs match exactly.

- [ ] **Step 5: Run vendored registration and staging suites**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_capability_env_vars.py \
  tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py \
  tests/hermes_cli/test_brand_runtime.py -q
```

Expected: all pass.

- [ ] **Step 6: Commit only the managed vendor snapshot and Keys test**

Use `capabilities/ericsson-vendored-paths.json` to enumerate the vendor-owned paths, then stage those paths, `capabilities/ericsson.json`, the ledger, and the Keys test. Do not stage unrelated documentation changes.

```bash
git add capabilities/ericsson.json capabilities/ericsson-vendored-paths.json \
  capabilities/mcp-servers.yaml \
  skills/ericsson/onboard-ericsson-capabilities/references/capabilities/glean-search.md \
  skills/ericsson/onboard-ericsson-capabilities/references/catalog.json \
  tests/hermes_cli/test_capability_env_vars.py
git commit -m "fix(capabilities): vendor disabled Glean defaults"
```

If the vendor inventory lists additional changed managed files, inspect and stage only those generated changes.

---

### Task 4: Verify the neutral source and Hermes base delivery

**Files:**
- Verify only; no expected source edits.

**Interfaces:**
- Consumes: source commits from Tasks 1–3.
- Produces: evidence that source, vendor, staging, and onboarding contracts pass before brand merges.

- [ ] **Step 1: Re-run the Ericsson source gate at the committed source revision**

Run from `ericsson-capabilities`:

```bash
./bootstrap.sh
git status --short --branch
```

Expected: all tests pass and the repository is clean on `main`.

- [ ] **Step 2: Run the Hermes base capability gate**

Run from `hermes-agent`:

```bash
scripts/run_tests.sh tests/hermes_cli/test_capability_env_vars.py \
  tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py \
  tests/hermes_cli/test_brand_runtime.py \
  tests/hermes_cli/test_mcp_config.py \
  tests/hermes_cli/test_mcp_startup.py \
  tests/hermes_cli/test_mcp_tools_config.py \
  tests/hermes_cli/test_tools_config.py -q
```

Expected: all tests pass.

- [ ] **Step 3: Verify no task-owned uncommitted changes remain on `base`**

Run:

```bash
git diff --check
git status --short --branch
```

Expected: only the known unrelated portable-workflow documentation changes remain; no Glean or staging file is modified or untracked.

---

### Task 5: Merge, regenerate, test, and build every brand

**Files:**
- Generated branding overlays only if the brand generator changes them.

**Interfaces:**
- Consumes: committed Hermes `base` delivery.
- Produces: matching shared Glean bytes and verified branded builds for every descriptor in `brands/*.json`.

- [ ] **Step 1: Discover brands rather than hardcoding them**

Run:

```bash
python - <<'PY'
import json
from pathlib import Path

for path in sorted(Path("brands").glob("*.json")):
    print(json.loads(path.read_text())["slug"])
PY
```

Expected in the current tree: `loop24` and `otto`.

- [ ] **Step 2: Merge and regenerate Loop24**

Run:

```bash
git switch loop24
git merge base
node scripts/brand/generate.mjs loop24 --write
node scripts/brand/generate.mjs loop24 --check
```

Expected: merge succeeds and all 8 current emitters report `OK`.

- [ ] **Step 3: Test and build Loop24**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_capability_env_vars.py \
  tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py \
  tests/hermes_cli/test_brand_runtime.py -q
(cd apps/desktop && npm run build)
```

Expected: tests and desktop build pass with Loop24 branding.

- [ ] **Step 4: Merge and regenerate OTTO**

Run:

```bash
git switch otto
git merge base
node scripts/brand/generate.mjs otto --write
node scripts/brand/generate.mjs otto --check
```

Expected: merge succeeds and all 8 current emitters report `OK`.

- [ ] **Step 5: Test and build OTTO**

Run:

```bash
scripts/run_tests.sh tests/hermes_cli/test_capability_env_vars.py \
  tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py \
  tests/hermes_cli/test_brand_runtime.py -q
scripts/run_tests.sh tests/hermes_cli/test_skin_engine.py -q
(cd apps/desktop && npm run build)
```

Expected: capability tests, OTTO-only skin tests, and desktop build pass.

- [ ] **Step 6: Verify shared bytes match across all branches**

Run:

```bash
git diff --exit-code base..otto -- \
  capabilities/ericsson.json capabilities/mcp-servers.yaml \
  skills/ericsson/onboard-ericsson-capabilities/references/capabilities/glean-search.md \
  skills/ericsson/onboard-ericsson-capabilities/references/catalog.json \
  hermes_cli/capability_staging.py tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py tests/hermes_cli/test_capability_env_vars.py
git diff --exit-code base..loop24 -- \
  capabilities/ericsson.json capabilities/mcp-servers.yaml \
  skills/ericsson/onboard-ericsson-capabilities/references/capabilities/glean-search.md \
  skills/ericsson/onboard-ericsson-capabilities/references/catalog.json \
  hermes_cli/capability_staging.py tests/hermes_cli/test_baked_seed.py \
  tests/hermes_cli/test_capability_staging.py tests/hermes_cli/test_capability_env_vars.py
```

Expected: both commands exit 0 with no output.

- [ ] **Step 7: Finish on OTTO and report the preserved unrelated state**

Run:

```bash
git switch otto
git status --short --branch
git log -2 --oneline --decorate
git log -1 --oneline base
git log -1 --oneline loop24
```

Expected: final branch is `otto`; all task-owned files are committed; the previously observed portable-workflow documentation changes remain untouched; nothing has been pushed.

Report the source commit, base commits, brand merge commits, RED/GREEN evidence, exact test totals, brand generator results, builds, URL/enablement before-and-after behavior, and confirmation that the Gateway repository was not modified.
