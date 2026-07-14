import json
import subprocess
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from pathlib import Path
from xml.etree import ElementTree

import pytest


REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skills/ericsson/opportunity-visuals"
SCRIPTS = SKILL_DIR / "scripts"
TEMPLATE = SKILL_DIR / "templates/opportunity-visual.svg"
sys.path.insert(0, str(SCRIPTS))

import render_opportunity_visual as renderer  # noqa: E402
from render_opportunity_visual import (  # noqa: E402
    RenderError,
    atomic_write_text,
    paginate,
    render_svg_page,
)


MONTHS = [
    {"key": "2026-03", "label": "Mar '26"},
    {"key": "2026-04", "label": "Apr '26"},
    {"key": "2026-05", "label": "May '26"},
    {"key": "2026-06", "label": "Jun '26"},
]


def month(key, label, stage, classification, skipped_months=None):
    return {
        "key": key,
        "label": label,
        "stage": stage,
        "classification": classification,
        "skipped_months": skipped_months or [],
    }


def record(
    row_id,
    source_row,
    area,
    sub_area,
    name,
    tcv,
    probability,
    months,
    *,
    probability_kind="categorical",
    probability_sort=2,
    terminal=None,
):
    return {
        "id": row_id,
        "source_row": source_row,
        "area": area,
        "sub_area": sub_area,
        "opportunity_name": name,
        "tcv": {"display": tcv, "sort": 3, "kind": "categorical"},
        "probability": {
            "display": probability,
            "sort": probability_sort,
            "kind": probability_kind,
        },
        "months": months,
        "terminal": terminal,
        "warnings": [],
    }


@pytest.fixture
def normalized_document():
    records = [
        record(
            "OV-001",
            2,
            "Core Group",
            "Core",
            "Aurora Core Renewal",
            "X-Large",
            "Certain",
            [
                month("2026-03", "Mar '26", "Ideation", "initial"),
                month("2026-04", "Apr '26", "Proposal", "positive"),
                month("2026-05", "May '26", "Won", "won"),
            ],
            terminal={"kind": "positive", "month": "2026-05", "index": 2},
        ),
        record(
            "OV-006",
            3,
            "Core Group",
            "Automation",
            "Fjord Analytics",
            "Medium",
            "High",
            [
                month("2026-03", "Mar '26", "Ideation", "initial"),
                month("2026-04", "Apr '26", "", "empty"),
                month(
                    "2026-05",
                    "May '26",
                    "Proposal",
                    "positive",
                    ["Apr '26"],
                ),
                month("2026-06", "Jun '26", "Proposal", "neutral"),
            ],
        ),
        record(
            "OV-008",
            4,
            "OSS Group",
            "Observability",
            "Harbor Observability <Pilot> =1+1",
            "Small",
            "Medium",
            [
                month("2026-03", "Mar '26", "Ideation", "initial"),
                month("2026-04", "Apr '26", "<script>bad & worse</script>", "positive"),
                month("2026-05", "May '26", "Solution & Review", "neutral"),
                month("2026-06", "Jun '26", "Solution", "neutral"),
            ],
        ),
        record(
            "OV-009",
            5,
            "Edge Group",
            "Delivery",
            "Ion Edge Program",
            "X-Large",
            "Low",
            [
                month("2026-03", "Mar '26", "Proposal", "initial"),
                month("2026-04", "Apr '26", "Lost", "lost"),
            ],
            terminal={"kind": "negative", "month": "2026-04", "index": 1},
        ),
    ]
    return {
        "schema_version": 1,
        "view": "all-progression",
        "source": {"basename": "showcase.json", "sha256": "not-rendered"},
        "mapping": {},
        "semantics": {},
        "selected_months": deepcopy(MONTHS),
        "filters": {},
        "records": records,
        "exclusions": [],
        "warnings": [],
        "counts": {"included_rows": len(records)},
    }


def expanded_document(document, *, record_count=20, month_count=10):
    expanded = deepcopy(document)
    expanded["selected_months"] = [
        {"key": f"2026-{number:02d}", "label": f"Month {number}"}
        for number in range(1, month_count + 1)
    ]
    records = []
    for index in range(record_count):
        item = deepcopy(document["records"][index % len(document["records"])])
        item["id"] = f"ROW-{index + 1:03d}"
        item["source_row"] = index + 2
        item["area"] = "Area A" if index < record_count // 2 else "Area B"
        item["sub_area"] = f"Sub-area {index % 3}"
        item["terminal"] = None
        item["months"] = [
            month(entry["key"], entry["label"], f"Stage {number}", "initial" if number == 1 else "neutral")
            for number, entry in enumerate(expanded["selected_months"], start=1)
        ]
        records.append(item)
    expanded["records"] = records
    expanded["counts"]["included_rows"] = len(records)
    return expanded


def test_template_is_static_safe_xml_without_interpolation_tokens():
    root = ElementTree.parse(TEMPLATE).getroot()
    text = TEMPLATE.read_text(encoding="utf-8")

    assert root.tag == "{http://www.w3.org/2000/svg}svg"
    assert "{{" not in text and "${" not in text
    assert "<script" not in text.lower()
    assert "https://" not in text
    assert text.count("http://") == 1
    assert "href=" not in text.lower()


