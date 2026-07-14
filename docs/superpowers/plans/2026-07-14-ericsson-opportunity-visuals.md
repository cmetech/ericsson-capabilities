# Ericsson Opportunity Visuals Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build and vendor a Hermes coworker skill that interviews users and renders four data-faithful Ericsson opportunity progression views, with a synthetic showcase pack.

**Architecture:** A focused `opportunity-visuals` skill drives a conditional interview and two-stage local pipeline. Python helpers inspect/normalize CSV, JSON, or XLSX into an auditable JSON contract, then create deterministic SVG and self-contained HTML; optional Python Playwright capture adds PNG without blocking the baseline output. Repository-owned synthetic fixtures, expected selection JSON, canonical SVG, and transcript scenarios demonstrate all four Loop24 views.

**Tech Stack:** Python 3.11+, standard-library CSV/JSON/XML/dataclasses/argparse, `openpyxl>=3.1.5` for XLSX, optional `playwright>=1.52` plus Chromium for PNG, pytest, Markdown, Ericsson capability manifest, Node vendoring script.

## Global Constraints

- Use skill slug `opportunity-visuals` and frontmatter description `Create Ericsson opportunity progression visuals.`.
- Support only wins, losses, all-stage progression, and positive progression in version 1.
- Keep parsing and rendering local; do not call `image_generate`, a hosted model, web search, or a remote renderer with opportunity data.
- Require no API key, endpoint, MCP server, or plugin for SVG/HTML output.
- Support UTF-8 CSV, JSON arrays/object arrays, and XLSX; never execute spreadsheet formulas.
- Preserve display values and stage labels exactly; never fill blank months.
- Exclude rows with fewer than two populated stages and record stable exclusion reasons.
- Use confirmed stage semantics; render `mixed` and `unknown` transitions neutral gray and expose warnings.
- Stop each row after its first positive or negative terminal, according to the selected view contract.
- Default to 1920×1080 pages; paginate rather than reduce text below the documented minimum.
- Use only `#1174E6`, `#23969A`, `#E65D6A`, white, black, and approved neutral grays; no gradients, shadows, remote assets, or executable markup.
- Treat SVG as canonical, HTML as self-contained preview, and PNG as optional local Playwright output.
- Ask only missing interview questions, exactly one per turn, then play back and confirm before writing.
- Keep `CLAUDE.md` and `AGENTS.md` byte-identical if durable repository memory changes.
- Run commands from `ericsson-capabilities/` unless a step explicitly names `hermes-agent/`.

---

## Planned file structure

```text
ericsson-capabilities/
├── skills/ericsson/opportunity-visuals/
│   ├── SKILL.md
│   ├── requirements.txt
│   ├── references/
│   │   ├── data-contract.md
│   │   ├── interview-guide.md
│   │   └── visual-rules.md
│   ├── scripts/
│   │   ├── opportunity_data.py
│   │   ├── prepare_opportunities.py
│   │   └── render_opportunity_visual.py
│   └── templates/
│       └── opportunity-visual.svg
├── tests/
│   ├── fixtures/opportunity_visuals/
│   │   ├── build_showcase_fixtures.py
│   │   ├── showcase-opportunities.csv
│   │   ├── showcase-opportunities.json
│   │   ├── showcase-opportunities.xlsx
│   │   ├── stage-semantics.json
│   │   ├── expected-normalized.json
│   │   ├── expected-wins.json
│   │   ├── expected-losses.json
│   │   ├── expected-all-progression.json
│   │   └── expected-positive-progression.json
│   ├── golden/opportunity_visuals/
│   │   ├── wins-p01.svg
│   │   ├── losses-p01.svg
│   │   ├── all-progression-p01.svg
│   │   └── positive-progression-p01.svg
│   ├── test_opportunity_visuals_prepare.py
│   ├── test_opportunity_visuals_render.py
│   ├── test_opportunity_visuals_showcase.py
│   └── test_opportunity_visuals_skill.py
└── docs/showcases/opportunity-visuals.md
```

`opportunity_data.py` owns pure loaders, month/mapping logic, normalization, classification, and view selection. `prepare_opportunities.py` owns inspection/preparation CLI behavior and JSON files. `render_opportunity_visual.py` owns layout, SVG/HTML output, optional PNG capture, and render manifests. The renderer consumes normalized JSON only and does not import spreadsheet parsing behavior.

### Task 1: Skill contract, references, dependencies, and manifest

**Files:**
- Create: `skills/ericsson/opportunity-visuals/SKILL.md`
- Create: `skills/ericsson/opportunity-visuals/requirements.txt`
- Create: `skills/ericsson/opportunity-visuals/references/data-contract.md`
- Create: `skills/ericsson/opportunity-visuals/references/interview-guide.md`
- Create: `skills/ericsson/opportunity-visuals/references/visual-rules.md`
- Modify: `sets/ericsson.json`
- Modify: `requirements-dev.txt`
- Modify: `tests/test_manifest.py`
- Create: `tests/test_opportunity_visuals_skill.py`

**Interfaces:**
- Consumes: Approved design at `docs/superpowers/specs/2026-07-14-ericsson-opportunity-visuals-design.md`.
- Produces: Skill path `skills/ericsson/opportunity-visuals`, manifest entry, runtime dependency declaration, and behavioral text assertions used by later tasks.

- [ ] **Step 1: Write failing skill and manifest tests**

Add the following focused assertions:

```python
# tests/test_opportunity_visuals_skill.py
from pathlib import Path

import yaml

REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skills/ericsson/opportunity-visuals"


def test_opportunity_visuals_frontmatter_contract():
    text = (SKILL_DIR / "SKILL.md").read_text()
    fm = yaml.safe_load(text.split("---\n", 2)[1])
    assert fm["name"] == "opportunity-visuals"
    assert fm["description"] == "Create Ericsson opportunity progression visuals."
    assert len(fm["description"]) <= 60
    assert fm["platforms"] == ["macos", "linux", "windows"]
    assert "Ericsson" in fm["metadata"]["hermes"]["tags"]


def test_opportunity_visuals_interview_and_trigger_contract():
    body = (SKILL_DIR / "SKILL.md").read_text()
    required = (
        "one question at a time",
        "wins",
        "losses",
        "all-stage progression",
        "positive progression",
        "play back",
        "confirm",
        "prepare_opportunities.py",
        "render_opportunity_visual.py",
        "image_generate",
        "generic image",
        "exclusions.json",
        "render-manifest.json",
    )
    for phrase in required:
        assert phrase in body


def test_opportunity_visuals_references_and_requirements_exist():
    for rel in (
        "references/data-contract.md",
        "references/interview-guide.md",
        "references/visual-rules.md",
        "requirements.txt",
    ):
        assert (SKILL_DIR / rel).is_file()
    requirements = (SKILL_DIR / "requirements.txt").read_text().splitlines()
    assert "openpyxl>=3.1.5" in requirements
    assert "playwright>=1.52" in requirements
```

In `tests/test_manifest.py`, extend `test_manifest_content()` with:

```python
assert "skills/ericsson/opportunity-visuals" in doc["skills"]
assert doc["skills"].count("skills/ericsson/opportunity-visuals") == 1
assert doc["version"] == "0.3.0"
```

- [ ] **Step 2: Run the focused tests and verify the intended failures**

Run:

```bash
.venv/bin/pytest tests/test_opportunity_visuals_skill.py tests/test_manifest.py tests/test_skill_frontmatter.py -q
```

Expected: failures because the skill path and manifest entry do not exist and the manifest is still version `0.2.0`.

- [ ] **Step 3: Add the manifest and dependency contract**

Change `sets/ericsson.json` version to `0.3.0` and append the skill exactly once:

```json
"skills": [
  "skills/ericsson/workflow-orchestrator",
  "skills/ericsson/workflow-builder",
  "skills/ericsson/opportunity-visuals"
]
```

Add `openpyxl>=3.1.5` to `requirements-dev.txt`. Create the skill-local `requirements.txt` with:

```text
openpyxl>=3.1.5
playwright>=1.52
```

Do not add an environment variable or provider key to the manifest.

- [ ] **Step 4: Write the skill instructions**

Create `SKILL.md` with this frontmatter and section order:

