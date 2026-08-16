# Task 1 Report: Canonical package, sync script, and drift test

## Implementation summary

Added the canonical `shared/ericsson_common` package with `SHARED_VERSION = "1.0.0"`, a sync script that replaces each consuming connector's generated `_common/` directory, and a pytest drift test enforcing completeness, byte identity, and no stale Python files.

## Files changed

- `shared/ericsson_common/__init__.py`
- `scripts/sync_shared.py`
- `tests/test_shared_sync.py`
- `plugins/ericsson-jira/_common/__init__.py` (generated)
- `plugins/ericsson-gitlab/_common/__init__.py` (generated)

## TDD evidence

### RED: initial missing canonical source

Command:

```text
. .venv/bin/activate && pytest tests/test_shared_sync.py -q
```

Output:

```text
FFF....                                                                  [100%]
3 failed, 4 passed in 0.04s
```

The primary failure was `missing canonical shared source at .../shared/ericsson_common`; the two consumer-copy failures were also expected before implementation.

### GREEN: sync and focused test

Command:

```text
. .venv/bin/activate && python scripts/sync_shared.py && pytest tests/test_shared_sync.py -q
```

Output:

```text
synced -> plugins/ericsson-jira/_common
synced -> plugins/ericsson-gitlab/_common
.......                                                                  [100%]
7 passed in 0.03s
```

### Drift-tamper RED proof

After appending `# tampered` to `plugins/ericsson-jira/_common/__init__.py`, command:

```text
. .venv/bin/activate && pytest tests/test_shared_sync.py -q
```

Output:

```text
...F...                                                                  [100%]
1 failed, 6 passed in 0.03s
```

The failure named `ericsson-jira/_common has hand-edited files: ['__init__.py']`.

### Restored GREEN proof

Command:

```text
python scripts/sync_shared.py && . .venv/bin/activate && pytest tests/test_shared_sync.py -q
```

Output:

```text
synced -> plugins/ericsson-jira/_common
synced -> plugins/ericsson-gitlab/_common
.......                                                                  [100%]
7 passed in 0.03s
```

## Test results

Focused shared-sync suite: 7 passed after restoration.

## Self-review findings

- Canonical and generated files are byte-identical (`cmp` passed for both consumers).
- Sync removes each target first, so canonical deletions propagate.
- Sync ignores `__pycache__` and `*.pyc` while copying.
- Drift test covers missing files, changed files, and extra Python files.

## Concerns

None within Task 1 scope. The full repository suite was not run because the brief specifies the focused commands for this task.
