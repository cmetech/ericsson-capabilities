# Ericsson ARM (Artifactory) Connector Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the missing Artifactory connector — 6 tools covering AQL search, artefact and folder metadata, build properties, repository enumeration, and two approval-gated writes (checksum-first deploy, path delete) — targeting the Cloudflare-Access-fronted JFrog instance OSCAR actually publishes to.

**Architecture:** A standalone connector at `plugins/ericsson-arm/`, shaped like `ericsson-jira` and built on the shared `_common` transport from Plan 2. Three sources are merged:

- **From super-cli's `internal/arm`** — the endpoint set, header shapes, and the `X-Checksum-Deploy` idea, all byte-confirmed from the stripped binary.
- **From `oscar_app/oscar/utils`** — the operational knowledge super-cli does not have: checksum-deploy *with a full-upload fallback*, the mandatory AQL `.include("repo","path","name")` permission rule, folder-level delete semantics, and the fact that this instance sits behind Cloudflare Access with mTLS.
- **From `ericsson-jira`** — auth resolution, redaction discipline, argument-scoped write approvals, and edge-authentication classification (its Cloudflare-1010 handling is the nearest precedent).

The connector's distinguishing feature is that it **fails legibly**. The three shell scripts it supersedes report an expired client certificate as "No files found", "Failed to parse response as JSON", and "AQL query failed" respectively. This connector checks certificate validity before the first request and classifies a Cloudflare Access redirect as its own error category.

**Tech Stack:** Python 3.11+, shared `_common` from Plan 2, stdlib `ssl` + `hashlib` (no new dependency), `httpx>=0.27` via `_common`, pytest via `./bootstrap.sh`.

**Spec:** Endpoints in `/Users/coreyellis/tmp_supercli/SUPER-CLI-ARCHITECTURE.md` §6.6 and the per-function string table in `/Users/coreyellis/tmp_supercli/out/func-strings.txt`; operational behaviour in `oscar_app/oscar/utils/{bulk_upload_verify.sh,cleanup_artifactory_releases.sh,pull_images_from_artifactory_repo.sh}`; gap analysis in `/Users/coreyellis/tmp_supercli/PLUGIN-GAP-ANALYSIS.md`.

**Repo:** `/Users/coreyellis/code/github.com/cmetech/otto_hermes/ericsson-capabilities`

**Depends on:** Plan 2 (`2026-08-15-ericsson-shared-transport.md`) — built on `_common` from the first commit rather than migrated later. Task 2 of this plan additively amends that shared code.

## Global Constraints

- **Tests:** `./bootstrap.sh` (or `. .venv/bin/activate && pytest -q`) must pass before vendoring — `CLAUDE.md:106`.
- **Branch-placement invariant:** this plan stops at the `ericsson-capabilities` commit — `CLAUDE.md:32-34`.
- **New standalone connector registration:** drop `plugins/ericsson-arm/` with its own `plugin.yaml`, add `{path, id, enabled: false}` to `plugins[]` in `sets/ericsson.json` — `CLAUDE.md:22`. The vendor script derives from that manifest, so **no `vendor-ericsson.mjs` change is required**.
- **Errors never carry remote or secret text.** Raise `ArmError(category)`; unknown categories silently coerce to `"transient"`, so every category the shared client can raise must exist in `SAFE_ERROR_MESSAGES`.
- **`ConnectorError` never escapes the connector.** Translate at the boundary via `_as_arm_error`. `ConnectorError.detail` may quote caller input; `ArmError` guarantees neither remote nor secret text reaches the host.
- **No new third-party dependencies.** `httpx` via `_common`, plus stdlib `ssl` and `hashlib`.
- **Four-point checklist per tool:** `SCHEMAS` → `invoke()` dispatch → `ArmOperations` method → `plugin.yaml` `provides_tools`; writes add `_WRITE_TOOLS` + an argument-scoped approval summary.
- **Every write:** `require_explicit_intent(dry_run=, confirm=, action=)`. Neither flag is a refusal, matching super-cli's `requires --dry-run or --confirm`.
- **Every list-returning read:** `result_envelope(items, total=, truncated=, hint=)`; omit `total` when genuinely unknown rather than reporting 0.
- **Validation uses `type(x) is not bool` / `type(x) is not int`** — `bool` subclasses `int`, so `isinstance` lets `True` pass a range check.

## Decisions Taken

| # | Decision | Rationale |
|---|---|---|
| D1 | **Target the Rosetta instance**, not super-cli's `arm.seli.gic.ericsson.se` | `artifactory.rosetta.ericssondevops.com` is where OSCAR builds actually publish. Same REST surface; different auth. `base_url` is a per-profile `storage: setting`, so `arm.seli` is a second profile, not a second connector. |
| D2 | **Xray is out of the first cut** | Nothing in OSCAR's scripts touches `/xray/`, and it may not be licensed on this tenant. This also collapses the two-API-base problem: every remaining path lives under `/artifactory/`, so the transport keeps one exact `path_prefix` instead of needing a widened allow-list. |
| D3 | `auth_mode` enum — `bearer` (default) or `api_key` | The scripts use `X-JFrog-Art-Api`; super-cli uses `Authorization: Bearer`. The token value is a JFrog *reference token*, which both headers accept, but this could not be confirmed against a live instance because the client certificate had expired. One enum field costs nothing and removes the guess. Precedent: `ericsson-jira/config.schema.json:18-31`. |
| D4 | **mTLS needs no transport change** | `HttpxTransport` already takes `tls_context` and passes it to httpx's `verify=`. httpx 0.28 accepts an `ssl.SSLContext` there, and a client cert is loaded into that context with `load_cert_chain`. Verified against the installed httpx 0.28.1. |
| D5 | **Certificate expiry is checked before the first request** | The observed failure mode is a `302` to `cloudflareaccess.com` with `auth_status: FAILED:FAILED:certificate has expired`. All three shell scripts turn that into an unrelated-sounding error. `ssl._ssl._test_decode_cert` reads `notAfter` from a PEM with no third-party dependency (verified). This is the single highest-value thing the connector adds. |
| D6 | **Cloudflare Access gets its own error category** | `edge_authentication` is distinct from `authentication`: the credential that failed is the client certificate at the edge, not the Artifactory token at the origin. Collapsing them would send an operator to rotate the wrong secret. |
| D7 | **AQL is exposed raw**, with connector-enforced bounds | The token carries the user's own permissions, so a query cannot reach what the user could not already read — the same argument that justified raw CQL in Plan 3c. What differs is shape, not authority: AQL result sets are unbounded, so the connector rejects a caller `.limit(` and appends its own from `max_results`. |
| D8 | **The connector injects AQL's required `include` fields** | Artifactory rejects an `.include()` lacking `repo`, `path`, and `name` with *"For permissions reasons AQL demands the following fields: repo, path and name."* — documented at `cleanup_artifactory_releases.sh:174-178`. super-cli passes AQL through raw and would surface this as an opaque 400. Injecting is additive and cannot change which rows match. |
| D9 | **AQL omits `total`** | Artifactory's `range.total` reflects the limited response, not the full match count. Reporting it as `total` would be a wrong number, and the envelope's contract is that a wrong number is worse than none. `truncated` + `returned` carry the signal instead. |
| D10 | **Deploy tries checksum-deploy, then falls back to a full upload** | Ported from `bulk_upload_verify.sh:183-228`. super-cli sets `X-Checksum-Deploy: true` unconditionally with no fallback, so its deploy fails outright against a repository that does not already hold the blob. All three checksums are sent, not just sha256. |
| D11 | **Delete is one call, one path — no bulk loop** | `cleanup_artifactory_releases.sh` has a per-file delete loop as a fallback. The connector deliberately does not replicate it: Artifactory recurses server-side on a folder path, so the correct agent-facing operation is "delete this folder or nothing". An agent iterating deletes is precisely the failure mode approval gating exists to prevent. |
| D12 | **`delete` dry-run performs a read** | Previewing what is about to be destroyed is the entire value of the dry run. It costs one GET and is pinned by a test so it stays a decision rather than drifting. `deploy`'s dry run makes no request, because the checksum probe *is* a deploy. |
| D13 | **No `download` tool** | super-cli itself never emits artefact bytes — `arm artifact download` writes to a local file and returns `{file, bytes, sha256}`. What an agent needs from an artefact is the checksum, which `arm_artifact_info` returns at zero bytes transferred. Reading a *text* artefact (SBOM, manifest) is a different, bounded tool and is not in this cut. |
| D14 | **`deploy_root` is an optional confinement setting** | An agent choosing an arbitrary local file to upload into a corporate repository is a real supply-chain surface. The primary control is the approval prompt, which shows the exact source path. `deploy_root`, when set, additionally confines sources to one subtree. Left unset by default because the build server's layout is not knowable here. |
| D15 | **Properties are read-only in this cut** | Artifactory properties drive promotion gates. An agent flipping one could promote an unscanned artefact. super-cli's `joinComma`/`joinSemicolon` property encoders are documented in the README for whoever adds `set_properties` later. |

## File Structure

| File | Responsibility |
|---|---|
| **Modify** `shared/ericsson_common/transport.py` | Add `content` + `extra_headers` to `request()`. |
| **Modify** `shared/ericsson_common/client.py` | Pass `content` + `extra_headers` through `BoundedClient.request()`. |
| **Create** `plugins/ericsson-arm/__init__.py` | Registration, handlers, argument-scoped write approvals. |
| **Create** `plugins/ericsson-arm/models.py` | `ArmAuth`, `ArmError`, `SAFE_ERROR_MESSAGES`. |
| **Create** `plugins/ericsson-arm/auth.py` | Configuration → validated identity, auth header, TLS context, certificate pre-flight. |
| **Create** `plugins/ericsson-arm/client.py` | `ArmClient` on `_common.BoundedClient`, with edge-auth classification. |
| **Create** `plugins/ericsson-arm/aql.py` | AQL validation, `include` injection, `limit` enforcement. |
| **Create** `plugins/ericsson-arm/operations.py` | `ArmOperations` — 6 methods. |
| **Create** `plugins/ericsson-arm/tools.py` | `SCHEMAS`, `check_available`, `invoke()`. |
| **Create** `plugins/ericsson-arm/config.schema.json` | Base URL, auth mode, token, mTLS paths, bounds. |
| **Create** `plugins/ericsson-arm/plugin.yaml` | Manifest. |
| **Create** `plugins/ericsson-arm/README.md` | Cloudflare Access, certificate renewal, deferred surface. |
| **Create** `plugins/ericsson-arm/skills/artifact-research/SKILL.md` | Connector skill. |
| **Modify** `sets/ericsson.json` | `plugins[]` entry, disabled by default. |
| **Modify** `scripts/sync_shared.py`, `tests/test_shared_sync.py` | Add connector to `CONSUMERS`. |
| **Create** `tests/test_arm_*.py` | Manifest, auth, client, AQL, reads, writes, contract. |

---

### Task 1: Scaffold, manifest, and shared-code registration

**Files:**
- Create: `plugins/ericsson-arm/{__init__.py,models.py,plugin.yaml,config.schema.json}`
- Modify: `sets/ericsson.json`, `scripts/sync_shared.py`, `tests/test_shared_sync.py`
- Test: `tests/test_arm_manifest.py` (create)

**Interfaces:**
- Produces:
  - `ArmError(category, *, remediation=None)` with `.category`, `.remediation`
  - `SAFE_ERROR_MESSAGES: dict[str, str]`
  - `ArmAuth(origin, api_root, auth_header_name, auth_header_value, token, tls_context, certificate_not_after, request_timeout_seconds, default_max_results, max_deploy_bytes, deploy_root)`
  - `plugins/ericsson-arm/_common/` present and in sync

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arm_manifest.py`:

```python
"""The ARM connector must be registered and loadable."""

import json
import sys
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
PLUGIN = REPO / "plugins" / "ericsson-arm"


class TestManifest:
    def test_plugin_directory_exists(self):
        assert PLUGIN.is_dir()
        assert (PLUGIN / "plugin.yaml").is_file()
        assert (PLUGIN / "__init__.py").is_file()

    def test_declared_in_the_capability_set(self):
        entries = json.loads((REPO / "sets" / "ericsson.json").read_text())["plugins"]
        matches = [
            e for e in entries
            if isinstance(e, dict) and e.get("id") == "ericsson-arm"
        ]
        assert len(matches) == 1
        assert matches[0]["path"] == "plugins/ericsson-arm"

    def test_disabled_by_default(self):
        entries = json.loads((REPO / "sets" / "ericsson.json").read_text())["plugins"]
        entry = next(
            e for e in entries
            if isinstance(e, dict) and e.get("id") == "ericsson-arm"
        )
        assert entry["enabled"] is False

    def test_manifest_declares_a_config_schema(self):
        manifest = yaml.safe_load((PLUGIN / "plugin.yaml").read_text())
        assert manifest["kind"] == "standalone"
        assert manifest["config_schema"] == "config.schema.json"

    def test_token_is_secret_storage(self):
        schema = json.loads((PLUGIN / "config.schema.json").read_text())
        token = next(f for f in schema["fields"] if f["id"] == "token")
        assert token["storage"] == "secret"

    def test_auth_mode_offers_both_header_schemes(self):
        """The token is a JFrog reference token, which both headers accept.
        Which one this instance wants could not be confirmed live, so the
        connector ships the choice rather than a guess."""
        schema = json.loads((PLUGIN / "config.schema.json").read_text())
        mode = next(f for f in schema["fields"] if f["id"] == "auth_mode")
        assert set(mode["validation"]["enum"]) == {"bearer", "api_key"}
        assert mode["default"] == "bearer"

    def test_client_certificate_paths_are_settings_not_secrets(self):
        """The key file stays on disk and is referenced by path. Putting a
        private key through the secret editor would mean storing it in the
        profile store, which is not what a PEM key file is for."""
        schema = json.loads((PLUGIN / "config.schema.json").read_text())
        ids = {f["id"]: f for f in schema["fields"]}
        assert ids["client_cert_path"]["storage"] == "setting"
        assert ids["client_key_path"]["storage"] == "setting"

    def test_shared_code_is_vendored(self):
        assert (PLUGIN / "_common" / "client.py").is_file(), (
            "run: python scripts/sync_shared.py"
        )


