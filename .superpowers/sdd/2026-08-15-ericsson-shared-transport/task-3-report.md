# Task 3 report: bounded HTTP transport abstraction

## RED evidence

Added `tests/test_shared_transport.py` before the implementation and ran:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_transport.py -q
```

Collection failed as required with:

```text
ModuleNotFoundError: No module named 'ericsson_common.transport'
```

## GREEN evidence

Implemented `Response` and `HttpxTransport` in
`shared/ericsson_common/transport.py`. The focused test command:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_transport.py -q
```

passed all 7 tests.

The implementation provides case-insensitive header lookup, path-prefix and
absolute-URL validation, `trust_env=False`, `follow_redirects=False`, timeout
handling, streamed response collection, and a response-byte capacity bound.

## Sync and drift evidence

Ran:

```text
. .venv/bin/activate && python scripts/sync_shared.py
pytest tests/test_shared_sync.py -q
PYTHONPATH=shared pytest tests/test_shared_transport.py -q
```

The sync regenerated both consumers; sync tests passed (7), and transport tests
passed (7). SHA-256 is identical for the canonical and both generated files:

```text
ce19ccecd34e0bc9d367500961a231ea00a42588fef2dff1859d7182201304d0
```

## Files

- `shared/ericsson_common/transport.py`
- `tests/test_shared_transport.py`
- `plugins/ericsson-jira/_common/transport.py` (generated)
- `plugins/ericsson-gitlab/_common/transport.py` (generated)

## Self-review

- Scope is limited to Task 3 implementation, tests, generated copies, and this
  report.
- The dual relative/standalone import pattern is preserved.
- No connector clients, retry policy, or plan documents were changed.
- `git diff --check` produced no whitespace errors.

## Concerns

The focused Task 3 and sync tests pass. A full `PYTHONPATH=shared pytest -q`
run is blocked by pre-existing environment-dependent GitLab workflow tests that
require a paired Hermes checkout with `plugins/workflow/schema.py`; the first
failure is `tests/test_gitlab_workflows.py::test_real_scheduler_makes_every_application_terminal_state_total[...]`
with `AssertionError: paired Hermes checkout with the real workflow compiler is missing`.

## Fix Round 1

Closed the prefix-boundary bypass for literal and percent-encoded dot segments.
Path validation now percent-decodes the path before splitting it and rejects any
`.` or `..` segment, so HTTPX cannot normalize or forward a request outside the
configured prefix.

Added the parameterized regression in `tests/test_shared_transport.py` covering:

- `/api/v4/../admin/secrets`
- `/api/v4/%2e%2e/admin/secrets`

TDD evidence before the fix:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_transport.py -q
```

```text
.......FF                                                               [100%]
2 failed, 7 passed
```

Both failures showed the mock handler being reached; HTTPX normalized the
literal path to `/api/admin/secrets`, while the encoded path remained an
out-of-prefix request.

Verification after the fix and regeneration:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_transport.py -q
python scripts/sync_shared.py
pytest tests/test_shared_sync.py -q
```

```text
.........                                                                [100%]
synced -> plugins/ericsson-jira/_common
synced -> plugins/ericsson-gitlab/_common
.......                                                                  [100%]
```

The canonical and both generated transport files have identical SHA-256:
`0e3c94d5283e3e11d6cf4c4f7e886b6ecea1ecc659aece21de9df9338fa31cbe`.
