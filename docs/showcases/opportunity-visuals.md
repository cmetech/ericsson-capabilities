# Opportunity Visuals showcase

Opportunity Visuals turns monthly opportunity pipeline data into exact,
Ericsson-branded progression tables. It supports four views: `wins`, `losses`,
`all-progression`, and `positive-progression`. The skill interviews for only
the decisions it cannot infer, one question at a time, then asks for
confirmation before writing.

This is a deterministic data renderer, not a generative image model. It keeps
opportunity names, values, stages, blank months, and row selection auditable.
It never sends sales data to `image_generate`, a hosted model, web search, or a
remote renderer. Generic image generation is a non-trigger and belongs with
the ordinary image capability.

## Synthetic showcase data

Run this showcase from the repository root after `./bootstrap.sh` has created
the supported Python 3.11+ environment at `.venv`. Use only the committed
synthetic pack:

The commands below use the POSIX venv executable. On Windows, use the same
arguments with `.venv\Scripts\python.exe`; if `bootstrap.sh` is unavailable,
create a Python 3.11+ venv and install the repository development requirements
first.

- CSV: `tests/fixtures/opportunity_visuals/showcase-opportunities.csv`
- JSON: `tests/fixtures/opportunity_visuals/showcase-opportunities.json`
- XLSX: `tests/fixtures/opportunity_visuals/showcase-opportunities.xlsx`
  (worksheet `Pipeline`)
- stage rules: `tests/fixtures/opportunity_visuals/stage-semantics.json`
- independent expected results: `tests/fixtures/opportunity_visuals/expected-*.json`
- reviewed SVG references: `tests/golden/opportunity_visuals/*.svg`

The CSV, JSON, and XLSX files contain the same twelve invented records. They
contain no customer or account identifiers.

| ID | Synthetic data story | What it demonstrates |
|---|---|---|
| OV-001 | Aurora Core Renewal moves Ideation → Proposal → Won, followed by an ignored source value | Wins inclusion and first-terminal truncation |
| OV-002 | Beacon Automation moves Proposal → Workshop → Commercials | The explicit positive Proposal → Workshop edge |
| OV-003 | Cedar Assurance regresses Solution → Ideation → Lost | Negative movement and losses inclusion |
| OV-004 | Delta Capacity remains at Solution | Neutral movement; all-progression only |
| OV-005 | Echo Modernization has one populated stage | Exclusion as `insufficient_stages` in every view |
| OV-006 | Fjord Analytics skips April, then advances | Empty-month preservation and a skipped-month warning |
| OV-007 | Grove Orchestration advances while probability falls | `mixed` classification and warning |
| OV-008 | Harbor Observability `<Pilot> =1+1` contains markup- and formula-like text | Escaping and non-execution |
| OV-009 | Ion Edge Program reaches Lost before later source values | First-terminal truncation in losses/all-progression |
| OV-010 | Juniper Expansion regresses, advances, then reaches Won | Negative, positive, and terminal colors in one row |
| OV-011 | Kite Discovery moves to unrecognized Deferred | `unknown` classification and warning |
| OV-012 | Lumen Platform uses categorical TCV and probability | Stable categorical sorting and probability styling |

## Trigger boundary

Requests that should trigger the skill include:

- “Create an Ericsson opportunity progression infographic from this spreadsheet.”
- “Show me only the opportunities we won this quarter.”
- “Make a losses view from this pipeline data.”
- “Visualize positive opportunity movement from March through May.”

Requests that should not trigger it include:

- “Generate an image of a cellular tower at sunset.”
- “Make this headshot look more professional.”
- “What opportunities are assigned to me in Jira?”
- “Create a pie chart from these survey results.”

The word “opportunity” alone is not enough. The request must combine
opportunity/deal pipeline data with one of the supported progression outcomes.

## Coworker transcript scenarios

### 1. Fully specified

> **User:** Create a 1920×1080 wins view from `pipeline.csv`, using March
> through June and our confirmed stage rules. Write SVG, HTML, and PNG to
> `/tmp/q2-wins`.
>
> **Coworker:** I’ll read `pipeline.csv`, select wins from March through June,
> apply the confirmed stage rules, and write local 1920×1080 SVG, HTML, and
> optional PNG pages to `/tmp/q2-wins`. I will not change the source. Proceed?
>
> **User:** Proceed.