class TestErrors:
    def test_unknown_category_coerces_to_transient(self):
        sys.path.insert(0, str(PLUGIN))
        from models import ArmError

        assert ArmError("not-a-real-category").category == "transient"

    def test_categories_the_shared_client_raises_are_all_known(self):
        """Both error classes coerce unknown categories to 'transient', so a
        missing entry does not crash -- it silently destroys the signal."""
        sys.path.insert(0, str(PLUGIN))
        from models import SAFE_ERROR_MESSAGES

        for category in (
            "conflict", "confirmation_required", "write_ambiguous",
            "circuit_open", "capacity", "deadline", "cancelled",
        ):
            assert category in SAFE_ERROR_MESSAGES, category

    def test_arm_specific_categories_exist(self):
        sys.path.insert(0, str(PLUGIN))
        from models import SAFE_ERROR_MESSAGES

        for category in ("edge_authentication", "certificate_invalid"):
            assert category in SAFE_ERROR_MESSAGES, category

    def test_edge_authentication_is_distinct_from_authentication(self):
        """The credential that fails at the edge is the client certificate,
        not the Artifactory token. Collapsing them sends an operator to
        rotate the wrong secret."""
        sys.path.insert(0, str(PLUGIN))
        from models import SAFE_ERROR_MESSAGES

        assert (
            SAFE_ERROR_MESSAGES["edge_authentication"]
            != SAFE_ERROR_MESSAGES["authentication"]
        )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_manifest.py -q`
Expected: FAIL — `assert PLUGIN.is_dir()`

- [ ] **Step 3: Create the skeleton**

```bash
mkdir -p plugins/ericsson-arm/skills/artifact-research
```

`plugins/ericsson-arm/plugin.yaml`:

```yaml
name: ericsson-arm
version: 1.0.0
description: "Ericsson Artifactory tools — AQL search, artefact metadata and build properties, repository enumeration, and gated checksum-first deploy and delete."
author: Ericsson (cmetech)
kind: standalone
config_schema: config.schema.json
provides_tools: []
```

`plugins/ericsson-arm/models.py`:

```python
"""Stable, redacted error and identity types for the Artifactory connector."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

SAFE_ERROR_MESSAGES = {
    "invalid_configuration": "Artifactory configuration is invalid",
    "invalid_input": "Artifactory request input is invalid",
    "authentication": "Artifactory authentication failed",
    "permission": "Artifactory permission denied",
    "not_found": "Artifactory content was not found",
    "conflict": "Artifactory content changed since it was read",
    "rate_limited": "Artifactory rate limit was reached",
    "transient": "Artifactory service is temporarily unavailable",
    "write_ambiguous": "Artifactory write outcome is unknown",
    "invalid_remote_data": "Artifactory returned invalid data",
    "cancelled": "Artifactory request was cancelled",
    "deadline": "Artifactory request deadline was exceeded",
    "capacity": "Artifactory result exceeded a safe limit",
    "circuit_open": "Artifactory calls are paused after repeated failures",
    "confirmation_required": "Artifactory change needs explicit confirmation",
    # ARM-specific. Deliberately distinct from "authentication": the
    # credential that fails here is the mTLS client certificate presented
    # to Cloudflare Access, not the Artifactory token at the origin.
    "edge_authentication": (
        "Artifactory edge access was refused before the request reached "
        "Artifactory"
    ),
    "certificate_invalid": (
        "Artifactory client certificate is missing, expired, or unreadable"
    ),
}


class ArmError(RuntimeError):
    """Stable classified failure that never includes remote or secret text."""

    def __init__(self, category: str, *, remediation: str | None = None) -> None:
        self.category = category if category in SAFE_ERROR_MESSAGES else "transient"
        self.remediation = remediation
        super().__init__(SAFE_ERROR_MESSAGES[self.category])


@dataclass(frozen=True, slots=True)
class ArmAuth:
    origin: str
    # Every path in this connector lives under /artifactory/. Xray would add
    # a second root; it is deliberately out of this cut, which is what keeps
    # the transport's allow-list a single exact prefix.
    api_root: str
    auth_header_name: str
    auth_header_value: str
    # Retained separately from the header value so redaction can strip the
    # bare token as well as the full "Bearer <token>" form.
    token: str
    # ssl.SSLContext or None. Typed loosely so models.py imports no ssl.
    tls_context: Any
    # Unix seconds from the client certificate's notAfter, or None when no
    # certificate is configured. Read once at configuration time.
    certificate_not_after: float | None
    request_timeout_seconds: int
    default_max_results: int
    max_deploy_bytes: int
    deploy_root: str | None
```

`plugins/ericsson-arm/__init__.py` — loadable stub; tools arrive in Task 5:

```python
"""Ericsson Artifactory standalone connector registration."""

from __future__ import annotations

import hashlib
import json

_WRITE_TOOLS: frozenset[str] = frozenset()
WRITE_APPROVALS: dict = {}


def _arg(args: dict, name: str) -> str:
    """Render one argument for an approval prompt, safely and bounded."""
    value = args.get(name) if isinstance(args, dict) else None
    return json.dumps(value, ensure_ascii=True)[:512]


def register(ctx) -> None:
    """Register Artifactory tools. Populated from Task 5 onward."""

    def require_write_approval(tool_name: str, args: dict, **_kwargs):
        summarise = WRITE_APPROVALS.get(tool_name)
        if summarise is None:
            return None
        canonical_args = json.dumps(
            args if isinstance(args, dict) else {},
            ensure_ascii=True,
            separators=(",", ":"),
            sort_keys=True,
        )
        return {
            "action": "approve",
            "message": (
                f"Approve Ericsson Artifactory change: {tool_name}\n"
                f"{summarise(args if isinstance(args, dict) else {})}"
            ),
            # Argument-derived, never the bare tool name: a tool-name
            # rule_key turns one "always" into a standing grant for every
            # future call. See hermes-agent tools/approval.py:3366.
            "rule_key": (
                f"{tool_name}:"
                f"{hashlib.sha256(canonical_args.encode('utf-8')).hexdigest()}"
            ),
        }

    ctx.register_hook("pre_tool_call", require_write_approval)
```

- [ ] **Step 4: Write the configuration schema**

`plugins/ericsson-arm/config.schema.json`:

```json
{
  "version": 1,
  "fields": [
    {
      "id": "base_url",
      "label": "Artifactory base URL",
      "type": "string",
      "storage": "setting",
      "required": true,
      "help": "Exact HTTP(S) Artifactory origin, without a path. Example: https://artifactory.rosetta.ericssondevops.com",
      "validation": { "format": "url", "min_length": 8, "max_length": 2048 },
      "readiness": true
    },
    {
      "id": "auth_mode",
      "label": "Authentication header",
      "type": "string",
      "storage": "setting",
      "required": true,
      "default": "bearer",
      "help": "Send the token as Authorization: Bearer (modern JFrog access tokens) or as the legacy X-JFrog-Art-Api header.",
      "validation": { "enum": ["bearer", "api_key"] },
      "readiness": true
    },
    {
      "id": "token",
      "label": "Artifactory token",
      "type": "string",
      "storage": "secret",
      "required": true,
      "help": "Write-only JFrog access or reference token.",
      "validation": { "min_length": 1, "max_length": 4096 },
      "readiness": true
    },
    {
      "id": "client_cert_path",
      "label": "Client certificate (PEM)",
      "type": "string",
      "storage": "setting",
      "help": "Required when the instance is behind Cloudflare Access mTLS. Path to the client certificate PEM file.",
      "validation": { "format": "path", "max_length": 4096 },
      "readiness": true
    },
    {
      "id": "client_key_path",
      "label": "Client private key (PEM)",
      "type": "string",
      "storage": "setting",
      "help": "Path to the private key for the client certificate. Set together with the certificate.",
      "validation": { "format": "path", "max_length": 4096 },
      "readiness": true
    },
    {
      "id": "deploy_root",
      "label": "Deploy source root",
      "type": "string",
      "storage": "setting",
      "help": "When set, artefact uploads may only read files under this directory. Leave empty to allow any absolute path (the approval prompt still shows the exact file).",
      "advanced": true,
      "validation": { "format": "path", "max_length": 4096 }
    },
    {
      "id": "max_deploy_megabytes",
      "label": "Maximum upload size (MB)",
      "type": "integer",
      "storage": "setting",
      "default": 2048,
      "advanced": true,
      "validation": { "minimum": 1, "maximum": 16384 }
    },
    {
      "id": "request_timeout_seconds",
      "label": "Request timeout (seconds)",
      "type": "integer",
      "storage": "setting",
      "default": 60,
      "help": "Hard deadline for each bounded Artifactory request. Higher than the other connectors because artefact operations move real bytes.",
      "advanced": true,
      "validation": { "minimum": 1, "maximum": 600 }
    },
    {
      "id": "default_max_results",
      "label": "Default maximum results",
      "type": "integer",
      "storage": "setting",
      "default": 25,
      "advanced": true,
      "validation": { "minimum": 1, "maximum": 100 }
    }
  ]
}
```

- [ ] **Step 5: Register in the capability set and shared-code sync**

In `sets/ericsson.json`, add to `plugins[]`:

```json
    {"path": "plugins/ericsson-arm", "id": "ericsson-arm", "enabled": false}
```

In `scripts/sync_shared.py` and `tests/test_shared_sync.py`:

```python
CONSUMERS = ["ericsson-jira", "ericsson-gitlab", "ericsson-confluence", "ericsson-arm"]
```

Then: `. .venv/bin/activate && python scripts/sync_shared.py`

- [ ] **Step 6: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_manifest.py tests/test_shared_sync.py -q`
Expected: PASS (12 tests)

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-arm/ sets/ericsson.json scripts/sync_shared.py tests/
git commit -m "feat: scaffold ericsson-arm connector, disabled by default"
```

---

### Task 2: Raw request bodies in the shared transport

**Files:**
- Modify: `shared/ericsson_common/transport.py`
- Modify: `shared/ericsson_common/client.py`
- Test: `tests/test_shared_transport.py`, `tests/test_shared_client.py`

**Interfaces:**
- Consumes: `Response`, `HttpxTransport`, `BoundedClient` from Plan 2 Tasks 3–4
- Produces:
  - `HttpxTransport.request(method, path, *, params, json_body, timeout_seconds, content=None, extra_headers=None) -> Response`
  - `BoundedClient.request(method, path, *, params=None, json_body=None, deadline=None, raise_on_status=True, content=None, extra_headers=None) -> Response`

Two ARM operations cannot be expressed with `json_body`. AQL posts a query string with `Content-Type: text/plain` — httpx's `json=` would force `application/json` and Artifactory answers a 400. Deploy sends artefact bytes with checksum headers. Both need a raw body and a per-request header override.

This is additive and backward-compatible: every existing call site passes neither parameter and is unaffected. **mTLS needs no change here** — `HttpxTransport` already accepts `tls_context` and forwards it to httpx's `verify=`, which accepts an `ssl.SSLContext` in httpx 0.27+ (verified against the installed 0.28.1).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_shared_transport.py`:

```python
class TestRawBodies:
    def test_content_is_sent_verbatim(self):
        seen = {}

        def handler(request):
            seen["body"] = request.content
            seen["content_type"] = request.headers.get("content-type")
            return httpx.Response(200, json={"ok": True})

        _transport(handler).request(
            "POST", "/api/v4/projects", params=None, json_body=None,
            timeout_seconds=5, content=b'items.find({"repo":"x"})',
            extra_headers={"Content-Type": "text/plain"},
        )
        assert seen["body"] == b'items.find({"repo":"x"})'
        assert seen["content_type"] == "text/plain"

    def test_extra_headers_do_not_leak_into_later_requests(self):
        """Per-request headers must not mutate the client's shared header
        map, or one AQL call would make every later call text/plain."""
        seen = []

        def handler(request):
            seen.append(request.headers.get("content-type"))
            return httpx.Response(200, json={})

        transport = _transport(handler)
        transport.request(
            "POST", "/api/v4/projects", params=None, json_body=None,
            timeout_seconds=5, content=b"x",
            extra_headers={"Content-Type": "text/plain"},
        )
        transport.request(
            "GET", "/api/v4/projects", params=None, json_body=None,
            timeout_seconds=5,
        )
        assert seen[0] == "text/plain"
        assert seen[1] != "text/plain"

    def test_content_and_json_body_together_are_rejected(self):
        def handler(request):  # pragma: no cover - must never be reached
            raise AssertionError("request should not have been issued")

        with pytest.raises(ConnectorError) as excinfo:
            _transport(handler).request(
                "PUT", "/api/v4/projects", params=None, json_body={"a": 1},
                timeout_seconds=5, content=b"bytes",
            )
        assert excinfo.value.category == "invalid_input"

    def test_a_file_object_streams_without_being_read_into_memory(self, tmp_path):
        source = tmp_path / "artifact.bin"
        source.write_bytes(b"z" * 4096)
        seen = {}

        def handler(request):
            seen["body"] = request.content
            return httpx.Response(201, json={"ok": True})

        with source.open("rb") as handle:
            _transport(handler).request(
                "PUT", "/api/v4/projects", params=None, json_body=None,
                timeout_seconds=5, content=handle,
            )
        assert seen["body"] == b"z" * 4096
```

Append to `tests/test_shared_client.py`:

```python
class TestRawBodyPassthrough:
    def test_content_and_headers_reach_the_transport(self):
        transport = FakeTransport([Response(200, {}, b"{}")])
        client = BoundedClient(transport, service="arm")
        client.request(
            "POST", "/artifactory/api/search/aql",
            content=b"items.find({})",
            extra_headers={"Content-Type": "text/plain"},
        )
        call = transport.calls[0]
        assert call["content"] == b"items.find({})"
        assert call["extra_headers"] == {"Content-Type": "text/plain"}

    def test_a_raw_body_write_is_still_not_retried(self):
        """Method-awareness in the retry decision must not be bypassed just
        because the body is bytes rather than JSON."""
        transport = FakeTransport([Response(503, {}, b""), Response(200, {}, b"{}")])
        client = BoundedClient(transport, service="arm")
        with pytest.raises(ConnectorError) as excinfo:
            client.request("PUT", "/artifactory/repo/a.tgz", content=b"bytes")
        assert excinfo.value.category == "write_ambiguous"
        assert len(transport.calls) == 1
```

`FakeTransport` in `tests/test_shared_client.py` records keyword arguments; extend its `request` signature to accept and record `content` and `extra_headers`:

```python
    def request(self, method, path, *, params, json_body, timeout_seconds,
                content=None, extra_headers=None):
        self.calls.append({
            "method": method, "path": path, "params": params,
            "json_body": json_body, "content": content,
            "extra_headers": extra_headers,
        })
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_transport.py tests/test_shared_client.py -q`
Expected: FAIL — `TypeError: request() got an unexpected keyword argument 'content'`

- [ ] **Step 3: Amend the transport**

In `shared/ericsson_common/transport.py`, replace `HttpxTransport.request`:

```python
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None,
        json_body: Any | None,
        timeout_seconds: float,
        content: Any | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Response:
        """Issue one bounded request.

        ``content`` carries a raw body -- bytes, or any file-like object
        httpx can stream -- for the cases JSON cannot express: Artifactory's
        AQL endpoint wants text/plain, and artefact upload wants the file.
        ``extra_headers`` overrides the client's headers for this request
        only; passing them to httpx per-call rather than mutating
        ``self._client.headers`` is what stops one text/plain POST from
        making every later request text/plain.
        """
        self._validate_path(path)
        if content is not None and json_body is not None:
            raise ConnectorError(
                "invalid_input",
                detail="content and json_body are mutually exclusive",
            )
        timeout = httpx.Timeout(
            connect=min(self._connect_timeout_seconds, timeout_seconds),
            read=timeout_seconds,
            write=timeout_seconds,
            pool=min(self._connect_timeout_seconds, timeout_seconds),
        )
        body = bytearray()
        with self._client.stream(
            method,
            path,
            params=params,
            json=json_body,
            content=content,
            headers=dict(extra_headers) if extra_headers else None,
            timeout=timeout,
        ) as response:
            for chunk in response.iter_bytes():
                if len(body) + len(chunk) > self._max_response_bytes:
                    raise ConnectorError("capacity")
                body.extend(chunk)
            headers = dict(response.headers)
            status = response.status_code
        return Response(status=status, headers=headers, body=bytes(body))
```

- [ ] **Step 4: Amend the bounded client**

In `shared/ericsson_common/client.py`, add the two parameters to `BoundedClient.request` and forward them to every `self._transport.request(...)` call inside the retry loop:

```python
    def request(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        deadline: float | None = None,
        raise_on_status: bool = True,
        content: Any | None = None,
        extra_headers: Mapping[str, str] | None = None,
    ) -> Response:
```

and at the transport call site inside the loop:

```python
            response = self._transport.request(
                method,
                path,
                params=params,
                json_body=json_body,
                timeout_seconds=attempt_timeout,
                content=content,
                extra_headers=extra_headers,
            )
```

The retry decision is unchanged and stays method-aware: a non-idempotent method still refuses to replay, which is what `test_a_raw_body_write_is_still_not_retried` pins. This matters more with a raw body than with JSON — a file-like `content` has already been consumed by the first attempt and could not be replayed correctly even if the policy allowed it.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_transport.py tests/test_shared_client.py -q`
Expected: PASS

- [ ] **Step 6: Confirm no existing connector regressed**

```bash
. .venv/bin/activate && python scripts/sync_shared.py && pytest -q
```
Expected: PASS. Every existing call site omits both new parameters, so this is a pure addition — but the whole suite is what proves it.

- [ ] **Step 7: Commit**

```bash
git add shared/ericsson_common/ tests/test_shared_transport.py tests/test_shared_client.py plugins/*/_common/
git commit -m "feat: support raw request bodies and per-request headers in shared transport"
```

---

### Task 3: `auth.py` with mTLS and certificate pre-flight

**Files:**
- Create: `plugins/ericsson-arm/auth.py`
- Test: `tests/test_arm_auth.py` (create)

**Interfaces:**
- Produces:
  - `authentication_from_configuration(configuration, *, now=None) -> ArmAuth`
  - `certificate_not_after(cert_path: str) -> float`
  - `API_ROOT: str` (`"/artifactory/"`)

This is the task that fixes the observed failure. Against the live instance, an expired client certificate produces a `302` to `cloudflareaccess.com` carrying `auth_status: FAILED:FAILED:certificate has expired`. The three shell scripts this connector supersedes each check only `[ -f "$CERT_PATH" ]` — existence, not validity — and so report that condition as "No files found", "Failed to parse response as JSON", and "AQL query failed" respectively. Reading `notAfter` at configuration time turns it into one accurate sentence.

`ssl._ssl._test_decode_cert` is a private stdlib entry point. It is used deliberately: it is the only way to read a PEM's validity window without adding `cryptography` as a dependency, and it is verified working on the installed CPython 3.13. The call is isolated in one function with a broad `except` so that a CPython change degrades to "cannot read the certificate" rather than breaking the connector.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arm_auth.py`:

```python
"""Configuration must resolve to one validated identity, header and TLS context."""

import ssl
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from auth import (  # noqa: E402
    API_ROOT,
    authentication_from_configuration,
    certificate_not_after,
)
from models import ArmError  # noqa: E402


def _write_certificate(directory: Path, *, days: int) -> tuple[Path, Path]:
    """Generate a throwaway self-signed cert/key pair with openssl.

    Real files rather than fixtures: the code under test reads a PEM from
    disk and builds a real SSLContext, and a fake would test neither.
    """
    cert = directory / "client.pem"
    key = directory / "client-key.pem"
    subprocess.run(
        [
            "openssl", "req", "-x509", "-newkey", "rsa:2048", "-nodes",
            "-keyout", str(key), "-out", str(cert),
            "-days", str(days), "-subj", "/CN=test-endpoint",
        ],
        check=True, capture_output=True,
    )
    return cert, key


@pytest.fixture
def certificate(tmp_path):
    return _write_certificate(tmp_path, days=30)


@pytest.fixture
def expired_certificate(tmp_path):
    """Expiry is tested by moving the clock, not by minting a past-dated
    certificate: openssl cannot backdate notAfter portably, and
    authentication_from_configuration takes `now` precisely so the
    expiry branch is reachable without one."""
    return _write_certificate(tmp_path, days=1)


class FakeConfig:
    def __init__(self, settings, secrets):
        self._settings = settings
        self._secrets = secrets

    def setting(self, field_id):
        if field_id not in self._settings:
            raise KeyError(field_id)
        return self._settings[field_id]

    def secret(self, field_id):
        if field_id not in self._secrets:
            raise KeyError(field_id)
        return self._secrets[field_id]


def _config(**overrides):
    settings = {"base_url": "https://artifactory.test", "auth_mode": "bearer"}
    settings.update(overrides.pop("settings", {}))
    secrets = {"token": "token-value"}
    secrets.update(overrides.pop("secrets", {}))
    return FakeConfig(settings, secrets)


class TestAuthHeader:
    def test_bearer_mode_builds_an_authorization_header(self):
        auth = authentication_from_configuration(_config())
        assert auth.auth_header_name == "Authorization"
        assert auth.auth_header_value == "Bearer token-value"
        assert auth.token == "token-value"

    def test_api_key_mode_builds_the_legacy_jfrog_header(self):
        """The OSCAR shell scripts use this header. The token value is the
        same either way -- a JFrog reference token satisfies both."""
        auth = authentication_from_configuration(
            _config(settings={"auth_mode": "api_key"})
        )
        assert auth.auth_header_name == "X-JFrog-Art-Api"
        assert auth.auth_header_value == "token-value"

    def test_unknown_auth_mode_is_rejected(self):
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={"auth_mode": "basic"})
            )
        assert excinfo.value.category == "invalid_configuration"

    def test_missing_token_is_rejected(self):
        with pytest.raises(ArmError):
            authentication_from_configuration(_config(secrets={"token": ""}))


class TestOrigin:
    def test_scheme_is_added_when_missing(self):
        auth = authentication_from_configuration(
            _config(settings={"base_url": "artifactory.test"})
        )
        assert auth.origin == "https://artifactory.test"

    def test_api_root_is_the_artifactory_mount(self):
        """Xray would add a second root. Leaving it out is what keeps the
        transport allow-list a single exact prefix."""
        assert API_ROOT == "/artifactory/"
        assert authentication_from_configuration(_config()).api_root == "/artifactory/"

    @pytest.mark.parametrize(
        "bad",
        [
            "https://user:pw@artifactory.test",
            "https://artifactory.test?q=1",
            "https://artifactory.test#frag",
            "ftp://artifactory.test",
            "https://artifactory .test",
            "https://artifactory.test\\evil",
            "https://artifactory.test/artifactory",
        ],
    )
    def test_hostile_base_urls_are_rejected(self, bad):
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(_config(settings={"base_url": bad}))
        assert excinfo.value.category == "invalid_configuration"

    def test_a_path_segment_is_rejected(self):
        """Unlike Confluence, no path is ever legitimate here: the REST mount
        is always /artifactory on the origin."""
        with pytest.raises(ArmError):
            authentication_from_configuration(
                _config(settings={"base_url": "https://artifactory.test/foo"})
            )


class TestClientCertificate:
    def test_no_certificate_configured_means_no_tls_context(self):
        auth = authentication_from_configuration(_config())
        assert auth.tls_context is None
        assert auth.certificate_not_after is None

    def test_certificate_builds_a_tls_context(self, certificate):
        cert, key = certificate
        auth = authentication_from_configuration(
            _config(settings={
                "client_cert_path": str(cert), "client_key_path": str(key),
            })
        )
        assert isinstance(auth.tls_context, ssl.SSLContext)
        assert auth.certificate_not_after is not None

    def test_certificate_without_a_key_is_rejected(self, certificate):
        cert, _key = certificate
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={"client_cert_path": str(cert)})
            )
        assert excinfo.value.category == "invalid_configuration"

    def test_missing_certificate_file_is_certificate_invalid(self, tmp_path):
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(tmp_path / "absent.pem"),
                    "client_key_path": str(tmp_path / "absent-key.pem"),
                })
            )
        assert excinfo.value.category == "certificate_invalid"

    def test_expired_certificate_is_refused_before_any_request(self, expired_certificate):
        """This is the whole point of the task. The live failure mode was a
        302 to cloudflareaccess.com carrying 'certificate has expired'; the
        shell scripts reported it as 'No files found'."""
        cert, key = expired_certificate
        not_after = certificate_not_after(str(cert))
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(cert), "client_key_path": str(key),
                }),
                now=not_after + 1.0,
            )
        assert excinfo.value.category == "certificate_invalid"
        assert "expired" in (excinfo.value.remediation or "")

    def test_expiry_remediation_names_the_actual_date(self, expired_certificate):
        """The date is the whole point: 'your certificate expired' sends an
        operator looking, 'expired on 2026-03-21' ends the investigation."""
        import time

        cert, key = expired_certificate
        not_after = certificate_not_after(str(cert))
        expected = time.strftime("%Y-%m-%d", time.gmtime(not_after))
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(cert), "client_key_path": str(key),
                }),
                now=not_after + 1.0,
            )
        assert expected in (excinfo.value.remediation or "")

    def test_a_certificate_expiring_soon_is_still_accepted(self, certificate):
        """Warn-vs-fail matters: refusing a still-valid certificate would
        break a working build the day before renewal was due."""
        cert, key = certificate
        auth = authentication_from_configuration(
            _config(settings={
                "client_cert_path": str(cert), "client_key_path": str(key),
            }),
            now=certificate_not_after(str(cert)) - 60.0,
        )
        assert auth.tls_context is not None

    def test_unreadable_certificate_is_certificate_invalid(self, tmp_path):
        junk = tmp_path / "junk.pem"
        junk.write_text("not a certificate")
        key = tmp_path / "junk-key.pem"
        key.write_text("not a key")
        with pytest.raises(ArmError) as excinfo:
            authentication_from_configuration(
                _config(settings={
                    "client_cert_path": str(junk), "client_key_path": str(key),
                })
            )
        assert excinfo.value.category == "certificate_invalid"


class TestBounds:
    def test_defaults_apply_when_settings_absent(self):
        auth = authentication_from_configuration(_config())
        assert auth.request_timeout_seconds == 60
        assert auth.default_max_results == 25
        assert auth.max_deploy_bytes == 2048 * 1024 * 1024
        assert auth.deploy_root is None

    def test_bool_is_not_accepted_as_an_integer(self):
        with pytest.raises(ArmError):
            authentication_from_configuration(
                _config(settings={"default_max_results": True})
            )

    def test_deploy_megabytes_convert_to_bytes(self):
        auth = authentication_from_configuration(
            _config(settings={"max_deploy_megabytes": 10})
        )
        assert auth.max_deploy_bytes == 10 * 1024 * 1024

    def test_deploy_root_is_normalised(self, tmp_path):
        auth = authentication_from_configuration(
            _config(settings={"deploy_root": str(tmp_path) + "/"})
        )
        assert auth.deploy_root == str(tmp_path.resolve())
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_auth.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'auth'`

- [ ] **Step 3: Implement**

Create `plugins/ericsson-arm/auth.py`:

```python
"""Resolve Hermes' opaque per-profile configuration into safe Artifactory auth.

