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
    apply_filters,
    classify_transition,
    inspect_source,
    load_source,
    normalize_rank,
    normalize_rows,
    parse_month_header,
    resolve_mapping,
    select_records,
)
from prepare_opportunities import prepare  # noqa: E402


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


@pytest.fixture
def semantics():
    return {
        "positive_terminals": ["Won"],
        "negative_terminals": ["Lost", "Cancelled"],
        "stage_paths": [
            ["Ideation", "Solution", "Proposal", "SDP2", "Won"],
            ["POC", "Workshop", "Commercials", "Won"],
        ],
        "positive_transitions": [["Proposal", "Workshop"]],
        "tcv_order": ["X-Small", "Small", "Medium", "Large", "X-Large"],
        "probability_order": ["Low", "Medium", "High", "Certain"],
    }


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


@pytest.mark.parametrize(
    ("value", "field", "expected"),
    [
        ("$2.5M", "tcv", ("$2.5M", 2_500_000.0, "numeric")),
        ("1,250", "tcv", ("1,250", 1250.0, "numeric")),
        (0.25, "probability", ("0.25", 25.0, "numeric")),
        ("75%", "probability", ("75%", 75.0, "numeric")),
        ("high", "probability", ("high", 2, "categorical")),
    ],
)
def test_normalize_rank_accepts_numeric_and_categorical_values(
    value, field, expected, semantics
):
    order = semantics[f"{field}_order"]
    assert normalize_rank(value, order, field) == expected