def test_paginate_splits_months_contiguously_and_rows_vertically(normalized_document):
    document = expanded_document(normalized_document)
    pages = paginate(document, width=1920, height=360)

    by_horizontal = defaultdict(list)
    for page in pages:
        by_horizontal[page.horizontal_index].append(page)

    assert len(by_horizontal) == 2
    assert [key for index in sorted(by_horizontal) for key in by_horizontal[index][0].month_keys] == [
        entry["key"] for entry in document["selected_months"]
    ]
    expected_ids = [item["id"] for item in document["records"]]
    for horizontal_pages in by_horizontal.values():
        assert [row_id for page in horizontal_pages for row_id in page.row_ids] == expected_ids
    assert any(page.continued_areas for page in pages)
    assert [page.number for page in pages] == list(range(1, len(pages) + 1))
    assert all(page.month_keys and page.row_ids for page in pages)


def test_paginate_at_planned_half_scale_preserves_all_rows_per_month_slice(normalized_document):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    pages = paginate(document, width=960, height=540)

    assert len(pages) > 1
    assert Counter(key for page in pages for key in page.month_keys) == Counter(
        entry["key"] for entry in document["selected_months"]
    )
    assert set(row_id for page in pages for row_id in page.row_ids) == {
        record["id"] for record in document["records"]
    }


def test_svg_is_deterministic_and_escapes_user_values(normalized_document):
    page = paginate(normalized_document, 1920, 1080)[0]
    first = render_svg_page(normalized_document, page, TEMPLATE)
    second = render_svg_page(normalized_document, page, TEMPLATE)

    assert first == second
    assert "Harbor Observability &lt;Pilot&gt; =1+1" in first
    assert "&lt;script&gt;bad &amp; worse&lt;/script&gt;" in first
    assert "<script" not in first.lower()
    assert "https://" not in first
    assert first.count("http://") == 1
    assert 'xmlns="http://www.w3.org/2000/svg"' in first
    assert 'href="http' not in first and 'href="https' not in first
    assert first.startswith('<?xml version="1.0" encoding="UTF-8"?>\n')
    assert first.endswith("\n")
    ElementTree.fromstring(first)


def test_svg_has_exact_view_title_palette_layout_and_group_context(normalized_document):
    page = paginate(normalized_document, 1920, 1080)[0]
    svg = render_svg_page(normalized_document, page, TEMPLATE)

    assert "Ericsson Opportunity Stage Progression — Monthly History" in svg
    for color in ("#1174E6", "#23969A", "#E65D6A", "#A6A6A6", "#D8D8D8", "#F2F2F2", "#FFFFFF", "#000000"):
        assert color in svg
    assert '.stage { font-size: 16px;' in svg
    assert 'width="1920" height="1080" viewBox="0 0 1920 1080"' in svg
    header_positions = [svg.index(f">{label}<") for label in (
        "Area", "Sub-area", "Opportunity Name", "TCV", "Probability", "Mar '26"
    )]
    assert header_positions == sorted(header_positions)
    assert 'class="probability-bullet"' in svg
    assert 'data-area="Core Group"' in svg
    assert 'data-sub-area="Automation"' in svg
    assert "Area: Core Group" in svg


@pytest.mark.parametrize(
    ("view", "title"),
    [
        ("wins", "Ericsson Opportunity Wins — Stage Progression, TCV &amp; Probability"),
        ("losses", "Ericsson Opportunity Losses — Stage Progression, TCV &amp; Probability"),
        ("all-progression", "Ericsson Opportunity Stage Progression — Monthly History"),
        ("positive-progression", "Ericsson Opportunity Progression — Positive Movement"),
    ],
)
def test_each_view_uses_exact_title(normalized_document, view, title):
    normalized_document["view"] = view
    svg = render_svg_page(
        normalized_document,
        paginate(normalized_document, 1920, 1080)[0],
        TEMPLATE,
    )
    assert title in svg


def test_terminal_and_blank_month_cells_render_exactly(normalized_document):
    pages = paginate(normalized_document, 1920, 1080)
    assert len(pages) == 1
    svg = render_svg_page(normalized_document, pages[0], TEMPLATE)

    assert svg.count(">Lost<") == 1
    assert "data-stage-after-terminal" not in svg
    assert 'data-opportunity-id="OV-006" data-month="2026-04" data-empty="true"' in svg
    assert 'data-opportunity-id="OV-009" data-month="2026-05" data-empty="true"' not in svg


def test_probability_bullets_use_exact_categorical_and_numeric_thresholds(normalized_document):
    numeric = deepcopy(normalized_document)
    probabilities = [("39.9%", 39.9), ("40%", 40), ("70%", 70), ("100%", 100)]
    for item, (display, rank) in zip(numeric["records"], probabilities, strict=True):
        item["probability"] = {"display": display, "sort": rank, "kind": "numeric"}
    svg = render_svg_page(numeric, paginate(numeric, 1920, 1080)[0], TEMPLATE)

    assert svg.count('class="probability-bullet" fill="#E65D6A"') == 1
    assert svg.count('class="probability-bullet" fill="#A6A6A6"') == 1
    assert svg.count('class="probability-bullet" fill="#23969A"') == 2


