---
source_flow: flows/img_generation/Image Generation.json
source_commit: 3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e
source_sha256: 697e8fc382e9a0e881665ca0df7c4349c9748d1fa30a4d830e289a56f024eea0
status: not-ported
target_artifacts: [branded-visual-skill, optional-html-renderer-tool]
supporting_capabilities: [hermes-agent, playwright]
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

Inputs are raw data, template choice, output filename/format/directory, and presentation requirements. Output is a rendered image artifact. The source default filename contains a typo and should not be treated as a contract.

## Supporting capabilities and configuration

The HTML path requires Playwright and installed Chromium. It uses the active Hermes model rather than a flow-specific key. See [visual rendering configuration](../configuration.md#branded-visual-rendering).

## Failure, safety, and privacy behavior

Untrusted generated HTML can load network resources or access local content if the renderer is not constrained. Use a sandboxed, network-disabled renderer, approved local assets, bounded canvas size, and an artifact directory. Validate that data labels are accurate and do not expose confidential sales/customer information.

## Hermes port status and target shape

Not ported. First decide whether the user wants a data-faithful branded infographic or an illustrative image. The former favors a branded-visual skill plus a constrained HTML renderer; the latter may use Hermes' native image generation. These should not be conflated.

## How Hermes should explain and configure it

Ask what data is being visualized, which template/story, required brand treatment, format/dimensions, and confidentiality. Explain the HTML-rendering approach. Validate with synthetic data and inspect the produced artifact for correctness, clipping, fonts, and external requests.
