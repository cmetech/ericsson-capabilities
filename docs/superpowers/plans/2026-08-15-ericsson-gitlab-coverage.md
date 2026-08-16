# Ericsson GitLab Connector Coverage Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the GitLab connector's review loop and CI gap — take it from 17 tools to 28 so an agent can reply to and resolve merge-request discussions, approve and merge, read job logs, and retry failed pipelines, instead of only observing them. Fix the connector's approval-granularity defect first, because everything added here makes it more dangerous.

**Architecture:** Every new tool follows the connector's existing wiring: a `_schema(...)` entry in `tools.py:SCHEMAS`, a dispatch branch in `invoke()`, and a `GitLabOperations` method. Unlike the Jira connector, `invoke()` derives its argument allowlist from the schema itself, so there is no parallel allowlist dict to keep in sync. Writes go through `_WRITE_TOOLS` plus a per-tool approval summary, and use `require_explicit_intent` from Plan 2. Read tools return the Plan 2 result envelope.

**Tech Stack:** Python 3.11+, the shared `_common` package from Plan 2, pytest via `./bootstrap.sh`.

**Spec:** `PLUGIN-GAP-ANALYSIS.md` (super-cli analysis workspace) §1.2 and §4 Tier 2 items 7–8, with endpoint detail in `SUPER-CLI-ARCHITECTURE.md` (super-cli analysis workspace) §6.5.

**Repo:** `ericsson-capabilities` (this repo)

**Depends on:** Plan 2 (`2026-08-15-ericsson-shared-transport.md`) — Tasks here consume `_common.guardrails.require_explicit_intent` and `_common.envelope.result_envelope`, and rely on the migrated `GitLabClient`.

## Global Constraints

- **Tests:** `./bootstrap.sh` (or `. .venv/bin/activate && pytest -q`) must pass before vendoring — `CLAUDE.md:106`.
- **Branch-placement invariant:** this plan stops at the `ericsson-capabilities` commit — `CLAUDE.md:32-34`.
- **Errors never carry remote or secret text.** Raise `GitLabError(category)`; the category must exist in `SAFE_ERROR_MESSAGES` or it silently coerces to `"transient"`.
- **`invoke()` validates from the schema.** A property absent from a tool's schema is rejected before dispatch, so the schema is the single source of truth for arguments. Do not add a parallel allowlist.
- **Every write is admission-gated *and* argument-scoped.** See Task 1 — a `rule_key` that is not argument-derived turns one approval into a standing grant.
- **Bounded output.** Job logs and diffs are unbounded server-side; every new read tool caps what it returns and says so through the envelope.
- **Four-point checklist per tool.** `SCHEMAS` → `invoke()` branch → `GitLabOperations` method → `plugin.yaml` `provides_tools`; writes add `_WRITE_TOOLS` + an approval summary.

## Decisions Taken

| # | Decision | Rationale |
|---|---|---|
| D1 | Fix approval granularity before adding any write tool | Adding `merge` on top of a blanket `rule_key` would let one approval authorise every future merge. Order matters here. |
| D2 | `gitlab_job_log` ships before the mutating CI tools | It is what an agent actually needs to diagnose a failure; retry without diagnosis is just noise. |
| D3 | Job log is tail-biased and byte-capped | Failures are at the end. Returning the head of a 50 MB log burns context and answers nothing. |
| D4 | Discussion reply and resolve are separate tools | Resolving is a judgement about whether a thread is settled; replying is not. Fusing them would let an agent silently close threads while commenting. |
| D5 | `merge` requires an expected SHA | GitLab accepts `sha` to refuse the merge if the branch moved. Without it an agent can merge a commit it never reviewed. |
| D6 | No `gitlab_cancel_pipeline` on the first pass | Cancelling someone else's running pipeline is disruptive and rarely what an agent should decide. Retry covers the recovery case. |

## File Structure

| File | Responsibility |
|---|---|
| **Modify** `plugins/ericsson-gitlab/__init__.py` | Argument-scoped approvals, per-tool summaries, `_WRITE_TOOLS`. |
| **Modify** `plugins/ericsson-gitlab/tools.py` | `SCHEMAS` and `invoke()` branches for 11 new tools. |
| **Modify** `plugins/ericsson-gitlab/operations.py` | 11 new `GitLabOperations` methods. |
| **Modify** `plugins/ericsson-gitlab/models.py` | `SAFE_ERROR_MESSAGES` entry for `confirmation_required`. |
| **Modify** `plugins/ericsson-gitlab/plugin.yaml` | `provides_tools`. |
| **Create** `tests/test_gitlab_approval.py` | Approval granularity and summary coverage. |
| **Create** `tests/test_gitlab_review_loop.py` | Notes, discussions, approvals, merge, update. |
| **Create** `tests/test_gitlab_ci.py` | Job log, job and pipeline retry. |

---

### Task 1: Fix approval granularity ⚠️ security

**Files:**
- Modify: `plugins/ericsson-gitlab/__init__.py:142-149`
- Modify: `plugins/ericsson-gitlab/models.py`
- Test: `tests/test_gitlab_approval.py` (create)

**Interfaces:**
- Produces: `WRITE_APPROVALS: dict[str, Callable[[dict], str]]` in `__init__.py`

The connector currently returns:

```python
        return {
            "action": "approve",
            "message": "Approve Ericsson GitLab mutation",
            "rule_key": tool_name,
        }
```

Two defects. The message tells the operator nothing about what they are approving. And `rule_key` is the bare tool name — which the host explicitly warns against in `tools/approval.py:3366`:

> *"Allowlist grain: an explicit plugin rule_key wins; otherwise derive from tool + a short hash of the reason so distinct reasons on the same tool get independent [a]lways entries (**Finding: rule_key=tool_name alone was too coarse — one "always" would blanket every rule on that tool**.)"*

The host's fallback derivation exists precisely to avoid this. By supplying `rule_key` explicitly, the connector **overrides the safer default and reintroduces the bug the host guarded against**. A user who picks "always" when approving one MR creation has silently authorised every future one — permanently, in the persistent allowlist.

This is already wrong for three write tools. It becomes considerably worse once this plan adds merge, approve and job retry. Fix it first.

The Jira connector already does it correctly (`f"{tool_name}:{sha256(canonical_args)}"`), so this is bringing GitLab up to a standard that exists in the same repo.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gitlab_approval.py`:

```python
"""Write approvals must be scoped to the specific change, not the tool."""

import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
sys.path.insert(0, str(PLUGIN))

import __init__ as gitlab_plugin  # noqa: E402


class FakeCtx:
    def __init__(self):
        self.hooks = {}
        self.tools = {}

    def configuration(self):
        return object()

    def register_tool(self, *, name, toolset, schema, handler, check_fn, emoji):
        self.tools[name] = handler

    def register_hook(self, event, fn):
        self.hooks[event] = fn


def _hook():
    ctx = FakeCtx()
    gitlab_plugin.register(ctx)
    return ctx.hooks["pre_tool_call"]


class TestApprovalScope:
    def test_different_arguments_get_different_rule_keys(self):
        """Approving 'merge MR !42' must not also approve 'merge MR !43'."""
        hook = _hook()
        first = hook("gitlab_create_merge_request",
                     {"project": "g/p", "source_branch": "a"})
        second = hook("gitlab_create_merge_request",
                      {"project": "g/p", "source_branch": "b"})
        assert first["rule_key"] != second["rule_key"]

    def test_identical_arguments_get_a_stable_rule_key(self):
        hook = _hook()
        args = {"project": "g/p", "source_branch": "a"}
        assert hook("gitlab_create_merge_request", dict(args))["rule_key"] == (
            hook("gitlab_create_merge_request", dict(args))["rule_key"]
        )

    def test_rule_key_is_not_the_bare_tool_name(self):
        hook = _hook()
        result = hook("gitlab_create_merge_request", {"project": "g/p"})
        assert result["rule_key"] != "gitlab_create_merge_request"
        assert result["rule_key"].startswith("gitlab_create_merge_request:")

    def test_argument_order_does_not_change_the_key(self):
        hook = _hook()
        a = hook("gitlab_commit_changes", {"project": "g/p", "branch": "x"})
        b = hook("gitlab_commit_changes", {"branch": "x", "project": "g/p"})
        assert a["rule_key"] == b["rule_key"]


