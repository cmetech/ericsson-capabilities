# Authoring and Catalog Maintenance

Use this procedure whenever an Ericsson capability is added, removed, or materially
changed. After following it, a maintainer should have an implementation, education
entry, compact catalog, and vendored snapshot that agree.

## What is generated and what is authored

Author the focused Markdown entry under the onboarding skill's capability
references. Its YAML frontmatter is the structured contract and its body is the
progressively loaded user guidance. Do not edit `references/catalog.json` directly;
`build_catalog.py` deterministically compiles it.

Each entry has a stable lowercase ID matching its filename and supplies:

- display name, aliases, at least three goal-oriented examples, maturity, and
  recommendation eligibility;
- source flow documents and exact skill, plugin, MCP, workflow, and tool
  registrations;
- platforms and configuration items classified as `static-secret`,
  `static-setting`, `interactive-sign-in`, `permission`, `local-software`, or
  `workflow-input`;
- reads, writes, approvals, artifacts, supported demonstration modes, and
  troubleshooting categories;
- the required plain-language sections: problem, example prompts, questions,
  reads/writes, readiness, demonstration, artifacts, and troubleshooting.

Only `available` entries may be recommendation-eligible. Partial, planned, and
unsupported entries explain status but cannot claim readiness or execution.

## Add a capability

1. Implement the skill, plugin, MCP server, workflow, or other already-supported
   artifact type.
2. Add its package path and any Keys metadata to `sets/ericsson.json`; align runtime
   registration and platform declarations.
3. Add or update the user-facing capability and flow documentation.
4. Add one focused onboarding entry. Reuse shared safety, configuration,
   demonstration, artifact, and troubleshooting references instead of copying them.
5. Add realistic natural-language trigger examples and follow-ups for scope,
   filters, preview versus execution, format, destination, exclusions, warnings,
   and safe reruns.
6. Add synthetic demo/test artifacts when a useful offline demonstration exists.
7. Generate, check, and validate the catalog.
8. Run the source tests before requesting delivery approval.

## Change a capability

Treat a change as material when it alters availability, registration, keys,
authentication, permissions, dependencies, platforms, reads, writes, approvals,
prompts, outputs, artifact locations, demonstration behavior, or common failures.
Update all affected sources in the same change and regenerate the catalog. Never
leave the old behavior advertised for compatibility.

## Remove a capability

1. Remove or de-register the implementation and remove its manifest path.
2. Update flow status and user-facing documentation.
3. Remove the onboarding entry, or retain a recommendation-ineligible tombstone
   only when a durable product decision requires historical answers.
4. Remove configuration, trigger, demonstration, and troubleshooting claims that no
   longer exist.
5. Regenerate the catalog and confirm validation catches no stale advertisement.
6. Re-vendor so the managed Hermes snapshot removes paths no longer present in the
   source manifest.

## Required maintenance checklist

Adding, removing, or materially changing an Ericsson capability must update, as
applicable:

- its implementation;
- manifest and runtime registration;
- user-facing capability documentation and flow status;
- configuration requirements, authentication, permissions, dependencies, and
  platforms;
- natural-language trigger examples and follow-up language;
- reads, writes, approvals, outputs, artifact destinations, and inspection guidance;
- demo/test artifacts, expected results, and troubleshooting where applicable;
- its onboarding entry and the generated onboarding catalog;
- the vendored Hermes snapshot.

Prefer the validators below over relying on checklist memory.

## Generate and validate

Run from the `ericsson-capabilities` repository root:

```bash
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/build_catalog.py --check
.venv/bin/python skills/ericsson/onboard-ericsson-capabilities/scripts/validate_catalog.py
.venv/bin/pytest tests/test_onboarding_catalog.py tests/test_onboarding_skill.py -q
```

The check must find the committed catalog current. The validator's success payload is:

```json
{"ok": true, "problems": []}
```

Validation reconciles entries with the manifest, skill frontmatter, plugin and tool
registrations, MCP servers, workflows, flow maturity, configuration names, and
referenced paths. Every workflow `kind: tool` node must declare `tools`, use those
names in its prompt, and source them from `requires.toolsets`,
`requires.mcp_servers`, or the manifest's explicit `workflowCoreTools` allowlist.
Manifest environment keys must be consumed by an implementation environment access,
MCP placeholder, or workflow requirement; catalog documentation alone cannot keep a
stale key alive. A mismatch is work to fix, not a warning to waive.

## Source delivery gate

Focused tests are useful during authoring, but they do not replace the complete
source gate. Before requesting delivery approval, run from the
`ericsson-capabilities` repository root:

```bash
.venv/bin/python scripts/lint_manifest.py sets/ericsson.json
.venv/bin/pytest -q
git diff --check
```

Expected outcomes: manifest lint prints JSON containing `"ok": true`; the full source suite passes,
with Windows-native skips reported as pending rather than passes on a non-Windows
host; and `git diff --check` exits 0 with no whitespace errors. Review
`git status --short` separately so unrelated or untracked work is not accidentally
delivered.

