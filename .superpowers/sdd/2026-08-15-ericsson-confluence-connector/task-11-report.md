# Task 11 — `confluence_update_page`

## RED

Added the ten specified `TestUpdatePage` cases, then ran:

```text
. .venv/bin/activate && pytest tests/test_confluence_writes.py -q -k UpdatePage
10 failed: ConfluenceOperations has no attribute update_page
```

Added a registration regression after the operation was green.  Before wiring,
it failed because `confluence_update_page` was neither a declared write nor a
registered handler.

## GREEN

`ConfluenceOperations.update_page` now:

- rejects absent title and Markdown before any request;
- rejects absent dry-run/confirm intent before its current-page GET;
- reads `body.storage,version`, carries over the untouched title or body, and
  PUTs version `current + 1` only when confirmed;
- uses the existing Markdown-to-storage converter for all caller Markdown;
- performs the read but no PUT during dry-run; and
- lets a client `conflict` error propagate unchanged.

Verification:

```text
. .venv/bin/activate && pytest tests/test_confluence_writes.py -q
21 passed

. .venv/bin/activate && pytest tests/test_confluence*.py -q
149 passed
```

## Parity and admission

`tools.SCHEMAS`, `plugin.yaml`, and registration now declare the same eight
tools:

```text
OK 8 tools
```

The update tool is in both `_WRITE_TOOLS` and `WRITE_APPROVALS`.  The durable
handler regression proves an otherwise-valid admission minted for
`confluence_create_page` is rejected by `confluence_update_page`; only an
admission whose policy and exact tool name match the update write is accepted.

`git diff --check` also passed.