class TestApprovalMessage:
    def test_message_names_the_tool_and_its_target(self):
        hook = _hook()
        message = hook(
            "gitlab_create_merge_request",
            {"project": "group/proj", "source_branch": "fix/x"},
        )["message"]
        assert "gitlab_create_merge_request" in message
        assert "group/proj" in message

    def test_every_write_tool_has_a_summary(self):
        missing = sorted(
            gitlab_plugin._WRITE_TOOLS - set(gitlab_plugin.WRITE_APPROVALS)
        )
        assert not missing, f"write tools with no approval summary: {missing}"

    def test_summary_survives_missing_arguments(self):
        for name, summarise in gitlab_plugin.WRITE_APPROVALS.items():
            assert isinstance(summarise({}), str)

    def test_read_tools_are_not_gated(self):
        assert _hook()("gitlab_read_file", {"project": "g/p"}) is None
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_approval.py -q`
Expected: FAIL — `AttributeError: module has no attribute 'WRITE_APPROVALS'`

- [ ] **Step 3: Implement**

In `plugins/ericsson-gitlab/__init__.py`, add `import hashlib` and `import json` if absent, then add near `_WRITE_TOOLS`:

```python
def _arg(args: dict, name: str) -> str:
    """Render one argument for an approval prompt, safely and bounded."""
    value = args.get(name) if isinstance(args, dict) else None
    return json.dumps(value, ensure_ascii=True)[:512]


WRITE_APPROVALS = {
    "gitlab_create_branch": lambda a: (
        f"Project: {_arg(a, 'project')}\nTicket: {_arg(a, 'ticket_key')}"
    ),
    "gitlab_commit_changes": lambda a: (
        f"Project: {_arg(a, 'project')}\nBranch: {_arg(a, 'branch')}\n"
        f"Message: {_arg(a, 'commit_message')}"
    ),
    "gitlab_create_merge_request": lambda a: (
        f"Project: {_arg(a, 'project')}\n"
        f"Source: {_arg(a, 'source_branch')} -> {_arg(a, 'target_branch')}"
    ),
}
```

Replace `require_write_approval`:

```python
    def require_write_approval(tool_name: str, args: dict, **kwargs):
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
                f"Approve Ericsson GitLab change: {tool_name}\n"
                f"{summarise(args if isinstance(args, dict) else {})}"
            ),
            # Argument-derived, NOT the bare tool name. See
            # tools/approval.py:3366 -- a tool-name rule_key means one
            # "always" blankets every future call of that tool.
            "rule_key": (
                f"{tool_name}:"
                f"{hashlib.sha256(canonical_args.encode('utf-8')).hexdigest()}"
            ),
        }
```

- [ ] **Step 4: Add the mutation-gate error category**

In `plugins/ericsson-gitlab/models.py`, add to `SAFE_ERROR_MESSAGES`:

```python
    "confirmation_required": "GitLab change needs explicit confirmation",
```

- [ ] **Step 5: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_approval.py -q`
Expected: PASS (8 tests)

- [ ] **Step 6: Verify no regression**

Run: `. .venv/bin/activate && pytest tests/ -q -k gitlab`
Expected: PASS.

> **Operator note for the release.** Existing users may already hold a permanent "always" allowlist entry keyed `plugin_rule:gitlab_create_branch` (and the other two). Those entries no longer match after this change, so the next such action will prompt again. That is the correct outcome — the old entry was broader than the user could have understood — but it should be called out in release notes rather than surprising people.

- [ ] **Step 7: Commit**

```bash
git add plugins/ericsson-gitlab/__init__.py plugins/ericsson-gitlab/models.py tests/test_gitlab_approval.py
git commit -m "fix: scope GitLab write approvals to arguments, not tool name"
```

---

### Task 2: `gitlab_job_log`

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`, `operations.py`, `plugin.yaml`
- Test: `tests/test_gitlab_ci.py` (create)

**Interfaces:**
- Produces: `GitLabOperations.job_log(project, job_id, *, max_bytes=20000) -> dict`

Endpoint: `GET /api/v4/projects/{id}/jobs/{job_id}/trace` (super-cli `gitlab.JobLog`). Returns **plain text, not JSON**, which is why it needs its own path rather than reusing `get_json`.

Per D2 this ships before the mutating CI tools: an agent that can retry but not read the failure is guessing. Per D3 the log is tail-biased — failures are at the end, and returning the head of a 50 MB log burns context to no purpose.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gitlab_ci.py`:

```python
"""GitLab CI tools: job log, job retry, pipeline retry."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
sys.path.insert(0, str(PLUGIN))

from _common.transport import Response  # noqa: E402
from models import GitLabError  # noqa: E402
from operations import GitLabOperations  # noqa: E402


class FakeClient:
    """Stands in for GitLabClient, recording calls."""

    def __init__(self, json_results=None, raw_results=None):
        self.json_results = list(json_results or [])
        self.raw_results = list(raw_results or [])
        self.calls = []
        self.max_pages = 10

        class _Auth:
            origin = "https://gitlab.test"
            pat = "secret-pat-value"

        self.auth = _Auth()

    def operation_deadline(self):
        return 0.0

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

    def request_raw(self, method, path, *, params=None, deadline=None):
        self.calls.append((method, path, params))
        result = self.raw_results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _project_resolved(ops):
    """GitLabOperations resolves a project before most calls; short-circuit."""
    ops.resolve_project = lambda project: {"id": 7, "path": "g/p"}
    return ops


class TestJobLog:
    def test_fetches_the_trace_endpoint(self):
        client = FakeClient(raw_results=[Response(200, {}, b"build ok")])
        ops = _project_resolved(GitLabOperations(client))
        result = ops.job_log("g/p", 42)
        assert client.calls[0][:2] == ("GET", "/api/v4/projects/7/jobs/42/trace")
        assert result["log"] == "build ok"
        assert result["truncated"] is False

    def test_long_log_is_tail_biased(self):
        """Failures are at the end of a job log. Returning the head answers
        nothing and costs the same context."""
        body = ("head\n" + "x" * 50_000 + "\nTHE ACTUAL ERROR").encode()
        client = FakeClient(raw_results=[Response(200, {}, body)])
        ops = _project_resolved(GitLabOperations(client))
        result = ops.job_log("g/p", 42, max_bytes=1000)
        assert result["truncated"] is True
        assert "THE ACTUAL ERROR" in result["log"]
        assert "head" not in result["log"]
        assert result["hint"]

    def test_reports_original_size(self):
        client = FakeClient(raw_results=[Response(200, {}, b"y" * 5000)])
        ops = _project_resolved(GitLabOperations(client))
        result = ops.job_log("g/p", 42, max_bytes=100)
        assert result["total_bytes"] == 5000
        assert result["returned_bytes"] == len(result["log"].encode())

    def test_empty_log_is_not_an_error(self):
        """A queued job legitimately has no trace yet."""
        client = FakeClient(raw_results=[Response(200, {}, b"")])
        ops = _project_resolved(GitLabOperations(client))
        assert ops.job_log("g/p", 42)["log"] == ""

    def test_undecodable_bytes_do_not_raise(self):
        """CI logs carry ANSI and occasionally invalid UTF-8; a decode error
        must not lose the whole log."""
        client = FakeClient(raw_results=[Response(200, {}, b"ok \xff\xfe bad")])
        ops = _project_resolved(GitLabOperations(client))
        assert "ok" in ops.job_log("g/p", 42)["log"]

    def test_log_carries_the_untrusted_content_warning(self):
        """Job logs contain arbitrary text from the build, including anything
        a branch author chose to echo."""
        client = FakeClient(raw_results=[Response(200, {}, b"log")])
        ops = _project_resolved(GitLabOperations(client))
        assert ops.job_log("g/p", 42)["content_warning"]

    def test_pat_is_redacted_from_the_log(self):
        client = FakeClient(
            raw_results=[Response(200, {}, b"token=secret-pat-value")]
        )
        ops = _project_resolved(GitLabOperations(client))
        assert "secret-pat-value" not in ops.job_log("g/p", 42)["log"]

    def test_bad_job_id_rejected_without_a_request(self):
        client = FakeClient()
        ops = _project_resolved(GitLabOperations(client))
        with pytest.raises(GitLabError):
            ops.job_log("g/p", 0)
        assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_ci.py -q`
Expected: FAIL — `AttributeError: 'GitLabOperations' object has no attribute 'job_log'`

- [ ] **Step 3: Add raw fetch support to the client**

`GET .../trace` returns plain text, so `GitLabClient` needs a non-JSON path. Add to `plugins/ericsson-gitlab/client.py`:

```python
    def request_raw(
        self,
        method: str,
        path: str,
        *,
        params: Mapping[str, Any] | None = None,
        deadline: float | None = None,
    ):
        """Fetch a non-JSON body (job traces, raw file contents).

        Still bounded by the transport's max_response_bytes, so a runaway
        job log cannot exhaust memory.
        """
        with _as_gitlab_error():
            return self._client.request(
                method, path, params=params, json_body=None, deadline=deadline
            )
```

- [ ] **Step 4: Implement the operation**

Add to `plugins/ericsson-gitlab/operations.py`:

