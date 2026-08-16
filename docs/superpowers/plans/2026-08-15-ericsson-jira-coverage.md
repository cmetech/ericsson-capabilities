# Ericsson Jira Connector Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Take the Ericsson Jira connector from 4 tools to 14 — adding the discovery operations an agent needs to act safely, then the write operations that let it act at all — so it can transition, assign, edit, label, create and link issues instead of only reading and commenting.

**Architecture:** Every new tool follows the connector's existing six-point wiring: a JSON Schema in `tools.py:SCHEMAS`, an argument allowlist in `invoke()`, a dispatch entry, a `JiraOperations` method, `plugin.yaml` registration, and — for writes — `_WRITE_TOOLS` plus a `pre_tool_call` approval hook. Writes reuse the connector's existing reconciliation pattern: after an ambiguous outcome, re-read to establish what actually happened rather than guessing. Discovery lands before writes because you cannot safely transition an issue without first listing its valid transitions.

**Tech Stack:** Python 3.11+, the shared `_common` package from Plan 2, pytest via `./bootstrap.sh`.

**Spec:** `PLUGIN-GAP-ANALYSIS.md` (super-cli analysis workspace) §1.1 and §4 Tier 2 items 5–6, with endpoint detail in `SUPER-CLI-ARCHITECTURE.md` (super-cli analysis workspace) §6.3.

**Repo:** `ericsson-capabilities` (this repo)

**Depends on:** Plan 2 (`2026-08-15-ericsson-shared-transport.md`) must be complete — Task 1 consumes `_common.envelope` and `_common.guardrails`.

## Global Constraints

- **Tests:** `./bootstrap.sh` (or `. .venv/bin/activate && pytest -q`) must pass before vendoring — `CLAUDE.md:106`.
- **Branch-placement invariant:** this plan stops at the `ericsson-capabilities` commit. Vendoring to `hermes-agent/base` is a separate operation — `CLAUDE.md:32-34`.
- **Errors never carry remote or secret text.** Raise `JiraError(category)`; the category must exist in `SAFE_ERROR_MESSAGES` or it silently coerces to `"transient"`.
- **Redact before returning.** Any string that originates from Jira and reaches the model goes through `JiraOperations._redact` — `operations.py:222`.
- **Validate with `type(x) is not bool` / explicit regex,** matching the connector's existing strictness. Truthiness checks are not sufficient here.
- **Every write is admission-gated.** A tool in `_WRITE_TOOLS` without a matching `require_write_approval` branch is a silent hole: `_has_write_admission` would reject it, but the operator would never see a prompt explaining what is being approved.
- **Jira Cloud and Data Center both supported.** Where a body differs between REST v3 and v2, pass `json_body_by_version={"3": ..., "2": ...}` — `client.rest_json` handles the negotiation.
- **Six-point checklist per tool.** `SCHEMAS` → `allowed_arguments` → `handlers` → `JiraOperations` method → `plugin.yaml` `provides_tools` → (writes only) `_WRITE_TOOLS` + approval branch. Missing any one produces a tool that is invisible, un-callable, or un-approvable.

## Decisions Taken

| # | Decision | Rationale |
|---|---|---|
| D1 | Discovery tools ship before write tools | You cannot safely transition without listing valid transitions, nor set a custom field without resolving its ID. Writes without discovery force hardcoding per deployment. |
| D2 | Writes use `require_explicit_intent` from Plan 2 | Closes F3. `dry_run` defaulting to False means an agent that says nothing performs the write. |
| D3 | Reads adopt `result_envelope`; existing four tools are migrated too | A mixed contract — some tools enveloped, some not — is worse than either. Task 1 migrates the incumbents. |
| D4 | Label add/remove is one tool with an `operation` parameter | Two near-identical tools double the schema surface an agent must reason over for no gain. |
| D5 | `jira_update_fields` accepts a bounded field map, not arbitrary JSON | super-cli exposes `--json` raw passthrough. Here that would let a model write any field including security level; an allowlist is the safer default. |
| D6 | Writes reconcile after ambiguity wherever a read can confirm | The connector already does this in `add_comment` (`operations.py:562-574`) and it is the correct answer to `write_ambiguous`. |

## File Structure

| File | Responsibility |
|---|---|
| **Modify** `plugins/ericsson-jira/__init__.py` | Remediation in error JSON, generalised write approval, new tools in `_WRITE_TOOLS`. |
| **Modify** `plugins/ericsson-jira/tools.py` | `SCHEMAS`, `allowed_arguments`, `handlers` for 10 new tools. |
| **Modify** `plugins/ericsson-jira/operations.py` | 10 new `JiraOperations` methods plus shared validation helpers. |
| **Modify** `plugins/ericsson-jira/models.py` | `SAFE_ERROR_MESSAGES` entries for new categories. |
| **Modify** `plugins/ericsson-jira/plugin.yaml` | `provides_tools` list. |
| **Create** `tests/test_jira_discovery.py` | Discovery tool tests. |
| **Create** `tests/test_jira_writes.py` | Write tool tests including approval and reconciliation. |

---

### Task 1: Connector contract — remediation, envelope, generalised approval

**Files:**
- Modify: `plugins/ericsson-jira/__init__.py`
- Modify: `plugins/ericsson-jira/operations.py`
- Test: `tests/test_jira_contract.py` (create)

**Interfaces:**
- Consumes: `_common.envelope.result_envelope`, `JiraError.remediation` (Plan 2 Task 9)
- Produces:
  - error JSON gains `"remediation"` when present
  - `WRITE_APPROVALS: dict[str, Callable[[dict], str]]` in `__init__.py` — maps a tool name to a human-readable approval summary
  - list-returning operations return `result_envelope(...)` shape

Do this first: it changes the shape every later tool returns, and retrofitting ten tools afterwards is ten chances to miss one.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jira_contract.py`:

```python
"""Connector-level contract: error shape, envelope shape, approval coverage."""

import json
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
sys.path.insert(0, str(PLUGIN))

import __init__ as jira_plugin  # noqa: E402
from models import JiraError  # noqa: E402


class FakeCtx:
    def __init__(self):
        self.tools = {}
        self.hooks = {}

    def configuration(self):
        return object()

    def register_tool(self, *, name, toolset, schema, handler, check_fn, emoji):
        self.tools[name] = handler

    def register_hook(self, event, fn):
        self.hooks[event] = fn


class TestErrorShape:
    def test_error_json_includes_remediation_when_present(self, monkeypatch):
        err = JiraError("authentication", remediation="Update the Jira token.")
        monkeypatch.setattr(
            jira_plugin.jira_tools,
            "invoke",
            lambda *a, **k: (_ for _ in ()).throw(err),
        )
        ctx = FakeCtx()
        jira_plugin.register(ctx)
        payload = json.loads(ctx.tools["jira_get_issue"]({"key": "ABC-1"}))
        assert payload["success"] is False
        assert payload["error"]["remediation"] == "Update the Jira token."

    def test_remediation_omitted_when_absent(self, monkeypatch):
        monkeypatch.setattr(
            jira_plugin.jira_tools,
            "invoke",
            lambda *a, **k: (_ for _ in ()).throw(JiraError("transient")),
        )
        ctx = FakeCtx()
        jira_plugin.register(ctx)
        payload = json.loads(ctx.tools["jira_get_issue"]({"key": "ABC-1"}))
        assert "remediation" not in payload["error"]


class TestApprovalCoverage:
    def test_every_write_tool_has_an_approval_summary(self):
        """A write tool with no approval branch is a silent hole: the host
        would refuse it with a bare 'permission' error and the operator would
        never see what was being asked."""
        missing = sorted(
            jira_plugin._WRITE_TOOLS - set(jira_plugin.WRITE_APPROVALS)
        )
        assert not missing, f"write tools with no approval summary: {missing}"

    def test_approval_summary_names_the_tool_and_survives_bad_args(self):
        for name, summarise in jira_plugin.WRITE_APPROVALS.items():
            text = summarise({})
            assert isinstance(text, str) and text
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_contract.py -q`
Expected: FAIL — `AttributeError: module has no attribute 'WRITE_APPROVALS'`

- [ ] **Step 3: Generalise approval and add remediation in `__init__.py`**

Replace the hardcoded `require_write_approval` body with a table-driven version, and add the `remediation` field to the error JSON.

Add near `_WRITE_TOOLS`:

```python
def _arg(args: dict, name: str) -> str:
    """Render one argument for an approval prompt, safely and bounded."""
    value = args.get(name) if isinstance(args, dict) else None
    return json.dumps(value, ensure_ascii=True)[:512]


WRITE_APPROVALS = {
    "jira_add_comment": lambda a: (
        f"Issue: {_arg(a, 'key')}\nBody: {_arg(a, 'body')}"
    ),
}
```

Replace `require_write_approval` with:

```python
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
                f"Approve Ericsson Jira change: {tool_name}\n"
                f"{summarise(args if isinstance(args, dict) else {})}"
            ),
            "rule_key": (
                f"{tool_name}:"
                f"{hashlib.sha256(canonical_args.encode('utf-8')).hexdigest()}"
            ),
        }
