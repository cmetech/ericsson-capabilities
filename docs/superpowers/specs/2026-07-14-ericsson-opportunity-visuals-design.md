# Ericsson Opportunity Visuals Skill Design

**Date:** 2026-07-14  
**Status:** Approved design; implementation not started  
**Target repository:** `ericsson-capabilities`  
**Source flow:** Loop24 `flows/img_generation/Image Generation.json` at commit `3f124f5cbda2d77e636f6d1d2b03bdcd43fa264e`

## Summary

Port the Loop24 Image Generation flow as a focused Hermes coworker skill named `opportunity-visuals`. The skill will turn opportunity pipeline data into deterministic, Ericsson-branded progression visuals. It will recognize natural-language requests, interview the user one question at a time for any missing decisions, normalize and validate the data, and render data-faithful SVG and HTML artifacts. It will also produce PNG files when a local Chromium renderer is available.

This is not a general text-to-image skill. The source flow asks an LLM to write HTML and then screenshots it; the port replaces that unconstrained generation step with deterministic parsing, classification, and rendering. Hermes' `image_generate` tool is deliberately out of scope because generative image models cannot reliably reproduce exact opportunity names, values, stages, and table structure.

The first release supports the four stories in the Loop24 Prompt Library:

1. Opportunity wins
2. Opportunity losses
3. All opportunity stage progression
4. Positive progression

## Goals

- Preserve the source flow's business intent and Ericsson visual language.
- Produce exact, auditable representations of the supplied data.
- Let a user start with ordinary natural language rather than a command syntax.
- Let the coworker discover missing input through a short, one-question-at-a-time interview.
- Support CSV, JSON, and XLSX opportunity data without requiring an external service or API key.
- Make every inclusion, exclusion, classification, and output file explainable.
- Provide a synthetic showcase pack that can demonstrate all four views without exposing customer or sales data.
- Deliver the capability through the existing Ericsson manifest and vendoring path.

## Non-goals

- General illustration, photography, concept art, or arbitrary infographic generation.
- Reproducing Langflow's graph runtime or keeping its LLM-generated-HTML architecture.
- Editing source CRM, Jira, Outlook, Glean, or spreadsheet records.
- Fetching data from remote systems in the first release.
- Inferring confidential business meaning from customer names.
- Inventing missing stages, probabilities, values, month labels, or terminal outcomes.
- Requiring a hosted rendering API or an image-generation provider.
- Supporting arbitrary user-supplied HTML, JavaScript, fonts, or remote assets.

## Source behavior retained and corrected

The Loop24 flow reads a file, injects its contents into one of four long prompt templates, asks the active text model for HTML, and uses Playwright to screenshot the rendered body. The templates establish the following useful contract:

- Group rows by Area and Sub-area.
- Show Opportunity Name, TCV, Probability, and chronological monthly stages.
- Preserve stage labels exactly as supplied.
- Leave missing months empty.
- Use a neutral first stage, teal/blue for positive movement, coral for negative movement, and gray for no change.
- Stop wins and losses at the first applicable terminal stage.
- Exclude rows with fewer than two populated stages.
- Use a wide, slide-ready Ericsson presentation.

The source prompts are ambiguous in three places. The port resolves them explicitly:

1. They discuss month-to-month probability changes even though the described input has one Probability column. The port uses probability movement only when monthly probability columns are present. A single probability value remains a display and sorting field.
2. They describe several different stage paths but no universal stage order. The port uses confirmed stage semantics and records unknown transitions instead of guessing.
3. They classify both a stage advance and a simultaneous probability decrease as directional movement. The port classifies opposing signals as `mixed`, renders them neutrally, and records the conflict in the manifest.

## Chosen approach

### Decision

Build a specialist skill with local normalization and rendering helpers. Use deterministic SVG as the canonical visual, self-contained HTML as a convenient preview, and constrained Chromium capture as an optional rasterization step.

### Alternatives considered

**Faithful arbitrary-HTML port.** This would keep the source sequence of LLM-produced HTML followed by Playwright. It is flexible and superficially close to Langflow, but it is difficult to validate, vulnerable to untrusted markup and external resource loading, and unreliable for exact labels and pagination.

