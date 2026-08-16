# Task 5 report: circuit breaker behaviour

## RED

Appended the supplied `TestCircuitBreaker` tests to `tests/test_shared_client.py`.

Command:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_client.py -q -k CircuitBreaker
```

Result: `....F... [100%]`; the only failure was
`TestCircuitBreaker.test_circuit_open_has_remediation`, failing on
`assert excinfo.value.remediation` because the value was `None`.

## GREEN

Added the specified `circuit_open` entry to the canonical
`shared/ericsson_common/errors.py` remediation map.

Command:

```text
. .venv/bin/activate && PYTHONPATH=shared pytest tests/test_shared_client.py tests/test_shared_errors.py -q
```

Result: `................................... [100%]`, exit code `0` (`35 passed`).

## Sync and drift

Command:

```text
. .venv/bin/activate && python scripts/sync_shared.py && pytest tests/test_shared_sync.py -q
```

Result:

```text
synced -> plugins/ericsson-jira/_common
synced -> plugins/ericsson-gitlab/_common
.......                                                                  [100%]
```

The generated copies are byte-synchronized; the sync drift suite passed.
`git diff --check` also passed.

## Files

- `tests/test_shared_client.py` — supplied circuit-breaker behaviour tests.
- `shared/ericsson_common/errors.py` — canonical `circuit_open` remediation.
- `plugins/ericsson-jira/_common/errors.py` — generated copy.
- `plugins/ericsson-gitlab/_common/errors.py` — generated copy.

## Self-review

- Breaker tests cover threshold refusal, local refusal without transport calls,
  success reset, endpoint scoping, query normalization, deterministic 4xx and
  auth exclusions, and suppressed 5xx counting.
- No production breaker implementation was changed; Task 4 wiring is exercised
  as supplied.
- `ConnectorError` remains internal and no dependencies were added.
- Only the canonical remediation entry was authored; generated copies were
  produced by `scripts/sync_shared.py`.

## Concerns

The focused Task 5 suites and generated-copy drift gate are green. A repository-wide
`pytest -q --tb=short` invocation emitted failures outside this task's scoped tests
in the available environment but did not return a stable summary through the command
runner; those failures were not investigated or changed.