```markdown
---
name: opportunity-visuals
description: Create Ericsson opportunity progression visuals.
version: 1.0.0
author: Ericsson (cmetech)
platforms: [macos, linux, windows]
metadata:
  hermes:
    tags: [Ericsson, Opportunities, Visualization, Sales]
---

# Opportunity Visuals

Turn opportunity pipeline history into exact Ericsson-branded progression
tables. This skill is local and deterministic; it is not a general image
generator.

## When to Use

Use for natural-language requests that combine opportunity/deal data with
wins, losses, all-stage progression, positive progression, a Loop24
opportunity image, or an Ericsson slide-ready progression visual. Do not use
for a generic image, photo edit, unrelated chart, or a request that merely
contains the word opportunity. Route those generic image requests to the
ordinary image capability. Never send opportunity data to `image_generate`.

## Prerequisites

Python and local file access provide CSV/JSON plus SVG/HTML. XLSX requires
`openpyxl>=3.1.5`. PNG additionally requires `playwright>=1.52` and local
Chromium. Missing PNG support does not block SVG/HTML.

## How to Run

1. Inspect the request and source metadata before asking anything.
2. Ask only for missing decisions, one question at a time, following
   `references/interview-guide.md`.
3. Read `references/data-contract.md`; confirm ambiguous columns, months, and
   stage semantics without changing display labels.
4. Play back source, view, range, rules, filters, formats, and destination.
   Wait for the user to confirm before writing.
5. Run `scripts/prepare_opportunities.py inspect` as needed, then
   `scripts/prepare_opportunities.py prepare` into a new timestamped output
   directory.
6. Run `scripts/render_opportunity_visual.py` using `normalized-data.json`.
7. Read `exclusions.json` and `render-manifest.json`; report included,
   excluded, warning, page, and PNG fallback counts with artifact paths.

## Quick Reference

- Views: wins, losses, all-stage progression, positive progression.
- Default size: 1920×1080.
- Canonical output: SVG; preview: HTML; optional raster: PNG.
- No API key and no remote renderer.
- Source files are read-only and blank months remain blank.

## Procedure

Use the exact CLI forms documented in `references/data-contract.md`. If
inspection reports more than one sheet, ambiguous columns/months, or unknown
transitions that affect inclusion, ask one resolving question and rerun. For
confidential data, say rendering stays local and confirm the output directory.
Never overwrite an existing run directory by default.

## Pitfalls

- Do not invent, rename, carry forward, or backfill stages.
- Do not infer monthly probability movement from one current Probability field.
- Do not classify an unknown stage order as forward or backward.
- Do not render user values as HTML or SVG markup.
- Do not claim PNG failure means the SVG/HTML run failed.
- Do not use this skill for generic image generation.

## Verification

Confirm artifact hashes and counts in `render-manifest.json`, review every
warning/exclusion, and apply `references/visual-rules.md`. For a showcase,
use only the repository-owned synthetic fixture pack when it is available.
```

- [ ] **Step 5: Write the three reference contracts**

Write `interview-guide.md` with the exact conditional order: source, view, range, mapping, semantics, filters, output, confidentiality; state “one question at a time,” skip known answers, and require a playback confirmation. Accept pasted tabular data by writing it to an approved temporary UTF-8 CSV before inspection. Include the eight positive trigger examples and four negative examples from the design spec.

Write `data-contract.md` with these exact CLI contracts:

```text
python3 scripts/prepare_opportunities.py inspect SOURCE [--sheet SHEET] [--json-key KEY]
python3 scripts/prepare_opportunities.py prepare SOURCE --view VIEW \
  --semantics SEMANTICS.json [--mapping MAPPING.json] \
  --output-dir DIRECTORY [--sheet SHEET] [--json-key KEY] \
  [--months LABEL] [--filters FILTERS.json]
python3 scripts/render_opportunity_visual.py --preflight --output-dir DIRECTORY
python3 scripts/render_opportunity_visual.py normalized-data.json \
  --output-dir DIRECTORY [--width 1920] [--height 1080] \
  [--png auto|never|required]
```

Document the normalized keys `schema_version`, `view`, `source`, `mapping`, `semantics`, `selected_months`, `filters`, `records`, `exclusions`, `warnings`, and `counts`. Document stable exclusion codes `missing_required_value`, `invalid_tcv`, `invalid_probability`, `insufficient_stages`, `filter_not_matched`, `view_not_matched`, and `terminal_before_range`. Document transition values `initial`, `positive`, `negative`, `neutral`, `mixed`, `unknown`, `won`, and `lost`.

Document this exact optional mapping shape; when it is absent, unambiguous aliases/months are auto-detected:

```json
{
  "area": "Area",
  "sub_area": "Sub-area",
  "opportunity_name": "Opportunity Name",
  "tcv": "TCV",
  "probability": "Probability",
  "months": [
    {"key": "2026-03", "label": "Mar '26", "stage": "Mar '26", "probability": "Mar '26 Probability"}
  ]
}
```

Document this exact semantics shape:

```json
{
  "positive_terminals": ["Won"],
  "negative_terminals": ["Lost", "Cancelled"],
  "stage_paths": [["Ideation", "Solution", "Proposal", "SDP2", "Won"]],
  "positive_transitions": [["Proposal", "Workshop"]],
  "tcv_order": ["X-Small", "Small", "Medium", "Large", "X-Large"],
  "probability_order": ["Low", "Medium", "High", "Certain"]
}
```

Write `visual-rules.md` with the exact colors and layout constraints from Global Constraints, a minimum 16px body/stage font at 1920×1080, fixed column order, repeated headers, terminal truncation, no network resources, and the manual checks: labels, clipping, overlap, colors, empty months, group boundaries, page continuity, terminal cutoff, and PNG dimensions.

- [ ] **Step 6: Run focused and full Ericsson tests**

Run:

```bash
./bootstrap.sh
.venv/bin/pytest tests/test_opportunity_visuals_skill.py tests/test_manifest.py tests/test_skill_frontmatter.py -q
.venv/bin/pytest -q
```

Expected: the development environment contains `openpyxl>=3.1.5`, all focused tests pass, then the full suite passes with no failures. Dependency installation may require network approval during execution.

- [ ] **Step 7: Commit the skill contract slice**

```bash
git add skills/ericsson/opportunity-visuals sets/ericsson.json requirements-dev.txt tests/test_manifest.py tests/test_opportunity_visuals_skill.py
git commit -m "feat: add opportunity visuals skill contract"
```

### Task 2: Source inspection, loaders, field mapping, and month detection

**Files:**
- Create: `skills/ericsson/opportunity-visuals/scripts/opportunity_data.py`
- Create: `skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py`
- Create: `tests/test_opportunity_visuals_prepare.py`

**Interfaces:**
- Consumes: `openpyxl>=3.1.5` from Task 1.
- Produces: `load_source(path: Path, sheet: str | None = None, json_key: str | None = None) -> tuple[list[dict[str, object]], dict[str, object]]`, `parse_month_header(header: str) -> tuple[str, str] | None`, `resolve_mapping(headers: list[str], explicit: dict[str, object] | None) -> dict[str, object]`, `inspect_source(path: Path, sheet: str | None = None, json_key: str | None = None) -> dict[str, object]`, and `inspect` CLI JSON.

- [ ] **Step 1: Write failing loader and inspection tests**

Create tests that build CSV/JSON/XLSX equivalents under `tmp_path` and assert:

```python
def test_loaders_return_equivalent_rows(csv_source, json_source, xlsx_source):
    csv_rows, _ = load_source(csv_source, None)
    json_rows, _ = load_source(json_source, None)
    xlsx_rows, meta = load_source(xlsx_source, "Pipeline")
    assert csv_rows == json_rows == xlsx_rows
    assert meta["sheet"] == "Pipeline"


def test_inspect_lists_sheets_headers_and_month_candidates(xlsx_source):
    report = inspect_source(xlsx_source, "Pipeline")
    assert report["format"] == "xlsx"
    assert report["headers"][:5] == [
        "Area", "Sub-area", "Opportunity Name", "TCV", "Probability"
    ]
    assert [m["label"] for m in report["month_candidates"]] == [
        "Mar '26", "Apr '26", "May '26"
    ]


def test_parse_month_header_handles_loop24_labels():
    assert parse_month_header("March’26") == ("2026-03", "stage")
    assert parse_month_header("Apr '26 Probability") == ("2026-04", "probability")
    assert parse_month_header("2026-05 Status") == ("2026-05", "stage")
    assert parse_month_header("Opportunity Name") is None


def test_ambiguous_alias_requires_explicit_mapping():
    with pytest.raises(DataContractError, match="ambiguous field area"):
        resolve_mapping(["Area", "Sales Area", "Name", "TCV", "Probability"], None)


def test_json_with_multiple_arrays_requires_key(tmp_path):
    source = tmp_path / "pipeline.json"
    source.write_text(json.dumps({"current": [{"Area": "A"}], "archive": [{"Area": "B"}]}))
    with pytest.raises(DataContractError, match="JSON array key is required"):
        load_source(source, None, None)
    rows, meta = load_source(source, None, "current")
    assert rows == [{"Area": "A"}]
    assert meta["json_key"] == "current"


def test_xlsx_formula_without_cached_value_is_reported(xlsx_with_formula):
    _, meta = load_source(xlsx_with_formula, "Pipeline", None)
    assert meta["uncached_formulas"] == [{"row": 2, "header": "TCV"}]
```

