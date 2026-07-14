import json
import subprocess
import sys
from pathlib import Path

import pytest
from openpyxl import Workbook


REPO = Path(__file__).resolve().parents[1]
SCRIPTS = REPO / "skills/ericsson/opportunity-visuals/scripts"
sys.path.insert(0, str(SCRIPTS))

from opportunity_data import (  # noqa: E402
    DataContractError,
    inspect_source,
    load_source,
    parse_month_header,
    resolve_mapping,
)


HEADERS = [
    "Area",
    "Sub-area",
    "Opportunity Name",
    "TCV",
    "Probability",
    "Mar '26",
    "Apr '26",
    "May '26",
]
ROW = ["North", "Cloud", "Project Cedar", "Large", "High", "Ideation", "Proposal", "Won"]


@pytest.fixture
def csv_source(tmp_path):
    source = tmp_path / "pipeline.csv"
    source.write_text(
        ",".join(HEADERS) + "\n" + ",".join(ROW) + "\n",
        encoding="utf-8",
    )
    return source


@pytest.fixture
def json_source(tmp_path):
    source = tmp_path / "pipeline.json"
    source.write_text(json.dumps([dict(zip(HEADERS, ROW, strict=True))]), encoding="utf-8")
    return source


@pytest.fixture
def xlsx_source(tmp_path):
    source = tmp_path / "pipeline.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pipeline"
    sheet.append(HEADERS)
    sheet.append(ROW)
    workbook.save(source)
    return source


@pytest.fixture
def xlsx_with_formula(tmp_path):
    source = tmp_path / "formula.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pipeline"
    sheet.append(HEADERS)
    row = ROW.copy()
    row[3] = "=1+1"
    sheet.append(row)
    workbook.save(source)
    return source


def test_loaders_return_equivalent_rows(csv_source, json_source, xlsx_source):
    csv_rows, _ = load_source(csv_source, None)
    json_rows, _ = load_source(json_source, None)
    xlsx_rows, meta = load_source(xlsx_source, "Pipeline")
    assert csv_rows == json_rows == xlsx_rows
    assert meta["sheet"] == "Pipeline"


def test_loaders_and_mapping_preserve_padded_header_labels(tmp_path):
    headers = [
        "  Area  ",
        " Sub-area",
        "Opportunity Name ",
        " TCV ",
        "Probability  ",
        " Mar '26 ",
        " Apr '26 ",
        "Apr '26 Probability ",
    ]
    expected_rows = [dict(zip(headers, ROW, strict=True))]

    csv_source = tmp_path / "padded.csv"
    csv_source.write_text(
        ",".join(headers) + "\n" + ",".join(ROW) + "\n",
        encoding="utf-8",
    )
    json_source = tmp_path / "padded.json"
    json_source.write_text(json.dumps(expected_rows), encoding="utf-8")
    xlsx_source = tmp_path / "padded.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pipeline"
    sheet.append(headers)
    sheet.append(ROW)
    workbook.save(xlsx_source)

    csv_rows, _ = load_source(csv_source)
    json_rows, _ = load_source(json_source)
    xlsx_rows, _ = load_source(xlsx_source, "Pipeline")

    assert csv_rows == json_rows == xlsx_rows == expected_rows
    mapping = resolve_mapping(list(csv_rows[0]), None)
    assert mapping["area"] == "  Area  "
    assert mapping["sub_area"] == " Sub-area"
    assert mapping["months"] == [
        {"key": "2026-03", "label": " Mar '26 ", "stage": " Mar '26 "},
        {
            "key": "2026-04",
            "label": " Apr '26 ",
            "stage": " Apr '26 ",
            "probability": "Apr '26 Probability ",
        },
    ]