## Source-first delivery

Delivery is intentionally separate from source authoring and requires explicit
approval:

**Task 9 delivery prerequisite:** the Hermes vendor must stamp the full source SHA
and generate `capabilities/ericsson-vendored-paths.json` as its reconciled managed
inventory. The approved vendor accepts only the real, clean Git worktree at a full
40-character commit. It rejects staged, tracked, untracked, relevant ignored,
submodule, assume-unchanged, and skip-worktree differences, then copies from an
isolated commit-pinned `checkout-index` snapshot rather than from mutable working
files. If the full stamp or inventory is absent, stop; never weaken the contract to
accept a short SHA or an untracked stale vendor path.

The ledger is an index, not unilateral deletion authority: reconciliation also
requires ownership proven by the prior manifest (including the documented legacy
MCP transition). Run vendor invocations serialized because the command has no
cross-process lock. Publication is journaled with per-path recovery and publishes
the manifest last; it is recoverable, not a globally atomic tree swap. If an
invocation is interrupted, do not edit its journal or transaction directory; rerun
the same vendor command after confirming no other invocation is active.
Windows-native validation remains pending until the separate release checklist
passes on Windows.

Run steps 1 through 6 in the same Bash session so recorded variables remain in
scope. Enable immediate pipeline failure before any verification command.

1. Commit the verified source in `ericsson-capabilities`, record its repository and
   full revision, and reject anything except a full 40-character commit:

   ```bash
   set -euo pipefail
   SOURCE_REPO=/absolute/path/to/ericsson-capabilities
   SOURCE_SHA=$(git -C "$SOURCE_REPO" rev-parse HEAD)
   test "${#SOURCE_SHA}" -eq 40
   test -z "$(git -C "$SOURCE_REPO" status --porcelain=v1 --untracked-files=all)"
   ```
2. In `hermes-agent` on neutral `base`, vendor that exact clean source revision:

   ```bash
   git switch base
   node scripts/vendor-ericsson.mjs
   git status --short
   ```

   Verify `capabilities/ericsson.json` records the full source revision, then run the
   neutral shared gates before committing the snapshot:

   ```bash
   node --test scripts/__tests__/vendor-ericsson.test.mjs
   .venv/bin/python -m pytest tests/hermes_cli/test_capability_staging.py tests/hermes_cli/test_capability_env_vars.py tests/hermes_cli/test_brand_runtime.py -q
   .venv/bin/python -m pytest tests/providers -q
   ```

   Do not run the OTTO-literal skin suite on `base`.

3. Discover the real brand slugs from `brands/*.json` in `hermes-agent`; do not keep
   a separate hard-coded brand list:

   ```bash
   BRANDS_FILE=/tmp/ericsson-brands.txt
   node -e "const fs=require('fs');for(const f of fs.readdirSync('brands').filter(f=>f.endsWith('.json')&&!f.startsWith('_')&&f!=='schema.json')){const d=JSON.parse(fs.readFileSync('brands/'+f));if(typeof d.slug==='string')console.log(d.slug)}" > "$BRANDS_FILE"
   cat "$BRANDS_FILE"
   ```

4. After the neutral vendor commit exists, merge and verify each discovered brand.
   Execute one branch at a time so regenerated overlay changes can be inspected:

   ```bash
   while IFS= read -r brand; do
     git switch "$brand"
     git merge base
     node scripts/brand/generate.mjs $brand --write
     node scripts/brand/generate.mjs $brand --check
     node --test scripts/__tests__/vendor-ericsson.test.mjs
     .venv/bin/python -m pytest tests/hermes_cli/test_capability_staging.py tests/hermes_cli/test_capability_env_vars.py tests/hermes_cli/test_brand_runtime.py -q
     .venv/bin/python -m pytest tests/providers -q
     npm --prefix apps/desktop run test:desktop:platforms
     git status --short
   done < "$BRANDS_FILE"
   ```

   Run `.venv/bin/python -m pytest tests/hermes_cli/test_skin_engine.py -q` only
   while `otto` is checked out. If `--write` changes tracked overlay files, inspect,
   retest, and commit only those generated brand files; never amend the shared base
   commit.