**Extend the general `baoyu-infographic`/`image_generate` path.** This would reuse an existing creative skill and image provider. It is appropriate for illustrative infographics, but it cannot guarantee table accuracy, spelling, row inclusion, or repeatable output. It would also introduce provider credentials that this capability does not otherwise need.

**Specialist deterministic skill — selected.** This adds a focused skill and two small helper programs. It has the narrowest trigger surface, the clearest test contract, and the best fidelity and privacy properties. SVG/HTML also make visual defects and data mismatches inspectable.

## User experience

### Skill identity and trigger boundary

The skill directory will be `skills/ericsson/opportunity-visuals/`. Its frontmatter description will be:

> Create Ericsson opportunity progression visuals.

The skill should activate when a request combines opportunity or deal pipeline data with a progression, wins, losses, or Ericsson-branded visual outcome. Representative positive triggers include:

- “Create an Ericsson opportunity progression infographic from this spreadsheet.”
- “Show me only the opportunities we won this quarter.”
- “Make a losses view from this pipeline data.”
- “Visualize positive opportunity movement from March through May.”
- “Turn this CSV into a 16:9 Ericsson stage-progression visual.”
- “Create a slide-ready view of our TCV, probability, and monthly stages.”
- “Which deals progressed positively, and can you visualize them?”
- “Make the Loop24 opportunity image from this data.”

The skill should not activate for ordinary image generation, photo editing, generic charts, unrelated sales questions, or a request that only contains the word “opportunity.” Examples that must remain outside its trigger surface include:

- “Generate an image of a cellular tower at sunset.”
- “Make this headshot look more professional.”
- “What opportunities are assigned to me in Jira?”
- “Create a pie chart from these survey results.”

### Interview behavior

The coworker first inspects the user's request and available file metadata. It asks only for decisions it cannot safely infer, and asks exactly one question per turn. It never forces the user through a fixed wizard when the request already contains the answer.

The decision sequence is:

1. **Data source:** obtain a local CSV, JSON, or XLSX path, or accept pasted tabular data.
2. **View:** wins, losses, all-stage progression, or positive progression.
3. **Time range:** identify the chronological month columns to include.
4. **Field mapping:** confirm Area, Sub-area, Opportunity Name, TCV, Probability, and month columns when aliases are ambiguous.
5. **Stage semantics:** confirm terminal aliases, ordered stages, and any special positive transitions needed by the supplied data.
6. **Filters:** accept optional Area, Sub-area, TCV, probability, or opportunity filters.
7. **Output:** default to 1920×1080 pages and SVG/HTML/PNG; ask only if the user needs another size, format, or output directory.
8. **Confidentiality:** if the data appears sensitive, state that rendering remains local and confirm the destination before writing files.

Before rendering, the coworker plays back a concise execution summary: source, selected rows/time range, chosen view, stage rules, output formats, and destination. A correction from the user returns to the relevant interview decision. A confirmation starts normalization and rendering.

Example abbreviated interview:

> **User:** Make a positive progression visual from `pipeline.xlsx`.  
> **Coworker:** I found two sheets. Which sheet contains the opportunity history?  
> **User:** May Pipeline.  
> **Coworker:** I found monthly stages from March through May. Use all three months?  
> **User:** Yes.  
> **Coworker:** I recognize Won and Lost, but this file also contains Deferred. Should Deferred be treated as a negative terminal stage or a non-terminal stage?  
> **User:** Non-terminal.  
> **Coworker:** I’ll include opportunities with at least one confirmed forward movement from March through May, keep Deferred non-terminal, and write local 1920×1080 SVG, HTML, and PNG pages under `opportunity-visuals/<timestamp>/`. Proceed?  
> **User:** Proceed.

## Capability architecture

```text
skills/ericsson/opportunity-visuals/
├── SKILL.md
├── references/
│   ├── data-contract.md
│   ├── interview-guide.md
│   └── visual-rules.md
├── scripts/
│   ├── prepare_opportunities.py
│   └── render_opportunity_visual.py
└── templates/
    └── opportunity-visual.svg
```