def test_inspect_lists_sheets_headers_and_month_candidates(xlsx_source):
    report = inspect_source(xlsx_source, "Pipeline")
    assert report["format"] == "xlsx"
    assert report["headers"][:5] == [
        "Area",
        "Sub-area",
        "Opportunity Name",
        "TCV",
        "Probability",
    ]
    assert [month["label"] for month in report["month_candidates"]] == [
        "Mar '26",
        "Apr '26",
        "May '26",
    ]
    assert report["row_count"] == 1
    assert report["source"] == "pipeline.xlsx"
    assert len(report["sha256"]) == 64
    assert "rows" not in report


def test_parse_month_header_handles_loop24_labels():
    assert parse_month_header("March’26") == ("2026-03", "stage")
    assert parse_month_header("Apr '26 Probability") == ("2026-04", "probability")
    assert parse_month_header("2026-05 Status") == ("2026-05", "stage")
    assert parse_month_header("Opportunity Name") is None


def test_parse_month_header_handles_four_digit_year_and_normalized_spacing():
    assert parse_month_header("September_2027 stage") == ("2027-09", "stage")
    assert parse_month_header("  2028-01   Probability ") == ("2028-01", "probability")


def test_ambiguous_alias_requires_explicit_mapping():
    with pytest.raises(DataContractError, match="ambiguous field area"):
        resolve_mapping(["Area", "Sales Area", "Name", "TCV", "Probability"], None)


def test_explicit_mapping_is_validated_and_months_are_sorted():
    headers = [
        "Sales Area",
        "Subarea",
        "Deal Name",
        "Total Contract Value",
        "Current Probability",
        "Apr '26",
        "Mar '26 Probability",
        "Mar '26",
    ]
    explicit = {
        "area": "Sales Area",
        "sub_area": "Subarea",
        "opportunity_name": "Deal Name",
        "tcv": "Total Contract Value",
        "probability": "Current Probability",
        "months": [
            {"key": "2026-04", "label": "April", "stage": "Apr '26"},
            {
                "key": "2026-03",
                "label": "March",
                "stage": "Mar '26",
                "probability": "Mar '26 Probability",
            },
        ],
    }
    mapping = resolve_mapping(headers, explicit)
    assert mapping["area"] == "Sales Area"
    assert mapping["months"] == [
        {
            "key": "2026-03",
            "label": "March",
            "stage": "Mar '26",
            "probability": "Mar '26 Probability",
        },
        {"key": "2026-04", "label": "April", "stage": "Apr '26"},
    ]


@pytest.mark.parametrize(
    ("months", "reused_header"),
    [
        (
            [
                {"key": "2026-03", "label": "March", "stage": "Mar '26"},
                {"key": "2026-04", "label": "April", "stage": "Mar '26"},
            ],
            "Mar '26",
        ),
        (
            [
                {
                    "key": "2026-03",
                    "label": "March",
                    "stage": "Mar '26",
                    "probability": "Mar '26",
                },
            ],
            "Mar '26",
        ),
        (
            [
                {
                    "key": "2026-03",
                    "label": "March",
                    "stage": "Mar '26",
                    "probability": "Monthly Probability",
                },
                {
                    "key": "2026-04",
                    "label": "April",
                    "stage": "Apr '26",
                    "probability": "Monthly Probability",
                },
            ],
            "Monthly Probability",
        ),
    ],
    ids=("stage-stage", "stage-probability", "probability-probability"),
)
def test_explicit_mapping_rejects_reused_month_headers(months, reused_header):
    headers = [
        "Area",
        "Sub-area",
        "Opportunity Name",
        "TCV",
        "Probability",
        "Mar '26",
        "Apr '26",
        "Monthly Probability",
    ]
    explicit = {
        "area": "Area",
        "sub_area": "Sub-area",
        "opportunity_name": "Opportunity Name",
        "tcv": "TCV",
        "probability": "Probability",
        "months": months,
    }

    with pytest.raises(DataContractError, match="reused month header") as error:
        resolve_mapping(headers, explicit)
    assert error.value.code == "invalid_mapping"
    assert error.value.details["header"] == reused_header