```

In the `except JiraError as exc:` block, replace the error payload with:

```python
            except JiraError as exc:
                error = {
                    "category": exc.category,
                    "message": SAFE_ERROR_MESSAGES[exc.category],
                }
                remediation = getattr(exc, "remediation", None)
                if remediation:
                    error["remediation"] = remediation
                return _json({"success": False, "error": error})
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_contract.py -q`
Expected: PASS (4 tests)

- [ ] **Step 5: Migrate the four incumbent read tools to the envelope**

In `operations.py`, add the import and wrap the two list-returning results.

```python
if __package__:
    from ._common.envelope import result_envelope
else:
    from _common.envelope import result_envelope
```

`search_issues` currently returns `{"issues": ..., "truncated": ..., "warnings": [...]}`. Replace that return with:

```python
        return result_envelope(
            selected[:max_results],
            total=total,
            truncated=truncated,
            hint=(
                "More issues match this JQL. Raise max_results or narrow the "
                "query." if truncated else None
            ),
            untrusted=True,
        )
```

`my_tickets` returns a bare list; wrap it the same way with `untrusted=True`.
`get_issue` returns a single normalized issue — leave its shape, but add the
warning key, because descriptions and comments are the highest-risk injection
surface in this connector:

```python
        result["content_warning"] = UNTRUSTED_CONTENT_WARNING
```

importing `UNTRUSTED_CONTENT_WARNING` alongside `result_envelope`.

- [ ] **Step 6: Update the existing tests for the new shape**

Run: `. .venv/bin/activate && pytest tests/ -q -k jira`
Existing assertions on `payload["issues"]` become `payload["items"]`, and
`payload["warnings"]` becomes `payload["truncated"]` plus `payload["hint"]`.
Update them. If more than a handful need editing, stop — the envelope was
meant to be adopted at the boundary, not threaded through internals.

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-jira/__init__.py plugins/ericsson-jira/operations.py tests/
git commit -m "feat: add remediation to Jira errors, adopt result envelope, generalise write approval"
```

---

### Task 2: `jira_list_fields` — custom field discovery

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `plugin.yaml`
- Test: `tests/test_jira_discovery.py` (create)

**Interfaces:**
- Consumes: `client.rest_json`, `result_envelope`
- Produces: `JiraOperations.list_fields(*, custom_only: bool = False, max_results: int = 100) -> dict`

**This is the sleeper gap.** Without it an agent cannot resolve `customfield_10234` → "Story Points", so every custom-field interaction must be hardcoded per deployment. It also unblocks Task 8.