The implementation plan may split a helper if testing shows a clear boundary, but it must preserve the following responsibilities.

### `SKILL.md`

- Defines trigger and non-trigger language.
- Explains the conditional, one-question-at-a-time interview.
- Directs the coworker to inspect safely before asking questions.
- Requires playback and confirmation before artifact creation.
- Runs the preparation helper before the renderer.
- Explains the resulting manifest, exclusions, and raster fallback.
- Directs general illustrative image requests to the ordinary image-generation capability.

### `references/data-contract.md`

- Documents accepted file types and column aliases.
- Defines normalized records and stage semantics.
- Describes terminal, positive, negative, neutral, mixed, and unknown classifications.
- Explains parsing errors and how the coworker asks for corrections.

### `references/interview-guide.md`

- Gives the decision order and conditional skip rules.
- Includes concise question patterns and the confirmation playback format.
- Covers confidential-data messaging and safe output selection.

### `references/visual-rules.md`

- Records Ericsson palette, layout, pagination, typography fallback, table rules, and per-view behavior.
- Separates mandatory rules from optional presentation choices.
- Provides the visual verification checklist.

### `scripts/prepare_opportunities.py`

- Reads CSV and JSON with the standard library and XLSX with `openpyxl`.
- Detects sheets, headers, month columns, and supported aliases.
- Validates or applies an explicit field mapping.
- Normalizes values without changing display labels.
- Applies filters, terminal truncation, view selection, grouping, and sorting.
- Emits normalized data, exclusions, warnings, and a source summary.
- Never renders and never calls a model or remote service.

### `scripts/render_opportunity_visual.py`

- Accepts only normalized data and explicit render options.
- Builds deterministic SVG pages with escaped text and approved local styling.
- Writes a self-contained HTML preview around the generated SVG.
- Optionally rasterizes the local HTML/SVG to PNG with an installed Chromium/Playwright path.
- Produces the render manifest and leaves SVG/HTML usable if PNG capture is unavailable.
- Never evaluates input data as markup or script.

### `templates/opportunity-visual.svg`

- Holds the static, reviewed visual frame and style tokens.
- Contains no remote URLs, JavaScript, or user data.
- Is populated only through escaped renderer operations.

## Data contract

### Accepted sources

- UTF-8 CSV with a header row.
- JSON as an array of row objects or an object containing a selected array.
- XLSX with a user-selected or uniquely detected worksheet.
- Pasted tabular data written to a temporary local CSV by the coworker before preparation.

Formula cells in XLSX are read from cached values. If required cached values are missing, the coworker asks the user to recalculate/save the workbook or provide CSV; it does not execute spreadsheet formulas.

### Required logical fields

| Logical field | Requirement | Notes |
|---|---|---|
| Area | Required | Preserved exactly for display and grouping. |
| Sub-area | Required | Common aliases such as `Sub Area` and `Sub-Area` may be detected. |
| Opportunity Name | Required | Serves as display label; a generated row ID is used internally. |
| TCV | Required | Numeric/currency or one consistent categorical scale. |
| Probability | Required | Numeric percentage/ratio or one consistent label scale. |
| Monthly stage | At least two populated cells per included row | Headers must be parseable or explicitly ordered. |

Monthly probabilities are optional. If present, each must map to the same month as a stage column. A lone Probability column is the current/display value and is not treated as historical movement.

### Normalized record

Each record contains:

- stable generated row ID;
- source row number;
- original display values for Area, Sub-area, Opportunity Name, TCV, and Probability;
- normalized sortable TCV and probability ranks;
- ordered month entries containing the original month label, parsed chronological key, stage display value, and optional monthly probability;
- first positive terminal index, first negative terminal index, and transition classifications;
- inclusion decision and exclusion/warning reason codes.

The normalized representation is JSON and is the only input to the renderer. No renderer behavior depends on the original spreadsheet parser.

### Stage semantics