def _showcase_rows():
    histories = {
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
    fixed = {
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
    rows = []
    for row_id, fields in fixed.items():
        area, sub_area, name, tcv, probability = fields
        row = {
            "ID": row_id,
            "Area": area,
            "Sub-area": sub_area,
            "Opportunity Name": name,
            "TCV": tcv,
            "Probability": probability,
        }
        for label, values in zip(("Mar '26", "Apr '26", "May '26", "Jun '26"), histories[row_id], strict=True):
            row[label], row[f"{label} Probability"] = values
        rows.append(row)
    return rows


def _showcase_mapping():
    return {
        "area": "Area",
        "sub_area": "Sub-area",
        "opportunity_name": "Opportunity Name",
        "tcv": "TCV",
        "probability": "Probability",
        "months": [
            {
                "key": f"2026-{month:02d}",
                "label": label,
                "stage": label,
                "probability": f"{label} Probability",
            }
            for month, label in enumerate(
                ("Mar '26", "Apr '26", "May '26", "Jun '26"), start=3
            )
        ],
    }


def test_normalize_rows_preserves_values_blanks_ranks_and_warnings(semantics):
    records, excluded = normalize_rows(_showcase_rows(), _showcase_mapping(), semantics)
    by_id = {record["id"]: record for record in records}

    assert "OV-005" not in by_id
    assert excluded == [
        {
            "id": "OV-005",
            "source_row": 6,
            "code": "insufficient_stages",
            "message": "At least two populated stages are required",
        }
    ]
    assert by_id["OV-008"]["opportunity_name"] == "Harbor Observability <Pilot> =1+1"
    assert by_id["OV-012"]["tcv"] == {
        "display": "Medium",
        "sort": 2,
        "kind": "categorical",
    }
    assert by_id["OV-012"]["probability"] == {
        "display": "High",
        "sort": 2,
        "kind": "categorical",
    }
    assert [month["classification"] for month in by_id["OV-006"]["months"]] == [
        "initial",
        "empty",
        "positive",
        "neutral",
    ]
    assert by_id["OV-006"]["months"][2]["skipped_months"] == ["Apr '26"]
    assert "skipped_blank_months" in {
        warning["code"] for warning in by_id["OV-006"]["warnings"]
    }
    assert [month["classification"] for month in by_id["OV-007"]["months"]] == [
        "initial",
        "mixed",
        "neutral",
        "neutral",
    ]
    assert "mixed_signals" in {warning["code"] for warning in by_id["OV-007"]["warnings"]}
    assert "unknown_transition" in {
        warning["code"] for warning in by_id["OV-011"]["warnings"]
    }
    assert len(by_id["OV-001"]["months"]) == 3
    assert by_id["OV-001"]["terminal"] == {
        "kind": "positive",
        "month": "2026-05",
        "index": 2,
    }


def test_select_records_applies_each_view_and_deterministic_sorting(semantics):
    records, _ = normalize_rows(_showcase_rows(), _showcase_mapping(), semantics)

    assert [record["id"] for record in select_records(records, "wins")[0]] == [
        "OV-001",
        "OV-010",
    ]
    assert [record["id"] for record in select_records(records, "losses")[0]] == [
        "OV-003",
        "OV-009",
    ]
    all_ids = [record["id"] for record in select_records(records, "all-progression")[0]]
    positive_ids = [
        record["id"]
        for record in select_records(records, "positive-progression")[0]
    ]
    assert "OV-004" in all_ids
    assert "OV-004" not in positive_ids
    assert "OV-005" not in all_ids
    assert all_ids == [
        "OV-003",
        "OV-004",
        "OV-002",
        "OV-006",
        "OV-001",
        "OV-010",
        "OV-009",
        "OV-011",
        "OV-008",
        "OV-007",
        "OV-012",
    ]


def test_apply_filters_matches_case_insensitively_and_uses_rank_bounds(semantics):
    records, _ = normalize_rows(_showcase_rows(), _showcase_mapping(), semantics)
    filters = {
        "areas": ["core group"],
        "sub_areas": ["automation"],
        "opportunity_contains": "automation",
        "tcv_min": 2,
        "tcv_max": 4,
        "probability_min": 1,
        "probability_max": 3,
    }

    included, excluded = apply_filters(records, filters)

    assert [record["id"] for record in included] == ["OV-002"]
    assert all(record["area"] == "Core Group" for record in included)
    assert all(item["code"] == "filter_not_matched" for item in excluded)
    assert all("Harbor Observability" not in item["message"] for item in excluded)


def test_prepare_cli_writes_stable_artifacts_and_refuses_nonempty_output(
    tmp_path, semantics
):
    source = tmp_path / "pipeline.csv"
    rows = _showcase_rows()[:2]
    headers = list(rows[0])
    source.write_text(
        ",".join(headers)
        + "\n"
        + "\n".join(
            ",".join(str(row[header]) for header in headers) for row in rows
        )
        + "\n",
        encoding="utf-8",
    )
    semantics_path = tmp_path / "semantics.json"
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")
    output_dir = tmp_path / "prepared"
    command = [
        sys.executable,
        str(SCRIPTS / "prepare_opportunities.py"),
        "prepare",
        str(source),
        "--view",
        "wins",
        "--semantics",
        str(semantics_path),
        "--output-dir",
        str(output_dir),
    ]

    result = subprocess.run(command, check=False, capture_output=True, text=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert result.stderr == ""
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "exclusions.json",
        "normalized-data.json",
        "source-summary.json",
    ]
    summary = json.loads((output_dir / "source-summary.json").read_text())
    normalized = json.loads((output_dir / "normalized-data.json").read_text())
    assert summary["source"] == "pipeline.csv"
    assert len(summary["sha256"]) == 64
    assert normalized["source"] == {
        "basename": "pipeline.csv",
        "sha256": summary["sha256"],
    }
    assert normalized["schema_version"] == 1
    assert [record["id"] for record in normalized["records"]] == ["OV-001"]
    for artifact in output_dir.iterdir():
        text = artifact.read_text(encoding="utf-8")
        assert text.endswith("\n")
        assert text == json.dumps(json.loads(text), indent=2, sort_keys=True) + "\n"

    repeated = subprocess.run(command, check=False, capture_output=True, text=True)
    assert repeated.returncode == 2
    assert json.loads(repeated.stdout)["error"]["code"] == "output_exists"


def test_prepare_function_rejects_formula_only_when_selected_field_is_uncached(
    tmp_path, xlsx_with_formula, semantics
):
    semantics_path = tmp_path / "semantics.json"
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")

    with pytest.raises(DataContractError) as error:
        prepare(
            xlsx_with_formula,
            "wins",
            semantics_path,
            tmp_path / "prepared",
            sheet="Pipeline",
        )
    assert error.value.code == "formula_cache_missing"


def test_prepare_preserves_source_rows_after_terminal_before_selected_range(
    tmp_path, semantics
):
    source = tmp_path / "pipeline.csv"
    source.write_text(
        "ID,Area,Sub-area,Opportunity Name,TCV,Probability,Mar '26,Apr '26,May '26,Jun '26\n"
        "OV-A,Area A,Sub A,Terminal First,Large,High,Proposal,Lost,Restarted,Won\n"
        "OV-B,Area B,Sub B,Still Eligible,Medium,Medium,,,Ideation,Proposal\n",
        encoding="utf-8",
    )
    semantics_path = tmp_path / "semantics.json"
    semantics_path.write_text(json.dumps(semantics), encoding="utf-8")
    output_dir = tmp_path / "prepared"

    prepare(
        source,
        "all-progression",
        semantics_path,
        output_dir,
        months=["May '26", "Jun '26"],
    )

    normalized = json.loads((output_dir / "normalized-data.json").read_text())
    assert [(record["id"], record["source_row"]) for record in normalized["records"]] == [
        ("OV-B", 3)
    ]
    assert normalized["exclusions"] == [
        {
            "id": "OV-A",
            "source_row": 2,
            "code": "terminal_before_range",
            "message": "Row reached a terminal before the selected range",
        }
    ]


def test_semantics_reject_conflicting_case_insensitive_configuration(semantics):
    conflicting = dict(semantics)
    conflicting["stage_paths"] = [["Ideation", "Solution"], ["solution", "Ideation"]]

    with pytest.raises(DataContractError) as error:
        classify_transition({"stage": "Ideation"}, {"stage": "Solution"}, conflicting)
    assert error.value.code == "conflicting_stage_order"