Endpoint: `GET /rest/api/2/field` (super-cli `jira.ListFields`).

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jira_discovery.py`:

```python
"""Jira discovery tools: fields, project metadata, transitions, users."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
sys.path.insert(0, str(PLUGIN))

from models import JiraError  # noqa: E402
from operations import JiraOperations  # noqa: E402


class FakeClient:
    """Records calls and replays scripted rest_json results."""

    def __init__(self, results):
        self.results = list(results)
        self.calls = []

        class _Auth:
            authorization = "Bearer secret-token-value"
            rest_api_version = "auto"

        self.auth = _Auth()

    def rest_json(self, method, resource, **kwargs):
        self.calls.append((method, resource, kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TestListFields:
    def test_returns_id_name_and_custom_flag(self):
        client = FakeClient([[
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10234", "name": "Story Points", "custom": True},
        ]])
        result = JiraOperations(client).list_fields()
        assert client.calls[0][:2] == ("GET", "field")
        assert result["items"] == [
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10234", "name": "Story Points", "custom": True},
        ]
        assert result["returned"] == 2

    def test_custom_only_filters(self):
        client = FakeClient([[
            {"id": "summary", "name": "Summary", "custom": False},
            {"id": "customfield_10234", "name": "Story Points", "custom": True},
        ]])
        result = JiraOperations(client).list_fields(custom_only=True)
        assert [f["id"] for f in result["items"]] == ["customfield_10234"]

    def test_truncates_and_reports_total(self):
        client = FakeClient([[
            {"id": f"f{i}", "name": f"Field {i}", "custom": False}
            for i in range(10)
        ]])
        result = JiraOperations(client).list_fields(max_results=3)
        assert result["returned"] == 3
        assert result["total"] == 10
        assert result["truncated"] is True
        assert result["hint"]

    def test_malformed_payload_raises(self):
        client = FakeClient([{"not": "a list"}])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).list_fields()
        assert excinfo.value.category == "invalid_remote_data"

    def test_entries_without_an_id_are_skipped(self):
        client = FakeClient([[{"name": "Nameless"}, {"id": "ok", "name": "OK"}]])
        result = JiraOperations(client).list_fields()
        assert [f["id"] for f in result["items"]] == ["ok"]

    def test_bad_max_results_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).list_fields(max_results=0)

    def test_field_names_are_redacted(self):
        """Field names are remote text; a token echoed into one must not
        reach the model."""
        client = FakeClient([[
            {"id": "f1", "name": "Bearer secret-token-value", "custom": False}
        ]])
        result = JiraOperations(client).list_fields()
        assert "secret-token-value" not in result["items"][0]["name"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q`
Expected: FAIL — `AttributeError: 'JiraOperations' object has no attribute 'list_fields'`

- [ ] **Step 3: Implement the operation**

Add to `plugins/ericsson-jira/operations.py`:

```python
    def list_fields(
        self, *, custom_only: bool = False, max_results: int = 100
    ) -> dict[str, Any]:
        """List Jira fields so custom field IDs can be resolved by name.

        Without this an agent cannot map customfield_10234 to "Story Points",
        so every custom-field interaction has to be hardcoded per Jira
        deployment.
        """
        if type(custom_only) is not bool:
            raise JiraError("invalid_input")
        if type(max_results) is not int or not 1 <= max_results <= 200:
            raise JiraError("invalid_input")
        payload = self.client.rest_json("GET", "field")
        if not isinstance(payload, list):
            raise JiraError("invalid_remote_data")
        fields: list[dict[str, Any]] = []
        for entry in payload:
            if not isinstance(entry, Mapping):
                continue
            identifier = _bounded_string(entry.get("id"), 255)
            if not identifier:
                continue
            is_custom = bool(entry.get("custom"))
            if custom_only and not is_custom:
                continue
            fields.append(
                {
                    "id": self._redact(identifier),
                    "name": self._redact(_bounded_string(entry.get("name"), 255))
                    or "",
                    "custom": is_custom,
                }
            )
        total = len(fields)
        truncated = total > max_results
        return result_envelope(
            fields[:max_results],
            total=total,
            truncated=truncated,
            hint=(
                "More fields exist. Raise max_results, or pass custom_only "
                "to narrow the list." if truncated else None
            ),
        )
```

Ensure `Mapping` is imported from `typing` at the top of the file if it is not already.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Wire the tool**

In `tools.py`, add to `SCHEMAS`:

```python
    "jira_list_fields": {
        "name": "jira_list_fields",
        "description": (
            "List Jira field IDs and names, so custom field identifiers such "
            "as customfield_10234 can be resolved before reading or writing "
            "them."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "custom_only": {"type": "boolean", "default": False},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 200},
            },
            "additionalProperties": False,
        },
    },
```

Add to `allowed_arguments`:

```python
        "jira_list_fields": {"custom_only", "max_results"},
```

Add to `handlers`:

```python
            "jira_list_fields": operations.list_fields,
```

In `plugin.yaml`, append `jira_list_fields` to `provides_tools`.

- [ ] **Step 6: Verify the tool is reachable end to end**

Run: `. .venv/bin/activate && pytest tests/ -q -k jira`
Expected: PASS. Then confirm the wiring is complete:

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-jira")
import tools, yaml
declared = set(yaml.safe_load(open("plugins/ericsson-jira/plugin.yaml"))["provides_tools"])
schemas = set(tools.SCHEMAS)
print("schema-only:", sorted(schemas - declared))
print("manifest-only:", sorted(declared - schemas))
assert schemas == declared
print("OK", len(schemas), "tools")
PY
```
Expected: `OK 5 tools`, with both difference lists empty. A tool present in one and not the other is invisible or dangling.

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-jira/ tests/test_jira_discovery.py
git commit -m "feat: add jira_list_fields for custom field discovery"
```

---

### Task 3: `jira_get_project` — issue types, components, versions

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `plugin.yaml`
- Test: `tests/test_jira_discovery.py`

**Interfaces:**
- Produces: `JiraOperations.get_project(key: str) -> dict`

Endpoint: `GET /rest/api/2/project/{key}` (super-cli `jira.GetProject`). Returns the issue types, components and versions that `jira_create_issue` (Task 10) needs in order to submit a valid issue.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_discovery.py`:

```python
class TestGetProject:
    def test_returns_metadata_needed_to_create_an_issue(self):
        client = FakeClient([{
            "key": "PROJ",
            "name": "Project",
            "id": "10000",
            "projectTypeKey": "software",
            "archived": False,
            "issueTypes": [
                {"id": "1", "name": "Bug", "subtask": False},
                {"id": "5", "name": "Sub-task", "subtask": True},
            ],
            "components": [{"id": "9", "name": "API"}],
            "versions": [{"id": "3", "name": "1.2.0", "released": False}],
        }])
        result = JiraOperations(client).get_project("PROJ")
        assert client.calls[0][:2] == ("GET", "project/PROJ")
        assert result["key"] == "PROJ"
        assert [t["name"] for t in result["issue_types"]] == ["Bug", "Sub-task"]
        assert result["issue_types"][1]["subtask"] is True
        assert [c["name"] for c in result["components"]] == ["API"]
        assert [v["name"] for v in result["versions"]] == ["1.2.0"]

    def test_missing_collections_default_to_empty(self):
        client = FakeClient([{"key": "PROJ", "name": "Project", "id": "1"}])
        result = JiraOperations(client).get_project("PROJ")
        assert result["issue_types"] == []
        assert result["components"] == []
        assert result["versions"] == []

    def test_invalid_key_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).get_project("../admin")
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_non_mapping_payload_raises(self):
        client = FakeClient([["not", "a", "mapping"]])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).get_project("PROJ")
        assert excinfo.value.category == "invalid_remote_data"

    def test_project_text_is_redacted(self):
        client = FakeClient([
            {"key": "PROJ", "name": "Bearer secret-token-value", "id": "1"}
        ])
        result = JiraOperations(client).get_project("PROJ")
        assert "secret-token-value" not in result["name"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q -k GetProject`
Expected: FAIL — `AttributeError: 'JiraOperations' object has no attribute 'get_project'`

- [ ] **Step 3: Implement**

Add to `operations.py`, alongside the existing `_ISSUE_KEY` regex:

```python
_PROJECT_KEY = re.compile(r"^[A-Za-z][A-Za-z0-9_]{0,60}$")
```

```python
    def _named_entries(self, raw: Any, *, extra: tuple[str, ...] = ()) -> list:
        """Normalize a Jira list of {id, name, ...} objects, bounded."""
        entries = []
        if not isinstance(raw, list):
            return entries
        for item in raw[:200]:
            if not isinstance(item, Mapping):
                continue
            identifier = _bounded_string(item.get("id"), 128)
            if not identifier:
                continue
            entry = {
                "id": identifier,
                "name": self._redact(_bounded_string(item.get("name"), 255)) or "",
            }
            for key in extra:
                entry[key] = bool(item.get(key))
            entries.append(entry)
        return entries

    def get_project(self, key: str) -> dict[str, Any]:
        """Fetch the project metadata needed to compose a valid issue.

        Issue types, components and versions are all required to create or
        edit an issue correctly, and all three are per-project.
        """
        if not isinstance(key, str) or _PROJECT_KEY.fullmatch(key) is None:
            raise JiraError("invalid_input")
        payload = self.client.rest_json("GET", f"project/{key}")
        if not isinstance(payload, Mapping):
            raise JiraError("invalid_remote_data")
        return {
            "key": self._redact(_bounded_string(payload.get("key"), 128)) or "",
            "name": self._redact(_bounded_string(payload.get("name"), 255)) or "",
            "id": _bounded_string(payload.get("id"), 128) or "",
            "project_type": _bounded_string(payload.get("projectTypeKey"), 64)
            or "",
            "archived": bool(payload.get("archived")),
            "issue_types": self._named_entries(
                payload.get("issueTypes"), extra=("subtask",)
            ),
            "components": self._named_entries(payload.get("components")),
            "versions": self._named_entries(
                payload.get("versions"), extra=("released",)
            ),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q`
Expected: PASS (12 tests)

- [ ] **Step 5: Wire the tool**

`SCHEMAS`:

```python
    "jira_get_project": {
        "name": "jira_get_project",
        "description": (
            "Fetch one Jira project's issue types, components and versions — "
            "the metadata required to create or edit an issue in it."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "minLength": 1, "maxLength": 64}
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_get_project": {"key"},`
`handlers`: `"jira_get_project": operations.get_project,`
`plugin.yaml`: append `jira_get_project`.

- [ ] **Step 6: Verify wiring and commit**

Run the schema/manifest parity check from Task 2 Step 6 (expect `OK 6 tools`), then:

```bash
git add plugins/ericsson-jira/ tests/test_jira_discovery.py
git commit -m "feat: add jira_get_project for issue type and component discovery"
```

---

### Task 4: `jira_list_transitions` — valid next states

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `plugin.yaml`
- Test: `tests/test_jira_discovery.py`

**Interfaces:**
- Produces: `JiraOperations.list_transitions(key: str) -> dict`

Endpoint: `GET /rest/api/2/issue/{key}/transitions` (super-cli `jira.GetTransitions`). **Task 6 depends on this** — a transition ID is workflow-specific and cannot be guessed.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_discovery.py`:

```python
class TestListTransitions:
    def test_returns_id_name_and_target_status(self):
        client = FakeClient([{
            "transitions": [
                {"id": "21", "name": "In Progress",
                 "to": {"name": "In Progress", "id": "3"}},
                {"id": "31", "name": "Done", "to": {"name": "Done", "id": "6"}},
            ]
        }])
        result = JiraOperations(client).list_transitions("ABC-1")
        assert client.calls[0][:2] == ("GET", "issue/ABC-1/transitions")
        assert result["items"] == [
            {"id": "21", "name": "In Progress", "to_status": "In Progress"},
            {"id": "31", "name": "Done", "to_status": "Done"},
        ]

    def test_empty_transitions_is_valid_not_an_error(self):
        """A closed issue legitimately offers no transitions."""
        client = FakeClient([{"transitions": []}])
        result = JiraOperations(client).list_transitions("ABC-1")
        assert result["items"] == []
        assert result["returned"] == 0

    def test_missing_transitions_key_raises(self):
        client = FakeClient([{"unexpected": True}])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).list_transitions("ABC-1")
        assert excinfo.value.category == "invalid_remote_data"

    def test_invalid_issue_key_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).list_transitions("not a key")
        assert client.calls == []

    def test_transition_without_an_id_is_skipped(self):
        client = FakeClient([{
            "transitions": [{"name": "Broken"}, {"id": "5", "name": "Fine"}]
        }])
        result = JiraOperations(client).list_transitions("ABC-1")
        assert [t["id"] for t in result["items"]] == ["5"]
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q -k ListTransitions`
Expected: FAIL — no attribute `list_transitions`

- [ ] **Step 3: Implement**

```python
    def list_transitions(self, key: str) -> dict[str, Any]:
        """List the workflow transitions currently available on an issue.

        Transition IDs are workflow-specific and cannot be guessed, so this
        is a hard prerequisite for jira_transition_issue.
        """
        if not isinstance(key, str) or _ISSUE_KEY.fullmatch(key) is None:
            raise JiraError("invalid_input")
        payload = self.client.rest_json("GET", f"issue/{key}/transitions")
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("transitions"), list
        ):
            raise JiraError("invalid_remote_data")
        transitions = []
        for item in payload["transitions"][:200]:
            if not isinstance(item, Mapping):
                continue
            identifier = _bounded_string(item.get("id"), 128)
            if not identifier:
                continue
            target = item.get("to")
            transitions.append(
                {
                    "id": identifier,
                    "name": self._redact(_bounded_string(item.get("name"), 255))
                    or "",
                    "to_status": self._redact(
                        _name(target) if isinstance(target, Mapping) else None
                    )
                    or "",
                }
            )
        return result_envelope(transitions, total=len(transitions))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q`
Expected: PASS (17 tests)

- [ ] **Step 5: Wire the tool**

`SCHEMAS`:

```python
    "jira_list_transitions": {
        "name": "jira_list_transitions",
        "description": (
            "List the workflow transitions currently available on a Jira "
            "issue. Required before transitioning: transition IDs are "
            "workflow-specific and cannot be guessed."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "minLength": 3, "maxLength": 128}
            },
            "required": ["key"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_list_transitions": {"key"},`
`handlers`: `"jira_list_transitions": operations.list_transitions,`
`plugin.yaml`: append `jira_list_transitions`.

- [ ] **Step 6: Verify wiring and commit**

Parity check expects `OK 7 tools`.

```bash
git add plugins/ericsson-jira/ tests/test_jira_discovery.py
git commit -m "feat: add jira_list_transitions"
```

---

### Task 5: `jira_search_assignable_users`

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `plugin.yaml`
- Test: `tests/test_jira_discovery.py`

**Interfaces:**
- Produces: `JiraOperations.search_assignable_users(project: str, query: str = "", *, max_results: int = 25) -> dict`

Endpoint: `GET /rest/api/2/user/assignable/search?project=&username=&maxResults=` (super-cli `jira.SearchAssignableUsers`). **Task 7 depends on this** — assignment needs a valid account name, and not every user can be assigned in every project.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_discovery.py`:

```python
class TestSearchAssignableUsers:
    def test_returns_names_and_display_names(self):
        client = FakeClient([[
            {"name": "jsmith", "displayName": "J Smith",
             "emailAddress": "j@x.test", "active": True},
        ]])
        result = JiraOperations(client).search_assignable_users("PROJ", "smith")
        method, resource, kwargs = client.calls[0]
        assert method == "GET"
        assert resource == "user/assignable/search"
        assert kwargs["params"]["project"] == "PROJ"
        assert kwargs["params"]["username"] == "smith"
        assert result["items"][0]["name"] == "jsmith"
        assert result["items"][0]["display_name"] == "J Smith"

    def test_inactive_users_are_excluded(self):
        client = FakeClient([[
            {"name": "gone", "displayName": "Gone", "active": False},
            {"name": "here", "displayName": "Here", "active": True},
        ]])
        result = JiraOperations(client).search_assignable_users("PROJ")
        assert [u["name"] for u in result["items"]] == ["here"]

    def test_email_is_omitted_when_absent(self):
        client = FakeClient([[{"name": "u", "displayName": "U", "active": True}]])
        result = JiraOperations(client).search_assignable_users("PROJ")
        assert "email" not in result["items"][0]

    def test_invalid_project_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).search_assignable_users("../x")
        assert client.calls == []

    def test_non_list_payload_raises(self):
        client = FakeClient([{"users": []}])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).search_assignable_users("PROJ")
        assert excinfo.value.category == "invalid_remote_data"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q -k Assignable`
Expected: FAIL — no attribute `search_assignable_users`

- [ ] **Step 3: Implement**

```python
    def search_assignable_users(
        self, project: str, query: str = "", *, max_results: int = 25
    ) -> dict[str, Any]:
        """Find users who can actually be assigned issues in one project.

        Assignability is per-project permission, not a global user list, so
        a name from elsewhere in Jira may still be rejected on assignment.
        """
        if not isinstance(project, str) or _PROJECT_KEY.fullmatch(project) is None:
            raise JiraError("invalid_input")
        if not isinstance(query, str) or len(query) > 255:
            raise JiraError("invalid_input")
        if type(max_results) is not int or not 1 <= max_results <= 100:
            raise JiraError("invalid_input")
        payload = self.client.rest_json(
            "GET",
            "user/assignable/search",
            params={
                "project": project,
                "username": query,
                "maxResults": max_results,
            },
        )
        if not isinstance(payload, list):
            raise JiraError("invalid_remote_data")
        users = []
        for item in payload[:max_results]:
            if not isinstance(item, Mapping) or not item.get("active", True):
                continue
            name = _bounded_string(item.get("name"), 255)
            if not name:
                continue
            user = {
                "name": self._redact(name) or "",
                "display_name": self._redact(
                    _bounded_string(item.get("displayName"), 255)
                )
                or "",
            }
            email = _bounded_string(item.get("emailAddress"), _MAX_EMAIL_LEN)
            if email:
                user["email"] = self._redact(email)
            users.append(user)
        return result_envelope(users, total=len(users))
```

Add `_MAX_EMAIL_LEN = 320` near the other module constants.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_discovery.py -q`
Expected: PASS (22 tests)

- [ ] **Step 5: Wire the tool**

`SCHEMAS`:

```python
    "jira_search_assignable_users": {
        "name": "jira_search_assignable_users",
        "description": (
            "Find users who can be assigned issues in one Jira project. "
            "Assignability is a per-project permission, so a valid Jira user "
            "may still be unassignable here."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "minLength": 1, "maxLength": 64},
                "query": {"type": "string", "maxLength": 255},
                "max_results": {"type": "integer", "minimum": 1, "maximum": 100},
            },
            "required": ["project"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_search_assignable_users": {"project", "query", "max_results"},`
`handlers`: `"jira_search_assignable_users": operations.search_assignable_users,`
`plugin.yaml`: append `jira_search_assignable_users`.

- [ ] **Step 6: Verify wiring and commit**

Parity check expects `OK 8 tools`.

```bash
git add plugins/ericsson-jira/ tests/test_jira_discovery.py
git commit -m "feat: add jira_search_assignable_users"
```

---

### Task 6: `jira_transition_issue` — the first write

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_jira_writes.py` (create)

**Interfaces:**
- Consumes: `require_explicit_intent` (Plan 2 Task 7), `list_transitions` (Task 4)
- Produces: `JiraOperations.transition_issue(key, transition_id, *, dry_run=False, confirm=False) -> dict`

Endpoint: `POST /rest/api/2/issue/{key}/transitions` with `{"transition":{"id":"<id>"}}`. This establishes the write pattern every later task follows: explicit intent, dry-run preview, and **reconciliation after ambiguity** by re-reading the issue's status.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_jira_writes.py`:

```python
"""Jira write tools: intent gating, dry-run, approval, reconciliation."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-jira"
sys.path.insert(0, str(PLUGIN))