Stage semantics are an explicit JSON object produced from defaults plus user confirmation:

- positive terminal aliases, initially case-insensitive `Won`;
- negative terminal aliases, initially case-insensitive `Lost` and `Cancelled`;
- ordered stage paths supplied or confirmed for the dataset;
- special positive transition edges, including Loop24's `Proposal` → `Workshop` example when relevant;
- optional probability label order, defaulting to `Low`, `Medium`, `High`, `Certain` when those exact labels occur.

Stage display values are never rewritten to match aliases. Aliases affect classification only.

For each transition:

1. A positive or negative terminal destination takes precedence.
2. Otherwise derive a stage signal from a confirmed order/edge and a probability signal from paired monthly probabilities, when available.
3. Matching directional signals, or one directional plus one neutral signal, produce `positive` or `negative`.
4. Opposing directional signals produce `mixed`.
5. No change produces `neutral`.
6. An unrecognized transition with no usable probability signal produces `unknown` and a warning.

`mixed` and `unknown` use neutral gray in the first release. They remain distinct in JSON and the manifest so the user can review them.

### View selection

| View | Included rows | Timeline rule |
|---|---|---|
| Wins | Reaches a positive terminal in range | Stop after the first positive terminal. |
| Losses | Reaches a negative terminal in range | Stop after the first negative terminal. |
| All-stage progression | Has at least two populated stages | Stop after the first terminal of either kind. |
| Positive progression | Has at least one `positive` transition | Stop after the first terminal of either kind. |

All views exclude rows with fewer than two populated stage cells in the selected range. Empty month cells remain empty; stages are never carried forward or backfilled.

### Sorting

Rows are grouped by Area, then Sub-area. Groups use case-insensitive lexical order while preserving original display spelling. Within each Sub-area, rows sort by normalized TCV descending, normalized probability descending, Opportunity Name ascending, then source row number. Mixed numeric and categorical values in either sorting field require user correction or an explicit mapping; the preparer does not invent a cross-type order.

## Rendering contract

### Visual system

- Default page: 1920×1080, wide slide format.
- Background: white or `#F2F2F2`.
- Text: black, with a bundled/installed Ericsson Hilda font used only when its license and local availability permit; otherwise a documented humanist sans-serif fallback stack.
- Positive stage fill: Teal `#23969A`.
- Negative stage fill: Coral `#E65D6A`.
- Neutral, mixed, unknown, and first-stage fill: Gray `#A6A6A6`.
- Structural accent: Ericsson Blue `#1174E6`.
- No gradients, shadows, decorative icons, photos, or external assets.
- Probability appears as its exact display label with a small approved-color bullet.

The first populated stage in each row is neutral regardless of its semantic position, except that a terminal stage keeps its terminal color. Subsequent populated stages use their transition classification. Empty month cells have no pill and no implied transition across the gap; comparison is between consecutive populated stages, and the manifest records the skipped month labels.

### Layout and pagination

- Fixed columns appear in this order: Area, Sub-area, Opportunity Name, TCV, Probability, then chronological months.
- All data rows on a page have equal height; all month columns have equal width.
- Text wraps within bounded lines or is ellipsized with the complete value retained in HTML metadata and the manifest.
- The renderer never reduces body text below the minimum documented in `visual-rules.md` merely to fit more rows.
- When rows or month columns do not fit legibly, the renderer creates numbered pages instead of shrinking the table.
- Every page repeats the title, fixed column headers, month headers, and applicable group context.
- Wins and losses display no stages after the first relevant terminal.
- Stage labels remain exactly as supplied.

### Safe HTML and rasterization

The HTML preview contains only locally generated markup and embedded SVG/CSS. Data values are escaped before insertion. It contains no JavaScript, remote URLs, stylesheets, fonts, images, iframes, or network-capable elements.

PNG capture is best-effort. The rasterizer uses a local file URL, disables network requests, sets the exact viewport, waits only for local layout/font readiness, and captures each page. A missing Playwright package or Chromium binary is a reported fallback, not a failure of the SVG/HTML render. JPEG is not part of the first release because PNG preserves the small text and line art more reliably.