The request supplies every decision, so the coworker asks only for final
confirmation.

### 2. Ambiguous worksheet

> **User:** Make an all-stage progression visual from `pipeline.xlsx`.
>
> **Coworker:** I found worksheets `Current` and `Archive`. Which worksheet
> contains the opportunity history?
>
> **User:** Current.
>
> **Coworker:** I found stages from March through June. Use all four months?

The coworker resolves one ambiguity per turn. It does not bundle the sheet,
range, semantics, and destination into one question.

### 3. Unknown stage

> **Coworker:** Inspection found the transition Discovery → Deferred. Should
> Deferred be a negative terminal or a non-terminal stage?
>
> **User:** Non-terminal.
>
> **Coworker:** I’ll keep Deferred non-terminal and report any transition whose
> direction remains unknown. Proceed with positive progression?

The coworker never guesses an unknown stage order. If the transition does not
affect inclusion, it may render it neutral and retain an
`unknown_transition` warning.

### 4. Confidential destination

> **User:** This pipeline is confidential. Create the losses visual.
>
> **Coworker:** Parsing and rendering stay local; no opportunity data is sent
> to a hosted model or remote renderer. May I write the artifacts to your
> private local directory `/secure/team-a/losses-run`?

The user must approve the local destination before confidential artifacts are
written. A shared or repository path is not assumed.

### 5. PNG fallback

> **Coworker:** SVG and HTML were created successfully. PNG is unavailable
> because local Playwright or Chromium is missing. The manifest records this
> fallback; would you like the user-approved setup commands for local PNG?

Missing PNG support does not turn the SVG/HTML run into a failure. Playwright
and Chromium are not installed automatically.

### 6. Generic-image non-trigger

> **User:** Generate an image of a cellular tower at sunset.
>
> **Coworker:** That is a general illustrative image request, so I’ll use the
> ordinary image capability rather than Opportunity Visuals.

No opportunity helper is run and no pipeline-data questions are asked.

## Reproduce all four views

First inspect the CSV without creating output artifacts:

```bash
.venv/bin/python skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py inspect \
  tests/fixtures/opportunity_visuals/showcase-opportunities.csv
```

Choose a fresh output root. Preparation refuses to reuse a non-empty run
directory.

```bash
RUN_ROOT="$(mktemp -d /tmp/opportunity-visuals-showcase.XXXXXX)"
```

Prepare each canonical view:

```bash
.venv/bin/python skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py prepare \
  tests/fixtures/opportunity_visuals/showcase-opportunities.csv \
  --view wins \
  --semantics tests/fixtures/opportunity_visuals/stage-semantics.json \
  --output-dir "$RUN_ROOT/wins"

.venv/bin/python skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py prepare \
  tests/fixtures/opportunity_visuals/showcase-opportunities.csv \
  --view losses \
  --semantics tests/fixtures/opportunity_visuals/stage-semantics.json \
  --output-dir "$RUN_ROOT/losses"

.venv/bin/python skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py prepare \
  tests/fixtures/opportunity_visuals/showcase-opportunities.csv \
  --view all-progression \
  --semantics tests/fixtures/opportunity_visuals/stage-semantics.json \
  --output-dir "$RUN_ROOT/all-progression"

.venv/bin/python skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py prepare \
  tests/fixtures/opportunity_visuals/showcase-opportunities.csv \
  --view positive-progression \
  --semantics tests/fixtures/opportunity_visuals/stage-semantics.json \
  --output-dir "$RUN_ROOT/positive-progression"
```

Render deterministic SVG/HTML without requiring Playwright:

```bash
.venv/bin/python skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py \
  "$RUN_ROOT/wins/normalized-data.json" \
  --output-dir "$RUN_ROOT/wins" --width 1920 --height 1080 --png never

.venv/bin/python skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py \
  "$RUN_ROOT/losses/normalized-data.json" \
  --output-dir "$RUN_ROOT/losses" --width 1920 --height 1080 --png never

.venv/bin/python skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py \
  "$RUN_ROOT/all-progression/normalized-data.json" \
  --output-dir "$RUN_ROOT/all-progression" --width 1920 --height 1080 --png never

.venv/bin/python skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py \
  "$RUN_ROOT/positive-progression/normalized-data.json" \
  --output-dir "$RUN_ROOT/positive-progression" --width 1920 --height 1080 \
  --png never
```