```python
_MAX_LOG_BYTES = 200_000


    def _redact_text(self, value: str) -> str:
        """Strip the configured PAT out of remote text before returning it."""
        secret = getattr(self.client.auth, "pat", "")
        if isinstance(secret, str) and len(secret) >= 4:
            value = value.replace(secret, "<redacted>")
        return value

    def job_log(
        self, project: str | int, job_id: int, *, max_bytes: int = 20_000
    ) -> dict[str, Any]:
        """Fetch one job's trace, biased to the tail.

        A failing job's cause is at the end of its log, so truncation keeps
        the tail and discards the head -- the opposite of the usual choice,
        and the reason this does not reuse the generic list envelope.
        """
        if type(job_id) is not int or job_id < 1:
            raise GitLabError("invalid_input")
        if type(max_bytes) is not int or not 1 <= max_bytes <= _MAX_LOG_BYTES:
            raise GitLabError("invalid_input")
        resolved = self.resolve_project(project)
        response = self.client.request_raw(
            "GET", f"/api/v4/projects/{resolved['id']}/jobs/{job_id}/trace"
        )
        raw = response.body
        total = len(raw)
        truncated = total > max_bytes
        tail = raw[-max_bytes:] if truncated else raw
        text = self._redact_text(tail.decode("utf-8", errors="replace"))
        result: dict[str, Any] = {
            "job_id": job_id,
            "log": text,
            "truncated": truncated,
            "total_bytes": total,
            "returned_bytes": len(text.encode("utf-8")),
            "content_warning": UNTRUSTED_CONTENT_WARNING,
        }
        if truncated:
            result["hint"] = (
                "Only the last portion of the log is shown, because a failing "
                "job's cause is normally at the end. Raise max_bytes to see "
                "more."
            )
        return result
```

Add `UNTRUSTED_CONTENT_WARNING` to the `_common.envelope` import at the top of the file.

- [ ] **Step 5: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_ci.py -q`
Expected: PASS (8 tests)

- [ ] **Step 6: Wire the tool**

`tools.py` `SCHEMAS`:

```python
    "gitlab_job_log": _schema(
        "gitlab_job_log",
        "Read one GitLab CI job's log. Returns the tail by default, because "
        "a failing job's cause is normally at the end.",
        {
            "project": _PROJECT,
            "job_id": {"type": "integer", "minimum": 1},
            "max_bytes": {"type": "integer", "minimum": 1, "maximum": 200000},
        },
        ["project", "job_id"],
    ),
```

`invoke()` branch:

```python
        if name == "gitlab_job_log":
            return operations.job_log(
                values["project"],
                values["job_id"],
                max_bytes=values.get("max_bytes", 20000),
            )
```

`plugin.yaml`: append `gitlab_job_log`.

- [ ] **Step 7: Verify wiring and commit**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-gitlab")
import tools, yaml
declared = set(yaml.safe_load(open("plugins/ericsson-gitlab/plugin.yaml"))["provides_tools"])
schemas = set(tools.SCHEMAS)
assert schemas == declared, f"mismatch: {schemas ^ declared}"
print("OK", len(schemas), "tools")
PY
```
Expected: `OK 18 tools`.

```bash
git add plugins/ericsson-gitlab/ tests/test_gitlab_ci.py
git commit -m "feat: add gitlab_job_log with tail-biased truncation"
```

---

### Task 3: `gitlab_create_mr_note`

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_gitlab_review_loop.py` (create)

**Interfaces:**
- Produces: `GitLabOperations.create_mr_note(project, iid, body, *, dry_run=False, confirm=False) -> dict`

Endpoint: `POST /api/v4/projects/{id}/merge_requests/{iid}/notes` (super-cli `gitlab.CreateMergeRequestNote`). This is the first half of making `merge-request-review` actionable — today the skill can produce a review it cannot deliver.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_gitlab_review_loop.py`:

```python
"""GitLab review loop: notes, discussions, approvals, merge, update."""

import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-gitlab"
sys.path.insert(0, str(PLUGIN))

from models import GitLabError  # noqa: E402
from operations import GitLabOperations  # noqa: E402


class FakeClient:
    def __init__(self, results=None):
        self.results = list(results or [])
        self.calls = []
        self.max_pages = 10

        class _Auth:
            origin = "https://gitlab.test"
            pat = "secret-pat-value"

        self.auth = _Auth()

    def operation_deadline(self):
        return 0.0

    def get_json(self, path, *, params=None, deadline=None):
        self.calls.append(("GET", path, params))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result

    def request_json(self, method, path, *, params=None, json_body=None,
                     deadline=None):
        self.calls.append((method, path, json_body))
        result = self.results.pop(0)
        if isinstance(result, Exception):
            raise result
        return result


def _ops(client):
    operations = GitLabOperations(client)
    operations.resolve_project = lambda project: {"id": 7, "path": "g/p"}
    return operations


class TestCreateMrNote:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).create_mr_note("g/p", 42, "Looks good")
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).create_mr_note(
            "g/p", 42, "Looks good", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["body"] == "Looks good"
        assert client.calls == []

    def test_confirm_posts_the_note(self):
        client = FakeClient([{"id": 9001}])
        result = _ops(client).create_mr_note(
            "g/p", 42, "Looks good", confirm=True
        )
        method, path, body = client.calls[0]
        assert method == "POST"
        assert path == "/api/v4/projects/7/merge_requests/42/notes"
        assert body == {"body": "Looks good"}
        assert result["note_id"] == 9001

    def test_empty_body_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).create_mr_note("g/p", 42, "   ", confirm=True)
        assert client.calls == []

    def test_oversized_body_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).create_mr_note("g/p", 42, "x" * 200_000, confirm=True)

    def test_bad_iid_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).create_mr_note("g/p", 0, "body", confirm=True)

    def test_response_without_an_id_raises(self):
        client = FakeClient([{"unexpected": True}])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).create_mr_note("g/p", 42, "body", confirm=True)
        assert excinfo.value.category == "invalid_remote_data"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q`
Expected: FAIL — no attribute `create_mr_note`

- [ ] **Step 3: Implement**

Add the guardrail import to `operations.py`:

```python
if __package__:
    from ._common.guardrails import require_explicit_intent
else:
    from _common.guardrails import require_explicit_intent
```

```python
_MAX_NOTE_BYTES = 100_000


    @staticmethod
    def _iid(value: Any) -> int:
        if type(value) is not int or value < 1:
            raise GitLabError("invalid_input")
        return value

    @staticmethod
    def _note_body(value: Any) -> str:
        if (
            not isinstance(value, str)
            or not value.strip()
            or len(value.encode("utf-8")) > _MAX_NOTE_BYTES
        ):
            raise GitLabError("invalid_input")
        return value

    def create_mr_note(
        self,
        project: str | int,
        iid: int,
        body: str,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Post one top-level note on a merge request."""
        iid = self._iid(iid)
        body = self._note_body(body)
        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"merge request !{iid}"
        )
        resolved = self.resolve_project(project)
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "project": resolved["path"],
                "iid": iid,
                "body": body,
                "note_id": None,
            }
        payload = self.client.request_json(
            "POST",
            f"/api/v4/projects/{resolved['id']}/merge_requests/{iid}/notes",
            json_body={"body": body},
        )
        if not isinstance(payload, Mapping) or type(payload.get("id")) is not int:
            raise GitLabError("invalid_remote_data")
        return {
            "ok": True,
            "dry_run": False,
            "project": resolved["path"],
            "iid": iid,
            "body": body,
            "note_id": payload["id"],
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q`
Expected: PASS (7 tests)

- [ ] **Step 5: Wire the tool and its approval**

`SCHEMAS`:

```python
    "gitlab_create_mr_note": _schema(
        "gitlab_create_mr_note",
        "Post one note on a GitLab merge request. Requires dry_run or "
        "confirm.",
        {
            "project": _PROJECT,
            "iid": {"type": "integer", "minimum": 1},
            "body": {"type": "string", "minLength": 1, "maxLength": 100000},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "iid", "body"],
    ),
```

`invoke()`:

```python
        if name == "gitlab_create_mr_note":
            return operations.create_mr_note(
                values["project"],
                values["iid"],
                values["body"],
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`: add `"gitlab_create_mr_note"` to `_WRITE_TOOLS` and:

```python
    "gitlab_create_mr_note": lambda a: (
        f"Project: {_arg(a, 'project')}\nMR: !{_arg(a, 'iid')}\n"
        f"Note: {_arg(a, 'body')}"
    ),
```

`plugin.yaml`: append `gitlab_create_mr_note`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 19 tools`. Also run `pytest tests/test_gitlab_approval.py -q` — `test_every_write_tool_has_a_summary` is what catches a `_WRITE_TOOLS` addition with no prompt.

```bash
git add plugins/ericsson-gitlab/ tests/test_gitlab_review_loop.py
git commit -m "feat: add gitlab_create_mr_note"
```

---

### Task 4: `gitlab_reply_to_discussion` and `gitlab_resolve_discussion`

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_gitlab_review_loop.py`