Add a subprocess test for `inspect` that expects exit `0`, one JSON object on stdout, and no files written.

- [ ] **Step 2: Run the tests and verify import failure**

Run:

```bash
.venv/bin/pytest tests/test_opportunity_visuals_prepare.py -q
```

Expected: collection fails because `opportunity_data.py` and `prepare_opportunities.py` do not exist.

- [ ] **Step 3: Implement source loaders and errors**

Create these public definitions in `opportunity_data.py`:

```python
class DataContractError(ValueError):
    def __init__(self, code: str, message: str, details: dict[str, object] | None = None):
        super().__init__(message)
        self.code = code
        self.details = details or {}


def load_source(
    path: Path,
    sheet: str | None = None,
    json_key: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
        return rows, {"format": "csv", "sheet": None}
    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            arrays = [(key, value) for key, value in payload.items() if isinstance(value, list)]
            if not arrays:
                raise DataContractError("invalid_json_shape", "JSON object contains no row array")
            if json_key is None and len(arrays) != 1:
                raise DataContractError(
                    "json_key_required", "JSON array key is required",
                    {"array_keys": [key for key, _ in arrays]},
                )
            selected_key = json_key or arrays[0][0]
            if selected_key not in payload or not isinstance(payload[selected_key], list):
                raise DataContractError("json_key_not_found", f"JSON row array not found: {selected_key}")
            rows = payload[selected_key]
        else:
            raise DataContractError("invalid_json_shape", "JSON must be a row array or contain one row array")
        if not all(isinstance(row, dict) for row in rows):
            raise DataContractError("invalid_json_row", "Every JSON row must be an object")
        return rows, {"format": "json", "sheet": None, "json_key": selected_key if isinstance(payload, dict) else None}
    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        formulas = load_workbook(path, read_only=True, data_only=False)
        if sheet is None:
            if len(workbook.sheetnames) != 1:
                raise DataContractError(
                    "sheet_required", "XLSX contains multiple worksheets",
                    {"sheets": workbook.sheetnames},
                )
            sheet = workbook.sheetnames[0]
        if sheet not in workbook.sheetnames:
            raise DataContractError("sheet_not_found", f"Worksheet not found: {sheet}")
        values = workbook[sheet].iter_rows(values_only=True)
        formula_values = formulas[sheet].iter_rows(values_only=True)
        headers = [str(value).strip() if value is not None else "" for value in next(values)]
        next(formula_values)
        rows = []
        uncached_formulas = []
        for row_number, (row, formula_row) in enumerate(zip(values, formula_values, strict=True), start=2):
            for index, formula in enumerate(formula_row):
                if isinstance(formula, str) and formula.startswith("=") and row[index] is None:
                    uncached_formulas.append({"row": row_number, "header": headers[index]})
            rows.append(dict(zip(headers, row, strict=True)))
        return rows, {
            "format": "xlsx",
            "sheet": sheet,
            "sheets": workbook.sheetnames,
            "uncached_formulas": uncached_formulas,
        }
    raise DataContractError("unsupported_format", f"Unsupported source format: {suffix}")
```

Before returning, all loaders must reject empty input, blank/duplicate headers, and rows that are not header-shaped. Metadata may contain only format, selected sheet, selected JSON key, available sheets/array keys, row count, source basename, SHA-256, and uncached-formula row/header locations; never print raw rows.

- [ ] **Step 4: Implement deterministic month and field resolution**

Use canonical aliases:

```python
FIELD_ALIASES = {
    "area": {"area", "sales area"},
    "sub_area": {"sub area", "sub-area", "subarea"},
    "opportunity_name": {"opportunity name", "opportunity", "deal name"},
    "tcv": {"tcv", "total contract value"},
    "probability": {"probability", "current probability"},
}
MONTHS = {name.lower(): index for index, names in enumerate((
    ("jan", "january"), ("feb", "february"), ("mar", "march"),
    ("apr", "april"), ("may",), ("jun", "june"),
    ("jul", "july"), ("aug", "august"), ("sep", "sept", "september"),
    ("oct", "october"), ("nov", "november"), ("dec", "december"),
), start=1) for name in names}
```

Normalize headers by replacing curly apostrophes, underscores, and repeated whitespace. `parse_month_header()` must remove `stage`, `status`, and `probability` tokens, recognize `YYYY-MM`, `Mon YY`, `Month 'YY`, and four-digit years, then return `(YYYY-MM, kind)`. Two-digit years map to 2000–2099. `resolve_mapping()` must accept the explicit mapping shape from `data-contract.md`, require one match for every fixed field, pair optional monthly probability headers by chronological key, reject duplicate stage months, and return months sorted by key while preserving display labels.

- [ ] **Step 5: Implement the inspection CLI**

Create `prepare_opportunities.py` with import-safe `main(argv: list[str] | None = None) -> int`. The `inspect` subcommand passes optional `--sheet` and `--json-key` to `inspect_source()`, prints exactly one JSON object with `ok: true`, and returns `0`. Inspection of multi-array JSON reports candidate array keys so the coworker can ask which one to use. Catch `DataContractError`, print a structured error object containing code, message, and details, and return `2`. Do not write during inspection.

- [ ] **Step 6: Run focused and full tests**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_prepare.py -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit the inspection slice**

```bash
git add skills/ericsson/opportunity-visuals/scripts tests/test_opportunity_visuals_prepare.py
git commit -m "feat: inspect opportunity data sources"
```

### Task 3: Normalization, stage semantics, view selection, and preparation outputs

**Files:**
- Modify: `skills/ericsson/opportunity-visuals/scripts/opportunity_data.py`
- Modify: `skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py`
- Modify: `tests/test_opportunity_visuals_prepare.py`

**Interfaces:**
- Consumes: `load_source`, `resolve_mapping`, and inspection error shape from Task 2.
- Produces: `normalize_rows(rows, mapping, semantics) -> tuple[list[dict[str, object]], list[dict[str, object]]]`, `classify_transition(previous, current, semantics) -> str`, `apply_filters(records, filters) -> tuple[list[dict[str, object]], list[dict[str, object]]]`, `select_records(records, view) -> tuple[list[dict[str, object]], list[dict[str, object]]]`, `prepare(source: Path, view: str, semantics_path: Path, output_dir: Path, mapping_path: Path | None = None, sheet: str | None = None, json_key: str | None = None, months: list[str] | None = None, filters_path: Path | None = None) -> dict[str, object]`, and the three preparation JSON artifacts.

- [ ] **Step 1: Write failing normalization and classification tests**

Add table-driven tests for all transition values and the source ambiguities:

```python
@pytest.mark.parametrize(
    ("previous", "current", "expected"),
    [
        ({"stage": "Ideation"}, {"stage": "Proposal"}, "positive"),
        ({"stage": "Proposal"}, {"stage": "Workshop"}, "positive"),
        ({"stage": "Solution"}, {"stage": "Ideation"}, "negative"),
        ({"stage": "Solution"}, {"stage": "Solution"}, "neutral"),
        ({"stage": "Proposal"}, {"stage": "Won"}, "won"),
        ({"stage": "Proposal"}, {"stage": "Lost"}, "lost"),
        (
            {"stage": "Solution", "probability_sort": 3},
            {"stage": "Proposal", "probability_sort": 2},
            "mixed",
        ),
        ({"stage": "Discovery"}, {"stage": "Deferred"}, "unknown"),
    ],
)
def test_classify_transition(previous, current, expected, semantics):
    assert classify_transition(previous, current, semantics) == expected
```