Origin validation is ported from ericsson-jira/auth.py. The mTLS and
certificate-expiry handling is new and exists because of an observed
failure: this instance sits behind Cloudflare Access, which authenticates
the caller by client certificate. When that certificate expires, Access
returns 302 to cloudflareaccess.com with
`auth_status: FAILED:FAILED:certificate has expired`, and every consumer
that does not check the redirect reports something unrelated instead --
"No files found", "Failed to parse response as JSON", "AQL query failed".
Reading notAfter here turns that into one accurate sentence.
"""

from __future__ import annotations

import os
import ssl
import time
from urllib.parse import urlsplit

if __package__:
    from .models import ArmAuth, ArmError
else:
    from models import ArmAuth, ArmError

# Every path this connector issues lives under this mount. Xray would add
# /xray/; it is out of scope, which is what lets the transport keep one
# exact allow-listed prefix instead of a widened one.
API_ROOT = "/artifactory/"

_MAX_ORIGIN = 2048
_MAX_SECRET = 4096
_MAX_PATH = 4096

_AUTH_HEADERS = {
    "bearer": "Authorization",
    "api_key": "X-JFrog-Art-Api",
}


def _setting(configuration, field_id: str, default):
    try:
        value = configuration.setting(field_id)
    except Exception:
        return default
    return default if value is None else value


def _secret(configuration, field_id: str) -> str:
    try:
        value = configuration.secret(field_id)
    except Exception:
        return ""
    if value is None:
        return ""
    if not isinstance(value, str) or len(value) > _MAX_SECRET:
        raise ArmError("invalid_configuration")
    return value.strip()


def _origin(value) -> str:
    """Validate scheme + host and nothing else.

    No path is ever legitimate: the REST mount is always /artifactory on
    the origin, so a path here means the operator pasted a deep link.
    """
    if not isinstance(value, str):
        raise ArmError("invalid_configuration")
    value = value.strip().rstrip("/")
    if (
        not value
        or len(value) > _MAX_ORIGIN
        or "\\" in value
        or any(character.isspace() for character in value)
    ):
        raise ArmError("invalid_configuration")
    if "://" not in value:
        value = f"https://{value}"
    try:
        parsed = urlsplit(value)
        port = parsed.port
    except ValueError:
        raise ArmError("invalid_configuration") from None
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or parsed.path.rstrip("/")
        or (port is not None and not 0 < port < 65536)
    ):
        raise ArmError("invalid_configuration")
    return value


def _bounded_integer(value, minimum: int, maximum: int) -> int:
    # type(...) is not int, not isinstance: bool subclasses int, so True
    # would otherwise satisfy a range check.
    if type(value) is not int or not minimum <= value <= maximum:
        raise ArmError("invalid_configuration")
    return value


def _path_setting(configuration, field_id: str) -> str | None:
    value = _setting(configuration, field_id, None)
    if value is None or value == "":
        return None
    if not isinstance(value, str) or len(value) > _MAX_PATH:
        raise ArmError("invalid_configuration")
    return value


def certificate_not_after(cert_path: str) -> float:
    """Read a PEM certificate's notAfter as Unix seconds.

    ssl._ssl._test_decode_cert is a private entry point, used deliberately:
    it is the only way to read a certificate's validity window without
    adding `cryptography` as a dependency. The broad except means a CPython
    change degrades to "cannot read the certificate" rather than breaking
    the connector outright.
    """
    try:
        decoded = ssl._ssl._test_decode_cert(cert_path)  # noqa: SLF001
        return float(ssl.cert_time_to_seconds(decoded["notAfter"]))
    except Exception:
        raise ArmError(
            "certificate_invalid",
            remediation=(
                f"Could not read a certificate from {cert_path}. Check that "
                f"it is a PEM-encoded X.509 certificate."
            ),
        ) from None


def _tls_context(
    cert_path: str | None, key_path: str | None, now: float
) -> tuple[object | None, float | None]:
    """Build the client-certificate SSL context, or (None, None).

    httpx takes this via `verify=`; a client certificate lives inside the
    context rather than in a separate `cert=` argument in httpx 0.28+.
    """
    if cert_path is None and key_path is None:
        return None, None
    if cert_path is None or key_path is None:
        raise ArmError(
            "invalid_configuration",
            remediation=(
                "Set both the client certificate and the client private key, "
                "or neither."
            ),
        )
    for path in (cert_path, key_path):
        if not os.path.isfile(path):
            raise ArmError(
                "certificate_invalid",
                remediation=f"No file at {path}.",
            )

    not_after = certificate_not_after(cert_path)
    if now >= not_after:
        expired_on = time.strftime("%Y-%m-%d", time.gmtime(not_after))
        raise ArmError(
            "certificate_invalid",
            remediation=(
                f"The client certificate expired on {expired_on}. Renew it "
                f"and update the certificate and key paths in this profile. "
                f"Until then every request is refused at the edge before it "
                f"reaches Artifactory."
            ),
        )

    context = ssl.create_default_context()
    try:
        context.load_cert_chain(certfile=cert_path, keyfile=key_path)
    except (ssl.SSLError, OSError):
        raise ArmError(
            "certificate_invalid",
            remediation=(
                "The certificate and key could not be loaded together. Check "
                "that the key matches the certificate and is not passphrase "
                "protected."
            ),
        ) from None
    return context, not_after


def authentication_from_configuration(configuration, *, now=None) -> ArmAuth:
    """Build one redacted, validated runtime identity for an Artifactory call."""
    current_time = time.time() if now is None else float(now)

    origin = _origin(_setting(configuration, "base_url", None))

    auth_mode = _setting(configuration, "auth_mode", "bearer")
    if auth_mode not in _AUTH_HEADERS:
        raise ArmError(
            "invalid_configuration",
            remediation="Authentication header must be 'bearer' or 'api_key'.",
        )

    token = _secret(configuration, "token")
    if not token:
        raise ArmError(
            "invalid_configuration",
            remediation="Set the Artifactory token in this profile.",
        )

    context, not_after = _tls_context(
        _path_setting(configuration, "client_cert_path"),
        _path_setting(configuration, "client_key_path"),
        current_time,
    )

    deploy_root = _path_setting(configuration, "deploy_root")
    if deploy_root is not None:
        deploy_root = os.path.realpath(deploy_root)

    return ArmAuth(
        origin=origin,
        api_root=API_ROOT,
        auth_header_name=_AUTH_HEADERS[auth_mode],
        auth_header_value=(
            f"Bearer {token}" if auth_mode == "bearer" else token
        ),
        token=token,
        tls_context=context,
        certificate_not_after=not_after,
        request_timeout_seconds=_bounded_integer(
            _setting(configuration, "request_timeout_seconds", 60), 1, 600
        ),
        default_max_results=_bounded_integer(
            _setting(configuration, "default_max_results", 25), 1, 100
        ),
        max_deploy_bytes=_bounded_integer(
            _setting(configuration, "max_deploy_megabytes", 2048), 1, 16384
        ) * 1024 * 1024,
        deploy_root=deploy_root,
    )


ArmAuth.from_configuration = staticmethod(  # type: ignore[attr-defined]
    authentication_from_configuration
)
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_auth.py -q`
Expected: PASS (24 tests)

If `openssl` is unavailable on the build machine, the four certificate tests will error at fixture setup rather than fail. `openssl` ships with macOS and every mainstream Linux; if a target environment lacks it, mark those four with `pytest.mark.skipif(shutil.which("openssl") is None, ...)` rather than replacing the real certificates with fakes — a fake PEM would exercise neither `_test_decode_cert` nor `load_cert_chain`, which are the two things under test.

- [ ] **Step 5: Commit**

```bash
git add plugins/ericsson-arm/auth.py tests/test_arm_auth.py
git commit -m "feat: add ARM auth with mTLS and certificate expiry pre-flight"
```

---

### Task 4: `client.py` with Cloudflare Access classification

**Files:**
- Create: `plugins/ericsson-arm/client.py`
- Test: `tests/test_arm_client.py` (create)

**Interfaces:**
- Produces: `ArmClient(auth, *, transport=None, max_retries=2, cancel_check=None, clock=time.monotonic, sleep=time.sleep, max_response_bytes=8*1024*1024)` with
  - `.send(method, path, *, params=None, json_body=None, content=None, extra_headers=None, deadline=None, classify=True) -> Response`
  - `.request_json(method, path, *, params=None, json_body=None, deadline=None) -> Any`
  - `.get_json(path, *, params=None, deadline=None) -> Any`
  - `.post_text(path, text, *, deadline=None) -> Any`
  - `.operation_deadline()`, `.close()`, `__enter__`/`__exit__`, `.path_prefix`, `.auth`

Headers from the binary (`out/func-strings.txt`, `arm.(*Client).doRequest`): the auth header, `Accept: application/json`, and `Content-Type: application/json` on bodied requests.

The client calls `BoundedClient.request(..., raise_on_status=False)` and classifies statuses itself. That is deliberate: `category_for_status` has no mapping for a 3xx, and a `302` is exactly what this instance returns when Cloudflare Access refuses the client certificate. Letting the shared mapper see it would produce `transient` — an infinitely retryable-looking answer to a condition that will never resolve on its own. `raise_on_status=False` is a documented `BoundedClient` affordance and still applies retry, deadline, cancellation and the circuit breaker.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arm_client.py`:

```python
"""Artifactory client rides the shared transport policy and classifies the edge."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from _common.errors import ConnectorError  # noqa: E402
from _common.transport import Response  # noqa: E402
from client import ArmClient  # noqa: E402
from models import ArmAuth, ArmError  # noqa: E402

ACCESS_REDIRECT = Response(
    302,
    {
        "location": (
            "https://ericssondevops.cloudflareaccess.com/cdn-cgi/access/login/"
            "artifactory.test?kid=abc"
        ),
        "www-authenticate": 'Cloudflare-Access resource_metadata="https://x/.well-known"',
    },
    b"<html>redirecting</html>",
)


class FakeTransport:
    def __init__(self, script):
        self.script = list(script)
        self.calls = []

    def request(self, method, path, *, params, json_body, timeout_seconds,
                content=None, extra_headers=None):
        self.calls.append({
            "method": method, "path": path, "params": params,
            "json_body": json_body, "content": content,
            "extra_headers": extra_headers,
        })
        item = self.script.pop(0)
        if isinstance(item, Exception):
            raise item
        return item

    def close(self):
        pass


class FakeClock:
    def __init__(self):
        self.now = 0.0
        self.slept = []

    def __call__(self):
        return self.now

    def sleep(self, seconds):
        self.slept.append(seconds)
        self.now += seconds


def _auth(**overrides):
    values = dict(
        origin="https://artifactory.test",
        api_root="/artifactory/",
        auth_header_name="Authorization",
        auth_header_value="Bearer secret-token-value",
        token="secret-token-value",
        tls_context=None,
        certificate_not_after=None,
        request_timeout_seconds=60,
        default_max_results=25,
        max_deploy_bytes=1024,
        deploy_root=None,
    )
    values.update(overrides)
    return ArmAuth(**values)


def _client(script, **overrides):
    clock = FakeClock()
    return (
        ArmClient(_auth(**overrides), transport=FakeTransport(script),
                  clock=clock, sleep=clock.sleep),
        clock,
    )


