---
source_flow: flows/how-to/TOL Generation.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: b026c540ec24685324d62b208058d2acc815639aa50de8a9976bd5ca24e8e7ea
status: not-ported
target_artifacts: [document-parser-tool, test-case-generation-workflow, spreadsheet-export-tool]
supporting_capabilities: [docling, spreadsheet-export, hermes-agent]
platforms: [macos, linux, windows]
---

# TOL Generation

## What it does

Turns a requirements document into a structured spreadsheet of telecom OSS/BSS test cases. The exported flow's internal name is “Test Case”; the acronym “TOL” is retained from the source filename and should not be expanded without product-owner confirmation.

## Original Loop24 flow

1. The user supplies a document through chat.
2. Docling parses it with the standard pipeline and table-structure recovery enabled, producing lossless and Markdown representations.
3. The Markdown is passed to an LLM instructed to act as a principal testing architect and cover every requirement.
4. The LLM must return one raw JSON object containing `test_cases`; each record has an ID, requirement, title, prerequisite, steps, and expected result.
5. JSON to Spreadsheet writes an XLSX (source default filename `output`, sheet `Sheet1`) and shows a preview.

## Inputs and outputs

Input is a supported requirements document plus optional parsing/OCR choices. Output is JSON and an XLSX artifact. The port should preserve requirement-to-test traceability, identify requirements that could not be parsed, and validate the output schema before writing the spreadsheet.

## Supporting capabilities and configuration

Docling and `openpyxl` are required; the active Hermes model replaces the source's embedded model configuration. See [document configuration](../configuration.md#document-parsing-and-spreadsheet-output).

## Failure, safety, and privacy behavior

Requirements may contain proprietary data. Keep parsing and artifacts local, bound document size, and warn before external model use if the active provider sends content outside the machine. Never silently omit a requirement: surface parse gaps and schema failures. Formula-like spreadsheet cells must be escaped to avoid formula injection.

## Hermes port status and target shape

No parser/export tools or workflow are present in this capability repo. The likely split is a local document parser tool, a prompt node that creates schema-validated test cases, a spreadsheet export tool, and a workflow coordinating artifacts. Do not port the Langflow model node as another provider client.

## How Hermes should explain and configure it

Ask what the document represents, desired test depth, output columns/format, and whether external model processing is allowed. Validate with a small synthetic requirements file, confirm every requirement maps to at least one case, then verify the XLSX opens safely.