Add normalization assertions for preserving markup-like/formula-like strings, blank April, skipped-month metadata, categorical ranks, and `insufficient_stages`. Add view tests asserting exact IDs:

```python
assert [r["id"] for r in select_records(records, "wins")[0]] == ["OV-001", "OV-010"]
assert [r["id"] for r in select_records(records, "losses")[0]] == ["OV-003", "OV-009"]
assert "OV-004" in [r["id"] for r in select_records(records, "all-progression")[0]]
assert "OV-004" not in [r["id"] for r in select_records(records, "positive-progression")[0]]
assert "OV-005" not in [r["id"] for r in select_records(records, "all-progression")[0]]
```

Add a preparation CLI test that checks `source-summary.json`, `normalized-data.json`, and `exclusions.json`, stable JSON ordering, source basename/hash, and refusal to overwrite an existing non-empty output directory.

Add a filter test using this contract:

```python
filters = {
    "areas": ["Core Group"],
    "sub_areas": ["Automation"],
    "opportunity_contains": "automation",
    "tcv_min": 2,
    "tcv_max": 4,
    "probability_min": 1,
    "probability_max": 3,
}
included, excluded = apply_filters(records, filters)
assert all(record["area"] == "Core Group" for record in included)
assert all(item["code"] == "filter_not_matched" for item in excluded)
```

- [ ] **Step 2: Run the focused tests and verify missing interfaces**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_prepare.py -q
```

Expected: failures identifying the missing normalization, classification, selection, and preparation functions.

- [ ] **Step 3: Implement value normalization and semantics validation**

Validate semantics with required keys and defaults:

```python
DEFAULT_SEMANTICS = {
    "positive_terminals": ["Won"],
    "negative_terminals": ["Lost", "Cancelled"],
    "stage_paths": [],
    "positive_transitions": [["Proposal", "Workshop"]],
    "tcv_order": ["X-Small", "Small", "Medium", "Large", "X-Large"],
    "probability_order": ["Low", "Medium", "High", "Certain"],
}
```

Implement `normalize_rank(value, configured_order, field)` as follows: blank is an error; numeric values and numeric strings accept currency symbols, commas, `%`, and `K/M/B` suffixes; ratios from 0 through 1 become percentage ranks only for probability; configured categorical labels compare case-insensitively and return their zero-based rank while preserving the original display string; any other value raises `DataContractError(f"invalid_{field}", f"Invalid {field} value: {value!r}")`. Reject a dataset that mixes numeric and categorical values in one field unless semantics supplies an explicit order covering every display value.

Validate that each `stage_paths` entry is a non-empty list with no case-insensitive duplicate stage, terminal lists do not overlap case-insensitively, and transition pairs contain two strings. Build case-insensitive rank maps from every stage path and treat contradictory ranks as `DataContractError("conflicting_stage_order", "Stage paths assign contradictory ranks")`. Preserve the original stage spelling for display while using case-folded values for all semantic comparisons.

- [ ] **Step 4: Implement row normalization and transition classification**

For each source row, create this exact JSON-compatible shape:

```python
record = {
    "id": row_id,
    "source_row": source_index + 2,
    "area": str(row[mapping["area"]]),
    "sub_area": str(row[mapping["sub_area"]]),
    "opportunity_name": str(row[mapping["opportunity_name"]]),
    "tcv": {"display": tcv_display, "sort": tcv_rank, "kind": tcv_kind},
    "probability": {
        "display": probability_display,
        "sort": probability_rank,
        "kind": probability_kind,
    },
    "months": normalized_months,
    "terminal": terminal,
    "warnings": warnings,
}
```

Use an explicit source `ID`/`Id` column when present; otherwise generate `ROW-0002` from the source row. A normalized month contains `key`, `label`, `stage`, optional `probability_display`/`probability_sort`, `classification`, and `skipped_months`. The first populated stage is `initial` unless terminal; compare each later populated stage with the previous populated stage and list intervening blank labels in `skipped_months`.

Classification priority is exact: destination positive terminal → `won`; destination negative terminal → `lost`; derive stage and paired-month probability signals; opposing non-neutral signals → `mixed`; one direction plus neutral/absent → that direction; neither changed → `neutral`; unrecognized stage with no probability direction → `unknown`. Add warning codes `mixed_signals`, `unknown_transition`, and `skipped_blank_months` as applicable.

Truncate normalized months after the first terminal of either kind and record `{ "kind": "positive"|"negative", "month": key, "index": index }`; keep empty cells before that terminal.

- [ ] **Step 5: Implement deterministic selection and sorting**

`apply_filters()` runs before view selection. Empty/missing filter keys mean no restriction. Area/Sub-area lists compare case-insensitively; `opportunity_contains` is a case-insensitive substring; TCV/probability bounds compare normalized ranks inclusively. Reject unknown filter keys or a minimum greater than its maximum. Return non-matches with `filter_not_matched` without exposing full row contents in the exclusion message.

`select_records()` must reject unsupported views and apply:

```python
VIEW_PREDICATES = {
    "wins": lambda record: record["terminal"] and record["terminal"]["kind"] == "positive",
    "losses": lambda record: record["terminal"] and record["terminal"]["kind"] == "negative",
    "all-progression": lambda record: populated_stage_count(record) >= 2,
    "positive-progression": lambda record: any(
        month["classification"] in {"positive", "won"} for month in record["months"]
    ),
}
```

Sort included rows by case-folded Area, case-folded Sub-area, TCV descending, Probability descending, case-folded Opportunity Name, then source row. Return view exclusions using `view_not_matched`. Rows invalid before selection keep their original stable reason code.

- [ ] **Step 6: Implement preparation files and CLI**

`prepare()` must create a new output directory, load source rows, auto-detect mapping when `mapping_path` is absent, reject `formula_cache_missing` only when an uncached formula intersects a selected fixed/month field, normalize rows, apply filters, select the view, and atomically write UTF-8 JSON with `indent=2`, `sort_keys=True`, and a final newline:

- `source-summary.json`: source basename/SHA-256/format/sheet, mapping, semantics hash, selected months, view, filters, and counts.
- `normalized-data.json`: `schema_version: 1`, view, source basename/hash, mapping, semantics, selected months, filters, included records, the minimal exclusion list, warnings, and counts.
- `exclusions.json`: invalid and view-excluded rows containing ID/source row/code/message only.

The CLI must require `--semantics`, support optional `--mapping`, `--sheet`, `--json-key`, repeated `--months`, and `--filters` JSON. It returns `2` with structured JSON on data errors. Refuse a non-empty output directory with `output_exists`. Use a sibling temporary file plus `Path.replace()` for each JSON write.

- [ ] **Step 7: Run focused and full tests**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_prepare.py -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit the data preparation slice**

```bash
git add skills/ericsson/opportunity-visuals/scripts tests/test_opportunity_visuals_prepare.py
git commit -m "feat: normalize opportunity progression data"
```

### Task 4: Deterministic SVG layout and pagination

**Files:**
- Create: `skills/ericsson/opportunity-visuals/templates/opportunity-visual.svg`
- Create: `skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py`
- Create: `tests/test_opportunity_visuals_render.py`

**Interfaces:**
- Consumes: `normalized-data.json` schema from Task 3.
- Produces: `PagePlan`, `paginate(document, width, height) -> list[PagePlan]`, `render_svg_page(document, page, template_path) -> str`, `atomic_write_text(path: Path, text: str) -> None`, and numbered canonical SVG files.

- [ ] **Step 1: Write failing pagination, fidelity, and safety tests**

Cover these exact behaviors:

```python
def test_paginate_repeats_headers_and_never_drops_rows(normalized_document):
    pages = paginate(normalized_document, width=960, height=540)
    assert len(pages) > 1
    assert sorted({row_id for page in pages for row_id in page.row_ids}) == sorted(
        record["id"] for record in normalized_document["records"]
    )
    assert all(page.month_keys for page in pages)


def test_svg_is_deterministic_and_escapes_user_values(normalized_document, template_path):
    page = paginate(normalized_document, 1920, 1080)[0]
    first = render_svg_page(normalized_document, page, template_path)
    second = render_svg_page(normalized_document, page, template_path)
    assert first == second
    assert "Harbor Observability &lt;Pilot&gt;" in first
    assert "<script" not in first.lower()
    assert "https://" not in first
    assert first.count("http://") == 1
    assert 'xmlns="http://www.w3.org/2000/svg"' in first
    assert "href=\"http" not in first and "href=\"https" not in first


