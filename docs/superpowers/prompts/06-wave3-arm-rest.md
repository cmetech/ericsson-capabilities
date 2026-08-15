# Session 6 — Wave 3 (parallel): ARM connector, Tasks 3–10

**Repo:** `ericsson-capabilities` · **Wave:** 3 · **Requires Wave 2 merged to `main`**
**Runs in parallel with Sessions 4 and 5 — use a worktree.**

---

Execute part of an implementation plan, task by task.

**Repository:** `/Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities`

**Plan file:** `docs/superpowers/plans/2026-08-15-ericsson-arm-connector.md`

**Scope: Tasks 3 through 10.** Two tasks are already done and merged in Wave 2 — **do not
run them again:**

- **Task 1** (scaffold, manifest, registration) created `plugins/ericsson-arm/` with
  `models.py`, `plugin.yaml`, `config.schema.json`, vendored `_common/`, the
  `sets/ericsson.json` entry and the `CONSUMERS` update.
- **Task 2** (raw request bodies in the shared transport) added `content` and
  `extra_headers` to `HttpxTransport.request` and `BoundedClient.request`.

Read both for context so you know what exists, then start work at Task 3.

## Isolation

Two other sessions are working in this repo at the same time. Work in your own worktree:

```bash
cd /Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities
git worktree add .worktrees/arm-connector -b feat/ericsson-arm-connector main
cd .worktrees/arm-connector
./bootstrap.sh
```

Your file footprint is `plugins/ericsson-arm/**` and `tests/test_arm_*.py`. Tasks 1 and 2
already did every shared-file edit this plan needs, so **nothing in Tasks 3–10 should
touch** `sets/ericsson.json`, `scripts/sync_shared.py`, `tests/test_shared_sync.py`, or
`shared/ericsson_common/**`. If a task seems to ask you to, stop and check you are not
re-running Task 1 or Task 2.

Running `python scripts/sync_shared.py` is fine — it regenerates vendored `_common/` from
unchanged shared source and produces no diff.

## Before you start

```bash
git rev-parse --abbrev-ref HEAD                  # expect: feat/ericsson-arm-connector
ls plugins/ericsson-arm/models.py                # Task 1 output — must exist
ls plugins/ericsson-arm/_common/client.py        # vendored shared code — must exist
grep -n "content" shared/ericsson_common/transport.py | head -3   # Task 2 output — must be present
ls plugins/ericsson-confluence/                  # Wave 2 must be merged
. .venv/bin/activate && pytest -q tests/test_arm_manifest.py tests/test_shared_transport.py
```

If `content` does not appear in `HttpxTransport.request`, Task 2 has not merged — **stop
and say so.** Task 7 (AQL) cannot work without it: AQL posts `Content-Type: text/plain`,
which `json_body` cannot express.

## How to execute

Read the plan in full first, including Tasks 1 and 2 for context. Use
`superpowers:subagent-driven-development` — fresh subagent per task, review between tasks.
When dispatching a subagent, state the task number explicitly and note that Tasks 1 and 2
are already done.

Follow the TDD cycle exactly: failing test → confirm it fails → implement → confirm it
passes → wire the tool → parity check → commit.

## Guardrails

- **Tests:** `. .venv/bin/activate && pytest -q` from inside your worktree.
- **Task 3 is the highest-value task in this plan.** It pre-flights the mTLS client
  certificate's expiry. The live instance sits behind Cloudflare Access, and an expired
  certificate produces a `302` that three existing shell scripts each report as something
  unrelated ("No files found", "Failed to parse response as JSON", "AQL query failed").
  Task 3 plus Task 4's `edge_authentication` classification are what turn that into one
  accurate sentence. Do not water either down.
- Task 3's certificate tests shell out to `openssl` to mint real throwaway certificates.
  That is deliberate — a fake PEM would exercise neither `_test_decode_cert` nor
  `load_cert_chain`, which are the two things under test. If `openssl` is unavailable, skip
  those tests rather than replacing the certificates with fakes.
- **Task 7's AQL rules each come from a specific source** and none are decoration: the
  `text/plain` content type is byte-confirmed from the binary; the injected
  `include("repo","path","name")` comes from a documented Artifactory permission rule that
  otherwise produces an opaque 400; the refusal of caller `.limit()` is what keeps the
  result bound enforceable.
- **Task 8's deploy tries checksum-deploy first, then falls back to a full upload.**
  Both halves matter — super-cli has no fallback and its deploy fails outright when the
  blob is new.
- Every write: `require_explicit_intent`. Approval `rule_key` argument-derived, never the
  bare tool name.
- Task 10 verifies three invariants mechanically. Run those checks.

## A known open question

Whether this Artifactory accepts `Authorization: Bearer` or requires the legacy
`X-JFrog-Art-Api` header could not be confirmed against the live instance — the client
certificate had expired, so every probe was refused at the edge before reaching
Artifactory. The `auth_mode` enum exists to carry that uncertainty, and Task 3 tests both
branches. **Keep both branches.** If someone confirms the answer during this work, note it
in your report rather than deleting a branch mid-plan.

## Definition of done

- Tasks 3–10 complete, each with its own commit
- Task 10's contract check reports `OK 6 tools, 2 gated writes` and the invariant check
  passes
- `. .venv/bin/activate && python scripts/sync_shared.py && pytest -q` green, no drift
- Branch `feat/ericsson-arm-connector` pushed
- Report: what landed, deviations and why, anything the plan got wrong

**Do not merge to `main`.** Report back.
