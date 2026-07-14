---
source_flow: flows/lcm_3pp/3PP_ Support and LCM Tracker.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: e773a9010bcbeb66e70ee0ed7cc82e4b044d66e560a08ee73d55f41aeb6ce376
status: not-ported
target_artifacts: [spreadsheet-tools, lifecycle-enrichment-workflow]
supporting_capabilities: [openpyxl, web-research, hermes-agent]
platforms: [macos, linux, windows]
---

# 3PP Support and LCM Tracker

## What it does

Reads a spreadsheet of third-party products, researches current lifecycle information, and writes an enriched spreadsheet comparing existing and proposed EOM/EOS/latest-version values with provenance and confidence.

## Original Loop24 flow

1. Accept a path to the tracker workbook.
2. Read the configured sheet using a 1-based column map for domain, component, subcomponent, current version, EOM, EOS, latest available, and reference URL.
3. Mark rows carrying the configured skip marker (normally licenses/subscriptions) as manually managed.
4. For each remaining record, optionally fetch the reference URL and ask the LLM to return JSON containing proposed EOM, EOS, latest version, verification status, and source note.
5. Status is one of Vendor Confirmed, AI Researched, Approximate - Needs Review, or Not Verified. Existing values are retained when better evidence is unavailable.
6. Write `lcm_data.xlsx` and show intermediate/final previews.

The source guide describes roughly 200 rows, about 46 skipped rows, and one model call per remaining component. Those counts are examples, not contracts.

## Inputs and outputs

Inputs are workbook, sheet, column map, skip marker, reference URL field, research policy, and output path. Output is a side-by-side enriched XLSX with evidence/status; it must not silently overwrite the input.

## Supporting capabilities and configuration

Requires `openpyxl`, local file access, safe URL retrieval/research, and the active Hermes model. The source uses Langflow globals such as `3PP_LCM_SHEET_NAME`, `3PP_SKIP_MARKER`, and `3PP_URL_FIELD_NAME`; the Hermes port should make these explicit workflow inputs/config. See [document configuration](../configuration.md#document-parsing-and-spreadsheet-output).

## Failure, safety, and privacy behavior

Lifecycle dates are time-sensitive and model knowledge is not authoritative. Prefer vendor sources, capture retrieval date/URL, distinguish inaccessible sources from absent evidence, and require human review before tracker replacement. Defend against spreadsheet formula injection and URL-based SSRF. Use bounded batches, checkpoints, and resume without reprocessing confirmed rows.

## Hermes port status and target shape

Not ported. Build reusable spreadsheet read/write tools and a workflow with per-record research, structured validation, checkpointing, and a review/approval stage. Do not hide 170 model calls inside one opaque plugin operation.

## How Hermes should explain and configure it

Ask for workbook/sheet, column mapping, skip rule, acceptable sources, batch size, and output location. Preview detected columns and skipped rows before research. Validate on a small copy, show evidence quality distribution, then request approval before a full run.