class TestClient:
    def test_decodes_json(self):
        client, _clock = _client([Response(200, {}, b'{"repo":"generic"}')])
        assert client.get_json("/artifactory/api/repositories") == {"repo": "generic"}

    def test_retry_after_is_honoured(self):
        client, clock = _client(
            [Response(429, {"Retry-After": "2"}, b""), Response(200, {}, b"{}")]
        )
        client.get_json("/artifactory/api/repositories")
        assert clock.slept == [2.0]

    def test_writes_are_not_retried(self):
        client, _clock = _client([Response(503, {}, b"")])
        with pytest.raises(ArmError) as excinfo:
            client.request_json("PUT", "/artifactory/generic/a.tgz", json_body={})
        assert excinfo.value.category == "write_ambiguous"

    def test_shared_error_type_never_escapes(self):
        client, _clock = _client([Response(401, {}, b"")])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert not isinstance(excinfo.value, ConnectorError)
        assert excinfo.value.remediation

    def test_empty_body_is_none_not_an_error(self):
        """DELETE returns 204 with no body."""
        client, _clock = _client([Response(204, {}, b"")])
        assert client.request_json("DELETE", "/artifactory/generic/a.tgz") is None

    def test_path_outside_the_api_root_is_rejected(self):
        client, _clock = _client([])
        with pytest.raises(ArmError):
            client.get_json("/xray/api/v1/violations")

    def test_the_auth_header_is_whatever_auth_resolved(self):
        client, _clock = _client(
            [Response(200, {}, b"{}")],
            auth_header_name="X-JFrog-Art-Api",
            auth_header_value="raw-token",
        )
        assert client.headers["X-JFrog-Art-Api"] == "raw-token"
        assert "Authorization" not in client.headers


class TestCloudflareAccess:
    def test_access_redirect_is_its_own_category(self):
        """The live failure mode. Classifying this as `authentication` would
        send an operator to rotate the Artifactory token, when the credential
        that actually failed is the mTLS client certificate."""
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/system/ping")
        assert excinfo.value.category == "edge_authentication"

    def test_access_remediation_points_at_the_certificate(self):
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/system/ping")
        assert "certificate" in (excinfo.value.remediation or "").lower()

    def test_detected_by_www_authenticate_alone(self):
        client, _clock = _client([
            Response(302, {"www-authenticate": "Cloudflare-Access"}, b"")
        ])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "edge_authentication"

    def test_detected_by_location_alone(self):
        client, _clock = _client([
            Response(302, {"location": "https://x.cloudflareaccess.com/login"}, b"")
        ])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "edge_authentication"

    def test_an_unrelated_redirect_is_not_an_access_failure(self):
        client, _clock = _client([
            Response(302, {"location": "https://artifactory.test/elsewhere"}, b"")
        ])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "invalid_remote_data"

    def test_access_failure_is_not_retried(self):
        """An expired certificate will not fix itself. Retrying wastes the
        deadline and hides the cause behind a timeout."""
        client, _clock = _client([ACCESS_REDIRECT])
        with pytest.raises(ArmError):
            client.get_json("/artifactory/api/repositories")
        assert len(client._transport.calls) == 1


class TestBodies:
    def test_post_text_sends_text_plain(self):
        """AQL is a DSL, not JSON. Sending application/json here is a 400,
        and it is the classic Artifactory integration mistake."""
        client, _clock = _client([Response(200, {}, b'{"results":[]}')])
        client.post_text("/artifactory/api/search/aql", 'items.find({})')
        call = client._transport.calls[0]
        assert call["content"] == b'items.find({})'
        assert call["extra_headers"]["Content-Type"] == "text/plain"
        assert call["json_body"] is None

    def test_html_body_raises_invalid_remote_data(self):
        """An HTML body where JSON was expected means an interstitial --
        the same signal super-cli detects for Jira."""
        client, _clock = _client([Response(200, {}, b"<html>login</html>")])
        with pytest.raises(ArmError) as excinfo:
            client.get_json("/artifactory/api/repositories")
        assert excinfo.value.category == "invalid_remote_data"

    def test_send_can_return_a_non_2xx_without_raising(self):
        """Deploy needs this: a failed checksum-deploy probe is a normal,
        expected outcome that must fall through to a full upload."""
        client, _clock = _client([Response(404, {}, b"")])
        response = client.send(
            "PUT", "/artifactory/generic/a.tgz", content=b"", classify=False
        )
        assert response.status == 404
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_client.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'client'`

- [ ] **Step 3: Implement**

Create `plugins/ericsson-arm/client.py`:

```python
"""Bounded Artifactory REST transport on the shared connector client."""

from __future__ import annotations

import json
import time
from contextlib import contextmanager
from typing import Any, Callable, Mapping

if __package__:
    from ._common.client import BoundedClient
    from ._common.errors import ConnectorError, category_for_status, remediation_for
    from ._common.transport import HttpxTransport, Response
    from .models import ArmAuth, ArmError
else:
    from _common.client import BoundedClient
    from _common.errors import ConnectorError, category_for_status, remediation_for
    from _common.transport import HttpxTransport, Response
    from models import ArmAuth, ArmError

# Cloudflare Access announces itself two ways. Either alone is sufficient:
# the WWW-Authenticate scheme is the documented signal, and the redirect
# host is what an older Access configuration sends.
_ACCESS_SCHEME = "cloudflare-access"
_ACCESS_HOST = "cloudflareaccess.com"

_ACCESS_REMEDIATION = (
    "Access to this Artifactory was refused at the edge, before the request "
    "reached Artifactory. This is normally an expired or missing mTLS client "
    "certificate rather than a problem with the Artifactory token. Check the "
    "client certificate and key configured for this profile."
)


@contextmanager
def _as_arm_error():
    """Translate shared errors at the connector boundary.

    ConnectorError.detail may quote caller input; ArmError guarantees no
    remote or secret text reaches the host.
    """
    try:
        yield
    except ConnectorError as exc:
        raise ArmError(exc.category, remediation=exc.remediation) from None


class ArmClient:
    def __init__(
        self,
        authentication: ArmAuth,
        *,
        transport=None,
        max_retries: int = 2,
        cancel_check: Callable[[], bool] | None = None,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        # Larger than the other connectors: a storage listing of a busy
        # folder is legitimately big. Still finite -- artefact bytes never
        # come back through this client, only metadata.
        max_response_bytes: int = 8 * 1024 * 1024,
    ) -> None:
        self.auth = authentication
        self.path_prefix = authentication.api_root
        self.headers = {
            authentication.auth_header_name: authentication.auth_header_value,
            "Accept": "application/json",
        }
        if transport is None:
            transport = HttpxTransport(
                base_url=authentication.origin,
                headers=self.headers,
                path_prefix=self.path_prefix,
                max_response_bytes=max_response_bytes,
                connect_timeout_seconds=5.0,
                tls_context=authentication.tls_context,
            )
        self._transport = transport
        self._client = BoundedClient(
            transport,
            service="arm",
            max_retries=max_retries,
            total_timeout_seconds=float(authentication.request_timeout_seconds),
            request_timeout_seconds=float(authentication.request_timeout_seconds),
            cancel_check=cancel_check,
            clock=clock,
            sleep=sleep,
        )

    def __repr__(self) -> str:
        return f"ArmClient(origin={self.auth.origin!r})"

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        self.close()

    def close(self) -> None:
        self._client.close()

    def operation_deadline(self) -> float:
        return self._client.operation_deadline()

    def _validate(self, path: str) -> None:
        if not isinstance(path, str) or not path.startswith(self.path_prefix):
            raise ArmError("invalid_input")

    @staticmethod
    def _is_access_challenge(response: Response) -> bool:
        return (
            _ACCESS_SCHEME in response.header("www-authenticate").lower()
            or _ACCESS_HOST in response.header("location").lower()
        )

    def _classify(self, response: Response) -> Response:
        """Raise for a non-2xx, naming the edge separately from the origin."""
        if 200 <= response.status < 300:
            return response
        if self._is_access_challenge(response):
            raise ArmError("edge_authentication", remediation=_ACCESS_REMEDIATION)
        if 300 <= response.status < 400:
            # Redirects are not followed by the transport, so an unexplained
            # one means something answered that is not Artifactory.
            raise ArmError(
                "invalid_remote_data",
                remediation=(
                    "Artifactory redirected the request instead of answering "
                    "it. Check that the base URL names the Artifactory origin."
                ),
            )
        category = category_for_status(response.status)
        raise ArmError(category, remediation=remediation_for(category, "arm"))

    def send(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        content: Any | None = None,
        extra_headers: Mapping[str, str] | None = None,
        deadline: float | None = None,
        classify: bool = True,
    ) -> Response:
        """Issue one request, classifying the response unless asked not to.

        raise_on_status=False on the shared client is deliberate: the shared
        status mapper has no entry for a 3xx, and a 302 is exactly what this
        instance returns when the edge refuses the client certificate.
        Letting it fall through would classify a permanent condition as
        `transient` and invite a retry loop.

        classify=False returns the raw Response. Deploy needs it, because a
        failed checksum-deploy probe is a normal outcome that falls through
        to a full upload rather than an error.
        """
        self._validate(path)
        with _as_arm_error():
            response = self._client.request(
                method,
                path,
                params=params,
                json_body=json_body,
                content=content,
                extra_headers=extra_headers,
                deadline=deadline,
                raise_on_status=False,
            )
        return self._classify(response) if classify else response

    @staticmethod
    def _decode(response: Response) -> Any:
        if not response.body:
            return None
        stripped = response.body.lstrip()[:1]
        if stripped == b"<":
            raise ArmError(
                "invalid_remote_data",
                remediation=(
                    "Artifactory returned HTML where JSON was expected, which "
                    "normally means an authentication interstitial answered "
                    "instead of the API."
                ),
            )
        try:
            return json.loads(response.body)
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            raise ArmError("invalid_remote_data") from None

    def request_json(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        json_body: Any | None = None,
        deadline: float | None = None,
    ) -> Any:
        return self._decode(
            self.send(
                method, path, params=params, json_body=json_body,
                deadline=deadline,
            )
        )

    def get_json(
        self,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        deadline: float | None = None,
    ) -> Any:
        return self.request_json("GET", path, params=params, deadline=deadline)

    def post_text(
        self, path: str, text: str, *, deadline: float | None = None
    ) -> Any:
        """POST a plain-text body.

        AQL is a DSL, not JSON. super-cli's arm.(*Client).AQLSearch sets
        Content-Type: text/plain explicitly for exactly this reason, and
        sending application/json here is a 400.
        """
        return self._decode(
            self.send(
                "POST",
                path,
                content=text.encode("utf-8"),
                extra_headers={"Content-Type": "text/plain"},
                deadline=deadline,
            )
        )
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_client.py -q`
Expected: PASS (17 tests)

- [ ] **Step 5: Commit**

```bash
git add plugins/ericsson-arm/client.py tests/test_arm_client.py
git commit -m "feat: add ARM client with Cloudflare Access classification"
```

---

### Task 5: `arm_list_repositories` and `arm_artifact_info`

**Files:**
- Create: `plugins/ericsson-arm/operations.py`, `plugins/ericsson-arm/tools.py`
- Modify: `plugins/ericsson-arm/__init__.py`, `plugin.yaml`
- Test: `tests/test_arm_reads.py` (create)

**Interfaces:**
- Produces:
  - `ArmOperations(client, *, max_pages=1)` with `.list_repositories(*, repository_type=None, package_type=None, max_results=25)` and `.artifact_info(repo, path, *, max_children=100)`
  - `tools.SCHEMAS`, `tools.check_available`, `tools.operations_from_configuration`, `tools.invoke`

Endpoints (`out/func-strings.txt`):
- `GET /artifactory/api/repositories` with `type` and `packageType` query parameters
- `GET /artifactory/api/storage/{repo}/{path}`

`FileInfo` and `FolderInfo` are **one tool**, not two. They are the same endpoint; the response discriminates — a folder carries `children[]`, a file carries `checksums` and `downloadUri`. Splitting them would force the caller to know the answer before asking the question.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arm_reads.py`:

```python
"""Bounded Artifactory reads."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from models import ArmError  # noqa: E402
from operations import ArmOperations  # noqa: E402


class FakeClient:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []

        class _Auth:
            auth_header_value = "Bearer secret-token-value"
            token = "secret-token-value"
            default_max_results = 25
            max_deploy_bytes = 1024 * 1024
            deploy_root = None

        self.auth = _Auth()
        self.path_prefix = "/artifactory/"

    def _next(self):
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def get_json(self, path, *, params=None, deadline=None):
        self.calls.append(("GET", path, params))
        return self._next()

    def request_json(self, method, path, *, params=None, json_body=None,
                     deadline=None):
        self.calls.append((method, path, json_body))
        return self._next()

    def post_text(self, path, text, *, deadline=None):
        self.calls.append(("POST", path, text))
        return self._next()


REPOSITORIES = [
    {"key": "generic-local", "type": "LOCAL", "packageType": "Generic",
     "description": "Release tarballs", "url": "https://artifactory.test/x"},
    {"key": "docker-remote", "type": "REMOTE", "packageType": "Docker",
     "description": "", "url": "https://artifactory.test/y"},
]

FILE_INFO = {
    "repo": "generic-local",
    "path": "/Infra/images/release-26.2.6/oscar.tar.gz",
    "created": "2026-07-01T10:00:00.000Z",
    "lastModified": "2026-07-01T10:05:00.000Z",
    "size": "5242880",
    "mimeType": "application/gzip",
    "downloadUri": "https://artifactory.test/artifactory/generic-local/Infra/images/release-26.2.6/oscar.tar.gz",
    "checksums": {"md5": "m" * 32, "sha1": "s" * 40, "sha256": "x" * 64},
}

FOLDER_INFO = {
    "repo": "generic-local",
    "path": "/Infra/images",
    "created": "2026-01-01T10:00:00.000Z",
    "children": [
        {"uri": "/release-26.2.5", "folder": True},
        {"uri": "/release-26.2.6", "folder": True},
        {"uri": "/oscar.tar.gz", "folder": False},
    ],
}


class TestListRepositories:
    def test_returns_bounded_identities(self):
        result = ArmOperations(FakeClient([REPOSITORIES])).list_repositories()
        assert [item["key"] for item in result["items"]] == [
            "generic-local", "docker-remote"
        ]
        assert result["items"][0]["package_type"] == "Generic"
        assert result["returned"] == 2

    def test_filters_are_sent_as_query_parameters(self):
        client = FakeClient([REPOSITORIES])
        ArmOperations(client).list_repositories(
            repository_type="local", package_type="generic"
        )
        _method, path, params = client.calls[0]
        assert path == "/artifactory/api/repositories"
        assert params == {"type": "local", "packageType": "generic"}

    def test_filters_are_omitted_when_unset(self):
        client = FakeClient([REPOSITORIES])
        ArmOperations(client).list_repositories()
        assert client.calls[0][2] == {}

    def test_total_is_reported_because_the_endpoint_is_unpaged(self):
        """/api/repositories returns every visible repository in one array,
        so the count is exact rather than a guess."""
        result = ArmOperations(FakeClient([REPOSITORIES])).list_repositories()
        assert result["total"] == 2
        assert result["truncated"] is False

    def test_truncation_is_reported(self):
        many = [dict(REPOSITORIES[0], key=f"repo-{i}") for i in range(40)]
        result = ArmOperations(FakeClient([many])).list_repositories(max_results=10)
        assert result["returned"] == 10
        assert result["total"] == 40
        assert result["truncated"] is True and result["hint"]

    def test_non_list_payload_raises(self):
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(FakeClient([{"error": "x"}])).list_repositories()
        assert excinfo.value.category == "invalid_remote_data"

    def test_bad_max_results_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).list_repositories(max_results=0)
        assert client.calls == []


class TestArtifactInfo:
    def test_file_returns_checksums_and_size(self):
        result = ArmOperations(FakeClient([FILE_INFO])).artifact_info(
            "generic-local", "Infra/images/release-26.2.6/oscar.tar.gz"
        )
        assert result["kind"] == "file"
        assert result["size"] == 5242880
        assert result["checksums"]["sha256"] == "x" * 64
        assert result["download_uri"].endswith("oscar.tar.gz")

    def test_size_is_an_integer_even_though_artifactory_sends_a_string(self):
        """Artifactory returns size as a JSON string. Leaving it a string
        makes every downstream comparison silently wrong."""
        result = ArmOperations(FakeClient([FILE_INFO])).artifact_info(
            "generic-local", "Infra/images/oscar.tar.gz"
        )
        assert isinstance(result["size"], int)

    def test_folder_returns_children(self):
        result = ArmOperations(FakeClient([FOLDER_INFO])).artifact_info(
            "generic-local", "Infra/images"
        )
        assert result["kind"] == "folder"
        assert result["size"] is None
        assert [child["name"] for child in result["children"]] == [
            "release-26.2.5", "release-26.2.6", "oscar.tar.gz"
        ]
        assert result["children"][0]["folder"] is True
        assert result["children"][2]["folder"] is False

    def test_children_are_bounded(self):
        payload = dict(
            FOLDER_INFO,
            children=[{"uri": f"/f{i}", "folder": False} for i in range(300)],
        )
        result = ArmOperations(FakeClient([payload])).artifact_info(
            "generic-local", "Infra/images", max_children=10
        )
        assert len(result["children"]) == 10
        assert result["children_truncated"] is True

    def test_storage_path_is_built_correctly(self):
        client = FakeClient([FILE_INFO])
        ArmOperations(client).artifact_info("generic-local", "Infra/images/a.tgz")
        _method, path, _params = client.calls[0]
        assert path == "/artifactory/api/storage/generic-local/Infra/images/a.tgz"

    def test_a_leading_slash_on_the_path_is_tolerated(self):
        client = FakeClient([FILE_INFO])
        ArmOperations(client).artifact_info("generic-local", "/Infra/images/a.tgz")
        assert client.calls[0][1] == (
            "/artifactory/api/storage/generic-local/Infra/images/a.tgz"
        )

    @pytest.mark.parametrize(
        "bad_repo", ["", "../etc", "a/b", "repo?x=1", "a" * 300]
    )
    def test_hostile_repository_names_rejected_without_a_request(self, bad_repo):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).artifact_info(bad_repo, "a.tgz")
        assert client.calls == []

    @pytest.mark.parametrize(
        "bad_path",
        ["../../etc/passwd", "Infra/../../secrets", "a\x00b", "a" * 5000],
    )
    def test_traversal_paths_rejected_without_a_request(self, bad_path):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).artifact_info("generic-local", bad_path)
        assert client.calls == []

    def test_the_token_is_redacted_from_remote_text(self):
        payload = dict(FILE_INFO, downloadUri="https://x/?t=secret-token-value")
        result = ArmOperations(FakeClient([payload])).artifact_info(
            "generic-local", "a.tgz"
        )
        assert "secret-token-value" not in result["download_uri"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_reads.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'operations'`