def test_terminal_and_blank_month_cells_render_exactly(normalized_document, template_path):
    pages = paginate(normalized_document, 1920, 1080)
    assert len(pages) == 1
    svg = render_svg_page(normalized_document, pages[0], template_path)
    assert svg.count(">Lost<") == 1
    assert "data-stage-after-terminal" not in svg
    assert 'data-opportunity-id="OV-006" data-month="2026-04" data-empty="true"' in svg
```

Also assert the approved colors, 16px minimum stage text, fixed column order, title by view, probability bullet, Area/Sub-area grouping, SVG dimensions, and unique page suffixes.

- [ ] **Step 2: Run the renderer tests and verify import failure**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_render.py -q
```

Expected: collection fails because the renderer and template do not exist.

- [ ] **Step 3: Create the safe static SVG template**

Create a valid XML template with no user-data interpolation tokens:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="1920" height="1080"
     viewBox="0 0 1920 1080" role="img" aria-labelledby="title desc">
  <title id="title">Ericsson Opportunity Visual</title>
  <desc id="desc">Opportunity stage progression table</desc>
  <style>
    text { font-family: "Ericsson Hilda", "Inter", "Segoe UI", Arial, sans-serif; fill: #000000; }
    .title { font-size: 30px; font-weight: 600; }
    .header { font-size: 17px; font-weight: 600; }
    .body { font-size: 16px; }
    .stage { font-size: 16px; font-weight: 600; fill: #FFFFFF; }
    .grid { stroke: #D8D8D8; stroke-width: 1; }
  </style>
  <rect width="1920" height="1080" fill="#FFFFFF"/>
  <g id="content"/>
</svg>
```

The renderer must parse this with `xml.etree.ElementTree`, set dimensions/viewBox/title/description, and append nodes through `ElementTree.SubElement`; never concatenate user values into XML markup.

Use one atomic text writer for SVG, HTML, and manifests:

```python
def atomic_write_text(path: Path, text: str) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    temporary.write_text(text, encoding="utf-8")
    temporary.replace(path)
```

- [ ] **Step 4: Implement deterministic page planning**

Use exact layout constants at scale 1.0:

```python
MARGIN = 48
TITLE_HEIGHT = 70
HEADER_HEIGHT = 50
AREA_HEIGHT = 30
ROW_HEIGHT = 46
FOOTER_HEIGHT = 26
FIXED_COLUMNS = (
    ("area", 120),
    ("sub_area", 150),
    ("opportunity_name", 300),
    ("tcv", 110),
    ("probability", 150),
)
MIN_MONTH_WIDTH = 116
```

Scale all constants by `width / 1920`, but clamp body/stage font to at least 16px when width is 1920 or larger. Split months into the largest contiguous slices that keep month width at least `MIN_MONTH_WIDTH * scale`. Within each month slice, add rows in sorted order until the next Area header/row would exceed `height - MARGIN - FOOTER_HEIGHT`; start another vertical page and repeat applicable Area context. A `PagePlan` dataclass contains `number`, `month_keys`, `row_ids`, `continued_areas`, and `horizontal_index`.

- [ ] **Step 5: Implement SVG drawing helpers and per-view rendering**

Create helpers `add_rect`, `add_text`, `add_line`, `add_stage_pill`, and `ellipsize`. `add_text` assigns `.text = value`; `ellipsize` returns the original value when it fits and otherwise a deterministic Unicode-ellipsis string, while storing the full value in `data-full-value`.

Render title, page marker, fixed headers, selected month labels, Area bands, Sub-area labels, all fixed values, probability dot/label, empty-cell metadata, and stage pills. Fill mapping is exact:

```python
STAGE_COLORS = {
    "initial": "#A6A6A6",
    "positive": "#23969A",
    "negative": "#E65D6A",
    "neutral": "#A6A6A6",
    "mixed": "#A6A6A6",
    "unknown": "#A6A6A6",
    "won": "#23969A",
    "lost": "#E65D6A",
}
VIEW_TITLES = {
    "wins": "Ericsson Opportunity Wins — Stage Progression, TCV & Probability",
    "losses": "Ericsson Opportunity Losses — Stage Progression, TCV & Probability",
    "all-progression": "Ericsson Opportunity Stage Progression — Monthly History",
    "positive-progression": "Ericsson Opportunity Progression — Positive Movement",
}
PROBABILITY_COLORS = {
    "low": "#E65D6A",
    "medium": "#A6A6A6",
    "high": "#23969A",
    "certain": "#23969A",
}
```

For numeric percentages, use coral for values below 40, gray for 40 through 69.999, and teal for 70 through 100. Reject numeric probability outside 0 through 100 during normalization.

Use XML comments or sorted attributes only if they remain deterministic. Serialize with a fixed XML declaration and final newline. Never embed timestamps, absolute paths, random IDs, or artifact hashes into SVG.

- [ ] **Step 6: Add SVG CLI output and run tests**

The initial renderer CLI reads/validates schema version `1`, rejects an empty `records` list, creates numbered `opportunity-visual-pNN.svg` files, and prints one JSON result. Run:

```bash
.venv/bin/pytest tests/test_opportunity_visuals_render.py -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 7: Commit the canonical renderer slice**

```bash
git add skills/ericsson/opportunity-visuals/templates skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py tests/test_opportunity_visuals_render.py
git commit -m "feat: render opportunity progression svg"
```

### Task 5: Self-contained HTML, optional PNG, and render manifest

**Files:**
- Modify: `skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py`
- Modify: `tests/test_opportunity_visuals_render.py`

**Interfaces:**
- Consumes: numbered SVG pages from Task 4.
- Produces: `write_html(svg_text: str, output_path: Path) -> None`, `rasterize_html(html_path: Path, png_path: Path, width: int, height: int, playwright_factory=None) -> None`, `preflight(output_dir: Path) -> dict[str, object]`, `write_render_manifest(document: dict[str, object], pages: list[PagePlan], artifacts: list[dict[str, object]], output_dir: Path, width: int, height: int, png_status: dict[str, str]) -> Path`, `render_document(normalized_path: Path, output_dir: Path, width: int = 1920, height: int = 1080, png_mode: str = "auto") -> dict[str, object]`, `--png auto|never|required`, HTML/PNG pages, and `render-manifest.json`.

- [ ] **Step 1: Write failing HTML, raster fallback, and manifest tests**

Add tests that assert:

```python
def test_html_is_self_contained(tmp_path, svg_text):
    output = tmp_path / "page.html"
    write_html(svg_text, output)
    html = output.read_text()
    assert svg_text.strip() in html
    assert "<script" not in html.lower()
    assert "https://" not in html
    assert html.count("http://") == 1
    assert 'xmlns="http://www.w3.org/2000/svg"' in html
    assert "href=\"http" not in html and "href=\"https" not in html
    assert "iframe" not in html.lower()


def test_png_auto_falls_back_without_failing_svg_html(tmp_path, normalized_path, monkeypatch):
    def unavailable(*args, **kwargs):
        raise RasterUnavailable("Playwright or Chromium is unavailable")

    monkeypatch.setattr(renderer, "rasterize_html", unavailable)
    result = renderer.render_document(normalized_path, tmp_path, png_mode="auto")
    assert result["ok"] is True
    assert result["png"]["status"] == "unavailable"
    assert list(tmp_path.glob("*.svg"))
    assert list(tmp_path.glob("*.html"))
    assert not list(tmp_path.glob("*.png"))


def test_png_required_returns_error_on_missing_renderer(tmp_path, normalized_path, monkeypatch):
    monkeypatch.setattr(renderer, "rasterize_html", Mock(side_effect=RasterUnavailable("missing")))
    with pytest.raises(RenderError, match="missing"):
        renderer.render_document(normalized_path, tmp_path, png_mode="required")
```

Add a fake Playwright object test proving `page.route("**/*", handler)` aborts an HTTPS request, allows a `file:` request, sets the exact viewport, navigates only to the local HTML URI, and screenshots the body to the requested PNG.

Add preflight tests proving the result has independent `csv_json`, `xlsx`, `svg_html`, `png_package`, `chromium`, and `output_directory` statuses. Monkeypatch import detection/browser launch/output permission checks so every state is testable without installing or launching a real browser.

Add manifest assertions for view/range/filters/dimensions/semantics hash, included IDs/source rows, excluded IDs/reasons, transition warnings, page-to-row mapping, artifact SHA-256, renderer version, and PNG status. Assert the manifest does not hash itself and does not contain an absolute source path.

- [ ] **Step 2: Run focused tests and verify failures**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_render.py -q
```

Expected: failures for missing HTML, raster, fallback, and manifest interfaces.

- [ ] **Step 3: Implement safe HTML writing**

Use this fixed wrapper and insert only already-generated SVG:

```python
def write_html(svg_text: str, output_path: Path) -> None:
    html = (
        "<!doctype html>\n<html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<meta name=\"viewport\" content=\"width=device-width,initial-scale=1\">"
        "<title>Ericsson Opportunity Visual</title>"
        "<style>html,body{margin:0;background:#fff}svg{display:block;width:100%;height:auto}</style>"
        "</head><body>" + svg_text.strip() + "</body></html>\n"
    )
    atomic_write_text(output_path, html)
```

Before writing, parse `svg_text` with `ElementTree.fromstring()` and reject any element named `script`, `iframe`, `image`, `foreignObject`, `use`, or `a`, any attribute beginning with `on`, and any attribute value containing a non-fragment URL.

- [ ] **Step 4: Implement optional local Playwright capture**

Implement lazy import and network denial:

```python
class RasterUnavailable(RuntimeError):
    pass


class RenderError(ValueError):
    pass


def rasterize_html(
    html_path: Path,
    png_path: Path,
    width: int,
    height: int,
    playwright_factory=None,
) -> None:
    if playwright_factory is None:
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise RasterUnavailable("Install playwright>=1.52 and Chromium for PNG output") from exc
        playwright_factory = sync_playwright
    try:
        with playwright_factory() as runtime:
            browser = runtime.chromium.launch(headless=True)
            page = browser.new_page(viewport={"width": width, "height": height})

            def local_only(route):
                if route.request.url.startswith("file:"):
                    route.continue_()
                else:
                    route.abort()

            page.route("**/*", local_only)
            page.goto(html_path.resolve().as_uri(), wait_until="load")
            page.locator("body").screenshot(path=str(png_path))
            browser.close()
    except RasterUnavailable:
        raise
    except Exception as exc:
        raise RasterUnavailable(f"Playwright/Chromium capture failed: {exc}") from exc
```

Do not install dependencies from the renderer. Configuration remains an explicit coworker-guided action.

`preflight()` must report CSV/JSON and SVG/HTML available when Python can run, `xlsx` from `importlib.util.find_spec("openpyxl")`, the Playwright package separately from a successful minimal Chromium launch, and output-directory writability using a temporary probe file that is always removed. The `--preflight` CLI prints one JSON object and writes no artifacts other than that removed probe.

- [ ] **Step 5: Implement manifest and CLI result behavior**

`render_document()` must refuse to overwrite any target SVG/HTML/PNG/manifest path. Hash SVG/HTML/available PNG files after all page writes. Write `render-manifest.json` atomically with sorted keys and no timestamp so deterministic runs compare cleanly. Include `renderer_version: 1`, `png: {status, reason}`, and `pages` entries with page number, month keys, row IDs, files, dimensions, and hashes. Return the exact top-level shape `{"ok": True, "manifest": str(manifest_path), "pages": page_results, "png": png_status}` where each `page_results` entry has `svg`, `html`, and nullable `png` path strings. The command returns `0` for `auto` fallback, `2` for required PNG failure or invalid input, and prints that one JSON object.

- [ ] **Step 6: Run focused and full tests**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_render.py -q
.venv/bin/pytest -q
```

Expected: all tests pass without requiring a real browser; real-browser coverage remains an explicitly marked showcase verification.

- [ ] **Step 7: Commit the output slice**

```bash
git add skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py tests/test_opportunity_visuals_render.py
git commit -m "feat: add safe html and png visual outputs"
```

### Task 6: Synthetic fixture pack, expected selections, golden SVG, and end-to-end showcase tests

**Files:**
- Create: `tests/fixtures/opportunity_visuals/build_showcase_fixtures.py`
- Create: `tests/fixtures/opportunity_visuals/showcase-opportunities.csv`
- Create: `tests/fixtures/opportunity_visuals/showcase-opportunities.json`
- Create: `tests/fixtures/opportunity_visuals/showcase-opportunities.xlsx`
- Create: `tests/fixtures/opportunity_visuals/stage-semantics.json`
- Create: `tests/fixtures/opportunity_visuals/expected-normalized.json`
- Create: `tests/fixtures/opportunity_visuals/expected-wins.json`
- Create: `tests/fixtures/opportunity_visuals/expected-losses.json`
- Create: `tests/fixtures/opportunity_visuals/expected-all-progression.json`
- Create: `tests/fixtures/opportunity_visuals/expected-positive-progression.json`
- Create: `tests/golden/opportunity_visuals/wins-p01.svg`
- Create: `tests/golden/opportunity_visuals/losses-p01.svg`
- Create: `tests/golden/opportunity_visuals/all-progression-p01.svg`
- Create: `tests/golden/opportunity_visuals/positive-progression-p01.svg`
- Create: `tests/test_opportunity_visuals_showcase.py`

**Interfaces:**
- Consumes: preparation and rendering CLIs from Tasks 3–5.
- Produces: privacy-safe test/showcase artifacts and an end-to-end regression contract for all four views.

- [ ] **Step 1: Write the failing showcase test against required artifact paths**

The test must load every committed artifact, compare CSV/JSON/XLSX normalization after removing source-format metadata, compare exact expected IDs/order/cutoffs/transitions, run all four views with `--png never`, canonicalize SVG XML, and compare it to the golden file. Define these helpers in the test file:

```python
def load_json(path: Path) -> dict[str, object]:
    return json.loads(path.read_text(encoding="utf-8"))


def project_view(output_dir: Path) -> dict[str, object]:
    document = load_json(output_dir / "normalized-data.json")
    exclusions = load_json(output_dir / "exclusions.json")["exclusions"]
    return {
        "included_ids": [record["id"] for record in document["records"]],
        "excluded": [{"id": item["id"], "code": item["code"]} for item in exclusions],
        "transitions": {
            record["id"]: [month["classification"] if month["stage"] else "empty" for month in record["months"]]
            for record in document["records"]
        },
        "terminals": {record["id"]: record["terminal"] for record in document["records"]},
    }


def canonical_svg(path: Path) -> str:
    root = ElementTree.parse(path).getroot()
    return ElementTree.tostring(root, encoding="unicode")
```

```python
@pytest.mark.parametrize(
    ("view", "expected_name", "golden_name"),
    [
        ("wins", "expected-wins.json", "wins-p01.svg"),
        ("losses", "expected-losses.json", "losses-p01.svg"),
        ("all-progression", "expected-all-progression.json", "all-progression-p01.svg"),
        ("positive-progression", "expected-positive-progression.json", "positive-progression-p01.svg"),
    ],
)
def test_showcase_view_end_to_end(tmp_path, view, expected_name, golden_name):
    prepared = tmp_path / view
    prepare(
        SHOWCASE_CSV,
        view,
        FIXTURES / "stage-semantics.json",
        prepared,
    )
    expected = load_json(FIXTURES / expected_name)
    assert project_view(prepared) == expected
    rendered = render_document(
        prepared / "normalized-data.json",
        prepared,
        png_mode="never",
    )
    assert canonical_svg(Path(rendered["pages"][0]["svg"])) == canonical_svg(GOLDEN / golden_name)
    assert rendered["png"]["status"] == "disabled"
```

Add tests that assert all names are invented, no forbidden real/customer tokens occur, XLSX contains one visible sheet/no formulas/no external links/no macros, output HTML has no network URLs, and every expected exclusion/warning appears.

- [ ] **Step 2: Run the showcase test and verify missing artifacts**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_showcase.py -q
```

Expected: collection or test failure listing the absent fixture and golden paths.

- [ ] **Step 3: Create the independent synthetic fixture builder**

Define headers:

```python
HEADERS = [
    "ID", "Area", "Sub-area", "Opportunity Name", "TCV", "Probability",
    "Mar '26", "Mar '26 Probability",
    "Apr '26", "Apr '26 Probability",
    "May '26", "May '26 Probability",
    "Jun '26", "Jun '26 Probability",
]
```

Create exactly twelve rows using the design IDs/names and these required histories:

```python
HISTORIES = {
    "OV-001": [("Ideation", "Low"), ("Proposal", "Medium"), ("Won", "Certain"), ("In Delivery", "Certain")],
    "OV-002": [("Proposal", "Medium"), ("Workshop", "High"), ("Commercials", "High"), ("Commercials", "High")],
    "OV-003": [("Solution", "High"), ("Ideation", "Medium"), ("Lost", "Low"), ("", "")],
    "OV-004": [("Solution", "Medium"), ("Solution", "Medium"), ("Solution", "Medium"), ("Solution", "Medium")],
    "OV-005": [("", ""), ("", ""), ("Discovery", "Low"), ("", "")],
    "OV-006": [("Ideation", "Low"), ("", ""), ("Proposal", "High"), ("Proposal", "High")],
    "OV-007": [("Solution", "High"), ("Proposal", "Medium"), ("Proposal", "Medium"), ("Proposal", "Medium")],
    "OV-008": [("Ideation", "Low"), ("Solution", "Medium"), ("Solution", "Medium"), ("Solution", "Medium")],
    "OV-009": [("Proposal", "High"), ("Lost", "Low"), ("Restarted", "Medium"), ("Won", "Certain")],
    "OV-010": [("Proposal", "High"), ("Solution", "Medium"), ("Proposal", "High"), ("Won", "Certain")],
    "OV-011": [("Discovery", "Low"), ("Deferred", "Low"), ("Deferred", "Low"), ("Deferred", "Low")],
    "OV-012": [("Ideation", "Low"), ("Solution", "Medium"), ("Proposal", "High"), ("Proposal", "High")],
}
```

Use these exact fixed fields so row ordering is independently predictable:

```python
BASE_FIELDS = {
    "OV-001": ("Core Group", "Core", "Aurora Core Renewal", "X-Large", "Certain"),
    "OV-002": ("Core Group", "Automation", "Beacon Automation", "Large", "High"),
    "OV-003": ("Cloud Group", "Assurance", "Cedar Assurance", "X-Large", "Low"),
    "OV-004": ("Cloud Group", "Assurance", "Delta Capacity", "Medium", "Medium"),
    "OV-005": ("Edge Group", "Discovery", "Echo Modernization", "Small", "Low"),
    "OV-006": ("Core Group", "Automation", "Fjord Analytics", "Medium", "High"),
    "OV-007": ("OSS Group", "Orchestration", "Grove Orchestration", "Large", "Medium"),
    "OV-008": ("OSS Group", "Observability", "Harbor Observability <Pilot> =1+1", "Small", "Medium"),
    "OV-009": ("Edge Group", "Delivery", "Ion Edge Program", "X-Large", "Low"),
    "OV-010": ("Core Group", "Core", "Juniper Expansion", "Large", "Certain"),
    "OV-011": ("Edge Group", "Discovery", "Kite Discovery", "X-Small", "Low"),
    "OV-012": ("OSS Group", "Platform", "Lumen Platform", "Medium", "High"),
}
```

The builder writes UTF-8 CSV, equivalent JSON, and one-sheet XLSX named `Pipeline` with plain values only. It also writes deterministic `stage-semantics.json` with paths `Ideation → Solution → Proposal → SDP2 → Won` and `POC → Workshop → Commercials → Won`, positive edge `Proposal → Workshop`, terminals, and categorical scales.

- [ ] **Step 4: Hand-author expected normalization and view projections**

Do not derive expected selection JSON by calling production functions. Encode the intended oracle directly in the builder as literals and verify it against the design table. `expected-wins.json`, `expected-losses.json`, `expected-all-progression.json`, and `expected-positive-progression.json` each have exactly the keys `included_ids`, `excluded`, `transitions`, and `terminals`, matching `project_view()`. The expected files must assert:

```python
EXPECTED_VIEW_IDS = {
    "wins": ["OV-001", "OV-010"],
    "losses": ["OV-003", "OV-009"],
    "all-progression": [
        "OV-003", "OV-004", "OV-002", "OV-006", "OV-001", "OV-010",
        "OV-009", "OV-011", "OV-008", "OV-007", "OV-012",
    ],
    "positive-progression": ["OV-002", "OV-006", "OV-001", "OV-010", "OV-008", "OV-012"],
}
```

The lists above are the exact expected sorted order. Encode these exact classification sequences in `expected-normalized.json`: OV-001 `initial,positive,won`; OV-002 `initial,positive,positive,neutral`; OV-003 `initial,negative,lost`; OV-004 `initial,neutral,neutral,neutral`; OV-005 `initial`; OV-006 `initial,empty,positive,neutral`; OV-007 `initial,mixed,neutral,neutral`; OV-008 `initial,positive,neutral,neutral`; OV-009 `initial,lost`; OV-010 `initial,negative,positive,won`; OV-011 `initial,unknown,neutral,neutral`; OV-012 `initial,positive,positive,neutral`. Record OV-005 as `insufficient_stages`, OV-006 as skipping April, and OV-001/OV-009 as terminal-truncated before later source values.

- [ ] **Step 5: Generate and inspect fixture files**

Run:

```bash
.venv/bin/python tests/fixtures/opportunity_visuals/build_showcase_fixtures.py
.venv/bin/pytest tests/test_opportunity_visuals_showcase.py -q
```

Expected: view assertions pass until golden SVG comparisons report missing files. Inspect `git diff --numstat`; the XLSX is the only binary artifact.

- [ ] **Step 6: Generate, canonicalize, and manually review golden SVG files**

Run preparation/rendering for all four views with the fixed fixture, semantics, mapping, 1920×1080, and `--png never`. Copy only the first canonical SVG page for each view into `tests/golden/opportunity_visuals/`. Before accepting, review labels, empty cells, group boundaries, colors, terminal cutoffs, and absence of remote URLs against `visual-rules.md`. Do not update a golden file to silence a functional mismatch; fix production code or the independent expected oracle first.

- [ ] **Step 7: Run showcase and full suites**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_showcase.py -q
.venv/bin/pytest tests/test_opportunity_visuals_prepare.py tests/test_opportunity_visuals_render.py tests/test_opportunity_visuals_skill.py -q
.venv/bin/pytest -q
```

Expected: all tests pass.

- [ ] **Step 8: Commit the showcase pack**

```bash
git add tests/fixtures/opportunity_visuals tests/golden/opportunity_visuals tests/test_opportunity_visuals_showcase.py
git commit -m "test: add opportunity visuals showcase pack"
```

### Task 7: User-facing showcase and port/configuration documentation

**Files:**
- Create: `docs/showcases/opportunity-visuals.md`
- Modify: `docs/configuration.md`
- Modify: `docs/flows/image-generation.md`
- Modify: `docs/README.md`
- Modify: `README.md`
- Modify: `tests/test_opportunity_visuals_skill.py`

**Interfaces:**
- Consumes: Working skill, fixture paths, and CLI behavior from Tasks 1–6.
- Produces: Reproducible showcase instructions, accurate configuration help, and `intent-ported` flow status.

- [ ] **Step 1: Write failing documentation assertions**

Extend `tests/test_opportunity_visuals_skill.py`:

```python
def test_opportunity_visuals_docs_match_the_live_port():
    showcase = (REPO / "docs/showcases/opportunity-visuals.md").read_text()
    config = (REPO / "docs/configuration.md").read_text()
    flow = (REPO / "docs/flows/image-generation.md").read_text()
    for phrase in (
        "showcase-opportunities.csv",
        "wins",
        "losses",
        "all-progression",
        "positive-progression",
        "one question at a time",
        "render-manifest.json",
        "visual verification",
    ):
        assert phrase in showcase
    assert "No API key is required" in config
    assert "openpyxl>=3.1.5" in config
    assert "playwright>=1.52" in config
    assert "status: intent-ported" in flow
    assert "opportunity-visuals" in flow
```

- [ ] **Step 2: Run the doc test and verify expected failures**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_skill.py -q
```

Expected: failure because the showcase page is absent and the flow remains `not-ported`.

- [ ] **Step 3: Write the reproducible showcase guide**

The guide must include:

- What the skill does and why it does not use generative image models.
- The exact synthetic fixture paths and a data-story table for OV-001 through OV-012.
- Positive and negative natural-language trigger examples.
- Six transcript scenarios: fully specified, ambiguous worksheet, unknown stage, confidential destination, PNG fallback, and generic-image non-trigger.
- Exact preparation and rendering commands for all four views.
- Expected included/excluded/warning counts read from the expected JSON.
- An output-tree example and explanation of all four JSON manifests/artifacts.
- Visual verification checklist and a real-Playwright PNG demonstration command.
- A privacy statement forbidding real sales/customer data in screenshots committed to the repository.

- [ ] **Step 4: Update configuration and flow inventory**

Replace the generic branded-rendering design language in `docs/configuration.md` with the live split:

```markdown
No API key is required for Opportunity Visuals. Python and local file access
provide CSV/JSON plus SVG/HTML. XLSX requires `openpyxl>=3.1.5`. PNG requires
`playwright>=1.52` and a locally installed Chromium browser; when unavailable,
the skill succeeds with SVG/HTML and reports PNG as unavailable.
```

Document preflight and user-approved install commands, output-directory permissions, local-only rendering, and separate failure messages for missing openpyxl, missing Playwright, missing Chromium, and unwritable output.

In `docs/flows/image-generation.md`, set `status: intent-ported`, change target artifacts to `[opportunity-visuals-skill]`, describe deterministic SVG/HTML plus optional PNG, and link the live skill/showcase. In `docs/README.md`, change the Image Generation inventory row to Intent ported and add the showcase link. In root `README.md`, add the skill to the shipped capability inventory without implying an API key.

- [ ] **Step 5: Verify docs, links, memory synchronization, and tests**

```bash
.venv/bin/pytest tests/test_opportunity_visuals_skill.py -q
.venv/bin/pytest -q
git diff --check
cmp -s CLAUDE.md AGENTS.md
```

Expected: tests and checks exit `0`. Verify every new relative Markdown link resolves to an existing file.

- [ ] **Step 6: Commit the documentation slice**

```bash
git add docs/showcases/opportunity-visuals.md docs/configuration.md docs/flows/image-generation.md docs/README.md README.md tests/test_opportunity_visuals_skill.py
git commit -m "docs: publish opportunity visuals showcase"
```

### Task 8: Ericsson source-repository release gate

**Files:**
- Modify only if verification exposes a defect: files already owned by Tasks 1–7.

**Interfaces:**
- Consumes: Complete Ericsson source implementation and tests.
- Produces: A clean, source-of-truth commit series ready for vendoring.

- [ ] **Step 1: Run manifest lint and full repository tests from a clean process**

```bash
.venv/bin/python scripts/lint_manifest.py sets/ericsson.json
.venv/bin/pytest -q
```

Expected: lint prints `{"ok": true}` and pytest reports no failures.

- [ ] **Step 2: Run deterministic rebuild checks**

Rebuild the synthetic fixtures and all four golden SVGs into a temporary directory, not over committed files. Compare SHA-256 against the committed CSV/JSON/expected JSON/SVG artifacts. For XLSX, compare logical worksheet values and workbook safety properties rather than ZIP container bytes because XLSX metadata may vary.

Expected: all text/JSON/SVG hashes match and XLSX logical content matches.

- [ ] **Step 3: Exercise optional real PNG capture when Playwright is available**

Run the showcase `wins` view with `--png required`. If Playwright/Chromium is installed, assert exit `0`, 1920×1080 PNG, non-zero file size, no network requests, and manual visual checks. If unavailable, run `--png auto`, assert exit `0`, and verify `render-manifest.json` records the actionable fallback. Do not install software without user approval.

- [ ] **Step 4: Audit privacy and generated content**

Search the new skill, tests, and docs for secret-like assignments, internal hostnames, bearer tokens, real customer/account terms, absolute user paths, remote URLs inside SVG/HTML, and spreadsheet formulas. Expected: only documented package/project links if intentionally included; no secrets or real business data.

- [ ] **Step 5: Inspect repository state and record source commit**

```bash
git status --short --branch
git log --oneline -8
```

Expected: no uncommitted implementation files. Record the full source commit with `git rev-parse HEAD`; this is the commit the Hermes vendor manifest must stamp.

### Task 9: Vendor the approved capability into Hermes and verify delivery

**Files:**
- Create via vendor script: `../hermes-agent/skills/ericsson/opportunity-visuals/**`
- Modify via vendor script: `../hermes-agent/capabilities/ericsson.json`
- Modify only if the generic vendor contract needs regression coverage: `../hermes-agent/scripts/__tests__/vendor-ericsson.test.mjs`

**Interfaces:**
- Consumes: Clean Ericsson source commit from Task 8 and existing `hermes-agent/scripts/vendor-ericsson.mjs`.
- Produces: Vendored runtime skill and manifest stamped with the Ericsson source commit.

- [ ] **Step 1: Verify both repository states before vendoring**

From `hermes-agent/`, run:

```bash
git status --short --branch
node --test scripts/__tests__/vendor-ericsson.test.mjs
```

Expected: vendor test passes. Preserve unrelated user changes; stop and ask if the generated destination overlaps uncommitted edits.

- [ ] **Step 2: Run the manifest-driven vendor command**

```bash
node scripts/vendor-ericsson.mjs
```

Expected: output states `vendored ericsson-capabilities @ <source-short-sha>`, the complete skill directory appears under `skills/ericsson/opportunity-visuals/`, and `capabilities/ericsson.json` contains version `0.3.0`, the skill path once, and matching `vendoredFrom`.

- [ ] **Step 3: Verify copied runtime contents and excluded repository artifacts**

Assert the vendored skill contains `SKILL.md`, requirements, three references, three Python scripts, and the SVG template. Assert it does not contain `tests/`, fixture data, golden files, `.pytest_cache`, `.venv`, `__pycache__`, or real output artifacts.

Run:

```bash
node --test scripts/__tests__/vendor-ericsson.test.mjs
python3 -m py_compile skills/ericsson/opportunity-visuals/scripts/opportunity_data.py skills/ericsson/opportunity-visuals/scripts/prepare_opportunities.py skills/ericsson/opportunity-visuals/scripts/render_opportunity_visual.py
```

Expected: commands exit `0`.

- [ ] **Step 4: Run targeted Hermes skill/manifest tests**

Locate existing Hermes tests that validate vendored Ericsson manifests and skill discovery, then run those exact modules plus the vendor test. At minimum run:

```bash
python3 -m pytest tests/hermes_cli/test_baked_seed.py tests/hermes_cli/test_capability_staging.py tests/hermes_cli/test_capability_env_vars.py -q
node --test scripts/__tests__/vendor-ericsson.test.mjs
```

Expected: all selected tests pass. If the active Hermes environment lacks its declared test dependencies, use the repository's documented environment rather than installing into an unrelated interpreter.

- [ ] **Step 5: Smoke-test the vendored skill with synthetic data**

Point the vendored preparation and rendering scripts at the Ericsson repository's synthetic CSV and semantics file, writing to a temporary directory. Run `--png never`. Compare included IDs, manifest page count, and canonical SVG hash to the Ericsson expected/golden artifacts.

Expected: identical non-source-metadata results, proving the copied skill is executable rather than merely present.

- [ ] **Step 6: Commit only the generated Hermes delivery files**

```bash
git add skills/ericsson/opportunity-visuals capabilities/ericsson.json
git commit -m "chore: vendor opportunity visuals skill"
```

Do not commit Ericsson test fixtures into `hermes-agent`; they remain in the source repository's harness.

- [ ] **Step 7: Report release handoff without pushing or restamping automatically**

Report the Ericsson source commit, Hermes vendor commit, tests run/counts, PNG verification mode, and any optional dependency fallback. Pushing, restamping OTTO/LOOP24, or releasing remains a separate explicitly authorized action.

## Final acceptance checklist

- [ ] Natural-language positive and negative trigger boundaries are documented and tested.
- [ ] The interview skips known answers, asks one question at a time, and confirms before writes.
- [ ] CSV, JSON, and XLSX showcase sources normalize equivalently.
- [ ] All four views match independent expected inclusion, ordering, transition, and terminal contracts.
- [ ] SVG and HTML succeed without a key; PNG succeeds locally or records an actionable fallback.
- [ ] No stage/value is invented, renamed, carried forward, or rendered as executable markup.
- [ ] Exclusions, mixed/unknown transitions, page mappings, and artifact hashes are auditable.
- [ ] Synthetic fixtures, expected JSON, golden SVG, transcripts, and visual checks are committed.
- [ ] Ericsson manifest lint and full pytest suite pass.
- [ ] Vendored Hermes skill matches the recorded Ericsson source commit and targeted delivery tests pass.
- [ ] No push, restamp, or release occurs without separate user authorization.