5. Compare every committed source artifact mapped by the source manifest with its
   committed vendored destination on `base`. This checks bytes from Git objects,
   not either working tree. The mapping covers all current manifest artifact types:
   skills and plugins retain their path, local MCP packages move under `plugins/`,
   workflows move under `capabilities/workflows/`, and the MCP server fragment
   moves under `capabilities/`.

   ```bash
   SOURCE_MAP_FILE=/tmp/ericsson-source-map.tsv
   git -C "$SOURCE_REPO" show "$SOURCE_SHA:sets/ericsson.json" |
     node -e "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const m=JSON.parse(s);const b=p=>p.split('/').pop();const pairs=[...(m.skills||[]).map(p=>[p,p]),...(m.plugins||[]).map(p=>[p,p]),...(m.mcpLocal||[]).map(p=>[p,'plugins/'+b(p)]),...(m.workflows||[]).map(p=>[p,'capabilities/workflows/'+b(p)])];if(m.mcpServers)pairs.push([m.mcpServers,'capabilities/'+b(m.mcpServers)]);for(const [source,destination] of pairs)process.stdout.write(source+'\t'+destination+'\n')})" > "$SOURCE_MAP_FILE"

   SOURCE_DESTINATIONS_FILE=/tmp/ericsson-source-destinations.txt
   LEDGER_DESTINATIONS_FILE=/tmp/ericsson-ledger-destinations.txt
   cut -f 2 "$SOURCE_MAP_FILE" | LC_ALL=C sort -u > "$SOURCE_DESTINATIONS_FILE"
   git show base:capabilities/ericsson-vendored-paths.json |
     node -e "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const paths=JSON.parse(s);if(!Array.isArray(paths)||paths.some(p=>typeof p!=='string'||!p))process.exit(1);for(const p of paths)console.log(p)})" |
     LC_ALL=C sort -u > "$LEDGER_DESTINATIONS_FILE"
   diff -u "$SOURCE_DESTINATIONS_FILE" "$LEDGER_DESTINATIONS_FILE"

   awk -F '\t' '$1 == "skills/ericsson/onboard-ericsson-capabilities" && $2 == $1 { found=1 } END { exit !found }' "$SOURCE_MAP_FILE"

   VERIFY_ROOT=$(mktemp -d)
   mapping_index=0
   while IFS="$(printf '\t')" read -r source_path vendored_path; do
     mkdir -p "$VERIFY_ROOT/source/$mapping_index" "$VERIFY_ROOT/base/$mapping_index"
     git -C "$SOURCE_REPO" archive "$SOURCE_SHA" "$source_path" |
       tar -x -C "$VERIFY_ROOT/source/$mapping_index"
     git archive base "$vendored_path" |
       tar -x -C "$VERIFY_ROOT/base/$mapping_index"
     diff -qr "$VERIFY_ROOT/source/$mapping_index/$source_path" \
       "$VERIFY_ROOT/base/$mapping_index/$vendored_path"
     mapping_index=$((mapping_index + 1))
   done < "$SOURCE_MAP_FILE"
   rm -rf "$VERIFY_ROOT"
   ```

   The first `diff` proves every ledger-owned destination has exactly one current
   manifest mapping, so the archive loop cannot silently omit a managed path. The
   explicit `awk` assertion makes the source
   `skills/ericsson/onboard-ericsson-capabilities` tree a mandatory same-path
   comparison. Every `diff` must be empty. Also confirm that
   `base:capabilities/ericsson.json` records `$SOURCE_SHA` in `vendoredFrom`.

6. Compare the manifest, ledger, and every ledger-owned destination across `base`
   and every discovered brand. Read the paths from the committed base ledger; do
   not repeat a hand-maintained capability subset in this command:

   ```bash
   MANAGED_PATHS_FILE=/tmp/ericsson-managed-paths.txt
   git show base:capabilities/ericsson-vendored-paths.json |
     node -e "let s='';process.stdin.setEncoding('utf8');process.stdin.on('data',c=>s+=c);process.stdin.on('end',()=>{const paths=JSON.parse(s);if(!Array.isArray(paths)||paths.some(p=>typeof p!=='string'||!p))process.exit(1);for(const p of paths)console.log(p)})" > "$MANAGED_PATHS_FILE"
   printf '%s\n' capabilities/ericsson.json capabilities/ericsson-vendored-paths.json >> "$MANAGED_PATHS_FILE"
   LC_ALL=C sort -u "$MANAGED_PATHS_FILE" -o "$MANAGED_PATHS_FILE"

   while IFS= read -r managed_path; do
     git cat-file -e "base:$managed_path"
   done < "$MANAGED_PATHS_FILE"
   xargs git ls-tree -r base -- < "$MANAGED_PATHS_FILE" > /tmp/ericsson-base.objects
   while IFS= read -r brand; do
     while IFS= read -r managed_path; do
       git cat-file -e "$brand:$managed_path"
     done < "$MANAGED_PATHS_FILE"
     xargs git ls-tree -r "$brand" -- < "$MANAGED_PATHS_FILE" > "/tmp/ericsson-$brand.objects"
     diff -u /tmp/ericsson-base.objects "/tmp/ericsson-$brand.objects"
   done < "$BRANDS_FILE"
   ```

   Every diff must be empty. Finish with:

   ```bash
   git switch otto
   node scripts/brand/generate.mjs otto --check
   git status --short --branch
   ```

Do not place shared content directly on `otto`, `loop24`, or another brand branch.
Do not push, release, or open a pull request without approval.