- [ ] **Step 3: Implement**

Create `plugins/ericsson-arm/operations.py`:

```python
"""Bounded, redacted Artifactory operations.

The endpoint set follows super-cli's internal/arm. The operational
behaviour -- checksum-first deploy with a fallback, AQL include rules,
folder delete semantics -- follows the OSCAR shell scripts in
oscar_app/oscar/utils, which have production knowledge super-cli does not.
Redaction and approval discipline follow ericsson-jira.
"""

from __future__ import annotations

import re
from typing import Any, Mapping

if __package__:
    from ._common.envelope import result_envelope
    from .models import ArmError
else:
    from _common.envelope import result_envelope
    from models import ArmError

# Artifactory repository keys are conservative by convention; this is the
# intersection of what JFrog allows and what is safe in a URL path segment.
_REPO_KEY = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_MAX_PATH_CHARS = 1024
_MAX_CHILDREN = 1000


def _bounded_string(value: Any, maximum: int) -> str | None:
    if not isinstance(value, str):
        return None
    return value[:maximum]


def _as_int(value: Any) -> int | None:
    """Artifactory sends size as a JSON string. Coerce, or report nothing."""
    if type(value) is int:
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


class ArmOperations:
    def __init__(self, client, *, max_pages: int = 1) -> None:
        if type(max_pages) is not int or not 1 <= max_pages <= 10:
            raise ArmError("invalid_configuration")
        self.client = client
        self.max_pages = max_pages
        self.base = client.path_prefix.rstrip("/")

    # -- helpers --------------------------------------------------------

    def _redact(self, value: str | None) -> str | None:
        """Strip the configured token out of any remote text."""
        if value is None:
            return None
        auth = self.client.auth
        for secret in (
            getattr(auth, "auth_header_value", ""),
            getattr(auth, "token", ""),
        ):
            if isinstance(secret, str) and len(secret) >= 4:
                value = value.replace(secret, "<redacted>")
        return value

    @staticmethod
    def _repo(value: Any) -> str:
        if not isinstance(value, str) or _REPO_KEY.fullmatch(value) is None:
            raise ArmError(
                "invalid_input",
                remediation="Repository must be a single Artifactory repository key.",
            )
        return value

    @staticmethod
    def _path(value: Any, *, allow_empty: bool = False) -> str:
        """Normalise an artefact path and refuse anything that escapes it.

        Traversal is rejected rather than normalised away: a caller that
        writes '..' meant something, and silently reinterpreting it is how
        a path-confinement bug gets built.
        """
        if not isinstance(value, str) or len(value) > _MAX_PATH_CHARS:
            raise ArmError("invalid_input")
        cleaned = value.strip().strip("/")
        if not cleaned:
            if allow_empty:
                return ""
            raise ArmError("invalid_input")
        if (
            "\x00" in cleaned
            or "\\" in cleaned
            or ".." in cleaned.split("/")
            or any(character.isspace() for character in cleaned)
        ):
            raise ArmError(
                "invalid_input",
                remediation="Path must be a plain repository path with no '..' segments.",
            )
        return cleaned

    @staticmethod
    def _bounded_max(value: Any, maximum: int) -> int:
        if type(value) is not int or not 1 <= value <= maximum:
            raise ArmError("invalid_input")
        return value

    @staticmethod
    def _mapping(payload: Any) -> Mapping[str, Any]:
        if not isinstance(payload, Mapping):
            raise ArmError("invalid_remote_data")
        return payload

    def _storage_path(self, repo: str, path: str) -> str:
        suffix = f"/{path}" if path else ""
        return f"{self.base}/api/storage/{repo}{suffix}"

    # -- reads ----------------------------------------------------------

    def list_repositories(
        self,
        *,
        repository_type: str | None = None,
        package_type: str | None = None,
        max_results: int = 25,
    ) -> dict[str, Any]:
        """Enumerate visible repositories, optionally filtered."""
        max_results = self._bounded_max(max_results, 100)
        params: dict[str, Any] = {}
        for name, value in (("type", repository_type),
                            ("packageType", package_type)):
            if value is None:
                continue
            if not isinstance(value, str) or not 1 <= len(value) <= 64:
                raise ArmError("invalid_input")
            params[name] = value

        payload = self.client.get_json(f"{self.base}/api/repositories", params=params)
        if not isinstance(payload, list):
            raise ArmError("invalid_remote_data")

        rows = [row for row in payload if isinstance(row, Mapping)]
        items = [
            {
                "key": self._redact(_bounded_string(row.get("key"), 128)) or "",
                "type": _bounded_string(row.get("type"), 64) or "",
                "package_type": _bounded_string(row.get("packageType"), 64) or "",
                "description": self._redact(
                    _bounded_string(row.get("description"), 512)
                ) or "",
                "url": self._redact(_bounded_string(row.get("url"), 2048)) or "",
            }
            for row in rows[:max_results]
        ]
        truncated = len(rows) > max_results
        return result_envelope(
            items,
            # This endpoint is unpaged -- it returns every visible repository
            # in one array -- so the count is exact rather than a guess.
            total=len(rows),
            truncated=truncated,
            hint=(
                "More repositories exist. Raise max_results, or filter with "
                "repository_type or package_type." if truncated else None
            ),
        )

    def artifact_info(
        self, repo: str, path: str, *, max_children: int = 100
    ) -> dict[str, Any]:
        """Fetch one artefact's or folder's metadata.

        File and folder are one operation because Artifactory serves them
        from one endpoint and the response discriminates. Splitting them
        would make the caller know the answer before asking.
        """
        repo = self._repo(repo)
        path = self._path(path, allow_empty=True)
        max_children = self._bounded_max(max_children, _MAX_CHILDREN)

        payload = self._mapping(self.client.get_json(self._storage_path(repo, path)))
        raw_children = payload.get("children")
        is_folder = isinstance(raw_children, list)

        children: list[dict[str, Any]] = []
        children_truncated = False
        if is_folder:
            entries = [c for c in raw_children if isinstance(c, Mapping)]
            children_truncated = len(entries) > max_children
            for child in entries[:max_children]:
                uri = _bounded_string(child.get("uri"), 1024) or ""
                children.append({
                    "name": self._redact(uri.lstrip("/")) or "",
                    "folder": child.get("folder") is True,
                })

        checksums = payload.get("checksums")
        return {
            "repo": self._redact(_bounded_string(payload.get("repo"), 128)) or repo,
            "path": self._redact(
                _bounded_string(payload.get("path"), _MAX_PATH_CHARS)
            ) or f"/{path}",
            "kind": "folder" if is_folder else "file",
            "size": None if is_folder else _as_int(payload.get("size")),
            "mime_type": _bounded_string(payload.get("mimeType"), 255),
            "created": _bounded_string(payload.get("created"), 64),
            "modified": _bounded_string(payload.get("lastModified"), 64),
            "download_uri": self._redact(
                _bounded_string(payload.get("downloadUri"), 2048)
            ),
            "checksums": {
                name: _bounded_string(checksums.get(name), 128) or ""
                for name in ("md5", "sha1", "sha256")
            } if isinstance(checksums, Mapping) else {},
            "children": children,
            "children_truncated": children_truncated,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_reads.py -q`
Expected: PASS (18 tests)

- [ ] **Step 5: Wire the tools**

Create `plugins/ericsson-arm/tools.py`:

```python
"""Tool schemas and safe invocation adapters for bounded Artifactory access."""

from __future__ import annotations

from typing import Any, Mapping

if __package__:
    from .auth import authentication_from_configuration
    from .client import ArmClient
    from .models import ArmError
    from .operations import ArmOperations
else:  # Standalone source tests import modules directly from the plugin root.
    from auth import authentication_from_configuration
    from client import ArmClient
    from models import ArmError
    from operations import ArmOperations


_REPO = {
    "type": "string", "minLength": 1, "maxLength": 128,
    "description": "Artifactory repository key, for example 'generic-local'.",
}
_PATH = {
    "type": "string", "maxLength": 1024,
    "description": "Path inside the repository, with no '..' segments.",
}
_LIMIT = {"type": "integer", "minimum": 1, "maximum": 100}


def _schema(name: str, description: str, properties: dict, required: list[str]):
    return {
        "name": name,
        "description": description,
        "parameters": {
            "type": "object",
            "properties": properties,
            "required": required,
            "additionalProperties": False,
        },
    }


SCHEMAS = {
    "arm_list_repositories": _schema(
        "arm_list_repositories",
        "List visible Artifactory repositories, optionally filtered by "
        "repository type (local, remote, virtual) or package type (generic, "
        "docker, maven).",
        {
            "repository_type": {"type": "string", "maxLength": 64},
            "package_type": {"type": "string", "maxLength": 64},
            "max_results": _LIMIT,
        },
        [],
    ),
    "arm_artifact_info": _schema(
        "arm_artifact_info",
        "Fetch metadata for one Artifactory path. A file returns size, "
        "checksums and download URI; a folder returns its children. Use this "
        "rather than downloading: the sha256 is what identifies a build "
        "artefact, and it costs no bytes.",
        {
            "repo": _REPO,
            "path": _PATH,
            "max_children": {"type": "integer", "minimum": 1, "maximum": 1000},
        },
        ["repo", "path"],
    ),
}


def check_available(configuration=None) -> bool:
    if configuration is None:
        return False
    try:
        authentication_from_configuration(configuration)
        return True
    except ArmError:
        return False


def operations_from_configuration(configuration, **client_options) -> ArmOperations:
    authentication = authentication_from_configuration(configuration)
    return ArmOperations(ArmClient(authentication, **client_options))


def invoke(name: str, args: Mapping[str, Any], configuration, **client_options):
    if name not in SCHEMAS or not isinstance(args, Mapping):
        raise ArmError("invalid_input")
    parameters = SCHEMAS[name]["parameters"]
    allowed = set(parameters["properties"])
    required = set(parameters.get("required", ()))
    if (
        any(not isinstance(key, str) for key in args)
        or not required.issubset(args)
        or not set(args).issubset(allowed)
    ):
        raise ArmError("invalid_input")
    operations = operations_from_configuration(configuration, **client_options)
    values = dict(args)
    try:
        if name == "arm_list_repositories":
            return operations.list_repositories(
                repository_type=values.get("repository_type"),
                package_type=values.get("package_type"),
                max_results=values.get("max_results", 25),
            )
        if name == "arm_artifact_info":
            return operations.artifact_info(
                values["repo"],
                values["path"],
                max_children=values.get("max_children", 100),
            )
        raise ArmError("invalid_input")
    finally:
        operations.client.close()
```

Complete `__init__.py`'s `register()` with the handler shape from `ericsson-jira/__init__.py:42-152`, **including the `remediation` field in the error payload** (Jira omits it; every plan from 3a onward adds it), registering each schema with `toolset="ericsson-arm"`, `emoji="📦"`.

`plugin.yaml`: `provides_tools: [arm_list_repositories, arm_artifact_info]`.

- [ ] **Step 6: Verify wiring**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-arm")
import tools, yaml
declared = set(yaml.safe_load(open("plugins/ericsson-arm/plugin.yaml"))["provides_tools"])
assert set(tools.SCHEMAS) == declared, f"mismatch: {set(tools.SCHEMAS) ^ declared}"
print("OK", len(declared), "tools")
PY
```
Expected: `OK 2 tools`.

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-arm/ tests/test_arm_reads.py
git commit -m "feat: add arm repository listing and artifact metadata reads"
```

---

### Task 6: `arm_get_properties`

**Files:**
- Modify: `plugins/ericsson-arm/operations.py`, `tools.py`, `plugin.yaml`
- Test: `tests/test_arm_reads.py`

**Interfaces:**
- Produces: `.get_properties(repo, path, *, keys=None) -> dict`

Endpoint: `GET /artifactory/api/storage/{repo}/{path}?properties[=key,key]`.

This is the highest-value read in the connector and the least obvious. Artifactory properties are where CI stamps `build.number`, `vcs.revision`, `build.url` — so this is the **join key back to GitLab**. Given an artefact, properties are what tell an agent which pipeline produced it and from which commit.

The optional `keys` filter is comma-joined, matching super-cli's `arm.joinComma` helper. Properties are read-only here (D15): they drive promotion gates, and an agent flipping one could promote an unscanned artefact.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_arm_reads.py`:

```python
PROPERTIES = {
    "uri": "https://artifactory.test/artifactory/api/storage/generic-local/a.tgz",
    "properties": {
        "build.number": ["1284"],
        "build.name": ["oscar-release"],
        "vcs.revision": ["9f2c1ab"],
        "qa.approved": ["yes", "by-ci"],
    },
}


class TestGetProperties:
    def test_returns_every_property_with_values_as_lists(self):
        """Artifactory properties are multi-valued. Flattening the single
        case to a bare string would make the shape depend on the data."""
        result = ArmOperations(FakeClient([PROPERTIES])).get_properties(
            "generic-local", "a.tgz"
        )
        assert result["properties"]["build.number"] == ["1284"]
        assert result["properties"]["qa.approved"] == ["yes", "by-ci"]

    def test_requests_the_properties_view(self):
        client = FakeClient([PROPERTIES])
        ArmOperations(client).get_properties("generic-local", "a.tgz")
        _method, path, params = client.calls[0]
        assert path == "/artifactory/api/storage/generic-local/a.tgz"
        assert params == {"properties": ""}

    def test_key_filter_is_comma_joined(self):
        """Matches super-cli's arm.joinComma helper."""
        client = FakeClient([PROPERTIES])
        ArmOperations(client).get_properties(
            "generic-local", "a.tgz", keys=["build.number", "vcs.revision"]
        )
        assert client.calls[0][2] == {"properties": "build.number,vcs.revision"}

    def test_empty_key_list_is_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).get_properties("generic-local", "a.tgz", keys=[])
        assert client.calls == []

    def test_a_key_containing_a_comma_is_rejected(self):
        """A comma inside a key would silently become two keys."""
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).get_properties(
                "generic-local", "a.tgz", keys=["a,b"]
            )
        assert client.calls == []

    def test_missing_properties_key_yields_an_empty_map_not_an_error(self):
        """An artefact with no properties is normal, not a failure."""
        result = ArmOperations(FakeClient([{"uri": "x"}])).get_properties(
            "generic-local", "a.tgz"
        )
        assert result["properties"] == {}

    def test_property_count_is_reported(self):
        result = ArmOperations(FakeClient([PROPERTIES])).get_properties(
            "generic-local", "a.tgz"
        )
        assert result["count"] == 4

    def test_values_are_redacted_and_bounded(self):
        payload = {"properties": {"leak": ["secret-token-value"], "big": ["z" * 5000]}}
        result = ArmOperations(FakeClient([payload])).get_properties(
            "generic-local", "a.tgz"
        )
        assert "secret-token-value" not in result["properties"]["leak"][0]
        assert len(result["properties"]["big"][0]) <= 1024

    def test_non_mapping_properties_raises(self):
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(FakeClient([{"properties": ["not", "a", "map"]}])).get_properties(
                "generic-local", "a.tgz"
            )
        assert excinfo.value.category == "invalid_remote_data"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_reads.py -q -k Properties`
Expected: FAIL — no attribute `get_properties`

- [ ] **Step 3: Implement**

Add to `plugins/ericsson-arm/operations.py`:

```python
_MAX_PROPERTY_KEYS = 64
_MAX_PROPERTY_VALUES = 32
_MAX_PROPERTY_CHARS = 1024


    def get_properties(
        self, repo: str, path: str, *, keys: list[str] | None = None
    ) -> dict[str, Any]:
        """Read an artefact's Artifactory properties.

        This is the join key back to GitLab: CI stamps build.number,
        build.name and vcs.revision here, so properties are what connect a
        deployed artefact to the pipeline and commit that produced it.

        Read-only by design. Properties drive promotion gates, so a write
        here could promote an artefact that has not passed them.
        """
        repo = self._repo(repo)
        path = self._path(path)

        selector = ""
        if keys is not None:
            if (
                not isinstance(keys, list)
                or not 1 <= len(keys) <= _MAX_PROPERTY_KEYS
                or any(
                    not isinstance(key, str)
                    or not key.strip()
                    or "," in key
                    or ";" in key
                    or len(key) > 255
                    for key in keys
                )
            ):
                raise ArmError(
                    "invalid_input",
                    remediation=(
                        "keys must be a non-empty list of property names "
                        "containing no commas or semicolons."
                    ),
                )
            # Comma-joined, matching super-cli's arm.joinComma. A comma
            # inside a key would silently become two keys, so it is refused
            # above rather than escaped.
            selector = ",".join(keys)

        payload = self._mapping(
            self.client.get_json(
                self._storage_path(repo, path), params={"properties": selector}
            )
        )
        raw = payload.get("properties")
        if raw is None:
            # An artefact with no properties is normal, not a failure.
            properties: dict[str, list[str]] = {}
        elif isinstance(raw, Mapping):
            properties = {
                (_bounded_string(name, 255) or ""): [
                    self._redact(_bounded_string(value, _MAX_PROPERTY_CHARS)) or ""
                    for value in values[:_MAX_PROPERTY_VALUES]
                ]
                for name, values in raw.items()
                if isinstance(values, list)
            }
        else:
            raise ArmError("invalid_remote_data")

        return {
            "repo": repo,
            "path": path,
            "properties": properties,
            "count": len(properties),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_reads.py -q`
