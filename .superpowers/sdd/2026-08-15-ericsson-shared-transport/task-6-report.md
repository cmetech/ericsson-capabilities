# Task 6 report: result envelope and untrusted-content warning

## RED evidence

Command:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_envelope.py -q
```

Result: collection failed as expected with:

```text
ModuleNotFoundError: No module named 'ericsson_common.envelope'
```

## GREEN evidence

Command:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_envelope.py -q
```

Result: `9 passed`.

After generated-copy synchronization, the focused contract and drift suites were run:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_envelope.py tests/test_shared_sync.py -q
```

Result: `16 passed`.

## Implementation

- Added `shared/ericsson_common/envelope.py` with `UNTRUSTED_CONTENT_WARNING` and
  `result_envelope`.
- Added the supplied `tests/test_shared_envelope.py` contract tests.
- `total` is omitted when unknown; `hint` and `content_warning` are omitted unless
  provided/requested; warning is attached to the result payload.
- Ran `scripts/sync_shared.py`; generated copies now include the canonical envelope in
  both `plugins/ericsson-jira/_common/` and `plugins/ericsson-gitlab/_common/`.

## Sync/drift

`tests/test_shared_sync.py`: `7 passed`.

SHA-1 of all three envelope files:

```text
fc0382a4b5f40df86dbf290c2636229d2c67b864
```

The canonical file and both generated copies are byte-identical.

## Full-suite verification

`. .venv/bin/activate && PYTHONPATH=shared pytest -q` reached `356 passed`, `11 skipped`,
and `14 failed`. The failures are unrelated integration tests requiring a paired Hermes
checkout containing `plugins/workflow/schema.py`; that checkout is absent in this
environment. The failures do not involve the envelope tests or shared-copy drift tests.

## Self-review

- Scope is limited to the requested helper, supplied tests, generated copies, and this
  report.
- No existing connectors were wired to the helper.
- No dependencies were added.
- The `ConnectorError` boundary and existing shared modules were not changed.

## Concerns

The full suite cannot be green until the paired Hermes checkout is available. No concerns
remain for the Task 6 focused contract.
