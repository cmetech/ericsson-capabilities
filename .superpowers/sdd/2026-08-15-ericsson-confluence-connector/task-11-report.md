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

## Review fix round 1 — plan deviation

The original task sample used empty-string fallbacks for an untouched remote
title and body, and a locally predicted version when the PUT response omitted
one.  That would silently overwrite malformed remote data or report a failed
response as success, so this deliberately deviates from that sample block.

### RED

Added regression cases for missing/non-string current title during a body-only
update; missing body, missing storage, and non-string storage value during a
title-only update; and a successful PUT payload without `version.number`.

```text
. .venv/bin/activate && pytest tests/test_confluence_writes.py -q -k \
  'missing_current_title or missing_or_malformed_current_body or missing_response_version'
5 failed (before the non-string-title parameter was added)
```

The first four failures showed an attempted PUT with an empty fallback field;
the fifth showed the missing response version being accepted. The added
non-string-title parameter passes through the same validation path.

### GREEN

When an update needs to preserve the current title or storage body, that field
is now required to be valid remote data.  Missing/non-string data raises
`invalid_remote_data` after the GET and before a PUT.  PUT responses now require
a valid integer `version.number` rather than falling back to the predicted
version.

```text
. .venv/bin/activate && pytest tests/test_confluence_writes.py -q
27 passed

. .venv/bin/activate && pytest tests/test_confluence*.py -q
155 passed

8-tool schema/manifest parity: OK 8 tools
git diff --check: passed
```

The existing exact-tool admission regression remains part of the full
Confluence suite and passed.