def test_renderer_rejects_out_of_range_normalized_probability(normalized_document):
    normalized_document["records"][0]["probability"] = {
        "display": "101%",
        "sort": 101,
        "kind": "numeric",
    }
    page = paginate(normalized_document, 1920, 1080)[0]
    with pytest.raises(RenderError, match="between 0 and 100"):
        render_svg_page(normalized_document, page, TEMPLATE)


def test_body_and_stage_fonts_scale_above_canonical_size(normalized_document):
    page = paginate(normalized_document, 3840, 2160)[0]
    svg = render_svg_page(normalized_document, page, TEMPLATE)

    assert 'width="3840" height="2160" viewBox="0 0 3840 2160"' in svg
    assert 'style="font-size:32px"' in svg
    assert 'style="font-size:34px;fill:#FFFFFF"' in svg


def test_renderer_rejects_xml_control_characters_in_user_values(normalized_document):
    normalized_document["records"][0]["opportunity_name"] = "Unsafe\x01Label"
    page = paginate(normalized_document, 1920, 1080)[0]

    with pytest.raises(RenderError, match="valid XML text"):
        render_svg_page(normalized_document, page, TEMPLATE)


def test_ellipsized_values_retain_exact_full_value_metadata(normalized_document):
    full_value = "An exceptionally long opportunity label that cannot fit in its fixed column"
    normalized_document["records"][0]["opportunity_name"] = full_value
    svg = render_svg_page(
        normalized_document,
        paginate(normalized_document, 1920, 1080)[0],
        TEMPLATE,
    )

    assert "…" in svg
    assert f'data-full-value="{full_value}"' in svg


def test_atomic_write_text_uses_sibling_temporary_and_refuses_overwrite(tmp_path):
    output = tmp_path / "page.svg"
    atomic_write_text(output, "first\n")
    assert output.read_text(encoding="utf-8") == "first\n"
    assert not (tmp_path / ".page.svg.tmp").exists()

    with pytest.raises(RenderError, match="already exists"):
        atomic_write_text(output, "second\n")
    assert output.read_text(encoding="utf-8") == "first\n"


def test_cli_writes_unique_numbered_svg_files_and_one_json_result(
    tmp_path, normalized_document
):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_opportunity_visual.py"),
            str(normalized_path),
            "--output-dir",
            str(output_dir),
            "--width",
            "960",
            "--height",
            "540",
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload == {
        "ok": True,
        "pages": 2,
        "files": ["opportunity-visual-p01.svg", "opportunity-visual-p02.svg"],
    }
    assert sorted(path.name for path in output_dir.glob("*.svg")) == payload["files"]
    for path in output_dir.glob("*.svg"):
        ElementTree.parse(path)


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (lambda document: document.update(schema_version=2), "unsupported_schema"),
        (lambda document: document.update(records=[]), "empty_records"),
    ],
)
def test_cli_rejects_invalid_normalized_documents_with_safe_structured_error(
    tmp_path, normalized_document, mutate, code
):
    mutate(normalized_document)
    normalized_path = tmp_path / "confidential-normalized-data.json"
    normalized_path.write_text(json.dumps(normalized_document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_opportunity_visual.py"),
            str(normalized_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["error"]["code"] == code
    assert payload["error"]["details"] == {}
    assert str(normalized_path) not in result.stdout
    assert not output_dir.exists()


def test_cli_reports_malformed_record_without_traceback(tmp_path, normalized_document):
    del normalized_document["records"][0]["tcv"]
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(normalized_document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_opportunity_visual.py"),
            str(normalized_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    assert json.loads(result.stdout)["error"]["code"] == "invalid_record"
    assert not output_dir.exists()


def test_cli_refuses_overwrite_without_changing_existing_page(tmp_path, normalized_document):
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(normalized_document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    output_dir.mkdir()
    existing = output_dir / "opportunity-visual-p01.svg"
    existing.write_text("keep me", encoding="utf-8")

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_opportunity_visual.py"),
            str(normalized_path),
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert json.loads(result.stdout)["error"]["code"] == "output_exists"
    assert existing.read_text(encoding="utf-8") == "keep me"
    assert list(output_dir.iterdir()) == [existing]


def test_cli_rolls_back_all_pages_when_an_atomic_replace_fails(
    tmp_path, normalized_document, monkeypatch, capsys
):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    original_replace = Path.replace
    calls = 0

    def fail_second_replace(self, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sensitive /private/data")
        return original_replace(self, target)

    monkeypatch.setattr(Path, "replace", fail_second_replace)
    result = renderer.main(
        [str(normalized_path), "--output-dir", str(output_dir), "--width", "960", "--height", "540"]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    payload = json.loads(captured.out)
    assert payload == {
        "ok": False,
        "error": {
            "code": "output_unwritable",
            "message": "Unable to write SVG artifacts",
            "details": {},
        },
    }
    assert "/private/data" not in captured.out
    assert not output_dir.exists() or list(output_dir.iterdir()) == []