## Output contract

By default, one confirmed run creates:

```text
opportunity-visuals/<timestamp>/
├── source-summary.json
├── normalized-data.json
├── exclusions.json
├── render-manifest.json
├── opportunity-visual-p01.svg
├── opportunity-visual-p01.html
└── opportunity-visual-p01.png
```

Additional pages increment the two-digit page suffix. If PNG capture is unavailable, the manifest marks PNG as `unavailable`, includes the actionable prerequisite message, and the SVG/HTML files remain successful outputs.

The manifest includes:

- view, selected range, mapping, filters, dimensions, and stage-semantics hash;
- source content hash and worksheet name, without copying source data into log text;
- included row IDs and source row numbers;
- excluded row IDs with stable reason codes;
- per-transition classification and warning codes;
- page-to-row mapping and artifact hashes;
- renderer version and PNG availability/fallback reason.

The coworker summarizes counts and links the artifacts. It explicitly mentions exclusions and warnings rather than silently presenting a partial visual.

## Failure and recovery behavior

| Condition | Required behavior |
|---|---|
| No readable source | Ask for a supported local file or pasted table. |
| Multiple XLSX sheets | Ask which sheet to use, one question only. |
| Ambiguous required columns | Show likely matches and ask for one mapping at a time. |
| Unparseable/duplicate month headers | Ask the user for explicit chronological order. |
| Unknown stage transitions | Ask for stage semantics before rendering when they affect selected-view inclusion; otherwise render neutral and warn. |
| Invalid TCV/probability values | Identify source rows and request correction or explicit categorical mapping. |
| No rows match | Produce normalization/exclusion artifacts, explain why, and do not create a blank visual. |
| Too much data | Paginate deterministically and report page count. |
| PNG dependency unavailable | Deliver SVG/HTML and explain how to enable local PNG capture. |
| Output path unwritable | Ask for another local destination; do not redirect silently. |
| Existing output directory | Create a new timestamped directory; never overwrite by default. |

## Privacy and security

- All parsing and rendering are local; no API key is required.
- The skill must not call `image_generate`, a hosted model, web search, or any remote renderer with the opportunity data.
- The coworker should avoid echoing full confidential rows in chat. It may cite row numbers and short opportunity labels when resolving errors.
- No raw input values appear in normal console logs.
- Output permissions follow the user's local environment; the skill warns before writing to a shared or repository path when the data appears confidential.
- Source files remain unchanged.
- JSON, CSV, and XLSX are treated as data, never executable content. Spreadsheet formulas are not executed.
- HTML/SVG escaping tests cover markup, quotes, ampersands, Unicode, and formula-like strings.
- The renderer denies all external requests during PNG capture.

## Configuration and dependencies

The baseline SVG and HTML path needs Python and local file access. XLSX input needs `openpyxl>=3.1.5`. PNG output needs an installed Playwright-compatible Chromium path already supported by Hermes' browser installation. No new secret, Ericsson endpoint, MCP server, plugin, or hosted API is required.

The coworker preflight reports capabilities independently:

- CSV/JSON parsing: available or unavailable;
- XLSX parsing: available or missing `openpyxl`;
- SVG/HTML rendering: available or unavailable;
- PNG capture: available or missing Playwright/Chromium;
- output directory: writable or not writable.

Missing optional PNG support must not block a successful data-faithful SVG/HTML run.

## Ericsson packaging and delivery

The new skill must be added to `sets/ericsson.json` under `skills[]`. Repository tests must cover its frontmatter and helpers. After the Ericsson repository change passes, the normal delivery path is:

1. Vendor with `hermes-agent/scripts/vendor-ericsson.mjs`.
2. Verify the copied skill and tests in `hermes-agent`.
3. Commit the vendored result on the intended Hermes branch.
4. Restamp OTTO/LOOP24 in the normal release workflow.

No new artifact type or manifest schema extension is required.

## Showcase and test artifacts

The implementation will include a synthetic showcase pack under test-owned paths. It must contain no real customer, account, opportunity, or financial data.

