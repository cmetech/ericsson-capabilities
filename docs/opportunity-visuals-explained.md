# Opportunity Visuals, explained

## Who this is for

This guide is for someone who wants to understand what Opportunity Visuals does without reading
Python or knowing how Hermes skills are packaged. After reading it, you should be able to explain
the user experience, recognize the generated files, understand the safety boundaries, and know
how the skill reaches both OTTO and LOOP24.

## What was delivered

Opportunity Visuals turns monthly sales-opportunity history into Ericsson-branded progression
tables. It is a deterministic reporting tool, not a generative image model. The same confirmed
input and rules produce the same result.

It supports four views:

- **Wins:** opportunities that reached a confirmed positive terminal stage.
- **Losses:** opportunities that reached a confirmed negative terminal stage.
- **All progression:** opportunities with enough monthly history to show movement.
- **Positive progression:** opportunities whose confirmed stage or probability movement is positive.

The source can be CSV, JSON, or XLSX. The normal outputs are SVG and HTML pages. PNG is optional
when Playwright and a local Chromium browser are available. The helper scripts do not call a
remote image service and require no new API key.

## What using it feels like

A user can ask naturally:

> Create an Ericsson wins visual from this opportunity spreadsheet for March through June.

The coworker follows this sequence:

1. Inspect the file without changing it.
2. Identify the worksheet, columns, months, and stage history it can safely infer.
3. Ask one question at a time for anything that changes the result.
4. Analyze the proposed report without writing output files.
5. Play back the source, date range, stage rules, filters, formats, and destination.
6. Wait for confirmation.
7. Prepare auditable data and render the visual pages.
8. Report what was included, excluded, warned about, and written.

Terminal meaning and movement direction are separate decisions. For example, the coworker first
asks whether `Deferred` is terminal or non-terminal. If it is non-terminal, it can then ask whether
moving to `Deferred` is forward, backward, or neutral. It reruns analysis after each answer instead
of guessing.

## The parts, in plain language

| Part | What it does |
|---|---|
| Skill instructions | Tell the coworker when this capability should trigger, which questions to ask, and when it may write files. |
| Interview guide | Enforces one question at a time and prevents the coworker from bundling several ambiguous decisions together. |
| Data contract | Defines valid columns, months, stage semantics, probabilities, filters, errors, and exclusions. |
| Data helper | Reads CSV, JSON, and XLSX; validates values; maps columns; classifies movement; and selects records for each view. |
| Preparation helper | Provides `inspect`, read-only `analyze`, and confirmed `prepare` operations. |
| Renderer | Builds fixed-size Ericsson SVG and HTML pages, optionally captures PNG, and records artifact hashes. |
| SVG template | Supplies the stable visual frame used by the renderer. |
| Ericsson manifest entry | Makes the skill discoverable in the bundled Hermes capability set. |

## What the generated files mean

Preparation creates three audit files:

- **source-summary.json** records which source, source hash, view, rules, months, and filters were used.
- **normalized-data.json** contains the validated records and decisions consumed by the renderer.
- **exclusions.json** explains which source rows were left out and why.

Rendering creates one or more numbered SVG and HTML pages, optional numbered PNG pages, and a
**render-manifest.json**. The render manifest records page assignments, artifact hashes, counts,
warnings, and whether PNG was available or fell back cleanly to SVG and HTML.

## Important behavior and safety boundaries

- Source files are read-only. Spreadsheet formulas are never executed.
- Blank months stay blank; the tool does not invent or carry stages forward.
- A known terminal stage stops later source values from changing that opportunity's result.
- Probabilities must be finite values between 0 and 100.
- User text is escaped before entering HTML or SVG.
- Existing output files are not overwritten by default.
- A failed multi-file write is rolled back without deleting files owned by another process.
- The renderer records hashes so a reviewer can confirm which bytes were produced.
- Local helpers make no model or network calls. The coworker conversation is model-backed, so
  minimal metadata and stage labels used to resolve ambiguity may enter the configured chat model.

## Demonstration and regression material

The repository includes a twelve-row fictional opportunity set in CSV, JSON, and XLSX. All three
formats describe the same invented records. Independent expected-result files define which records
belong in each view, expected counts and page assignments, and reviewed golden SVG pages.

This pack demonstrates wins, losses, positive and negative movement, stable stages, skipped months,
mixed stage/probability signals, terminal cutoffs, unknown stages, categorical values, text escaping,
and formula-like text that must remain inert.

## Why the implementation was substantial

This is closer to a small reporting product than a prompt file. The runtime package contains three
large helpers for ingestion and business rules, preparation and audit, and deterministic rendering.
The source repository also carries contracts, interview guidance, a showcase, independent fixtures,
expected results, and golden visual references.

The final test suite covers hundreds of cases. Review cycles found and corrected issues that a quick
prototype would normally miss, including blank identifiers, duplicate identifiers, invalid and
extremely large numbers, probability values outside 0–100, interrupted writes, concurrent output
changes, and integrity checks across a multi-file render. Much of the elapsed implementation time
was spent proving that the tool fails safely and reproducibly rather than merely producing an image
for the happy path.

## How the skill reaches OTTO and LOOP24

The Ericsson capabilities repository is the source of truth. Hermes receives a committed snapshot
through the manifest-driven vendor command.

Shared capability content belongs on Hermes's neutral **base** branch. From there, `base` is merged
into every discovered brand branch, including **otto** and **loop24**. Each brand then regenerates and
checks only its branding overlay. Opportunity Visuals itself is identical in both brands.

The invariant is:

```text
Ericsson source → Hermes base → OTTO
                              → LOOP24
```

Shared skills must never be introduced only on a brand branch. Direct brand-branch commits are
reserved for generated branding or truly brand-specific assets.