from models import JiraError  # noqa: E402
from operations import JiraOperations  # noqa: E402


class FakeClient:
    def __init__(self, results):
        self.results = list(results)
        self.calls = []

        class _Auth:
            authorization = "Bearer secret-token-value"
            rest_api_version = "auto"

        self.auth = _Auth()

    def rest_json(self, method, resource, **kwargs):
        self.calls.append((method, resource, kwargs))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


class TestTransitionIntent:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).transition_issue("ABC-1", "21")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_previews_without_writing(self):
        client = FakeClient([])
        result = JiraOperations(client).transition_issue(
            "ABC-1", "21", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["issue_key"] == "ABC-1"
        assert result["transition_id"] == "21"
        assert client.calls == []

    def test_both_flags_is_refused(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).transition_issue(
                "ABC-1", "21", dry_run=True, confirm=True
            )


class TestTransitionExecution:
    def test_confirm_posts_the_transition(self):
        client = FakeClient([None])
        result = JiraOperations(client).transition_issue(
            "ABC-1", "21", confirm=True
        )
        method, resource, kwargs = client.calls[0]
        assert (method, resource) == ("POST", "issue/ABC-1/transitions")
        assert kwargs["json_body"] == {"transition": {"id": "21"}}
        assert result["ok"] is True
        assert result["dry_run"] is False

    def test_invalid_issue_key_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).transition_issue(
                "bad key", "21", confirm=True
            )
        assert client.calls == []

    def test_non_numeric_transition_id_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).transition_issue(
                "ABC-1", "21; DROP", confirm=True
            )
        assert client.calls == []


class TestTransitionReconciliation:
    def test_ambiguous_write_that_landed_is_reported_as_reconciled(self):
        """A timeout does not mean the transition failed. Re-read the issue
        before telling the caller anything."""
        client = FakeClient([
            JiraError("write_ambiguous"),
            {"key": "ABC-1", "fields": {"status": {"name": "Done"}}},
        ])
        result = JiraOperations(client).transition_issue(
            "ABC-1", "31", confirm=True, expected_status="Done"
        )
        assert result["ok"] is True
        assert result["reconciled"] is True

    def test_ambiguous_write_that_did_not_land_still_raises(self):
        client = FakeClient([
            JiraError("write_ambiguous"),
            {"key": "ABC-1", "fields": {"status": {"name": "To Do"}}},
        ])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).transition_issue(
                "ABC-1", "31", confirm=True, expected_status="Done"
            )
        assert excinfo.value.category == "write_ambiguous"

    def test_no_reconciliation_without_an_expected_status(self):
        """With nothing to compare against, re-reading proves nothing."""
        client = FakeClient([JiraError("write_ambiguous")])
        with pytest.raises(JiraError):
            JiraOperations(client).transition_issue("ABC-1", "31", confirm=True)
        assert len(client.calls) == 1

    def test_other_errors_are_not_reconciled(self):
        client = FakeClient([JiraError("permission")])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).transition_issue(
                "ABC-1", "31", confirm=True, expected_status="Done"
            )
        assert excinfo.value.category == "permission"
        assert len(client.calls) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q`
Expected: FAIL — no attribute `transition_issue`

- [ ] **Step 3: Implement**

Add the import and the operation to `operations.py`:

```python
if __package__:
    from ._common.guardrails import require_explicit_intent
else:
    from _common.guardrails import require_explicit_intent