```text
tests/fixtures/opportunity_visuals/
├── showcase-opportunities.csv
├── showcase-opportunities.json
├── showcase-opportunities.xlsx
├── stage-semantics.json
├── expected-normalized.json
├── expected-wins.json
├── expected-losses.json
├── expected-all-progression.json
└── expected-positive-progression.json

tests/golden/opportunity_visuals/
├── wins-p01.svg
├── losses-p01.svg
├── all-progression-p01.svg
└── positive-progression-p01.svg

tests/
├── test_opportunity_visuals_prepare.py
├── test_opportunity_visuals_render.py
├── test_opportunity_visuals_showcase.py
└── test_opportunity_visuals_skill.py

docs/showcases/
└── opportunity-visuals.md
```

### Synthetic dataset coverage

The canonical fixture contains at least these invented cases:

| ID | Synthetic story | Expected purpose |
|---|---|---|
| OV-001 | `Aurora Core Renewal` advances from Ideation → Proposal → Won | Included in wins, all, and positive views; terminal truncation proven. |
| OV-002 | `Beacon Automation` moves Proposal → Workshop → Commercials | Exercises the explicit Loop24 positive edge. |
| OV-003 | `Cedar Assurance` regresses Solution → Ideation → Lost | Included in losses/all; negative movement proven. |
| OV-004 | `Delta Capacity` remains Solution across all months | Included only in all; neutral progression proven. |
| OV-005 | `Echo Modernization` has one populated stage | Excluded from every view with `insufficient_stages`. |
| OV-006 | `Fjord Analytics` skips April, then advances in May | Empty month preservation and skipped-month comparison proven. |
| OV-007 | `Grove Orchestration` advances a stage while monthly probability falls | Classified `mixed`, neutral-rendered, and surfaced in warnings. |
| OV-008 | `Harbor Observability <Pilot>` includes markup-like text and `=1+1` | Escaping and non-execution proven. |
| OV-009 | `Ion Edge Program` reaches Lost then has a later populated stage | First-terminal truncation proven. |
| OV-010 | `Juniper Expansion` reaches Won after a negative intermediate move | Wins inclusion plus both negative and positive timeline colors proven. |
| OV-011 | `Kite Discovery` uses an unknown transition | Unknown classification/interview behavior proven. |
| OV-012 | `Lumen Platform` uses categorical TCV and probability | Deterministic categorical sorting and probability bullet proven. |

The canonical showcase uses one consistent categorical TCV scale and one consistent categorical probability scale across all twelve rows. Separate small unit-test inputs exercise numeric currency and numeric percentage parsing; numeric and categorical values are never mixed within one sortable field unless an explicit mapping is supplied.

CSV, JSON, and XLSX showcase fixtures express the same logical records. Their expected normalized JSON must be identical except for source-format metadata. The XLSX file contains cached values only and no macros, external links, hidden sheets, formulas, or real-world identifiers.

### Expected view artifacts

Each `expected-*.json` file records exact included IDs, excluded IDs/reasons, row order, terminal cutoffs, transition classes, page assignment, and warning codes. Golden SVGs prove deterministic geometry and escaped content. Tests compare canonicalized SVG/XML rather than PNG pixels so font rasterization and operating-system differences do not create false failures.

PNG files are generated during a local showcase run but are not committed as the primary golden contract. A showcase script/test records their dimensions, verifies they are non-empty, and scans for clipping with structural bounds. A maintainer then performs the visual checklist before using the PNGs in a presentation.

### Natural-language and interview scenarios

The showcase document contains transcript-style demonstrations for:

1. a fully specified request that needs no questions beyond confirmation;
2. an ambiguous XLSX request that asks one question per turn;
3. an unknown stage requiring semantics clarification;
4. a confidential-data reminder and local output choice;
5. PNG fallback when Chromium is unavailable;
6. a generic image request that does not use this skill.

These scenarios are testable as skill-content assertions and manual coworker acceptance checks. They demonstrate both what the skill does and where it intentionally yields to another capability.

## Test strategy

### Unit tests