**Interfaces:**
- Produces:
  - `GitLabOperations.reply_to_discussion(project, iid, discussion_id, body, *, dry_run=False, confirm=False) -> dict`
  - `GitLabOperations.resolve_discussion(project, iid, discussion_id, *, resolved=True, dry_run=False, confirm=False) -> dict`

Endpoints: `POST .../discussions/{did}/notes` and `PUT .../discussions/{did}` (super-cli `gitlab.ReplyToDiscussion`, `gitlab.ResolveDiscussion`). Per D4 these stay separate tools: resolving is a judgement that a thread is settled, replying is not, and fusing them would let an agent silently close threads while commenting.

`gitlab_list_merge_request_discussions` already exists, so discussion IDs are obtainable.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gitlab_review_loop.py`:

```python
class TestReplyToDiscussion:
    def test_confirm_posts_to_the_discussion(self):
        client = FakeClient([{"id": 555}])
        result = _ops(client).reply_to_discussion(
            "g/p", 42, "abc123", "Addressed", confirm=True
        )
        method, path, body = client.calls[0]
        assert method == "POST"
        assert path == (
            "/api/v4/projects/7/merge_requests/42/discussions/abc123/notes"
        )
        assert body == {"body": "Addressed"}
        assert result["note_id"] == 555

    def test_neither_flag_is_refused(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).reply_to_discussion("g/p", 42, "abc123", "x")
        assert excinfo.value.category == "confirmation_required"

    def test_malformed_discussion_id_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).reply_to_discussion(
                "g/p", 42, "../../admin", "x", confirm=True
            )
        assert client.calls == []