```

```python
_NUMERIC_ID = re.compile(r"^[0-9]{1,19}$")
```

```python
    def _status_name(self, key: str) -> str | None:
        """Read one issue's current status name, for reconciliation."""
        payload = self.client.rest_json("GET", f"issue/{key}")
        if not isinstance(payload, Mapping):
            return None
        fields = payload.get("fields")
        if not isinstance(fields, Mapping):
            return None
        status = fields.get("status")
        return _name(status) if isinstance(status, Mapping) else None

    def transition_issue(
        self,
        key: str,
        transition_id: str,
        *,
        dry_run: bool = False,
        confirm: bool = False,
        expected_status: str | None = None,
    ) -> dict[str, Any]:
        """Move an issue through one workflow transition.

        transition_id comes from jira_list_transitions; it is workflow
        specific and cannot be guessed. expected_status enables
        reconciliation: if the POST outcome is ambiguous, the issue is
        re-read and the transition is treated as successful only when the
        status actually changed to what was expected.
        """
        if not isinstance(key, str) or _ISSUE_KEY.fullmatch(key) is None:
            raise JiraError("invalid_input")
        if (
            not isinstance(transition_id, str)
            or _NUMERIC_ID.fullmatch(transition_id) is None
        ):
            raise JiraError("invalid_input")
        if expected_status is not None and (
            not isinstance(expected_status, str) or len(expected_status) > 255
        ):
            raise JiraError("invalid_input")

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"Jira issue {key}"
        )
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "issue_key": key,
                "transition_id": transition_id,
                "reconciled": False,
            }

        body = {"transition": {"id": transition_id}}
        try:
            self.client.rest_json(
                "POST", f"issue/{key}/transitions", json_body=body
            )
        except JiraError as exc:
            if exc.category != "write_ambiguous" or expected_status is None:
                raise
            if self._status_name(key) != expected_status:
                raise
            return {
                "ok": True,
                "dry_run": False,
                "issue_key": key,
                "transition_id": transition_id,
                "reconciled": True,
            }
        return {
            "ok": True,
            "dry_run": False,
            "issue_key": key,
            "transition_id": transition_id,
            "reconciled": False,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q`
Expected: PASS (10 tests)

- [ ] **Step 5: Wire the tool and its approval**

`tools.py` `SCHEMAS`:

```python
    "jira_transition_issue": {
        "name": "jira_transition_issue",
        "description": (
            "Move a Jira issue through one workflow transition. Call "
            "jira_list_transitions first to obtain a valid transition_id. "
            "Requires dry_run or confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "minLength": 3, "maxLength": 128},
                "transition_id": {
                    "type": "string", "pattern": "^[0-9]{1,19}$"
                },
                "expected_status": {"type": "string", "maxLength": 255},
                "dry_run": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["key", "transition_id"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_transition_issue": {"key", "transition_id", "expected_status", "dry_run", "confirm"},`
`handlers`: `"jira_transition_issue": operations.transition_issue,`

`__init__.py` — add to `_WRITE_TOOLS` and `WRITE_APPROVALS`:

```python
_WRITE_TOOLS = frozenset({"jira_add_comment", "jira_transition_issue"})
```

```python
    "jira_transition_issue": lambda a: (
        f"Issue: {_arg(a, 'key')}\nTransition: {_arg(a, 'transition_id')}"
    ),
```

`plugin.yaml`: append `jira_transition_issue`.

- [ ] **Step 6: Verify approval coverage and wiring**

Run: `. .venv/bin/activate && pytest tests/test_jira_contract.py tests/test_jira_writes.py -q`
Expected: PASS. `test_every_write_tool_has_an_approval_summary` is what catches a `_WRITE_TOOLS` entry with no prompt.

Parity check expects `OK 9 tools`.

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-jira/ tests/test_jira_writes.py
git commit -m "feat: add jira_transition_issue with intent gating and reconciliation"
```

---

### Task 7: `jira_assign_issue`

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_jira_writes.py`

**Interfaces:**
- Produces: `JiraOperations.assign_issue(key, assignee, *, dry_run=False, confirm=False) -> dict`

Endpoint: `PUT /rest/api/2/issue/{key}/assignee` with `{"name": "<username>"}` on Data Center. Jira Cloud uses `{"accountId": ...}`, so this is a `json_body_by_version` case.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_writes.py`:

```python
class TestAssignIssue:
    def test_neither_flag_is_refused(self):
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).assign_issue("ABC-1", "jsmith")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient([])
        result = JiraOperations(client).assign_issue(
            "ABC-1", "jsmith", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["assignee"] == "jsmith"
        assert client.calls == []

    def test_confirm_puts_the_assignee(self):
        client = FakeClient([None])
        result = JiraOperations(client).assign_issue(
            "ABC-1", "jsmith", confirm=True
        )
        method, resource, kwargs = client.calls[0]
        assert (method, resource) == ("PUT", "issue/ABC-1/assignee")
        assert kwargs["json_body_by_version"]["2"] == {"name": "jsmith"}
        assert kwargs["json_body_by_version"]["3"] == {"accountId": "jsmith"}
        assert result["ok"] is True

    def test_unassign_uses_null(self):
        client = FakeClient([None])
        JiraOperations(client).assign_issue("ABC-1", None, confirm=True)
        kwargs = client.calls[0][2]
        assert kwargs["json_body_by_version"]["2"] == {"name": None}

    def test_ambiguous_write_reconciles_via_current_assignee(self):
        client = FakeClient([
            JiraError("write_ambiguous"),
            {"key": "ABC-1", "fields": {"assignee": {"name": "jsmith"}}},
        ])
        result = JiraOperations(client).assign_issue(
            "ABC-1", "jsmith", confirm=True
        )
        assert result["reconciled"] is True

    def test_ambiguous_write_that_did_not_land_raises(self):
        client = FakeClient([
            JiraError("write_ambiguous"),
            {"key": "ABC-1", "fields": {"assignee": {"name": "someone-else"}}},
        ])
        with pytest.raises(JiraError):
            JiraOperations(client).assign_issue("ABC-1", "jsmith", confirm=True)

    def test_overlong_assignee_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).assign_issue("ABC-1", "x" * 300, confirm=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q -k Assign`
Expected: FAIL — no attribute `assign_issue`

- [ ] **Step 3: Implement**

```python
    def _assignee_name(self, key: str) -> str | None:
        payload = self.client.rest_json("GET", f"issue/{key}")
        if not isinstance(payload, Mapping):
            return None
        fields = payload.get("fields")
        if not isinstance(fields, Mapping):
            return None
        assignee = fields.get("assignee")
        if not isinstance(assignee, Mapping):
            return None
        return _bounded_string(assignee.get("name"), 255)

    def assign_issue(
        self,
        key: str,
        assignee: str | None,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Assign an issue, or unassign it by passing assignee=None.

        Data Center identifies users by name; Cloud uses accountId. Both
        bodies are supplied so client.rest_json can negotiate.
        """
        if not isinstance(key, str) or _ISSUE_KEY.fullmatch(key) is None:
            raise JiraError("invalid_input")
        if assignee is not None and (
            not isinstance(assignee, str) or not assignee or len(assignee) > 255
        ):
            raise JiraError("invalid_input")

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"Jira issue {key}"
        )
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "issue_key": key,
                "assignee": assignee,
                "reconciled": False,
            }

        try:
            self.client.rest_json(
                "PUT",
                f"issue/{key}/assignee",
                json_body={"name": assignee},
                json_body_by_version={
                    "3": {"accountId": assignee},
                    "2": {"name": assignee},
                },
            )
        except JiraError as exc:
            if exc.category != "write_ambiguous":
                raise
            if self._assignee_name(key) != assignee:
                raise
            return {
                "ok": True,
                "dry_run": False,
                "issue_key": key,
                "assignee": assignee,
                "reconciled": True,
            }
        return {
            "ok": True,
            "dry_run": False,
            "issue_key": key,
            "assignee": assignee,
            "reconciled": False,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q`
Expected: PASS (17 tests)

- [ ] **Step 5: Wire the tool and its approval**

`SCHEMAS`:

```python
    "jira_assign_issue": {
        "name": "jira_assign_issue",
        "description": (
            "Assign a Jira issue to a user, or unassign it with assignee "
            "null. Use jira_search_assignable_users to find a valid name — "
            "assignability is a per-project permission. Requires dry_run or "
            "confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "minLength": 3, "maxLength": 128},
                "assignee": {"type": ["string", "null"], "maxLength": 255},
                "dry_run": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["key", "assignee"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_assign_issue": {"key", "assignee", "dry_run", "confirm"},`
`handlers`: `"jira_assign_issue": operations.assign_issue,`

`__init__.py`: add `"jira_assign_issue"` to `_WRITE_TOOLS` and:

```python
    "jira_assign_issue": lambda a: (
        f"Issue: {_arg(a, 'key')}\nAssignee: {_arg(a, 'assignee')}"
    ),
```

`plugin.yaml`: append `jira_assign_issue`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 10 tools`.

```bash
git add plugins/ericsson-jira/ tests/test_jira_writes.py
git commit -m "feat: add jira_assign_issue with Cloud and Data Center bodies"
```

---

### Task 8: `jira_update_fields`

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_jira_writes.py`

**Interfaces:**
- Consumes: `list_fields` (Task 2) for the caller to resolve custom field IDs
- Produces: `JiraOperations.update_fields(key, fields, *, dry_run=False, confirm=False) -> dict`

Endpoint: `PUT /rest/api/2/issue/{key}` with `{"fields": {...}}`. Per D5 this takes a bounded map rather than super-cli's raw `--json` passthrough — a model should not be able to write arbitrary fields including security level.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_writes.py`:

```python
WRITABLE = {"summary", "description", "priority", "duedate", "labels"}


class TestUpdateFields:
    def test_neither_flag_is_refused(self):
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).update_fields("ABC-1", {"summary": "New"})
        assert excinfo.value.category == "confirmation_required"

    def test_dry_run_echoes_the_change(self):
        client = FakeClient([])
        result = JiraOperations(client).update_fields(
            "ABC-1", {"summary": "New"}, dry_run=True
        )
        assert result["dry_run"] is True
        assert result["fields"] == {"summary": "New"}
        assert client.calls == []

    def test_confirm_puts_the_fields(self):
        client = FakeClient([None])
        JiraOperations(client).update_fields(
            "ABC-1", {"summary": "New"}, confirm=True
        )
        method, resource, kwargs = client.calls[0]
        assert (method, resource) == ("PUT", "issue/ABC-1")
        assert kwargs["json_body"] == {"fields": {"summary": "New"}}

    def test_custom_field_is_allowed(self):
        client = FakeClient([None])
        JiraOperations(client).update_fields(
            "ABC-1", {"customfield_10234": 5}, confirm=True
        )
        assert client.calls[0][2]["json_body"] == {
            "fields": {"customfield_10234": 5}
        }

    def test_field_outside_the_allowlist_is_rejected(self):
        """A model must not be able to set security level or reporter."""
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).update_fields(
                "ABC-1", {"security": {"id": "1"}}, confirm=True
            )
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_empty_field_map_is_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).update_fields("ABC-1", {}, confirm=True)

    def test_too_many_fields_is_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).update_fields(
                "ABC-1", {f"customfield_{i}": i for i in range(30)}, confirm=True
            )

    def test_non_mapping_fields_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).update_fields("ABC-1", ["summary"], confirm=True)
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q -k UpdateFields`
Expected: FAIL — no attribute `update_fields`

- [ ] **Step 3: Implement**

Add near `SAFE_FIELDS` in `operations.py`:

```python
# Fields a tool caller may write. Deliberately narrower than what Jira
# accepts: security level, reporter and project must not be settable by a
# model, and super-cli's raw --json passthrough has no equivalent here.
WRITABLE_FIELDS = frozenset(
    {"summary", "description", "priority", "duedate", "labels", "environment"}
)
_CUSTOM_FIELD = re.compile(r"^customfield_[0-9]{1,19}$")
_MAX_WRITABLE_FIELDS = 20
```

```python
    def update_fields(
        self,
        key: str,
        fields: Any,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Set bounded fields on an issue.

        Only WRITABLE_FIELDS and customfield_* identifiers are accepted.
        Resolve custom field IDs with jira_list_fields first.
        """
        if not isinstance(key, str) or _ISSUE_KEY.fullmatch(key) is None:
            raise JiraError("invalid_input")
        if not isinstance(fields, Mapping) or not fields:
            raise JiraError("invalid_input")
        if len(fields) > _MAX_WRITABLE_FIELDS:
            raise JiraError("invalid_input")
        for name in fields:
            if not isinstance(name, str):
                raise JiraError("invalid_input")
            if name not in WRITABLE_FIELDS and _CUSTOM_FIELD.fullmatch(name) is None:
                raise JiraError("invalid_input")

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"Jira issue {key}"
        )
        payload = dict(fields)
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "issue_key": key,
                "fields": payload,
            }
        self.client.rest_json("PUT", f"issue/{key}", json_body={"fields": payload})
        return {
            "ok": True,
            "dry_run": False,
            "issue_key": key,
            "fields": payload,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q`
Expected: PASS (25 tests)

- [ ] **Step 5: Wire the tool and its approval**

`SCHEMAS`:

```python
    "jira_update_fields": {
        "name": "jira_update_fields",
        "description": (
            "Set fields on a Jira issue. Accepts summary, description, "
            "priority, duedate, labels, environment, and customfield_* IDs "
            "resolved via jira_list_fields. Requires dry_run or confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "minLength": 3, "maxLength": 128},
                "fields": {"type": "object", "minProperties": 1,
                           "maxProperties": 20},
                "dry_run": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["key", "fields"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_update_fields": {"key", "fields", "dry_run", "confirm"},`
`handlers`: `"jira_update_fields": operations.update_fields,`

`__init__.py`: add to `_WRITE_TOOLS` and:

```python
    "jira_update_fields": lambda a: (
        f"Issue: {_arg(a, 'key')}\nFields: {_arg(a, 'fields')}"
    ),
```

`plugin.yaml`: append `jira_update_fields`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 11 tools`.

```bash
git add plugins/ericsson-jira/ tests/test_jira_writes.py
git commit -m "feat: add jira_update_fields with a write allowlist"
```

---

### Task 9: `jira_manage_labels`

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_jira_writes.py`

**Interfaces:**
- Produces: `JiraOperations.manage_labels(key, operation, labels, *, dry_run=False, confirm=False) -> dict`

Endpoint: `PUT /rest/api/2/issue/{key}` with `{"update": {"labels": [{"add": "x"}, {"remove": "y"}]}}`. Per D4 this is one tool with an `operation` parameter rather than two near-identical tools.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_writes.py`:

```python
class TestManageLabels:
    def test_add_builds_add_operations(self):
        client = FakeClient([None])
        JiraOperations(client).manage_labels(
            "ABC-1", "add", ["alpha", "beta"], confirm=True
        )
        assert client.calls[0][2]["json_body"] == {
            "update": {"labels": [{"add": "alpha"}, {"add": "beta"}]}
        }

    def test_remove_builds_remove_operations(self):
        client = FakeClient([None])
        JiraOperations(client).manage_labels(
            "ABC-1", "remove", ["alpha"], confirm=True
        )
        assert client.calls[0][2]["json_body"] == {
            "update": {"labels": [{"remove": "alpha"}]}
        }

    def test_unknown_operation_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).manage_labels(
                "ABC-1", "replace", ["x"], confirm=True
            )
        assert client.calls == []

    def test_neither_flag_is_refused(self):
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).manage_labels("ABC-1", "add", ["x"])
        assert excinfo.value.category == "confirmation_required"

    def test_dry_run_previews(self):
        client = FakeClient([])
        result = JiraOperations(client).manage_labels(
            "ABC-1", "add", ["x"], dry_run=True
        )
        assert result["dry_run"] is True
        assert result["labels"] == ["x"]
        assert client.calls == []

    def test_empty_label_list_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).manage_labels("ABC-1", "add", [], confirm=True)

    def test_label_with_whitespace_rejected(self):
        """Jira labels cannot contain spaces; catching it here gives a better
        error than a 400 from the server."""
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).manage_labels(
                "ABC-1", "add", ["has space"], confirm=True
            )

    def test_too_many_labels_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).manage_labels(
                "ABC-1", "add", [f"l{i}" for i in range(60)], confirm=True
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q -k ManageLabels`
Expected: FAIL — no attribute `manage_labels`

- [ ] **Step 3: Implement**

```python
_LABEL = re.compile(r"^[^\s]{1,255}$")
_MAX_LABELS = 50
```

```python
    def manage_labels(
        self,
        key: str,
        operation: str,
        labels: Any,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Add or remove labels on an issue.

        One tool with an operation parameter rather than two near-identical
        tools: the schema surface a model must reason over stays smaller for
        no loss of capability.
        """
        if not isinstance(key, str) or _ISSUE_KEY.fullmatch(key) is None:
            raise JiraError("invalid_input")
        if operation not in {"add", "remove"}:
            raise JiraError("invalid_input")
        if (
            not isinstance(labels, list)
            or not labels
            or len(labels) > _MAX_LABELS
            or any(
                not isinstance(label, str) or _LABEL.fullmatch(label) is None
                for label in labels
            )
        ):
            raise JiraError("invalid_input")

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"Jira issue {key}"
        )
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "issue_key": key,
                "operation": operation,
                "labels": list(labels),
            }
        self.client.rest_json(
            "PUT",
            f"issue/{key}",
            json_body={
                "update": {"labels": [{operation: label} for label in labels]}
            },
        )
        return {
            "ok": True,
            "dry_run": False,
            "issue_key": key,
            "operation": operation,
            "labels": list(labels),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q`
Expected: PASS (33 tests)

- [ ] **Step 5: Wire the tool and its approval**

`SCHEMAS`:

```python
    "jira_manage_labels": {
        "name": "jira_manage_labels",
        "description": (
            "Add or remove labels on a Jira issue. Labels cannot contain "
            "whitespace. Requires dry_run or confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "key": {"type": "string", "minLength": 3, "maxLength": 128},
                "operation": {"type": "string", "enum": ["add", "remove"]},
                "labels": {
                    "type": "array",
                    "items": {"type": "string", "minLength": 1, "maxLength": 255},
                    "minItems": 1,
                    "maxItems": 50,
                },
                "dry_run": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["key", "operation", "labels"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_manage_labels": {"key", "operation", "labels", "dry_run", "confirm"},`
`handlers`: `"jira_manage_labels": operations.manage_labels,`

`__init__.py`: add to `_WRITE_TOOLS` and:

```python
    "jira_manage_labels": lambda a: (
        f"Issue: {_arg(a, 'key')}\n"
        f"{_arg(a, 'operation')} labels: {_arg(a, 'labels')}"
    ),
```

`plugin.yaml`: append `jira_manage_labels`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 12 tools`.

```bash
git add plugins/ericsson-jira/ tests/test_jira_writes.py
git commit -m "feat: add jira_manage_labels"
```

---

### Task 10: `jira_create_issue`

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_jira_writes.py`

**Interfaces:**
- Consumes: `get_project` (Task 3) for valid issue type names
- Produces: `JiraOperations.create_issue(project, issue_type, summary, *, description=None, dry_run=False, confirm=False) -> dict`

Endpoint: `POST /rest/api/2/issue` with `{"fields": {...}}`. Description is ADF on Cloud and plain text on Data Center, so it needs `json_body_by_version` — the same split the connector already handles in `add_comment`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_writes.py`:

```python
class TestCreateIssue:
    def test_neither_flag_is_refused(self):
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).create_issue("PROJ", "Bug", "Broken")
        assert excinfo.value.category == "confirmation_required"

    def test_dry_run_previews_without_creating(self):
        client = FakeClient([])
        result = JiraOperations(client).create_issue(
            "PROJ", "Bug", "Broken", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["key"] is None
        assert client.calls == []

    def test_confirm_posts_and_returns_the_new_key(self):
        client = FakeClient([{"id": "10001", "key": "PROJ-42"}])
        result = JiraOperations(client).create_issue(
            "PROJ", "Bug", "Broken", confirm=True
        )
        method, resource, kwargs = client.calls[0]
        assert (method, resource) == ("POST", "issue")
        fields = kwargs["json_body"]["fields"]
        assert fields["project"] == {"key": "PROJ"}
        assert fields["issuetype"] == {"name": "Bug"}
        assert fields["summary"] == "Broken"
        assert result["key"] == "PROJ-42"

    def test_description_uses_adf_on_v3_and_text_on_v2(self):
        client = FakeClient([{"id": "1", "key": "PROJ-1"}])
        JiraOperations(client).create_issue(
            "PROJ", "Bug", "Broken", description="Details", confirm=True
        )
        by_version = client.calls[0][2]["json_body_by_version"]
        assert by_version["2"]["fields"]["description"] == "Details"
        assert by_version["3"]["fields"]["description"]["type"] == "doc"

    def test_response_without_a_key_raises(self):
        client = FakeClient([{"id": "10001"}])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).create_issue(
                "PROJ", "Bug", "Broken", confirm=True
            )
        assert excinfo.value.category == "invalid_remote_data"

    def test_blank_summary_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).create_issue("PROJ", "Bug", "   ", confirm=True)

    def test_invalid_project_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).create_issue("../x", "Bug", "S", confirm=True)
        assert client.calls == []

    def test_ambiguous_create_is_not_reconciled(self):
        """A create has no idempotency key, so a re-read cannot distinguish
        'my issue' from 'a similar issue someone else filed'. Reporting
        ambiguity is the only honest answer."""
        client = FakeClient([JiraError("write_ambiguous")])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).create_issue(
                "PROJ", "Bug", "Broken", confirm=True
            )
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q -k CreateIssue`
Expected: FAIL — no attribute `create_issue`

- [ ] **Step 3: Implement**

```python
    @staticmethod
    def _adf(text: str) -> dict[str, Any]:
        """Wrap plain text as an Atlassian Document Format paragraph."""
        return {
            "type": "doc",
            "version": 1,
            "content": [
                {"type": "paragraph", "content": [{"type": "text", "text": text}]}
            ],
        }

    def create_issue(
        self,
        project: str,
        issue_type: str,
        summary: str,
        *,
        description: str | None = None,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Create one issue.

        Deliberately not reconciled after an ambiguous outcome: a create has
        no idempotency key, so re-reading cannot distinguish the issue this
        call made from a similar one filed by somebody else. Reporting
        ambiguity is the only honest answer, and the caller can search.
        """
        if not isinstance(project, str) or _PROJECT_KEY.fullmatch(project) is None:
            raise JiraError("invalid_input")
        if (
            not isinstance(issue_type, str)
            or not issue_type.strip()
            or len(issue_type) > 255
        ):
            raise JiraError("invalid_input")
        if (
            not isinstance(summary, str)
            or not summary.strip()
            or len(summary) > 255
        ):
            raise JiraError("invalid_input")
        if description is not None and (
            not isinstance(description, str) or len(description) > 32_000
        ):
            raise JiraError("invalid_input")

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"a new issue in {project}"
        )
        base_fields: dict[str, Any] = {
            "project": {"key": project},
            "issuetype": {"name": issue_type},
            "summary": summary,
        }
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "key": None,
                "project": project,
                "issue_type": issue_type,
                "summary": summary,
            }

        v2_fields = dict(base_fields)
        v3_fields = dict(base_fields)
        if description is not None:
            v2_fields["description"] = description
            v3_fields["description"] = self._adf(description)
        payload = self.client.rest_json(
            "POST",
            "issue",
            json_body={"fields": v2_fields},
            json_body_by_version={
                "3": {"fields": v3_fields},
                "2": {"fields": v2_fields},
            },
        )
        if not isinstance(payload, Mapping):
            raise JiraError("invalid_remote_data")
        created_key = _bounded_string(payload.get("key"), 128)
        if not created_key:
            raise JiraError("invalid_remote_data")
        return {
            "ok": True,
            "dry_run": False,
            "key": created_key,
            "project": project,
            "issue_type": issue_type,
            "summary": summary,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q`
Expected: PASS (41 tests)

- [ ] **Step 5: Wire the tool and its approval**

`SCHEMAS`:

```python
    "jira_create_issue": {
        "name": "jira_create_issue",
        "description": (
            "Create one Jira issue. Use jira_get_project first to obtain a "
            "valid issue type name for the project. Requires dry_run or "
            "confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "project": {"type": "string", "minLength": 1, "maxLength": 64},
                "issue_type": {"type": "string", "minLength": 1, "maxLength": 255},
                "summary": {"type": "string", "minLength": 1, "maxLength": 255},
                "description": {"type": "string", "maxLength": 32000},
                "dry_run": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["project", "issue_type", "summary"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`: `"jira_create_issue": {"project", "issue_type", "summary", "description", "dry_run", "confirm"},`
`handlers`: `"jira_create_issue": operations.create_issue,`

`__init__.py`: add to `_WRITE_TOOLS` and:

```python
    "jira_create_issue": lambda a: (
        f"Project: {_arg(a, 'project')}\n"
        f"Type: {_arg(a, 'issue_type')}\n"
        f"Summary: {_arg(a, 'summary')}"
    ),
```

`plugin.yaml`: append `jira_create_issue`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 13 tools`.

```bash
git add plugins/ericsson-jira/ tests/test_jira_writes.py
git commit -m "feat: add jira_create_issue"
```

---

### Task 11: `jira_link_issues` and final verification

**Files:**
- Modify: `plugins/ericsson-jira/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_jira_writes.py`

**Interfaces:**
- Produces:
  - `JiraOperations.list_link_types() -> dict`
  - `JiraOperations.link_issues(inward, outward, link_type, *, dry_run=False, confirm=False) -> dict`

Endpoints: `GET /rest/api/2/issueLinkType` and `POST /rest/api/2/issueLink`. Link types are per-instance configuration, so listing them ships in the same task as the tool that consumes them.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_jira_writes.py`:

```python
class TestLinkTypes:
    def test_lists_names_and_directions(self):
        client = FakeClient([{
            "issueLinkTypes": [
                {"id": "10000", "name": "Blocks",
                 "inward": "is blocked by", "outward": "blocks"},
            ]
        }])
        result = JiraOperations(client).list_link_types()
        assert client.calls[0][:2] == ("GET", "issueLinkType")
        assert result["items"][0]["name"] == "Blocks"
        assert result["items"][0]["inward"] == "is blocked by"
        assert result["items"][0]["outward"] == "blocks"

    def test_missing_collection_raises(self):
        client = FakeClient([{"unexpected": True}])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).list_link_types()
        assert excinfo.value.category == "invalid_remote_data"


class TestLinkIssues:
    def test_neither_flag_is_refused(self):
        client = FakeClient([])
        with pytest.raises(JiraError) as excinfo:
            JiraOperations(client).link_issues("ABC-1", "ABC-2", "Blocks")
        assert excinfo.value.category == "confirmation_required"

    def test_confirm_posts_the_link(self):
        client = FakeClient([None])
        JiraOperations(client).link_issues(
            "ABC-1", "ABC-2", "Blocks", confirm=True
        )
        method, resource, kwargs = client.calls[0]
        assert (method, resource) == ("POST", "issueLink")
        assert kwargs["json_body"] == {
            "type": {"name": "Blocks"},
            "inwardIssue": {"key": "ABC-1"},
            "outwardIssue": {"key": "ABC-2"},
        }

    def test_dry_run_previews(self):
        client = FakeClient([])
        result = JiraOperations(client).link_issues(
            "ABC-1", "ABC-2", "Blocks", dry_run=True
        )
        assert result["dry_run"] is True
        assert client.calls == []

    def test_linking_an_issue_to_itself_is_rejected(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).link_issues(
                "ABC-1", "ABC-1", "Blocks", confirm=True
            )
        assert client.calls == []

    def test_invalid_keys_rejected_without_a_request(self):
        client = FakeClient([])
        with pytest.raises(JiraError):
            JiraOperations(client).link_issues(
                "not a key", "ABC-2", "Blocks", confirm=True
            )
        assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q -k Link`
Expected: FAIL — no attribute `list_link_types`

- [ ] **Step 3: Implement**

```python
    def list_link_types(self) -> dict[str, Any]:
        """List the issue link types configured on this Jira instance."""
        payload = self.client.rest_json("GET", "issueLinkType")
        if not isinstance(payload, Mapping) or not isinstance(
            payload.get("issueLinkTypes"), list
        ):
            raise JiraError("invalid_remote_data")
        types = []
        for item in payload["issueLinkTypes"][:200]:
            if not isinstance(item, Mapping):
                continue
            name = _bounded_string(item.get("name"), 255)
            if not name:
                continue
            types.append(
                {
                    "id": _bounded_string(item.get("id"), 128) or "",
                    "name": self._redact(name) or "",
                    "inward": self._redact(
                        _bounded_string(item.get("inward"), 255)
                    )
                    or "",
                    "outward": self._redact(
                        _bounded_string(item.get("outward"), 255)
                    )
                    or "",
                }
            )
        return result_envelope(types, total=len(types))

    def link_issues(
        self,
        inward: str,
        outward: str,
        link_type: str,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Link two issues.

        Direction matters and is not symmetric: with type "Blocks", inward
        is blocked by outward. Use jira_list_link_types to see both phrasings.
        """
        for key in (inward, outward):
            if not isinstance(key, str) or _ISSUE_KEY.fullmatch(key) is None:
                raise JiraError("invalid_input")
        if inward == outward:
            raise JiraError("invalid_input")
        if (
            not isinstance(link_type, str)
            or not link_type.strip()
            or len(link_type) > 255
        ):
            raise JiraError("invalid_input")

        execute = require_explicit_intent(
            dry_run=dry_run,
            confirm=confirm,
            action=f"a link between {inward} and {outward}",
        )
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "inward": inward,
                "outward": outward,
                "link_type": link_type,
            }
        self.client.rest_json(
            "POST",
            "issueLink",
            json_body={
                "type": {"name": link_type},
                "inwardIssue": {"key": inward},
                "outwardIssue": {"key": outward},
            },
        )
        return {
            "ok": True,
            "dry_run": False,
            "inward": inward,
            "outward": outward,
            "link_type": link_type,
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_jira_writes.py -q`
Expected: PASS (49 tests)

- [ ] **Step 5: Wire both tools**

`SCHEMAS`:

```python
    "jira_list_link_types": {
        "name": "jira_list_link_types",
        "description": (
            "List the issue link types configured on this Jira instance, "
            "with their inward and outward phrasings."
        ),
        "parameters": {
            "type": "object", "properties": {}, "additionalProperties": False,
        },
    },
    "jira_link_issues": {
        "name": "jira_link_issues",
        "description": (
            "Link two Jira issues. Direction is not symmetric: with type "
            "'Blocks', the inward issue is blocked by the outward issue. "
            "Requires dry_run or confirm."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "inward": {"type": "string", "minLength": 3, "maxLength": 128},
                "outward": {"type": "string", "minLength": 3, "maxLength": 128},
                "link_type": {"type": "string", "minLength": 1, "maxLength": 255},
                "dry_run": {"type": "boolean", "default": False},
                "confirm": {"type": "boolean", "default": False},
            },
            "required": ["inward", "outward", "link_type"],
            "additionalProperties": False,
        },
    },
```

`allowed_arguments`:

```python
        "jira_list_link_types": set(),
        "jira_link_issues": {"inward", "outward", "link_type", "dry_run", "confirm"},
```

`handlers`:

```python
            "jira_list_link_types": operations.list_link_types,
            "jira_link_issues": operations.link_issues,
```

`__init__.py`: add `"jira_link_issues"` to `_WRITE_TOOLS` and:

```python
    "jira_link_issues": lambda a: (
        f"Link: {_arg(a, 'inward')} -> {_arg(a, 'outward')}\n"
        f"Type: {_arg(a, 'link_type')}"
    ),
```

`plugin.yaml`: append `jira_list_link_types` and `jira_link_issues`.

- [ ] **Step 6: Full verification**

Run the schema/manifest parity check — expect `OK 15 tools` — then the whole suite:

```bash
. .venv/bin/activate && pytest -q
```
Expected: PASS.

Then confirm every write tool is gated and every gated tool is approvable:

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-jira")
import __init__ as p, tools
writes = p._WRITE_TOOLS
approvals = set(p.WRITE_APPROVALS)
assert writes == approvals, f"mismatch: {writes ^ approvals}"
mutating = {n for n, s in tools.SCHEMAS.items()
            if "confirm" in s["parameters"]["properties"]}
assert mutating <= writes, f"mutating but ungated: {sorted(mutating - writes)}"
print("OK", len(writes), "gated writes,", len(tools.SCHEMAS), "tools total")
PY
```
Expected: `OK 6 gated writes, 15 tools total`. A tool exposing `confirm` but absent from `_WRITE_TOOLS` would mutate Jira with no host approval — this check is what catches that.

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-jira/ tests/
git commit -m "feat: add jira_link_issues and jira_list_link_types"
```

---

## Self-Review

**Spec coverage.** Against `PLUGIN-GAP-ANALYSIS.md` §1.1: transition (Task 6), assign (Task 7), update fields (Task 8), labels (Task 9), create issue (Task 10), link issues + link types (Task 11), field discovery (Task 2), project/component/version discovery (Task 3), transitions listing (Task 4), assignable users (Task 5). Tier 2 recommendation 6's ordering — discovery before writes — is honoured: Tasks 2–5 precede 6–11.

**Deliberately out of scope**, tracked rather than dropped:
- **Agile: boards, sprints, sprint moves.** Three more endpoints (`/rest/agile/1.0/…`) and a separate API surface. They serve sprint planning rather than the defect and ticket-research flows these connectors exist for, so they belong in their own follow-up.
- **`jira_list_comments` as a standalone paginated tool.** `get_issue` already returns recent comments inline; a separate tool is only worth adding if a flow needs deep comment history.
- **F4 (cross-invocation throttle).** Still pending from Plan 2, and now more pressing: this plan takes the connector from 4 tools to 15, so there is materially more surface for an agent to loop on.
- **Priorities listing.** `get_project` covers the metadata needed to create an issue; priority names are instance-global and rarely change, so a dedicated tool earns its place only if a flow needs it.

**Type consistency.** `JiraOperations` methods all take `key`/`project` first and keyword-only `dry_run`/`confirm`. Every write returns a dict containing `ok` and `dry_run`; those that can reconcile also return `reconciled`. `result_envelope` is used by every list-returning operation (Tasks 2, 4, 5, 11) and never by single-object or write operations. `_bounded_string`, `_name`, `_redact`, `_ISSUE_KEY` are the connector's existing helpers; `_PROJECT_KEY`, `_NUMERIC_ID`, `_LABEL`, `_CUSTOM_FIELD`, `WRITABLE_FIELDS`, `_MAX_LABELS`, `_MAX_WRITABLE_FIELDS`, `_MAX_EMAIL_LEN` and `_adf` are introduced here, each in the task that first uses it.

**Two asymmetries a reviewer should check deliberately, because both are judgement calls:**

1. **`create_issue` does not reconcile** while transition and assign do. A create has no idempotency key, so re-reading cannot distinguish the issue this call made from a similar one filed by someone else — inventing a match would be worse than reporting ambiguity. `test_ambiguous_create_is_not_reconciled` pins the decision.
2. **`update_fields` and `manage_labels` do not reconcile** either. They could — re-read and compare — but a partial field update is genuinely ambiguous to interpret, and a wrong "succeeded" is more dangerous than an honest "unknown". If a flow needs it, add reconciliation for the single-field case only.