- CSV, JSON, and XLSX loaders produce equivalent logical records.
- Header aliases and explicit mappings resolve correctly.
- Month parsing and explicit ordering are chronological and deterministic.
- Numeric and categorical TCV/probability values normalize and sort correctly.
- Stage terminal aliases, ordered paths, special edges, and unknowns classify correctly.
- Opposing stage/probability signals produce `mixed`.
- Blank months remain blank and compare only consecutive populated stages.
- Each of the four view filters includes and excludes the canonical IDs expected above.
- Terminal truncation stops at the correct first terminal.
- All output strings are escaped and formula-like values remain inert text.
- Pagination is stable for identical input and options.
- Identical normalized data and configuration produce byte-stable canonical SVG.
- HTML contains no scripts or external resources.
- PNG unavailability returns a successful SVG/HTML result with a structured fallback.

### Contract and repository tests

- `SKILL.md` name matches `opportunity-visuals`.
- Description is one sentence, at most 60 characters, and ends with a period.
- Ericsson tags and supported platforms are present.
- Skill references and scripts exist and use only allowed relative paths.
- `sets/ericsson.json` lists the skill exactly once.
- Manifest lint and the full Ericsson pytest suite pass.
- Vendoring copies all intended skill files and no test fixtures into runtime content unless explicitly configured.

### Skill behavior tests

- Positive trigger examples are represented in When to Use guidance.
- Negative trigger examples are represented in non-trigger/pitfall guidance.
- The interview requires one question at a time and conditionally skips known decisions.
- Playback confirmation precedes writes.
- The skill explains exclusions, warnings, and PNG fallback.
- The skill never instructs the coworker to send source data to `image_generate` or a remote service.

### End-to-end showcase test

Run the canonical synthetic CSV through all four views with fixed dimensions, semantics, and deterministic output options. Compare normalized and view manifests to the expected JSON, compare canonical SVG to the golden files, validate HTML safety, and optionally capture PNG. The showcase is accepted only when:

- every expected row and transition is correct;
- all four views are produced;
- no stage/value label is invented or changed;
- no content is clipped or overlaps at the default size;
- no external network request occurs;
- the coworker summary matches manifest counts;
- the documentation transcript can be reproduced with the fixtures.

## Documentation updates at implementation time

- Update `docs/flows/image-generation.md` from `not-ported` to `intent-ported` only after the skill and its tests pass.
- Add setup and troubleshooting details to `docs/configuration.md`, including the no-key baseline and optional PNG prerequisites.
- Add the live skill and showcase links to `docs/README.md`.
- Add `docs/showcases/opportunity-visuals.md` with reproducible prompts, fixture descriptions, expected outputs, and visual verification steps.
- Keep `CLAUDE.md` and `AGENTS.md` synchronized if durable repository memory changes.

## Acceptance criteria

The port is ready to vendor when all of the following are true:

- Natural-language usage and non-usage boundaries are explicit.
- The coworker asks only missing questions, one at a time, and confirms before writing.
- CSV, JSON, and XLSX versions of the showcase data normalize equivalently.
- All four Loop24 views follow the deterministic inclusion and truncation rules.
- Stage names, month labels, opportunity labels, TCV, and probability remain data-faithful.
- SVG and HTML work without an API key; missing PNG support degrades cleanly.
- Rendered HTML/SVG cannot execute source data or load remote resources.
- Included, excluded, mixed, and unknown decisions are auditable in manifests.
- Synthetic fixtures, expected JSON, golden SVG, transcript scenarios, and visual checks are present.
- Manifest, skill, helper, security, and end-to-end tests pass.
- The flow page, configuration guide, showcase guide, manifest, and vendored Hermes copy agree with the implementation.

## Deferred extensions

These require a separate design after the first release:

- Direct CRM or data-warehouse retrieval.
- Additional visualization families beyond the four source views.
- User-authored branding themes or arbitrary HTML templates.
- Editable PowerPoint generation.
- Interactive browser filtering or dashboard behavior.
- Automated confidential-data classification beyond a conversational warning.
