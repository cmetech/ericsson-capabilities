---
source_flow: flows/img_generation/Image Generation.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: 697e8fc382e9a0e881665ca0df7c4349c9748d1fa30a4d830e289a56f024eea0
status: intent-ported
target_artifacts: [opportunity-visuals-skill]
supporting_capabilities: [python, openpyxl, playwright, chromium]
platforms: [macos, linux, windows]
---

# Image Generation

## What it does

Creates Ericsson-branded data infographics. Despite its name, the source does not use a diffusion image model: it asks an LLM to generate HTML from a branded prompt template and screenshots the rendered page.

## Original Loop24 flow

1. Read a local data file.
2. Prompt Library injects the data into one of several branded infographic templates. The checked-in selection is “Positive Progression”; other source templates cover opportunity wins, losses, and stage progression.
3. An LLM returns HTML implementing the visual.
4. Image Writer extracts that HTML, opens it in headless Chromium through Playwright, and writes PNG/JPEG.
5. Chat displays the resulting file path.

## Inputs and outputs

The live port accepts local CSV, JSON, or XLSX opportunity history, one of four
views (`wins`, `losses`, `all-progression`, or `positive-progression`),
confirmed stage semantics, optional filters, dimensions, and a local output
directory. It produces deterministic SVG pages, self-contained HTML previews,
optional local PNG pages, and JSON audit artifacts. The source default
filename contains a typo and is not a contract.

## Supporting capabilities and configuration

Python and local file access provide CSV/JSON plus SVG/HTML with no API key.
XLSX needs openpyxl. PNG alone needs Playwright and locally installed Chromium;
missing PNG support is an explicit fallback, not failure of SVG/HTML. See
[Opportunity Visuals configuration](../configuration.md#opportunity-visuals).

## Failure, safety, and privacy behavior

The port does not accept generated or user-authored HTML. It escapes input into
reviewed SVG/HTML, embeds no remote resources, and denies external requests
during local PNG capture. Source files are read-only. Ambiguous mappings or
stage semantics require clarification one question at a time; exclusions and
warnings remain auditable. Confidential outputs go only to a user-approved
local destination, and repository screenshots must use synthetic data.

## Hermes port status and target shape

Intent ported. The live
[`opportunity-visuals`](../../skills/ericsson/opportunity-visuals/SKILL.md)
skill preserves the source outcome for its four opportunity views while
replacing LLM-generated HTML with deterministic normalization and SVG/HTML
rendering. Optional PNG is a constrained local Playwright capture. General
illustrative requests remain with Hermes' ordinary image generation and do
not trigger this skill.

Use the [reproducible showcase](../showcases/opportunity-visuals.md) to run all
four views, inspect expected counts and manifests, exercise PNG, and perform
visual verification. The [approved design](../superpowers/specs/2026-07-14-ericsson-opportunity-visuals-design.md)
records why the intent port deliberately differs from the Langflow graph.

## How Hermes should explain and configure it

Inspect the request and source metadata, ask only for missing decisions one at
a time, then play back the source, view, range, semantics, filters, formats,
dimensions, and destination before writing. Explain that rendering is local,
deterministic, and no-key. Validate with synthetic data; review labels,
clipping, colors, blank months, terminal cutoffs, warnings, hashes, and any PNG
fallback against `render-manifest.json`.