class TestResolveDiscussion:
    def test_confirm_resolves(self):
        client = FakeClient([{"id": "abc123", "resolved": True}])
        result = _ops(client).resolve_discussion(
            "g/p", 42, "abc123", confirm=True
        )
        method, path, body = client.calls[0]
        assert method == "PUT"
        assert path == "/api/v4/projects/7/merge_requests/42/discussions/abc123"
        assert body == {"resolved": True}
        assert result["resolved"] is True

    def test_unresolve_sends_false(self):
        client = FakeClient([{"id": "abc123", "resolved": False}])
        result = _ops(client).resolve_discussion(
            "g/p", 42, "abc123", resolved=False, confirm=True
        )
        assert client.calls[0][2] == {"resolved": False}
        assert result["resolved"] is False

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).resolve_discussion(
            "g/p", 42, "abc123", dry_run=True
        )
        assert result["dry_run"] is True
        assert client.calls == []

    def test_non_boolean_resolved_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).resolve_discussion(
                "g/p", 42, "abc123", resolved="yes", confirm=True
            )
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q -k Discussion`
Expected: FAIL — no attribute `reply_to_discussion`

- [ ] **Step 3: Implement**

```python
_DISCUSSION_ID = re.compile(r"^[A-Za-z0-9_-]{1,128}$")


    @staticmethod
    def _discussion_id(value: Any) -> str:
        if not isinstance(value, str) or _DISCUSSION_ID.fullmatch(value) is None:
            raise GitLabError("invalid_input")
        return value

    def reply_to_discussion(
        self,
        project: str | int,
        iid: int,
        discussion_id: str,
        body: str,
        *,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Reply within an existing merge-request discussion thread."""
        iid = self._iid(iid)
        discussion_id = self._discussion_id(discussion_id)
        body = self._note_body(body)
        execute = require_explicit_intent(
            dry_run=dry_run,
            confirm=confirm,
            action=f"discussion {discussion_id} on !{iid}",
        )
        resolved = self.resolve_project(project)
        base = (
            f"/api/v4/projects/{resolved['id']}/merge_requests/{iid}"
            f"/discussions/{discussion_id}"
        )
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "project": resolved["path"],
                "iid": iid,
                "discussion_id": discussion_id,
                "body": body,
                "note_id": None,
            }
        payload = self.client.request_json(
            "POST", f"{base}/notes", json_body={"body": body}
        )
        if not isinstance(payload, Mapping) or type(payload.get("id")) is not int:
            raise GitLabError("invalid_remote_data")
        return {
            "ok": True,
            "dry_run": False,
            "project": resolved["path"],
            "iid": iid,
            "discussion_id": discussion_id,
            "body": body,
            "note_id": payload["id"],
        }

    def resolve_discussion(
        self,
        project: str | int,
        iid: int,
        discussion_id: str,
        *,
        resolved: bool = True,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Mark a discussion thread resolved, or reopen it.

        Kept separate from reply_to_discussion deliberately: resolving is a
        judgement that a thread is settled, and fusing the two would let an
        agent close threads as a side effect of commenting on them.
        """
        iid = self._iid(iid)
        discussion_id = self._discussion_id(discussion_id)
        if type(resolved) is not bool:
            raise GitLabError("invalid_input")
        execute = require_explicit_intent(
            dry_run=dry_run,
            confirm=confirm,
            action=f"discussion {discussion_id} on !{iid}",
        )
        project_info = self.resolve_project(project)
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "project": project_info["path"],
                "iid": iid,
                "discussion_id": discussion_id,
                "resolved": resolved,
            }
        payload = self.client.request_json(
            "PUT",
            f"/api/v4/projects/{project_info['id']}/merge_requests/{iid}"
            f"/discussions/{discussion_id}",
            json_body={"resolved": resolved},
        )
        if not isinstance(payload, Mapping):
            raise GitLabError("invalid_remote_data")
        return {
            "ok": True,
            "dry_run": False,
            "project": project_info["path"],
            "iid": iid,
            "discussion_id": discussion_id,
            "resolved": bool(payload.get("resolved", resolved)),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q`
Expected: PASS (14 tests)

- [ ] **Step 5: Wire both tools and their approvals**

`SCHEMAS`:

```python
    "gitlab_reply_to_discussion": _schema(
        "gitlab_reply_to_discussion",
        "Reply inside one GitLab merge-request discussion thread. Get "
        "discussion_id from gitlab_list_merge_request_discussions. Requires "
        "dry_run or confirm.",
        {
            "project": _PROJECT,
            "iid": {"type": "integer", "minimum": 1},
            "discussion_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "body": {"type": "string", "minLength": 1, "maxLength": 100000},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "iid", "discussion_id", "body"],
    ),
    "gitlab_resolve_discussion": _schema(
        "gitlab_resolve_discussion",
        "Mark one GitLab merge-request discussion resolved, or reopen it with "
        "resolved false. Requires dry_run or confirm.",
        {
            "project": _PROJECT,
            "iid": {"type": "integer", "minimum": 1},
            "discussion_id": {"type": "string", "minLength": 1, "maxLength": 128},
            "resolved": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "iid", "discussion_id"],
    ),
```

`invoke()`:

```python
        if name == "gitlab_reply_to_discussion":
            return operations.reply_to_discussion(
                values["project"],
                values["iid"],
                values["discussion_id"],
                values["body"],
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
        if name == "gitlab_resolve_discussion":
            return operations.resolve_discussion(
                values["project"],
                values["iid"],
                values["discussion_id"],
                resolved=values.get("resolved", True),
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`: add both to `_WRITE_TOOLS` and:

```python
    "gitlab_reply_to_discussion": lambda a: (
        f"Project: {_arg(a, 'project')}\nMR: !{_arg(a, 'iid')}\n"
        f"Thread: {_arg(a, 'discussion_id')}\nReply: {_arg(a, 'body')}"
    ),
    "gitlab_resolve_discussion": lambda a: (
        f"Project: {_arg(a, 'project')}\nMR: !{_arg(a, 'iid')}\n"
        f"Thread: {_arg(a, 'discussion_id')}\n"
        f"Set resolved: {_arg(a, 'resolved')}"
    ),
```

`plugin.yaml`: append both.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 21 tools`.

```bash
git add plugins/ericsson-gitlab/ tests/test_gitlab_review_loop.py
git commit -m "feat: add gitlab discussion reply and resolve"
```

---

### Task 5: `gitlab_merge_request_approvals` and `gitlab_approve_merge_request`

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_gitlab_review_loop.py`

**Interfaces:**
- Produces:
  - `GitLabOperations.merge_request_approvals(project, iid) -> dict`
  - `GitLabOperations.approve_merge_request(project, iid, *, sha=None, dry_run=False, confirm=False) -> dict`

Endpoints: `GET .../approvals` and `POST .../approve` (super-cli `gitlab.MergeRequestApprovals`, `gitlab.ApproveMergeRequest`). The read ships with the write because approving without first seeing approval state is exactly the mistake this pairing prevents.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gitlab_review_loop.py`:

```python
class TestApprovals:
    def test_reads_approval_state(self):
        client = FakeClient([{
            "approved": False,
            "approvals_required": 2,
            "approvals_left": 1,
            "approved_by": [{"user": {"username": "alice", "name": "Alice"}}],
        }])
        result = _ops(client).merge_request_approvals("g/p", 42)
        assert client.calls[0][1] == (
            "/api/v4/projects/7/merge_requests/42/approvals"
        )
        assert result["approvals_required"] == 2
        assert result["approvals_left"] == 1
        assert result["approved_by"] == ["alice"]

    def test_malformed_approval_payload_raises(self):
        client = FakeClient([["not", "a", "mapping"]])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_request_approvals("g/p", 42)
        assert excinfo.value.category == "invalid_remote_data"


class TestApproveMergeRequest:
    def test_neither_flag_is_refused(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).approve_merge_request("g/p", 42)
        assert excinfo.value.category == "confirmation_required"

    def test_confirm_approves(self):
        client = FakeClient([{"approved": True}])
        result = _ops(client).approve_merge_request("g/p", 42, confirm=True)
        method, path, _body = client.calls[0]
        assert method == "POST"
        assert path == "/api/v4/projects/7/merge_requests/42/approve"
        assert result["ok"] is True

    def test_sha_is_forwarded_when_supplied(self):
        """Pinning the SHA makes GitLab refuse if the branch moved since the
        review — approving a commit you never read is the failure mode."""
        client = FakeClient([{"approved": True}])
        _ops(client).approve_merge_request(
            "g/p", 42, sha="a" * 40, confirm=True
        )
        assert client.calls[0][2] == {"sha": "a" * 40}

    def test_malformed_sha_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).approve_merge_request(
                "g/p", 42, sha="not-a-sha", confirm=True
            )
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).approve_merge_request("g/p", 42, dry_run=True)
        assert result["dry_run"] is True
        assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q -k Approv`
Expected: FAIL — no attribute `merge_request_approvals`

- [ ] **Step 3: Implement**

```python
_SHA = re.compile(r"^[0-9a-f]{7,40}$")


    @staticmethod
    def _sha(value: Any) -> str:
        if not isinstance(value, str) or _SHA.fullmatch(value) is None:
            raise GitLabError("invalid_input")
        return value

    def merge_request_approvals(
        self, project: str | int, iid: int
    ) -> dict[str, Any]:
        """Read approval state: how many are required, and who has approved."""
        iid = self._iid(iid)
        resolved = self.resolve_project(project)
        payload = self.client.get_json(
            f"/api/v4/projects/{resolved['id']}/merge_requests/{iid}/approvals"
        )
        if not isinstance(payload, Mapping):
            raise GitLabError("invalid_remote_data")
        approvers = []
        raw_approved_by = payload.get("approved_by")
        if isinstance(raw_approved_by, list):
            for entry in raw_approved_by[:100]:
                if not isinstance(entry, Mapping):
                    continue
                user = entry.get("user")
                if not isinstance(user, Mapping):
                    continue
                username = user.get("username")
                if isinstance(username, str) and username:
                    approvers.append(self._redact_text(username[:255]))
        return {
            "project": resolved["path"],
            "iid": iid,
            "approved": bool(payload.get("approved")),
            "approvals_required": payload.get("approvals_required"),
            "approvals_left": payload.get("approvals_left"),
            "approved_by": approvers,
        }

    def approve_merge_request(
        self,
        project: str | int,
        iid: int,
        *,
        sha: str | None = None,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Approve a merge request.

        Passing sha pins the approval to a specific commit: GitLab refuses if
        the branch has moved since, which is the guard against approving a
        revision nobody reviewed.
        """
        iid = self._iid(iid)
        body: dict[str, Any] = {}
        if sha is not None:
            body["sha"] = self._sha(sha)
        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"merge request !{iid}"
        )
        resolved = self.resolve_project(project)
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "project": resolved["path"],
                "iid": iid,
                "sha": sha,
            }
        payload = self.client.request_json(
            "POST",
            f"/api/v4/projects/{resolved['id']}/merge_requests/{iid}/approve",
            json_body=body,
        )
        if not isinstance(payload, Mapping):
            raise GitLabError("invalid_remote_data")
        return {
            "ok": True,
            "dry_run": False,
            "project": resolved["path"],
            "iid": iid,
            "sha": sha,
            "approved": bool(payload.get("approved", True)),
        }
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q`
Expected: PASS (22 tests)

- [ ] **Step 5: Wire both tools**

`SCHEMAS`:

```python
    "gitlab_merge_request_approvals": _schema(
        "gitlab_merge_request_approvals",
        "Read approval state for one GitLab merge request: how many "
        "approvals are required, how many remain, and who has approved.",
        {"project": _PROJECT, "iid": {"type": "integer", "minimum": 1}},
        ["project", "iid"],
    ),
    "gitlab_approve_merge_request": _schema(
        "gitlab_approve_merge_request",
        "Approve one GitLab merge request. Supply sha to pin the approval to "
        "a reviewed commit so GitLab refuses if the branch moved. Requires "
        "dry_run or confirm.",
        {
            "project": _PROJECT,
            "iid": {"type": "integer", "minimum": 1},
            "sha": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "iid"],
    ),
```

`invoke()`:

```python
        if name == "gitlab_merge_request_approvals":
            return operations.merge_request_approvals(
                values["project"], values["iid"]
            )
        if name == "gitlab_approve_merge_request":
            return operations.approve_merge_request(
                values["project"],
                values["iid"],
                sha=values.get("sha"),
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`: add `"gitlab_approve_merge_request"` to `_WRITE_TOOLS` and:

```python
    "gitlab_approve_merge_request": lambda a: (
        f"Project: {_arg(a, 'project')}\nApprove MR: !{_arg(a, 'iid')}\n"
        f"Pinned SHA: {_arg(a, 'sha')}"
    ),
```

`plugin.yaml`: append both.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 23 tools`.

```bash
git add plugins/ericsson-gitlab/ tests/test_gitlab_review_loop.py
git commit -m "feat: add gitlab merge request approvals read and approve"
```

---

### Task 6: `gitlab_merge_merge_request`

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_gitlab_review_loop.py`

**Interfaces:**
- Produces: `GitLabOperations.merge_merge_request(project, iid, *, sha=None, squash=None, remove_source_branch=None, merge_when_pipeline_succeeds=False, dry_run=False, confirm=False) -> dict`

Endpoint: `PUT /api/v4/projects/{id}/merge_requests/{iid}/merge` (super-cli `gitlab.MergeMergeRequest`). The single most consequential tool in this plan.

Per D5 `sha` is strongly encouraged: GitLab refuses the merge if the branch moved, which is what stops an agent merging commits that appeared after its review.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gitlab_review_loop.py`:

```python
class TestMergeMergeRequest:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42)
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_dry_run_previews(self):
        client = FakeClient()
        result = _ops(client).merge_merge_request("g/p", 42, dry_run=True)
        assert result["dry_run"] is True
        assert client.calls == []

    def test_confirm_merges(self):
        client = FakeClient([{"state": "merged", "merge_commit_sha": "b" * 40}])
        result = _ops(client).merge_merge_request("g/p", 42, confirm=True)
        method, path, _body = client.calls[0]
        assert method == "PUT"
        assert path == "/api/v4/projects/7/merge_requests/42/merge"
        assert result["state"] == "merged"
        assert result["merge_commit_sha"] == "b" * 40

    def test_sha_pins_the_merge(self):
        client = FakeClient([{"state": "merged"}])
        _ops(client).merge_merge_request("g/p", 42, sha="a" * 40, confirm=True)
        assert client.calls[0][2]["sha"] == "a" * 40

    def test_optional_flags_are_omitted_when_not_set(self):
        """Sending squash=false explicitly would override a project default
        the maintainers deliberately configured."""
        client = FakeClient([{"state": "merged"}])
        _ops(client).merge_merge_request("g/p", 42, confirm=True)
        body = client.calls[0][2]
        assert "squash" not in body
        assert "should_remove_source_branch" not in body

    def test_flags_are_sent_when_set(self):
        client = FakeClient([{"state": "merged"}])
        _ops(client).merge_merge_request(
            "g/p", 42, squash=True, remove_source_branch=True, confirm=True
        )
        body = client.calls[0][2]
        assert body["squash"] is True
        assert body["should_remove_source_branch"] is True

    def test_merge_when_pipeline_succeeds(self):
        client = FakeClient([{"state": "opened"}])
        result = _ops(client).merge_merge_request(
            "g/p", 42, merge_when_pipeline_succeeds=True, confirm=True
        )
        assert client.calls[0][2]["merge_when_pipeline_succeeds"] is True
        assert result["state"] == "opened"

    def test_conflict_propagates_rather_than_retrying(self):
        client = FakeClient([GitLabError("conflict")])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "conflict"

    def test_write_ambiguous_is_not_reconciled_silently(self):
        """A merge that may or may not have happened must be reported as
        unknown, never guessed."""
        client = FakeClient([GitLabError("write_ambiguous")])
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).merge_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "write_ambiguous"
        assert len(client.calls) == 1
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q -k Merge`
Expected: FAIL — no attribute `merge_merge_request`

- [ ] **Step 3: Implement**

```python
    def merge_merge_request(
        self,
        project: str | int,
        iid: int,
        *,
        sha: str | None = None,
        squash: bool | None = None,
        remove_source_branch: bool | None = None,
        merge_when_pipeline_succeeds: bool = False,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Merge a merge request.

        Optional flags are omitted rather than defaulted: sending
        squash=false would override a project setting the maintainers chose
        deliberately, and this tool has no business doing that silently.

        Deliberately not reconciled on write_ambiguous. A merge either
        happened or did not; re-reading state cannot distinguish "my merge
        landed" from "someone else merged while I was timing out", and a
        wrong answer here is unrecoverable.
        """
        iid = self._iid(iid)
        body: dict[str, Any] = {}
        if sha is not None:
            body["sha"] = self._sha(sha)
        for key, value in (
            ("squash", squash),
            ("should_remove_source_branch", remove_source_branch),
        ):
            if value is not None:
                if type(value) is not bool:
                    raise GitLabError("invalid_input")
                body[key] = value
        if type(merge_when_pipeline_succeeds) is not bool:
            raise GitLabError("invalid_input")
        if merge_when_pipeline_succeeds:
            body["merge_when_pipeline_succeeds"] = True

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"merge request !{iid}"
        )
        resolved = self.resolve_project(project)
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "project": resolved["path"],
                "iid": iid,
                "requested": body,
            }
        payload = self.client.request_json(
            "PUT",
            f"/api/v4/projects/{resolved['id']}/merge_requests/{iid}/merge",
            json_body=body,
        )
        if not isinstance(payload, Mapping):
            raise GitLabError("invalid_remote_data")
        return {
            "ok": True,
            "dry_run": False,
            "project": resolved["path"],
            "iid": iid,
            "state": _bounded_string(payload.get("state"), 64) or "",
            "merge_commit_sha": _bounded_string(
                payload.get("merge_commit_sha"), 64
            ),
        }
```

If `_bounded_string` does not already exist in this connector's `operations.py`, add the same helper the Jira connector uses.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q`
Expected: PASS (31 tests)

- [ ] **Step 5: Wire the tool and its approval**

`SCHEMAS`:

```python
    "gitlab_merge_merge_request": _schema(
        "gitlab_merge_merge_request",
        "Merge one GitLab merge request. Supply sha to pin the merge to the "
        "reviewed commit so GitLab refuses if the branch moved. Omit squash "
        "and remove_source_branch to keep the project's own defaults. "
        "Requires dry_run or confirm.",
        {
            "project": _PROJECT,
            "iid": {"type": "integer", "minimum": 1},
            "sha": {"type": "string", "pattern": "^[0-9a-f]{7,40}$"},
            "squash": {"type": "boolean"},
            "remove_source_branch": {"type": "boolean"},
            "merge_when_pipeline_succeeds": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "iid"],
    ),
```

`invoke()`:

```python
        if name == "gitlab_merge_merge_request":
            return operations.merge_merge_request(
                values["project"],
                values["iid"],
                sha=values.get("sha"),
                squash=values.get("squash"),
                remove_source_branch=values.get("remove_source_branch"),
                merge_when_pipeline_succeeds=values.get(
                    "merge_when_pipeline_succeeds", False
                ),
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`: add to `_WRITE_TOOLS` and:

```python
    "gitlab_merge_merge_request": lambda a: (
        f"Project: {_arg(a, 'project')}\nMERGE MR: !{_arg(a, 'iid')}\n"
        f"Pinned SHA: {_arg(a, 'sha')}\n"
        f"Squash: {_arg(a, 'squash')}  "
        f"Remove source: {_arg(a, 'remove_source_branch')}"
    ),
```

`plugin.yaml`: append `gitlab_merge_merge_request`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 24 tools`.

```bash
git add plugins/ericsson-gitlab/ tests/test_gitlab_review_loop.py
git commit -m "feat: add gitlab_merge_merge_request with SHA pinning"
```

---

### Task 7: `gitlab_update_merge_request`

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_gitlab_review_loop.py`

**Interfaces:**
- Produces: `GitLabOperations.update_merge_request(project, iid, *, title=None, description=None, add_labels=None, remove_labels=None, state_event=None, draft=None, dry_run=False, confirm=False) -> dict`

Endpoint: `PUT /api/v4/projects/{id}/merge_requests/{iid}` (super-cli `gitlab.UpdateMergeRequest`). Uses `add_labels`/`remove_labels` rather than `labels`, because sending the full list races with anyone else editing and silently drops their changes.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gitlab_review_loop.py`:

```python
class TestUpdateMergeRequest:
    def test_neither_flag_is_refused(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request("g/p", 42, title="New")
        assert excinfo.value.category == "confirmation_required"

    def test_no_change_requested_is_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError) as excinfo:
            _ops(client).update_merge_request("g/p", 42, confirm=True)
        assert excinfo.value.category == "invalid_input"
        assert client.calls == []

    def test_title_and_description_are_sent(self):
        client = FakeClient([{"iid": 42, "title": "New"}])
        _ops(client).update_merge_request(
            "g/p", 42, title="New", description="Body", confirm=True
        )
        body = client.calls[0][2]
        assert body["title"] == "New"
        assert body["description"] == "Body"

    def test_labels_use_add_remove_not_wholesale_replace(self):
        """Sending the full label list races with concurrent edits and would
        silently drop labels somebody else just added."""
        client = FakeClient([{"iid": 42}])
        _ops(client).update_merge_request(
            "g/p", 42, add_labels=["needs-review"],
            remove_labels=["wip"], confirm=True,
        )
        body = client.calls[0][2]
        assert body["add_labels"] == "needs-review"
        assert body["remove_labels"] == "wip"
        assert "labels" not in body

    def test_state_event_close_is_allowed(self):
        client = FakeClient([{"iid": 42, "state": "closed"}])
        result = _ops(client).update_merge_request(
            "g/p", 42, state_event="close", confirm=True
        )
        assert client.calls[0][2]["state_event"] == "close"
        assert result["state"] == "closed"

    def test_invalid_state_event_rejected(self):
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).update_merge_request(
                "g/p", 42, state_event="delete", confirm=True
            )
        assert client.calls == []

    def test_draft_toggles_via_title(self):
        client = FakeClient([{"iid": 42}])
        _ops(client).update_merge_request("g/p", 42, draft=True, confirm=True)
        assert client.calls[0][2]["title"].startswith("Draft:")

    def test_dry_run_previews_the_body(self):
        client = FakeClient()
        result = _ops(client).update_merge_request(
            "g/p", 42, title="New", dry_run=True
        )
        assert result["dry_run"] is True
        assert result["requested"]["title"] == "New"
        assert client.calls == []
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q -k UpdateMergeRequest`
Expected: FAIL — no attribute `update_merge_request`

- [ ] **Step 3: Implement**

```python
_MR_STATE_EVENTS = frozenset({"close", "reopen"})


    def update_merge_request(
        self,
        project: str | int,
        iid: int,
        *,
        title: str | None = None,
        description: str | None = None,
        add_labels: list | None = None,
        remove_labels: list | None = None,
        state_event: str | None = None,
        draft: bool | None = None,
        dry_run: bool = False,
        confirm: bool = False,
    ) -> dict[str, Any]:
        """Edit an open merge request.

        Labels use add_labels/remove_labels rather than a wholesale labels
        list: replacing the list races with anyone else editing the MR and
        would silently drop labels they had just added.
        """
        iid = self._iid(iid)
        body: dict[str, Any] = {}
        if title is not None:
            if not isinstance(title, str) or not title.strip() or len(title) > 1024:
                raise GitLabError("invalid_input")
            body["title"] = title
        if description is not None:
            if not isinstance(description, str) or len(description) > 65_536:
                raise GitLabError("invalid_input")
            body["description"] = description
        for key, value in (("add_labels", add_labels), ("remove_labels", remove_labels)):
            if value is None:
                continue
            if (
                not isinstance(value, list)
                or not value
                or len(value) > 50
                or any(
                    not isinstance(label, str)
                    or not label.strip()
                    or "," in label
                    or len(label) > 255
                    for label in value
                )
            ):
                raise GitLabError("invalid_input")
            body[key] = ",".join(value)
        if state_event is not None:
            if state_event not in _MR_STATE_EVENTS:
                raise GitLabError("invalid_input")
            body["state_event"] = state_event
        if draft is not None:
            if type(draft) is not bool:
                raise GitLabError("invalid_input")
            base = body.get("title")
            if base is None:
                raise GitLabError("invalid_input")
            stripped = base
            for prefix in ("Draft:", "WIP:"):
                if stripped.startswith(prefix):
                    stripped = stripped[len(prefix):].strip()
            body["title"] = f"Draft: {stripped}" if draft else stripped
        if not body:
            raise GitLabError("invalid_input")

        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"merge request !{iid}"
        )
        resolved = self.resolve_project(project)
        if not execute:
            return {
                "ok": True,
                "dry_run": True,
                "project": resolved["path"],
                "iid": iid,
                "requested": body,
            }
        payload = self.client.request_json(
            "PUT",
            f"/api/v4/projects/{resolved['id']}/merge_requests/{iid}",
            json_body=body,
        )
        if not isinstance(payload, Mapping):
            raise GitLabError("invalid_remote_data")
        return {
            "ok": True,
            "dry_run": False,
            "project": resolved["path"],
            "iid": iid,
            "state": _bounded_string(payload.get("state"), 64) or "",
            "requested": body,
        }
```

Note the `draft` toggle requires `title` to be supplied in the same call, because GitLab expresses draft state through the title prefix. The test `test_draft_toggles_via_title` passes `draft=True` alone and therefore expects `invalid_input` — adjust that test to pass a title, or relax the operation to fetch the current title first. **Pick one and make the code and test agree**; fetching adds a request, so requiring the title is the cheaper contract.

- [ ] **Step 4: Reconcile the draft contract, then run the tests**

Update `test_draft_toggles_via_title` to:

```python
    def test_draft_toggles_via_title(self):
        client = FakeClient([{"iid": 42}])
        _ops(client).update_merge_request(
            "g/p", 42, title="Fix thing", draft=True, confirm=True
        )
        assert client.calls[0][2]["title"] == "Draft: Fix thing"

    def test_draft_without_a_title_is_rejected(self):
        """GitLab expresses draft state through the title prefix, so toggling
        it needs the title in the same call rather than a hidden extra read."""
        client = FakeClient()
        with pytest.raises(GitLabError):
            _ops(client).update_merge_request("g/p", 42, draft=True, confirm=True)
```

Run: `. .venv/bin/activate && pytest tests/test_gitlab_review_loop.py -q`
Expected: PASS (40 tests)

- [ ] **Step 5: Wire the tool and its approval**

`SCHEMAS`:

```python
    "gitlab_update_merge_request": _schema(
        "gitlab_update_merge_request",
        "Edit one GitLab merge request: title, description, labels, draft "
        "state, or close/reopen. Labels are added and removed individually "
        "rather than replaced wholesale. Requires dry_run or confirm.",
        {
            "project": _PROJECT,
            "iid": {"type": "integer", "minimum": 1},
            "title": {"type": "string", "minLength": 1, "maxLength": 1024},
            "description": {"type": "string", "maxLength": 65536},
            "add_labels": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 255},
                "maxItems": 50,
            },
            "remove_labels": {
                "type": "array",
                "items": {"type": "string", "minLength": 1, "maxLength": 255},
                "maxItems": 50,
            },
            "state_event": {"type": "string", "enum": ["close", "reopen"]},
            "draft": {"type": "boolean"},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "iid"],
    ),
```

`invoke()`:

```python
        if name == "gitlab_update_merge_request":
            return operations.update_merge_request(
                values["project"],
                values["iid"],
                title=values.get("title"),
                description=values.get("description"),
                add_labels=values.get("add_labels"),
                remove_labels=values.get("remove_labels"),
                state_event=values.get("state_event"),
                draft=values.get("draft"),
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`: add to `_WRITE_TOOLS` and:

```python
    "gitlab_update_merge_request": lambda a: (
        f"Project: {_arg(a, 'project')}\nMR: !{_arg(a, 'iid')}\n"
        f"Title: {_arg(a, 'title')}\nState: {_arg(a, 'state_event')}\n"
        f"+labels: {_arg(a, 'add_labels')}  -labels: {_arg(a, 'remove_labels')}"
    ),
```

`plugin.yaml`: append `gitlab_update_merge_request`.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 25 tools`.

```bash
git add plugins/ericsson-gitlab/ tests/test_gitlab_review_loop.py
git commit -m "feat: add gitlab_update_merge_request"
```

---

### Task 8: Job and pipeline retry

**Files:**
- Modify: `plugins/ericsson-gitlab/tools.py`, `operations.py`, `__init__.py`, `plugin.yaml`
- Test: `tests/test_gitlab_ci.py`

**Interfaces:**
- Produces:
  - `GitLabOperations.retry_job(project, job_id, *, dry_run=False, confirm=False) -> dict`
  - `GitLabOperations.play_job(project, job_id, *, dry_run=False, confirm=False) -> dict`
  - `GitLabOperations.retry_pipeline(project, pipeline_id, *, dry_run=False, confirm=False) -> dict`

Endpoints: `POST .../jobs/{id}/retry`, `POST .../jobs/{id}/play`, `POST .../pipelines/{id}/retry` (super-cli `gitlab.RetryJob`, `PlayJob`, `RetryPipeline`). Per D6 cancel is deliberately excluded on this pass.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_gitlab_ci.py`:

```python
class TestRetryJob:
    def test_neither_flag_is_refused_without_a_request(self):
        client = FakeClient()
        ops = _project_resolved(GitLabOperations(client))
        with pytest.raises(GitLabError) as excinfo:
            ops.retry_job("g/p", 42)
        assert excinfo.value.category == "confirmation_required"
        assert client.calls == []

    def test_confirm_retries(self):
        client = FakeClient(json_results=[{"id": 99, "status": "pending"}])
        ops = _project_resolved(GitLabOperations(client))
        result = ops.retry_job("g/p", 42, confirm=True)
        method, path, _ = client.calls[0]
        assert method == "POST"
        assert path == "/api/v4/projects/7/jobs/42/retry"
        assert result["new_job_id"] == 99
        assert result["status"] == "pending"

    def test_dry_run_previews(self):
        client = FakeClient()
        ops = _project_resolved(GitLabOperations(client))
        assert ops.retry_job("g/p", 42, dry_run=True)["dry_run"] is True
        assert client.calls == []


class TestPlayJob:
    def test_confirm_plays_a_manual_job(self):
        client = FakeClient(json_results=[{"id": 42, "status": "pending"}])
        ops = _project_resolved(GitLabOperations(client))
        result = ops.play_job("g/p", 42, confirm=True)
        assert client.calls[0][1] == "/api/v4/projects/7/jobs/42/play"
        assert result["status"] == "pending"

    def test_neither_flag_is_refused(self):
        client = FakeClient()
        ops = _project_resolved(GitLabOperations(client))
        with pytest.raises(GitLabError):
            ops.play_job("g/p", 42)


class TestRetryPipeline:
    def test_confirm_retries_the_pipeline(self):
        client = FakeClient(json_results=[{"id": 500, "status": "running"}])
        ops = _project_resolved(GitLabOperations(client))
        result = ops.retry_pipeline("g/p", 500, confirm=True)
        assert client.calls[0][1] == "/api/v4/projects/7/pipelines/500/retry"
        assert result["pipeline_id"] == 500
        assert result["status"] == "running"

    def test_bad_pipeline_id_rejected(self):
        client = FakeClient()
        ops = _project_resolved(GitLabOperations(client))
        with pytest.raises(GitLabError):
            ops.retry_pipeline("g/p", -1, confirm=True)
        assert client.calls == []

    def test_write_ambiguous_propagates(self):
        client = FakeClient(json_results=[GitLabError("write_ambiguous")])
        ops = _project_resolved(GitLabOperations(client))
        with pytest.raises(GitLabError) as excinfo:
            ops.retry_pipeline("g/p", 500, confirm=True)
        assert excinfo.value.category == "write_ambiguous"
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_ci.py -q -k "Retry or Play"`
Expected: FAIL — no attribute `retry_job`

- [ ] **Step 3: Implement**

```python
    def _ci_action(
        self,
        project: str | int,
        endpoint: str,
        identifier: int,
        label: str,
        *,
        dry_run: bool,
        confirm: bool,
    ) -> tuple[dict[str, Any], Any]:
        """Shared shape for the CI POST actions: validate, gate, resolve, act."""
        if type(identifier) is not int or identifier < 1:
            raise GitLabError("invalid_input")
        execute = require_explicit_intent(
            dry_run=dry_run, confirm=confirm, action=f"{label} {identifier}"
        )
        resolved = self.resolve_project(project)
        if not execute:
            return (
                {
                    "ok": True,
                    "dry_run": True,
                    "project": resolved["path"],
                },
                None,
            )
        payload = self.client.request_json(
            "POST", f"/api/v4/projects/{resolved['id']}/{endpoint}"
        )
        if not isinstance(payload, Mapping):
            raise GitLabError("invalid_remote_data")
        return (
            {"ok": True, "dry_run": False, "project": resolved["path"]},
            payload,
        )

    def retry_job(
        self, project: str | int, job_id: int, *,
        dry_run: bool = False, confirm: bool = False,
    ) -> dict[str, Any]:
        """Retry one failed CI job. Read its log first with gitlab_job_log."""
        base, payload = self._ci_action(
            project, f"jobs/{job_id}/retry", job_id, "CI job",
            dry_run=dry_run, confirm=confirm,
        )
        base["job_id"] = job_id
        if payload is None:
            return base
        base["new_job_id"] = payload.get("id")
        base["status"] = _bounded_string(payload.get("status"), 64) or ""
        return base

    def play_job(
        self, project: str | int, job_id: int, *,
        dry_run: bool = False, confirm: bool = False,
    ) -> dict[str, Any]:
        """Start one manual CI job."""
        base, payload = self._ci_action(
            project, f"jobs/{job_id}/play", job_id, "manual CI job",
            dry_run=dry_run, confirm=confirm,
        )
        base["job_id"] = job_id
        if payload is None:
            return base
        base["status"] = _bounded_string(payload.get("status"), 64) or ""
        return base

    def retry_pipeline(
        self, project: str | int, pipeline_id: int, *,
        dry_run: bool = False, confirm: bool = False,
    ) -> dict[str, Any]:
        """Retry the failed jobs in one pipeline."""
        base, payload = self._ci_action(
            project, f"pipelines/{pipeline_id}/retry", pipeline_id, "pipeline",
            dry_run=dry_run, confirm=confirm,
        )
        base["pipeline_id"] = pipeline_id
        if payload is None:
            return base
        base["status"] = _bounded_string(payload.get("status"), 64) or ""
        return base
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `. .venv/bin/activate && pytest tests/test_gitlab_ci.py -q`
Expected: PASS (16 tests)

- [ ] **Step 5: Wire all three tools**

`SCHEMAS` — three entries following this shape:

```python
    "gitlab_retry_job": _schema(
        "gitlab_retry_job",
        "Retry one failed GitLab CI job. Read gitlab_job_log first — "
        "retrying without diagnosing usually reproduces the failure. "
        "Requires dry_run or confirm.",
        {
            "project": _PROJECT,
            "job_id": {"type": "integer", "minimum": 1},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "job_id"],
    ),
    "gitlab_play_job": _schema(
        "gitlab_play_job",
        "Start one manual GitLab CI job. Requires dry_run or confirm.",
        {
            "project": _PROJECT,
            "job_id": {"type": "integer", "minimum": 1},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "job_id"],
    ),
    "gitlab_retry_pipeline": _schema(
        "gitlab_retry_pipeline",
        "Retry the failed jobs in one GitLab pipeline. Requires dry_run or "
        "confirm.",
        {
            "project": _PROJECT,
            "pipeline_id": {"type": "integer", "minimum": 1},
            "dry_run": {"type": "boolean"},
            "confirm": {"type": "boolean"},
        },
        ["project", "pipeline_id"],
    ),
```

`invoke()`:

```python
        if name == "gitlab_retry_job":
            return operations.retry_job(
                values["project"], values["job_id"],
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
        if name == "gitlab_play_job":
            return operations.play_job(
                values["project"], values["job_id"],
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
        if name == "gitlab_retry_pipeline":
            return operations.retry_pipeline(
                values["project"], values["pipeline_id"],
                dry_run=values.get("dry_run", False),
                confirm=values.get("confirm", False),
            )
```

`__init__.py`: add all three to `_WRITE_TOOLS` and:

```python
    "gitlab_retry_job": lambda a: (
        f"Project: {_arg(a, 'project')}\nRetry job: {_arg(a, 'job_id')}"
    ),
    "gitlab_play_job": lambda a: (
        f"Project: {_arg(a, 'project')}\nPlay manual job: {_arg(a, 'job_id')}"
    ),
    "gitlab_retry_pipeline": lambda a: (
        f"Project: {_arg(a, 'project')}\n"
        f"Retry pipeline: {_arg(a, 'pipeline_id')}"
    ),
```

`plugin.yaml`: append all three.

- [ ] **Step 6: Verify and commit**

Parity check expects `OK 28 tools`.

```bash
git add plugins/ericsson-gitlab/ tests/test_gitlab_ci.py
git commit -m "feat: add gitlab job retry, job play, and pipeline retry"
```

---

### Task 9: Final verification

**Files:**
- Test: all

**Interfaces:**
- Consumes: everything from Tasks 1-8

- [ ] **Step 1: Full suite**

Run: `. .venv/bin/activate && pytest -q`
Expected: PASS.

- [ ] **Step 2: Verify every mutating tool is gated and approvable**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-gitlab")
import __init__ as p, tools
writes = p._WRITE_TOOLS
approvals = set(p.WRITE_APPROVALS)
assert writes == approvals, f"gated/approvable mismatch: {writes ^ approvals}"
mutating = {n for n, s in tools.SCHEMAS.items()
            if "confirm" in s["parameters"]["properties"]}
ungated = mutating - writes
assert not ungated, f"mutating but ungated: {sorted(ungated)}"
print("OK", len(writes), "gated writes,", len(tools.SCHEMAS), "tools total")
PY
```
Expected: `OK 11 gated writes, 28 tools total`. A tool exposing `confirm` but absent from `_WRITE_TOOLS` would mutate GitLab with no host approval — this is the check that catches it.

- [ ] **Step 3: Verify approval keys are argument-scoped across every write tool**

```bash
python - <<'PY'
import sys; sys.path.insert(0, "plugins/ericsson-gitlab")
import __init__ as p

class Ctx:
    def __init__(self): self.hooks = {}
    def configuration(self): return object()
    def register_tool(self, **kw): pass
    def register_hook(self, event, fn): self.hooks[event] = fn

ctx = Ctx(); p.register(ctx); hook = ctx.hooks["pre_tool_call"]
for name in sorted(p._WRITE_TOOLS):
    a = hook(name, {"project": "g/p", "iid": 1})["rule_key"]
    b = hook(name, {"project": "g/p", "iid": 2})["rule_key"]
    assert a != b, f"{name}: rule_key ignores arguments"
    assert a != name, f"{name}: rule_key is the bare tool name"
print("OK", len(p._WRITE_TOOLS), "write tools argument-scoped")
PY
```
Expected: `OK 11 write tools argument-scoped`. This is Task 1's guarantee held across every tool added afterwards.

- [ ] **Step 4: Confirm the review loop is closed**

Read `plugins/ericsson-gitlab/skills/merge-request-review/SKILL.md` and confirm it can now express the full loop: read discussions → reply → resolve → approve → merge. Update the skill's guidance if it still tells the model the connector is read-only.

```bash
git add plugins/ericsson-gitlab/skills/
git commit -m "docs: update merge-request-review skill for the closed review loop"
```

---

## Self-Review

**Spec coverage.** Against `PLUGIN-GAP-ANALYSIS.md` §1.2: MR note create (Task 3), reply to discussion (Task 4), resolve/unresolve discussion (Task 4), MR approve and approvals state (Task 5), MR merge (Task 6), MR update (Task 7), job log (Task 2), job play/retry (Task 8), pipeline retry (Task 8). Tier 2 item 7 ("turns merge-request-review from advisory into actionable") is verified explicitly in Task 9 Step 4.

**Deliberately out of scope**, tracked rather than dropped:
- **`gitlab_rebase_merge_request`.** Rebase is asynchronous — it returns immediately and the result must be polled via `rebase_in_progress`. That polling contract deserves its own task rather than a footnote on another one.
- **Cancel (job and pipeline).** Per D6: cancelling a running pipeline is disruptive to whoever is waiting on it, and retry covers the recovery case. Add it if a flow actually needs it.
- **Releases, tags, CI/CD variables, webhooks, todos, code search.** Real gaps against super-cli, but none is on the review or CI-diagnosis path this plan exists to close. Variables and webhooks in particular are configuration surfaces where a mistaken write is expensive, and they deserve their own risk conversation.
- **F4 (cross-invocation throttle).** Still outstanding from Plan 2, and now materially more pressing: this plan adds eight write tools, and retry loops are exactly the shape a throttle exists to stop.

**Type consistency.** `_iid`, `_sha`, `_discussion_id`, `_note_body` and `_redact_text` are introduced in the task that first uses them and reused unchanged afterwards. Every write returns a dict with `ok`, `dry_run` and `project`. `require_explicit_intent` is called before `resolve_project` in every write **except** where the resolved path is needed for the dry-run preview — in those the gate still precedes the network write, which is what matters. `GitLabError` is raised throughout; `ConnectorError` never escapes the connector (Plan 2 Task 8).

**The finding this plan opens with was not in the original gap analysis.** `PLUGIN-GAP-ANALYSIS.md` did not flag the approval-granularity defect, because it only surfaced while reading `tools/approval.py` to plan the new write tools. It is arguably more serious than several findings that did make the list: it is live today for three tools, it silently converts one user click into a standing permanent grant, and the host codebase already documents the exact hazard at `approval.py:3366`. Treat Task 1 as shippable on its own, independent of the rest of this plan.