def test_auto_mapping_pairs_month_probability_and_preserves_labels():
    headers = [
        "Area",
        "Sub-area",
        "Opportunity Name",
        "TCV",
        "Probability",
        "Apr '26 Probability",
        "Mar '26",
        "Apr '26",
    ]
    mapping = resolve_mapping(headers, None)
    assert mapping["months"] == [
        {"key": "2026-03", "label": "Mar '26", "stage": "Mar '26"},
        {
            "key": "2026-04",
            "label": "Apr '26",
            "stage": "Apr '26",
            "probability": "Apr '26 Probability",
        },
    ]


def test_duplicate_stage_month_requires_explicit_mapping():
    headers = [
        "Area",
        "Sub-area",
        "Opportunity Name",
        "TCV",
        "Probability",
        "Mar '26",
        "March 2026 Status",
    ]
    with pytest.raises(DataContractError, match="ambiguous stage month 2026-03"):
        resolve_mapping(headers, None)


def test_json_with_multiple_arrays_requires_key(tmp_path):
    source = tmp_path / "pipeline.json"
    source.write_text(json.dumps({"current": [{"Area": "A"}], "archive": [{"Area": "B"}]}))
    with pytest.raises(DataContractError, match="JSON array key is required") as error:
        load_source(source, None, None)
    assert error.value.details == {"array_keys": ["current", "archive"]}
    rows, meta = load_source(source, None, "current")
    assert rows == [{"Area": "A"}]
    assert meta["json_key"] == "current"


def test_xlsx_formula_without_cached_value_is_reported(xlsx_with_formula):
    _, meta = load_source(xlsx_with_formula, "Pipeline", None)
    assert meta["uncached_formulas"] == [{"row": 2, "header": "TCV"}]


@pytest.mark.parametrize(
    ("name", "contents", "message"),
    [
        ("empty.csv", "", "source contains no rows"),
        ("blank.csv", "Area,,TCV\nA,B,Large\n", "blank header"),
        ("duplicate.csv", "Area,Area,TCV\nA,B,Large\n", "duplicate header"),
        ("short.csv", "Area,TCV\nA\n", "row 2 does not match headers"),
    ],
)
def test_csv_rejects_invalid_table_shapes(tmp_path, name, contents, message):
    source = tmp_path / name
    source.write_text(contents, encoding="utf-8")
    with pytest.raises(DataContractError, match=message):
        load_source(source)


def test_json_rejects_rows_with_different_headers(tmp_path):
    source = tmp_path / "pipeline.json"
    source.write_text(json.dumps([{"Area": "A", "TCV": "Large"}, {"Area": "B"}]))
    with pytest.raises(DataContractError, match="row 2 does not match headers"):
        load_source(source)


def test_inspect_cli_prints_one_safe_json_object_and_writes_nothing(csv_source):
    before = sorted(path.name for path in csv_source.parent.iterdir())
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "prepare_opportunities.py"), "inspect", str(csv_source)],
        check=False,
        capture_output=True,
        text=True,
    )
    after = sorted(path.name for path in csv_source.parent.iterdir())

    assert result.returncode == 0
    assert result.stderr == ""
    report = json.loads(result.stdout)
    assert report["ok"] is True
    assert report["format"] == "csv"
    assert result.stdout.count("\n") == 1
    assert "Project Cedar" not in result.stdout
    assert before == after


def test_inspect_cli_returns_structured_error_for_multi_array_json(tmp_path):
    source = tmp_path / "pipeline.json"
    source.write_text(json.dumps({"current": [{"Area": "A"}], "archive": [{"Area": "B"}]}))
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "prepare_opportunities.py"), "inspect", str(source)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 2
    assert json.loads(result.stdout) == {
        "ok": False,
        "error": {
            "code": "json_key_required",
            "message": "JSON array key is required",
            "details": {"array_keys": ["current", "archive"]},
        },
    }