Expected counts come from the committed independent expected JSON, while the
three warnings come from `expected-normalized.json` and the showcase contract:

| View | Included | Excluded | Warnings | Expected pages at 1920×1080 |
|---|---:|---:|---:|---:|
| `wins` | 2 | 10 | 3 | 1 |
| `losses` | 2 | 10 | 3 | 1 |
| `all-progression` | 11 | 1 | 3 | 1 |
| `positive-progression` | 6 | 6 | 3 | 1 |

Warnings are collected during normalization before view selection: OV-006
skips a blank month, OV-007 has mixed stage/probability signals, and OV-011
has an unknown transition. Read the actual run artifacts rather than assuming
these showcase counts for another dataset.

## Output and audit artifacts

Each one-page run has this shape when PNG is disabled:

```text
<view>/
├── source-summary.json
├── normalized-data.json
├── exclusions.json
├── render-manifest.json
├── opportunity-visual-p01.svg
└── opportunity-visual-p01.html
```

With working local PNG capture, `opportunity-visual-p01.png` is added. Larger
inputs may produce `p02`, `p03`, and further numbered pages.

The four JSON artifacts have separate jobs:

- `source-summary.json` records source hash/format/sheet, mapping, semantics
  hash, selected months, view, filters, and counts.
- `normalized-data.json` is the renderer input and full auditable record of
  included rows, transitions, warnings, exclusions, and counts.
- `exclusions.json` is the focused list of excluded row IDs, source rows,
  stable reason codes, and messages.
- `render-manifest.json` records view/range/dimensions, included and excluded
  row projections, warnings, transition classifications, page-to-row mapping,
  artifact filenames and SHA-256 hashes, and PNG status/reason.

SVG is the canonical output. HTML is a self-contained local preview with no
scripts or remote resources. PNG is an optional local rasterization of that
HTML, not a generated interpretation of the data.

## Real-Playwright PNG demonstration

Check each capability independently before installing anything:

```bash
.venv/bin/python skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py \
  --preflight --output-dir "$RUN_ROOT/png-demo"
```

If the user approves local installation and preflight reports that Playwright
or Chromium is unavailable, follow the configuration guide. Then prepare a
fresh wins directory and require a real browser capture:

```bash
.venv/bin/python skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py prepare \
  tests/fixtures/opportunity_visuals/showcase-opportunities.csv \
  --view wins \
  --semantics tests/fixtures/opportunity_visuals/stage-semantics.json \
  --output-dir "$RUN_ROOT/wins-png"

.venv/bin/python skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py \
  "$RUN_ROOT/wins-png/normalized-data.json" \
  --output-dir "$RUN_ROOT/wins-png" --width 1920 --height 1080 \
  --png required
```

Success reports PNG status `available`, writes a 1920×1080 PNG, and records its
hash in `render-manifest.json`. Failure with `png_unavailable` is specific to
local PNG support; it does not imply that the data or SVG/HTML renderer is
invalid.

## Visual verification

Complete this visual verification by opening every numbered SVG/HTML page and,
when produced, PNG page. Confirm:

- every label matches `normalized-data.json` exactly;
- no text, pill, header, row, or group context is clipped or overlaps;
- teal marks positive/won, coral marks negative/lost, and gray marks initial,
  neutral, mixed, and unknown stages;
- April stays empty for OV-006;
- Area/Sub-area boundaries and repeated page context are clear;
- no stage appears after the applicable first terminal;
- page-to-row mappings, counts, warnings, filenames, and hashes match
  `render-manifest.json`;
- every PNG has the requested dimensions, including 1920×1080 by default;
- HTML/SVG contains no external resource or unexpected network reference.

## Privacy rule

Never commit screenshots, PNGs, HTML, SVG, manifests, or transcripts made from
real sales, customer, account, opportunity, or financial data to this
repository. Repository demonstrations must use the committed synthetic
fixtures. Production inputs and outputs stay in a user-approved local
destination, and no sales data goes to a hosted model.

For dependency and failure guidance, see the [configuration
guide](../configuration.md#opportunity-visuals). For the port relationship to
Loop24, see the [Image Generation flow](../flows/image-generation.md). For the
live behavioral contract, see the [Opportunity Visuals
skill](../../skills/ericsson/opportunity-visuals/SKILL.md).