Expected: PASS (27 tests)

- [ ] **Step 5: Wire the tool**

`tools.py` `SCHEMAS`:

```python
    "arm_get_properties": _schema(
        "arm_get_properties",
        "Read one artefact's Artifactory properties. CI stamps build.number, "
        "build.name and vcs.revision here, so this is how you connect a "
        "deployed artefact back to the pipeline and commit that built it.",
        {
            "repo": _REPO,
            "path": _PATH,
            "keys": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 255},
                "minItems": 1,
                "maxItems": 64,
            },
        },
        ["repo", "path"],
    ),
```

`invoke()` branch:

```python
        if name == "arm_get_properties":
            return operations.get_properties(
                values["repo"], values["path"], keys=values.get("keys")
            )
```

`plugin.yaml`: append `arm_get_properties`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 3 tools`.

```bash
git add plugins/ericsson-arm/ tests/test_arm_reads.py
git commit -m "feat: add arm_get_properties as the artefact-to-pipeline join key"
```

---

### Task 7: `arm_search_artifacts` (AQL)

**Files:**
- Create: `plugins/ericsson-arm/aql.py`
- Modify: `plugins/ericsson-arm/operations.py`, `tools.py`, `plugin.yaml`
- Test: `tests/test_arm_aql.py` (create), `tests/test_arm_reads.py`

**Interfaces:**
- Produces:
  - `aql.prepare(query: str, *, max_results: int) -> str`
  - `.search_artifacts(query, *, max_results=25) -> dict`

Endpoint: `POST /artifactory/api/search/aql` with `Content-Type: text/plain`.

Three connector-enforced rules, each from a specific source:

1. **`Content-Type: text/plain`** — byte-confirmed in `arm.(*Client).AQLSearch`. AQL is a DSL; `application/json` is a 400.
2. **`include` must contain `repo`, `path`, `name`** — from `cleanup_artifactory_releases.sh:174-178`: *"For permissions reasons AQL demands the following fields: repo, path and name."* The connector injects the missing ones rather than surfacing an opaque 400. Injection is additive and cannot change which rows match.
3. **The caller may not supply `.limit()`** — AQL accepts exactly one, so the connector cannot append its own alongside a caller's. Refusing with a message pointing at `max_results` keeps the bound connector-enforced and the rule explainable.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arm_aql.py`:

```python
"""AQL preparation: bounds, permission fields, and shape validation."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from aql import prepare  # noqa: E402
from models import ArmError  # noqa: E402


class TestShape:
    def test_a_domain_find_call_is_required(self):
        with pytest.raises(ArmError) as excinfo:
            prepare("SELECT * FROM artifacts", max_results=10)
        assert excinfo.value.category == "invalid_input"

    @pytest.mark.parametrize(
        "query",
        [
            'items.find({"repo":"x"})',
            'builds.find({"name":"y"})',
            'archive.entries.find({"archive.name":"z"})',
            '  items . find ( {"repo":"x"} )  ',
        ],
    )
    def test_recognised_domains_are_accepted(self, query):
        assert prepare(query, max_results=5)

    def test_empty_query_is_rejected(self):
        with pytest.raises(ArmError):
            prepare("   ", max_results=10)

    def test_oversized_query_is_rejected(self):
        with pytest.raises(ArmError):
            prepare('items.find({"repo":"' + "x" * 9000 + '"})', max_results=10)

    def test_non_string_is_rejected(self):
        with pytest.raises(ArmError):
            prepare(None, max_results=10)


class TestLimit:
    def test_the_connector_appends_its_own_limit(self):
        assert prepare('items.find({"repo":"x"})', max_results=25).endswith(
            ".limit(25)"
        )

    def test_a_caller_supplied_limit_is_refused(self):
        """AQL accepts exactly one limit, so the connector cannot append its
        own alongside a caller's. Refusing keeps the bound enforceable."""
        with pytest.raises(ArmError) as excinfo:
            prepare('items.find({"repo":"x"}).limit(5000)', max_results=25)
        assert "max_results" in (excinfo.value.remediation or "")

    def test_spacing_does_not_hide_a_limit(self):
        with pytest.raises(ArmError):
            prepare('items.find({"repo":"x"}) . limit ( 5000 )', max_results=25)


class TestIncludeInjection:
    def test_a_default_include_is_added_when_absent(self):
        """Without .include() Artifactory returns roughly forty columns per
        row, which bloats the response by an order of magnitude."""
        prepared = prepare('items.find({"repo":"x"})', max_results=10)
        assert '.include(' in prepared
        for field in ("repo", "path", "name", "size", "created"):
            assert f'"{field}"' in prepared

    def test_required_permission_fields_are_injected_into_a_caller_include(self):
        """Artifactory: 'For permissions reasons AQL demands the following
        fields: repo, path and name.' Documented at
        cleanup_artifactory_releases.sh:174-178."""
        prepared = prepare(
            'items.find({"repo":"x"}).include("size","created")', max_results=10
        )
        for field in ("repo", "path", "name", "size", "created"):
            assert f'"{field}"' in prepared

    def test_an_already_complete_include_is_left_alone(self):
        query = 'items.find({"repo":"x"}).include("repo","path","name")'
        prepared = prepare(query, max_results=10)
        assert prepared.count(".include(") == 1
        assert prepared == query + ".limit(10)"

    def test_single_quoted_include_fields_are_recognised(self):
        prepared = prepare(
            "items.find({\"repo\":\"x\"}).include('repo','path','name')",
            max_results=10,
        )
        assert prepared.count(".include(") == 1

    def test_injection_does_not_duplicate_an_existing_field(self):
        prepared = prepare(
            'items.find({"repo":"x"}).include("repo")', max_results=10
        )
        assert prepared.count('"repo"') == 2, "repo appears in find and include only"


class TestSortAndOffsetSurvive:
    def test_caller_sort_is_preserved(self):
        prepared = prepare(
            'items.find({"repo":"x"}).sort({"$desc":["created"]})', max_results=10
        )
        assert '.sort({"$desc":["created"]})' in prepared
        assert prepared.endswith(".limit(10)")

    def test_caller_offset_is_preserved(self):
        prepared = prepare('items.find({"repo":"x"}).offset(20)', max_results=10)
        assert ".offset(20)" in prepared
```

Append to `tests/test_arm_reads.py`:

```python
AQL_RESPONSE = {
    "results": [
        {"repo": "generic-local", "path": "Infra/images/release-26.2.6",
         "name": "oscar.tar.gz", "size": "5242880",
         "created": "2026-07-01T10:00:00.000Z"},
        {"repo": "generic-local", "path": "Infra/images/release-26.2.6",
         "name": "oscar.manifest", "size": "512",
         "created": "2026-07-01T10:01:00.000Z"},
    ],
    "range": {"start_pos": 0, "end_pos": 2, "total": 2},
}


class TestSearchArtifacts:
    def test_posts_prepared_aql_as_text(self):
        client = FakeClient([AQL_RESPONSE])
        ArmOperations(client).search_artifacts(
            'items.find({"repo":"generic-local"})', max_results=25
        )
        method, path, body = client.calls[0]
        assert (method, path) == ("POST", "/artifactory/api/search/aql")
        assert body.endswith(".limit(25)")
        assert ".include(" in body

    def test_returns_bounded_rows_with_a_full_path(self):
        result = ArmOperations(FakeClient([AQL_RESPONSE])).search_artifacts(
            'items.find({"repo":"generic-local"})'
        )
        first = result["items"][0]
        assert first["name"] == "oscar.tar.gz"
        assert first["full_path"] == (
            "generic-local/Infra/images/release-26.2.6/oscar.tar.gz"
        )
        assert first["size"] == 5242880

    def test_total_is_omitted_because_aql_reports_the_limited_set(self):
        """range.total counts the returned rows, not the matching ones.
        Reporting it as total would be a wrong number, and the envelope's
        contract is that a wrong number is worse than none."""
        result = ArmOperations(FakeClient([AQL_RESPONSE])).search_artifacts(
            'items.find({"repo":"generic-local"})'
        )
        assert "total" not in result

    def test_a_full_page_is_reported_as_truncated(self):
        rows = [dict(AQL_RESPONSE["results"][0], name=f"f{i}.tgz") for i in range(10)]
        result = ArmOperations(FakeClient([{"results": rows}])).search_artifacts(
            'items.find({"repo":"x"})', max_results=10
        )
        assert result["truncated"] is True and result["hint"]

    def test_a_short_page_is_not_truncated(self):
        result = ArmOperations(FakeClient([AQL_RESPONSE])).search_artifacts(
            'items.find({"repo":"x"})', max_results=25
        )
        assert result["truncated"] is False

    def test_missing_results_key_raises(self):
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(FakeClient([{"range": {}}])).search_artifacts(
                'items.find({"repo":"x"})'
            )
        assert excinfo.value.category == "invalid_remote_data"

    def test_an_invalid_query_is_rejected_without_a_request(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).search_artifacts("DROP TABLE artifacts")
        assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_aql.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'aql'`

- [ ] **Step 3: Implement**

Create `plugins/ericsson-arm/aql.py`:

```python
"""AQL query preparation.

Raw AQL is exposed deliberately: it is the whole value of Artifactory
search, and the configured token carries the user's own permissions, so a
query cannot reach content the user could not already read. What the
connector adds is bounds and one non-obvious permission rule that
Artifactory enforces but does not advertise.
"""

from __future__ import annotations

import re

if __package__:
    from .models import ArmError
else:
    from models import ArmError

_MAX_QUERY_CHARS = 8192

# A domain call is what makes a string AQL. The domain itself may be dotted
# (archive.entries), so the pattern allows it rather than enumerating the
# domains JFrog happens to ship this version.
_DOMAIN_FIND = re.compile(r"^\s*[A-Za-z][A-Za-z0-9_]*(?:\.[A-Za-z][A-Za-z0-9_]*)*\s*\.\s*find\s*\(")
_LIMIT_CALL = re.compile(r"\.\s*limit\s*\(")
_INCLUDE_CALL = re.compile(r"\.\s*include\s*\(([^)]*)\)")
_QUOTED_FIELD = re.compile(r"""['"]([^'"]+)['"]""")

# Artifactory rejects an include that omits any of these:
#   "For permissions reasons AQL demands the following fields:
#    repo, path and name."
# Documented at oscar_app/oscar/utils/cleanup_artifactory_releases.sh:174-178.
REQUIRED_FIELDS = ("repo", "path", "name")

# Used when the caller supplies no include at all. Without one Artifactory
# returns roughly forty columns per row.
DEFAULT_FIELDS = ("repo", "path", "name", "size", "created", "modified")


def _render(fields) -> str:
    return ".include(" + ",".join(f'"{field}"' for field in fields) + ")"


def prepare(query, *, max_results: int) -> str:
    """Validate an AQL query and return it with bounds and permission fields.

    Rewriting a caller's query is normally the wrong instinct. It is right
    here because both edits are provably non-semantic: adding fields to an
    include changes which columns come back, never which rows match, and
    appending a limit is the bound the connector is responsible for.
    """
    if not isinstance(query, str):
        raise ArmError("invalid_input")
    text = query.strip()
    if not text or len(text) > _MAX_QUERY_CHARS:
        raise ArmError(
            "invalid_input",
            remediation=f"AQL query must be 1 to {_MAX_QUERY_CHARS} characters.",
        )
    if _DOMAIN_FIND.match(text) is None:
        raise ArmError(
            "invalid_input",
            remediation=(
                'AQL must begin with a domain find call, for example '
                'items.find({"repo":"generic-local"}).'
            ),
        )
    if _LIMIT_CALL.search(text):
        raise ArmError(
            "invalid_input",
            remediation=(
                "Do not put .limit() in the query; AQL accepts only one and "
                "the connector supplies it. Use max_results instead."
            ),
        )

    match = _INCLUDE_CALL.search(text)
    if match is None:
        text = f"{text}{_render(DEFAULT_FIELDS)}"
    else:
        present = _QUOTED_FIELD.findall(match.group(1))
        missing = [f for f in REQUIRED_FIELDS if f not in present]
        if missing:
            text = (
                text[: match.start()]
                + _render(list(present) + missing)
                + text[match.end():]
            )

    return f"{text}.limit({max_results})"
```

Add to `plugins/ericsson-arm/operations.py`:

```python
    def search_artifacts(
        self, query: str, *, max_results: int = 25
    ) -> dict[str, Any]:
        """Search artefacts with AQL.

        This is the only way to answer the questions that make Artifactory
        useful to an agent -- "which artefacts did this release produce",
        "what changed in this repository since Tuesday". A hand-rolled
        filter language would be strictly worse AQL.
        """
        max_results = self._bounded_max(max_results, 100)
        prepared = prepare_aql(query, max_results=max_results)

        payload = self._mapping(
            self.client.post_text(f"{self.base}/api/search/aql", prepared)
        )
        results = payload.get("results")
        if not isinstance(results, list):
            raise ArmError("invalid_remote_data")

        rows = [row for row in results if isinstance(row, Mapping)]
        items = []
        for row in rows[:max_results]:
            repo = _bounded_string(row.get("repo"), 128) or ""
            path = _bounded_string(row.get("path"), _MAX_PATH_CHARS) or ""
            name = _bounded_string(row.get("name"), 512) or ""
            joined = "/".join(part for part in (repo, path, name) if part and part != ".")
            items.append({
                "repo": self._redact(repo) or "",
                "path": self._redact(path) or "",
                "name": self._redact(name) or "",
                "full_path": self._redact(joined) or "",
                "size": _as_int(row.get("size")),
                "created": _bounded_string(row.get("created"), 64),
                "modified": _bounded_string(row.get("modified"), 64),
            })

        # AQL's range.total counts the rows this response carried, not the
        # rows that matched, so it is deliberately not reported as `total`.
        # A full page is the only truncation signal available.
        truncated = len(rows) >= max_results
        return result_envelope(
            items,
            truncated=truncated,
            hint=(
                "The result set filled max_results, so more artefacts may "
                "match. Raise max_results or narrow the query."
                if truncated else None
            ),
        )
```

Add the import at the top of `operations.py`:

```python
if __package__:
    from .aql import prepare as prepare_aql
else:
    from aql import prepare as prepare_aql
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_aql.py tests/test_arm_reads.py -q`
Expected: PASS (16 AQL tests, 34 read tests)

- [ ] **Step 5: Wire the tool**

```python
    "arm_search_artifacts": _schema(
        "arm_search_artifacts",
        "Search Artifactory with AQL, for example "
        "'items.find({\"repo\":\"generic-local\",\"path\":{\"$match\":"
        "\"Infra/images*\"}})'. Do not add .limit() — use max_results. "
        "Required permission fields are added automatically.",
        {
            "query": {"type": "string", "minLength": 1, "maxLength": 8192},
            "max_results": _LIMIT,
        },
        ["query"],
    ),
```

`invoke()`: dispatch to `operations.search_artifacts(values["query"], max_results=values.get("max_results", 25))`.
`plugin.yaml`: append `arm_search_artifacts`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 4 tools`.

```bash
git add plugins/ericsson-arm/ tests/
git commit -m "feat: add arm_search_artifacts with bounded AQL and permission fields"
```

---

### Task 8: `arm_deploy` — checksum-first upload

**Files:**
- Modify: `plugins/ericsson-arm/operations.py`, `tools.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_arm_writes.py` (create)

**Interfaces:**
- Produces: `.deploy(repo, path, source_file, *, dry_run=False, confirm=False) -> dict`

Endpoint: `PUT /artifactory/{repo}/{path}` — note this is **not** under `/api/`.

Two-phase, ported from `bulk_upload_verify.sh:183-228`:

1. **Checksum deploy.** `PUT` with `X-Checksum-Deploy: true` plus `X-Checksum-Sha256`, `X-Checksum-Sha1`, `X-Checksum-Md5`, and **no body**. If Artifactory already holds a blob with that checksum it links the new path to it and answers 2xx — the whole artefact is "uploaded" with zero bytes transferred.
2. **Full upload.** On any non-2xx, `PUT` the file with the same three checksum headers so Artifactory validates what it received.

super-cli sets `X-Checksum-Deploy: true` unconditionally with no fallback, so its deploy fails outright against a repository that does not already hold the blob. It also sends only sha256. This is the clearest case in the whole comparison where the OSCAR scripts are ahead of the binary, and the fallback is what makes the optimisation safe to use.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_arm_writes.py`:

```python
"""Artifactory write operations: intent gating, checksum deploy, delete."""

import hashlib
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-arm"
sys.path.insert(0, str(PLUGIN))

from _common.transport import Response  # noqa: E402
from models import ArmError  # noqa: E402
from operations import ArmOperations  # noqa: E402


class FakeClient:
    def __init__(self, json_results=None, raw_results=None, *, deploy_root=None,
                 max_deploy_bytes=1024 * 1024):
        self.json_results = list(json_results or [])
        self.raw_results = list(raw_results or [])
        self.calls = []

        class _Auth:
            pass

        self.auth = _Auth()
        self.auth.auth_header_value = "Bearer secret-token-value"
        self.auth.token = "secret-token-value"
        self.auth.default_max_results = 25
        self.auth.max_deploy_bytes = max_deploy_bytes
        self.auth.deploy_root = deploy_root
        self.path_prefix = "/artifactory/"

    def get_json(self, path, *, params=None, deadline=None):
        self.calls.append(("GET", path, params))
        result = self.json_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def request_json(self, method, path, *, params=None, json_body=None,
                     deadline=None):
        self.calls.append((method, path, json_body))
        result = self.json_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def send(self, method, path, *, params=None, json_body=None, content=None,
             extra_headers=None, deadline=None, classify=True):
        self.calls.append({
            "method": method, "path": path, "headers": dict(extra_headers or {}),
            "has_body": content is not None, "classify": classify,
        })
        result = self.raw_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


@pytest.fixture
def artifact(tmp_path):
    source = tmp_path / "oscar.tar.gz"
    payload = b"artifact-bytes" * 100
    source.write_bytes(payload)
    return source, {
        "md5": hashlib.md5(payload, usedforsecurity=False).hexdigest(),
        "sha1": hashlib.sha1(payload, usedforsecurity=False).hexdigest(),
        "sha256": hashlib.sha256(payload).hexdigest(),
    }


def _deployed(checksums, status=201):
    return Response(
        status, {},
        (
            '{"repo":"generic-local","path":"/Infra/a.tgz",'
            '"downloadUri":"https://artifactory.test/x",'
            f'"checksums":{{"md5":"{checksums["md5"]}",'
            f'"sha1":"{checksums["sha1"]}",'
            f'"sha256":"{checksums["sha256"]}"}}}}'
        ).encode(),
    )


class TestDeployIntent:
    def test_neither_flag_is_refused_without_a_request(self, artifact):
        source, _sums = artifact
        client = FakeClient()
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy("generic-local", "Infra/a.tgz", str(source))
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_reports_checksums_without_any_request(self, artifact):
        """Deploy's dry run cannot probe: the checksum-deploy probe IS a
        deploy. So it reports what would be sent and stops."""
        source, sums = artifact
        client = FakeClient()
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), dry_run=True
        )
        assert result["dry_run"] is True
        assert result["checksums"]["sha256"] == sums["sha256"]
        assert result["deduplicated"] is None
        assert client.calls == []


class TestChecksumDeploy:
    def test_checksum_deploy_sends_no_body_and_all_three_checksums(self, artifact):
        source, sums = artifact
        client = FakeClient(raw_results=[_deployed(sums)])
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        first = client.calls[0]
        assert first["method"] == "PUT"
        assert first["path"] == "/artifactory/generic-local/Infra/a.tgz"
        assert first["headers"]["X-Checksum-Deploy"] == "true"
        assert first["headers"]["X-Checksum-Sha256"] == sums["sha256"]
        assert first["headers"]["X-Checksum-Sha1"] == sums["sha1"]
        assert first["headers"]["X-Checksum-Md5"] == sums["md5"]
        assert first["has_body"] is False
        assert result["deduplicated"] is True
        assert result["bytes_uploaded"] == 0

    def test_only_one_request_when_the_blob_already_exists(self, artifact):
        source, sums = artifact
        client = FakeClient(raw_results=[_deployed(sums, status=200)])
        ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert len(client.calls) == 1

    def test_falls_back_to_a_full_upload(self, artifact):
        """super-cli sets X-Checksum-Deploy unconditionally and has no
        fallback, so its deploy fails against a repo that lacks the blob.
        Ported from bulk_upload_verify.sh:216-228."""
        source, sums = artifact
        client = FakeClient(raw_results=[Response(404, {}, b""), _deployed(sums)])
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert len(client.calls) == 2
        second = client.calls[1]
        assert second["has_body"] is True
        assert "X-Checksum-Deploy" not in second["headers"]
        assert second["headers"]["X-Checksum-Sha256"] == sums["sha256"]
        assert result["deduplicated"] is False
        assert result["bytes_uploaded"] == source.stat().st_size

    def test_the_probe_does_not_classify_its_response(self, artifact):
        """A non-2xx probe is a normal outcome, not an error -- classifying
        it would raise instead of falling through."""
        source, sums = artifact
        client = FakeClient(raw_results=[Response(404, {}, b""), _deployed(sums)])
        ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert client.calls[0]["classify"] is False
        assert client.calls[1]["classify"] is True

    def test_a_checksum_mismatch_in_the_response_is_an_error(self, artifact):
        source, _sums = artifact
        wrong = {"md5": "0" * 32, "sha1": "0" * 40, "sha256": "0" * 64}
        client = FakeClient(raw_results=[_deployed(wrong)])
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "invalid_remote_data"
        assert "checksum" in (excinfo.value.remediation or "").lower()

    def test_a_response_without_checksums_is_an_error(self, artifact):
        source, _sums = artifact
        client = FakeClient(raw_results=[Response(201, {}, b'{"repo":"x"}')])
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "invalid_remote_data"


class TestDeploySource:
    def test_a_relative_path_is_rejected(self, artifact):
        client = FakeClient()
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", "./oscar.tar.gz", confirm=True
            )
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_a_missing_file_is_rejected(self, tmp_path):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(tmp_path / "absent"), confirm=True
            )
        assert client.calls == []

    def test_a_directory_is_rejected(self, tmp_path):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(tmp_path), confirm=True
            )
        assert client.calls == []

    def test_a_file_over_the_size_bound_is_rejected(self, artifact):
        source, _sums = artifact
        client = FakeClient(max_deploy_bytes=10)
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "capacity"
        assert client.calls == []

    def test_deploy_root_confines_the_source(self, artifact, tmp_path):
        source, _sums = artifact
        other = tmp_path / "elsewhere"
        other.mkdir()
        client = FakeClient(deploy_root=str(other))
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(source), confirm=True
            )
        assert excinfo.value.category == "permission"
        assert client.calls == []

    def test_a_symlink_escaping_deploy_root_is_rejected(self, artifact, tmp_path):
        """Confinement must resolve symlinks, or it confines nothing."""
        source, _sums = artifact
        root = tmp_path / "allowed"
        root.mkdir()
        link = root / "sneaky.tar.gz"
        link.symlink_to(source)
        client = FakeClient(deploy_root=str(root))
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).deploy(
                "generic-local", "Infra/a.tgz", str(link), confirm=True
            )
        assert excinfo.value.category == "permission"

    def test_a_source_inside_deploy_root_is_allowed(self, tmp_path):
        root = tmp_path / "allowed"
        root.mkdir()
        source = root / "oscar.tar.gz"
        source.write_bytes(b"bytes")
        sums = {
            "md5": hashlib.md5(b"bytes", usedforsecurity=False).hexdigest(),
            "sha1": hashlib.sha1(b"bytes", usedforsecurity=False).hexdigest(),
            "sha256": hashlib.sha256(b"bytes").hexdigest(),
        }
        client = FakeClient(raw_results=[_deployed(sums)], deploy_root=str(root))
        result = ArmOperations(client).deploy(
            "generic-local", "Infra/a.tgz", str(source), confirm=True
        )
        assert result["ok"] is True
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_writes.py -q`
Expected: FAIL — no attribute `deploy`

- [ ] **Step 3: Implement**

Add to the imports at the top of `plugins/ericsson-arm/operations.py`:

```python
import hashlib
import json
import os
```

and to the `_common` import block:

```python
    from ._common.guardrails import require_explicit_intent
```
```python
    from _common.guardrails import require_explicit_intent
```

Add to `plugins/ericsson-arm/operations.py`:

```python
_CHECKSUM_CHUNK = 1024 * 1024


    def _resolve_source(self, source_file: Any) -> tuple[str, int]:
        """Validate a local upload source and return (real path, size).

        An absolute path is required because a relative one would resolve
        against the agent process's working directory, which the caller
        cannot see and did not choose.
        """
        if not isinstance(source_file, str) or not source_file:
            raise ArmError("invalid_input")
        if not os.path.isabs(source_file):
            raise ArmError(
                "invalid_input",
                remediation="source_file must be an absolute path.",
            )
        real = os.path.realpath(source_file)
        if not os.path.isfile(real):
            raise ArmError(
                "not_found",
                remediation="source_file does not name a readable file.",
            )

        root = getattr(self.client.auth, "deploy_root", None)
        if root:
            # realpath on both sides, so a symlink cannot point out of the
            # confined tree. Comparing the unresolved path would confine
            # nothing.
            if os.path.commonpath([real, root]) != root:
                raise ArmError(
                    "permission",
                    remediation=(
                        "This profile confines uploads to its configured "
                        "deploy source root."
                    ),
                )

        size = os.path.getsize(real)
        limit = getattr(self.client.auth, "max_deploy_bytes", 0)
        if size > limit:
            raise ArmError(
                "capacity",
                remediation=(
                    "The file is larger than this profile's maximum upload "
                    "size. Raise it in the profile if this is expected."
                ),
            )
        return real, size

    @staticmethod
    def _file_checksums(real_path: str) -> dict[str, str]:
        """Compute all three checksums in one pass over the file.

        Three, not one: Artifactory's checksum deploy matches on sha1 in
        older versions, and bulk_upload_verify.sh sends all three for
        exactly that reason. super-cli sends only sha256.

        usedforsecurity=False because md5 and sha1 here are content
        addresses that Artifactory chose, not security claims -- without it
        this raises on a FIPS-mode build.
        """
        digests = {
            "md5": hashlib.md5(usedforsecurity=False),
            "sha1": hashlib.sha1(usedforsecurity=False),
            "sha256": hashlib.sha256(),
        }
        with open(real_path, "rb") as handle:
            for block in iter(lambda: handle.read(_CHECKSUM_CHUNK), b""):
                for digest in digests.values():
                    digest.update(block)
        return {name: digest.hexdigest() for name, digest in digests.items()}

    def _verify_deploy(self, response, checksums: dict[str, str]) -> dict[str, Any]:
        """Parse a deploy response and confirm the server got what we sent."""
        try:
            payload = json.loads(response.body) if response.body else None
        except (UnicodeDecodeError, json.JSONDecodeError, ValueError):
            payload = None
        if not isinstance(payload, Mapping):
            raise ArmError(
                "invalid_remote_data",
                remediation="Artifactory did not return a deploy result.",
            )
        reported = payload.get("checksums")
        if not isinstance(reported, Mapping) or not reported.get("sha256"):
            raise ArmError(
                "invalid_remote_data",
                remediation="Artifactory returned no checksums to verify against.",
            )
        if reported.get("sha256") != checksums["sha256"]:
            raise ArmError(
                "invalid_remote_data",
                remediation=(
                    "The sha256 Artifactory reported does not match the file "
                    "that was sent. Do not treat this artefact as published."
                ),
            )
        return payload

    def deploy(
        self,
        repo: str,
        path: str,
        source_file: str,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Upload one local file to Artifactory, checksum-first.

        Two phases, ported from bulk_upload_verify.sh:183-228. The first PUT
        carries the checksums and no body: if Artifactory already holds that
        blob it links the path to it and the artefact is published with zero
        bytes transferred. Any non-2xx falls through to a full upload with
        the same checksum headers so the server validates what it received.

        super-cli sets X-Checksum-Deploy unconditionally and has no
        fallback, so its deploy fails outright when the blob is new. The
        fallback is what makes the optimisation safe to rely on.
        """
        repo = self._repo(repo)
        path = self._path(path)
        real_path, size = self._resolve_source(source_file)
        checksums = self._file_checksums(real_path)

        execute = require_explicit_intent(
            dry_run=dry_run,
            confirm=confirm,
            action=f"an upload of {real_path} to {repo}/{path}",
        )
        target = f"{self.base}/{repo}/{path}"
        checksum_headers = {
            "X-Checksum-Sha256": checksums["sha256"],
            "X-Checksum-Sha1": checksums["sha1"],
            "X-Checksum-Md5": checksums["md5"],
        }

        if not execute:
            return {
                "ok": True, "dry_run": True, "repo": repo, "path": path,
                "source_file": real_path, "size": size, "checksums": checksums,
                # Unknown by construction: finding out whether Artifactory
                # already holds this blob requires the probe, and the probe
                # is itself a deploy.
                "deduplicated": None, "bytes_uploaded": None,
            }

        probe = self.client.send(
            "PUT", target,
            extra_headers={"X-Checksum-Deploy": "true", **checksum_headers},
            content=b"",
            classify=False,
        )
        if 200 <= probe.status < 300:
            payload = self._verify_deploy(probe, checksums)
            return {
                "ok": True, "dry_run": False, "repo": repo, "path": path,
                "source_file": real_path, "size": size, "checksums": checksums,
                "deduplicated": True, "bytes_uploaded": 0,
                "download_uri": self._redact(
                    _bounded_string(payload.get("downloadUri"), 2048)
                ),
            }

        with open(real_path, "rb") as handle:
            response = self.client.send(
                "PUT", target, extra_headers=checksum_headers, content=handle
            )
        payload = self._verify_deploy(response, checksums)
        return {
            "ok": True, "dry_run": False, "repo": repo, "path": path,
            "source_file": real_path, "size": size, "checksums": checksums,
            "deduplicated": False, "bytes_uploaded": size,
            "download_uri": self._redact(
                _bounded_string(payload.get("downloadUri"), 2048)
            ),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_writes.py -q`
Expected: PASS (16 tests)

- [ ] **Step 5: Wire the tool and its approval**

```python
    "arm_deploy": _schema(
        "arm_deploy",
        "Upload one local file to Artifactory. Tries a checksum-only deploy "
        "first, which publishes with zero bytes transferred when the blob "
        "already exists, and falls back to a full upload otherwise. Requires "
        "dry_run or confirm.",
        {
            "repo": _REPO,
            "path": _PATH,
            "source_file": {
                "type": "string", "minLength": 1, "maxLength": 4096,
                "description": "Absolute path to the local file to upload.",
            },
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["repo", "path", "source_file"],
    ),
```

`invoke()` branch:

```python
        if name == "arm_deploy":
            return operations.deploy(
                values["repo"],
                values["path"],
                values["source_file"],
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`:

```python
_WRITE_TOOLS = frozenset({"arm_deploy"})

WRITE_APPROVALS = {
    # The source file is first because it is the argument a reviewer most
    # needs to see: this tool reads a local path chosen by the model and
    # publishes it to a shared repository.
    "arm_deploy": lambda a: (
        f"Upload file: {_arg(a, 'source_file')}\n"
        f"To repository: {_arg(a, 'repo')}\n"
        f"At path: {_arg(a, 'path')}"
    ),
}
```

`plugin.yaml`: append `arm_deploy`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 5 tools`.

```bash
git add plugins/ericsson-arm/ tests/test_arm_writes.py
git commit -m "feat: add arm_deploy with checksum-first upload and full fallback"
```

---

### Task 9: `arm_delete`

**Files:**
- Modify: `plugins/ericsson-arm/operations.py`, `tools.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_arm_writes.py`

**Interfaces:**
- Produces: `.delete(repo, path, *, dry_run=False, confirm=False) -> dict`

Endpoint: `DELETE /artifactory/{repo}/{path}`.

One call, one path — deliberately not the per-file loop in `cleanup_artifactory_releases.sh:349-371`. Artifactory recurses server-side, so deleting `Infra/images/release-26.2.5` removes the whole release in a single atomic round trip. An agent iterating deletes is precisely the failure mode approval gating exists to prevent, and one approval covering N hidden deletions is not meaningful consent.

The dry run performs a read (D12): previewing what is about to be destroyed is the whole value of the preview. `test_dry_run_reads_but_does_not_delete` pins it so it stays a decision.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_arm_writes.py`:

```python
FOLDER_TO_DELETE = {
    "repo": "generic-local",
    "path": "/Infra/images/release-26.2.5",
    "children": [
        {"uri": "/oscar.tar.gz", "folder": False},
        {"uri": "/oscar.manifest", "folder": False},
    ],
}

FILE_TO_DELETE = {
    "repo": "generic-local",
    "path": "/Infra/images/oscar.tar.gz",
    "size": "5242880",
    "checksums": {"md5": "m" * 32, "sha1": "s" * 40, "sha256": "x" * 64},
}


class TestDelete:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient()
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).delete("generic-local", "Infra/images/a.tgz")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_reads_but_does_not_delete(self):
        """Previewing what is about to be destroyed is the point of the
        preview, so this dry run costs one GET on purpose."""
        client = FakeClient(json_results=[FOLDER_TO_DELETE])
        result = ArmOperations(client).delete(
            "generic-local", "Infra/images/release-26.2.5", dry_run=True
        )
        # get_json records a tuple, send records a dict -- so checking the
        # recorded types is what proves no DELETE was issued, not just that
        # the first call happened to be a GET.
        assert len(client.calls) == 1
        assert isinstance(client.calls[0], tuple)
        assert client.calls[0][0] == "GET"
        assert result["dry_run"] is True
        assert result["kind"] == "folder"
        assert result["child_count"] == 2

    def test_dry_run_on_a_file_reports_its_size(self):
        client = FakeClient(json_results=[FILE_TO_DELETE])
        result = ArmOperations(client).delete(
            "generic-local", "Infra/images/oscar.tar.gz", dry_run=True
        )
        assert result["kind"] == "file"
        assert result["size"] == 5242880

    def test_dry_run_on_an_absent_path_says_so(self):
        client = FakeClient(json_results=[ArmError("not_found")])
        result = ArmOperations(client).delete(
            "generic-local", "Infra/gone", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["exists"] is False

    def test_confirm_issues_one_delete(self):
        client = FakeClient(raw_results=[Response(204, {}, b"")])
        result = ArmOperations(client).delete(
            "generic-local", "Infra/images/release-26.2.5", confirm=True
        )
        assert len(client.calls) == 1
        call = client.calls[0]
        assert call["method"] == "DELETE"
        assert call["path"] == "/artifactory/generic-local/Infra/images/release-26.2.5"
        assert result["deleted"] is True

    def test_a_folder_delete_is_one_call_not_a_loop(self):
        """Artifactory recurses server-side. One approval must not authorise
        N hidden deletions."""
        client = FakeClient(raw_results=[Response(204, {}, b"")])
        ArmOperations(client).delete(
            "generic-local", "Infra/images", confirm=True
        )
        assert len(client.calls) == 1

    @pytest.mark.parametrize("status", [200, 204])
    def test_success_statuses_are_accepted(self, status):
        client = FakeClient(raw_results=[Response(status, {}, b"")])
        assert ArmOperations(client).delete(
            "generic-local", "Infra/a.tgz", confirm=True
        )["deleted"] is True

    def test_404_is_success_and_flagged_as_already_absent(self):
        """Deleting something already gone is the desired end state, not a
        failure. Ported from cleanup_artifactory_releases.sh:340."""
        client = FakeClient(raw_results=[Response(404, {}, b"")])
        result = ArmOperations(client).delete(
            "generic-local", "Infra/a.tgz", confirm=True
        )
        assert result["deleted"] is True
        assert result["already_absent"] is True

    def test_a_permission_failure_is_classified(self):
        client = FakeClient(raw_results=[Response(403, {}, b"")])
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).delete(
                "generic-local", "Infra/a.tgz", confirm=True
            )
        assert excinfo.value.category == "permission"

    def test_deleting_a_whole_repository_root_is_refused(self):
        """An empty path would DELETE the repository root. There is no
        agent workflow that wants that, and the blast radius is total."""
        client = FakeClient()
        with pytest.raises(ArmError) as excinfo:
            ArmOperations(client).delete("generic-local", "", confirm=True)
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_traversal_in_the_path_is_refused(self):
        client = FakeClient()
        with pytest.raises(ArmError):
            ArmOperations(client).delete(
                "generic-local", "Infra/../../other", confirm=True
            )
        assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_arm_writes.py -q -k Delete`
Expected: FAIL — no attribute `delete`

- [ ] **Step 3: Implement**

Add to `plugins/ericsson-arm/operations.py`:

```python
    def delete(
        self,
        repo: str,
        path: str,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Delete one Artifactory path.

        One call, one path. Artifactory recurses server-side, so a folder
        path removes the whole subtree atomically -- which is why this does
        not replicate the per-file loop in
        cleanup_artifactory_releases.sh:349-371. One approval authorising N
        hidden deletions is not meaningful consent, and an agent iterating
        deletes is the failure mode the approval gate exists to prevent.

        The path is required and may not be empty: an empty path would
        DELETE the repository root.
        """
        repo = self._repo(repo)
        # allow_empty stays False: an empty path here is a repository wipe.
        path = self._path(path)

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"deletion of {repo}/{path}"
        )

        if not execute:
            try:
                preview = self.artifact_info(repo, path, max_children=1000)
            except ArmError as exc:
                if exc.category != "not_found":
                    raise
                return {
                    "ok": True, "dry_run": True, "repo": repo, "path": path,
                    "exists": False, "deleted": False,
                }
            return {
                "ok": True, "dry_run": True, "repo": repo, "path": path,
                "exists": True, "deleted": False,
                "kind": preview["kind"],
                "size": preview["size"],
                "child_count": len(preview["children"]),
                "child_count_truncated": preview["children_truncated"],
            }

        response = self.client.send(
            "DELETE", f"{self.base}/{repo}/{path}", classify=False
        )
        if response.status == 404:
            # Already gone is the desired end state, not a failure.
            # cleanup_artifactory_releases.sh:340 makes the same call.
            return {
                "ok": True, "dry_run": False, "repo": repo, "path": path,
                "deleted": True, "already_absent": True,
            }
        if not 200 <= response.status < 300:
            self.client._classify(response)  # raises with the right category
        return {
            "ok": True, "dry_run": False, "repo": repo, "path": path,
            "deleted": True, "already_absent": False,
        }
```

`self.client._classify` is a deliberate reach into the client rather than a duplicated status table — the alternative is a second copy of the Cloudflare Access detection, which would drift. Promote `_classify` to a public `classify` on `ArmClient` if a reviewer objects to the underscore; the behaviour is identical either way.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_arm_writes.py -q`
Expected: PASS (28 tests)

- [ ] **Step 5: Wire the tool and its approval**

```python
    "arm_delete": _schema(
        "arm_delete",
        "Delete one Artifactory path. A folder path removes the whole "
        "subtree in one atomic call. Run with dry_run first to see what "
        "would be removed. Requires dry_run or confirm.",
        {
            "repo": _REPO,
            "path": {
                "type": "string", "minLength": 1, "maxLength": 1024,
                "description": (
                    "Path inside the repository. A folder path deletes it and "
                    "everything under it."
                ),
            },
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["repo", "path"],
    ),
```

`invoke()` branch:

```python
        if name == "arm_delete":
            return operations.delete(
                values["repo"],
                values["path"],
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`:

```python
_WRITE_TOOLS = frozenset({"arm_deploy", "arm_delete"})

WRITE_APPROVALS = {
    "arm_deploy": lambda a: (
        f"Upload file: {_arg(a, 'source_file')}\n"
        f"To repository: {_arg(a, 'repo')}\n"
        f"At path: {_arg(a, 'path')}"
    ),
    "arm_delete": lambda a: (
        f"Delete from repository: {_arg(a, 'repo')}\n"
        f"Path: {_arg(a, 'path')}\n"
        f"A folder path removes everything beneath it, and Artifactory "
        f"deletion is not recoverable unless trash is enabled."
    ),
}
```

`plugin.yaml`: append `arm_delete`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 6 tools`.

```bash
git add plugins/ericsson-arm/ tests/test_arm_writes.py
git commit -m "feat: add arm_delete with a previewing dry run and no bulk loop"
```

---

### Task 10: Skill, README, and contract verification

**Files:**
- Create: `plugins/ericsson-arm/skills/artifact-research/SKILL.md`
- Create: `plugins/ericsson-arm/README.md`
- Modify: `plugins/ericsson-arm/__init__.py`
- Test: all

**Interfaces:**
- Consumes: everything from Tasks 1–9

- [ ] **Step 1: Write the connector skill**

Create `plugins/ericsson-arm/skills/artifact-research/SKILL.md`, following `plugins/ericsson-jira/skills/ticket-research/SKILL.md`. It must cover the one workflow that makes this connector worth having:

> **Tracing a release artefact back to its build.** Find the artefact with `arm_search_artifacts`, confirm its identity with `arm_artifact_info` (the sha256 is the artefact's identity — never download to compare), then read `arm_get_properties`. `build.name`, `build.number` and `vcs.revision` are what connect it to the GitLab pipeline and commit that produced it. That is the join the other four connectors cannot make on their own.

It must also state that `arm_delete` on a folder path is recursive and not recoverable, and that a dry run is the correct first call.

Register it in `__init__.py`:

```python
_PLUGIN_SKILLS = (
    ("artifact-research", "Trace a release artefact back to the build that made it."),
)
```

with the `register_skill` block from `ericsson-jira/__init__.py:154-158`.

- [ ] **Step 2: Verify the full tool contract**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-arm")
import __init__ as p, tools, yaml

declared = set(yaml.safe_load(open("plugins/ericsson-arm/plugin.yaml"))["provides_tools"])
schemas = set(tools.SCHEMAS)
assert schemas == declared, f"schema/manifest mismatch: {schemas ^ declared}"

writes = p._WRITE_TOOLS
approvals = set(p.WRITE_APPROVALS)
assert writes == approvals, f"gated/approvable mismatch: {writes ^ approvals}"

mutating = {n for n, s in tools.SCHEMAS.items()
            if "confirm" in s["parameters"]["properties"]}
assert mutating <= writes, f"mutating but ungated: {sorted(mutating - writes)}"
print("OK", len(schemas), "tools,", len(writes), "gated writes")
PY
```
Expected: `OK 6 tools, 2 gated writes`.

- [ ] **Step 3: Verify approvals are argument-scoped**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-arm")
import __init__ as p

class Ctx:
    def __init__(self): self.hooks = {}
    def configuration(self): return object()
    def register_tool(self, **kw): pass
    def register_hook(self, event, fn): self.hooks[event] = fn
    def register_skill(self, *a): pass

ctx = Ctx(); p.register(ctx); hook = ctx.hooks["pre_tool_call"]
for name in sorted(p._WRITE_TOOLS):
    a = hook(name, {"repo": "r1", "path": "p1", "source_file": "/a"})["rule_key"]
    b = hook(name, {"repo": "r2", "path": "p2", "source_file": "/b"})["rule_key"]
    assert a != b and a != name, f"{name}: rule_key not argument-scoped"
print("OK", len(p._WRITE_TOOLS), "write tools argument-scoped")
PY
```
Expected: `OK 2 write tools argument-scoped`.

- [ ] **Step 4: Verify the connector's three load-bearing invariants**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-arm")
import inspect, auth, client, operations
Ops = operations.ArmOperations

# 1. Every write goes through the shared intent gate.
for name in ("deploy", "delete"):
    src = inspect.getsource(getattr(Ops, name))
    assert "require_explicit_intent" in src, f"{name} mutates without an intent gate"

# 2. Every remote string a caller sees passes through redaction.
for name in ("list_repositories", "artifact_info", "get_properties",
             "search_artifacts"):
    src = inspect.getsource(getattr(Ops, name))
    assert "self._redact" in src, f"{name} returns remote text unredacted"

# 3. The two failure modes that the shell scripts mis-report are classified.
assert "certificate_invalid" in inspect.getsource(auth), (
    "auth does not pre-flight the client certificate")
assert "edge_authentication" in inspect.getsource(client), (
    "client does not classify a Cloudflare Access challenge")
print("OK: 2 gated writes, 4 redacted reads, both edge failures classified")
PY
```
Expected: `OK: 2 gated writes, 4 redacted reads, both edge failures classified`.

Checking these mechanically is what keeps them true as tools are added. Invariant 3 is the one that would otherwise rot silently — nothing in normal use exercises it until the certificate expires, which is once a year.

- [ ] **Step 5: Write the README**

Create `plugins/ericsson-arm/README.md` recording what the next person needs:

> **This instance is behind Cloudflare Access.** `artifactory.rosetta.ericssondevops.com` authenticates callers at the edge with an **mTLS client certificate** before any request reaches Artifactory. That certificate is issued per person with roughly one year of validity and it expires silently: Access answers `302` to `cloudflareaccess.com` with `auth_status: FAILED:FAILED:certificate has expired`, and any consumer that does not read the redirect reports something unrelated instead.
>
> The connector checks `notAfter` at configuration time (`auth.py`) and classifies an Access challenge as `edge_authentication` rather than `authentication` (`client.py`), because the credential that failed is the certificate, not the Artifactory token. Those are two different secrets held by two different systems, and sending an operator to rotate the wrong one costs a day.
>
> **Renewal:** the certificate subject looks like `O=rcli-temporary (Group #13093), OU=<user>@ericsson.com, CN=endpoint <id>`, so it is issued by the `rcli` tool. Renew there, then update `client_cert_path` and `client_key_path` in the profile.
>
> **Which auth header this instance wants is unconfirmed.** The token is a JFrog *reference token*, which both `Authorization: Bearer` and the legacy `X-JFrog-Art-Api` accept. This could not be tested against the live instance because the client certificate had expired, so `auth_mode` ships as a profile setting defaulting to `bearer`. Once confirmed, one of the two branches in `auth.py` can be deleted along with the setting.
>
> **Predecessors.** This connector supersedes three scripts in `oscar_app/oscar/utils`: `bulk_upload_verify.sh` (deploy), `cleanup_artifactory_releases.sh` (delete, AQL listing), and `pull_images_from_artifactory_repo.sh` (download). The first two are ported here; download is deliberately not — see below. Those scripts remain the right tool for bulk operator work; this connector is for an agent that needs to answer questions about artefacts.
>
> **Deliberately not implemented**, with what each would need:
>
> | Surface | Why not | What it needs |
> |---|---|---|
> | `download` | Streaming artefact bytes into a model's context is the wrong representation, and super-cli itself writes to a file rather than emitting them. The sha256 from `arm_artifact_info` is what identifies an artefact. | A bounded *text* read (SBOM, manifest) with a content-type check — a different tool, not this one. |
> | `set_properties` / `delete_properties` | Properties drive promotion gates; an agent flipping one could promote an unscanned artefact. | Artifactory's property syntax is `key=v1,v2;key2=v3` — super-cli's `arm.joinComma` and `arm.joinSemicolon` are those two joins. |
> | `copy` / `move` | Organisational blast radius, and no agent workflow needs them yet. | `POST /artifactory/api/{copy,move}/{path}?to=` |
> | Xray (`summary`, `violations`, `scanArtifact`) | Nothing in OSCAR's pipeline uses it and it may not be licensed on this tenant. | A second `path_prefix` for `/xray/`, which is why the client is written with a single `api_root` that a second base would extend rather than replace. `scanArtifact` builds its `componentID` as `concatstring3(repo, "://", path)` — byte-confirmed, but not Xray's documented component-ID form, so verify against a live instance before trusting it. |
> | Permission targets | An audit surface, not an SDLC one, and it hands a model a map of access control. | `GET /artifactory/api/v2/security/permissions[/{name}]` |
> | `storage_info` | Operator telemetry; nothing in the agent loop consumes it. | `GET /artifactory/api/storageinfo` |

- [ ] **Step 6: Full suite and drift check**

Run:
```bash
. .venv/bin/activate && python scripts/sync_shared.py && pytest -q
```
Expected: PASS, no drift failures.

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-arm/ tests/
git commit -m "feat: add ARM skill, contract verification, and deployment docs"
```

---

## Self-Review

**Spec coverage.** Six tools deliver the scope agreed after reviewing the OSCAR scripts: AQL search, artefact and folder metadata, properties, repository enumeration, and two gated writes. Every endpoint is byte-confirmed from `out/func-strings.txt` and cross-checked against a working shell implementation.

**What each source contributed.**

| Source | Contribution |
|---|---|
| super-cli `internal/arm` | Endpoint set, header matrix, `X-Checksum-Deploy`, AQL's `text/plain`, the `?properties=` comma join |
| `bulk_upload_verify.sh` | Checksum-deploy **with a fallback**, three checksums rather than one, response-checksum verification |
| `cleanup_artifactory_releases.sh` | The AQL `include` permission rule, folder-delete semantics, 404-as-success, the typed-confirmation instinct |
| The `302` investigation | Cloudflare Access as a distinct failure layer, and certificate pre-flight |
| `ericsson-jira` | Auth resolution, `_redact`, argument-scoped approvals, edge-failure classification |
| New here | `aql.py`'s non-semantic rewriting, `deploy_root` confinement, symlink-resolving path checks |

**Deliberately out of scope**, tracked in the README rather than dropped: `download`, `set_properties`/`delete_properties`, `copy`/`move`, all three Xray methods, permission targets, `storage_info`.

**Type consistency.** `ArmError(category, *, remediation=None)` is raised throughout and `ConnectorError` never escapes (Task 4's `_as_arm_error`). `_repo`, `_path`, `_bounded_max`, `_mapping`, `_storage_path`, `_redact`, `_resolve_source`, `_file_checksums`, `_verify_deploy` are each introduced in the task that first needs them. `size` is an `int` everywhere despite Artifactory sending a string, pinned by `test_size_is_an_integer_even_though_artifactory_sends_a_string` — a string size would make every downstream comparison silently wrong.

**Three decisions a reviewer should push on.**

1. **`aql.py` rewrites the caller's query.** Rewriting caller input is normally wrong. It is defensible here only because both edits are provably non-semantic: adding fields to an `include` changes which columns return, never which rows match; appending `.limit()` is the bound the connector is responsible for. If either stopped being true the argument collapses. The alternative — surfacing Artifactory's raw 400 — was rejected because the error text names three fields with no explanation of why they are required, and every caller would hit it once.

2. **`ssl._ssl._test_decode_cert` is a private stdlib API.** It is the only way to read a PEM's validity window without adding `cryptography`. It is isolated in one function behind a broad `except` so a CPython change degrades to "cannot read the certificate" rather than breaking the connector. If the project ever takes `cryptography` for another reason, replace it.

3. **`delete` reaches into `client._classify`.** The alternative is a second copy of the status mapping *including* the Cloudflare Access detection, which is exactly the duplication Plan 2 existed to remove. Promoting `_classify` to public is a rename and no behaviour change.

**One thing this plan does not know.** Whether this instance accepts `Authorization: Bearer` is unverified — the client certificate expired before it could be tested, so every probe returned an edge redirect rather than an Artifactory answer. `auth_mode` exists to carry that uncertainty rather than hide it, and Task 3 tests both branches. This is a genuine gap, not a hedge: when the certificate is renewed, one `curl` settles it and one of the two branches can be deleted.

**A limitation that is a real limitation.** `deploy` sends a local file the model named. The primary control is the approval prompt, which shows the absolute source path first because that is the argument a reviewer most needs to see; `deploy_root` adds subtree confinement when set. Neither is a substitute for the reviewer actually reading the path. This is not solvable inside the connector — a tool that publishes a caller-chosen local file to a shared repository is inherently a decision a human should make, which is why it is gated rather than made clever.
