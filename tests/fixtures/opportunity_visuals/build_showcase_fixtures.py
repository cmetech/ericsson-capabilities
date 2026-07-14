#!/usr/bin/env python3
"""Build the deterministic, synthetic Opportunity Visuals showcase pack."""

from __future__ import annotations

import argparse
import csv
import json
import re
import zipfile
from datetime import datetime
from io import BytesIO
from pathlib import Path

from openpyxl import Workbook


HEADERS = [
    "ID",
    "Area",
    "Sub-area",
    "Opportunity Name",
    "TCV",
    "Probability",
    "Mar '26",
    "Mar '26 Probability",
    "Apr '26",
    "Apr '26 Probability",
    "May '26",
    "May '26 Probability",
    "Jun '26",
    "Jun '26 Probability",
]

HISTORIES = {
    "OV-001": [
        ("Ideation", "Low"),
        ("Proposal", "Medium"),
        ("Won", "Certain"),
        ("In Delivery", "Certain"),
    ],
    "OV-002": [
        ("Proposal", "Medium"),
        ("Workshop", "High"),
        ("Commercials", "High"),
        ("Commercials", "High"),
    ],
    "OV-003": [
        ("Solution", "High"),
        ("Ideation", "Medium"),
        ("Lost", "Low"),
        ("", ""),
    ],
    "OV-004": [
        ("Solution", "Medium"),
        ("Solution", "Medium"),
        ("Solution", "Medium"),
        ("Solution", "Medium"),
    ],
    "OV-005": [("", ""), ("", ""), ("Discovery", "Low"), ("", "")],
    "OV-006": [
        ("Ideation", "Low"),
        ("", ""),
        ("Proposal", "High"),
        ("Proposal", "High"),
    ],
    "OV-007": [
        ("Solution", "High"),
        ("Proposal", "Medium"),
        ("Proposal", "Medium"),
        ("Proposal", "Medium"),
    ],
    "OV-008": [
        ("Ideation", "Low"),
        ("Solution", "Medium"),
        ("Solution", "Medium"),
        ("Solution", "Medium"),
    ],
    "OV-009": [
        ("Proposal", "High"),
        ("Lost", "Low"),
        ("Restarted", "Medium"),
        ("Won", "Certain"),
    ],
    "OV-010": [
        ("Proposal", "High"),
        ("Solution", "Medium"),
        ("Proposal", "High"),
        ("Won", "Certain"),
    ],
    "OV-011": [
        ("Discovery", "Low"),
        ("Deferred", "Low"),
        ("Deferred", "Low"),
        ("Deferred", "Low"),
    ],
    "OV-012": [
        ("Ideation", "Low"),
        ("Solution", "Medium"),
        ("Proposal", "High"),
        ("Proposal", "High"),
    ],
}

BASE_FIELDS = {
    "OV-001": ("Core Group", "Core", "Aurora Core Renewal", "X-Large", "Certain"),
    "OV-002": ("Core Group", "Automation", "Beacon Automation", "Large", "High"),
    "OV-003": ("Cloud Group", "Assurance", "Cedar Assurance", "X-Large", "Low"),
    "OV-004": ("Cloud Group", "Assurance", "Delta Capacity", "Medium", "Medium"),
    "OV-005": ("Edge Group", "Discovery", "Echo Modernization", "Small", "Low"),
    "OV-006": ("Core Group", "Automation", "Fjord Analytics", "Medium", "High"),
    "OV-007": ("OSS Group", "Orchestration", "Grove Orchestration", "Large", "Medium"),
    "OV-008": (
        "OSS Group",
        "Observability",
        "Harbor Observability <Pilot> =1+1",
        "Small",
        "Medium",
    ),
    "OV-009": ("Edge Group", "Delivery", "Ion Edge Program", "X-Large", "Low"),
    "OV-010": ("Core Group", "Core", "Juniper Expansion", "Large", "Certain"),
    "OV-011": ("Edge Group", "Discovery", "Kite Discovery", "X-Small", "Low"),
    "OV-012": ("OSS Group", "Platform", "Lumen Platform", "Medium", "High"),
}

SEMANTICS = {
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

TRANSITIONS = {
    "OV-001": ["initial", "positive", "won"],
    "OV-002": ["initial", "positive", "positive", "neutral"],
    "OV-003": ["initial", "negative", "lost"],
    "OV-004": ["initial", "neutral", "neutral", "neutral"],
    "OV-005": ["initial"],
    "OV-006": ["initial", "empty", "positive", "neutral"],
    "OV-007": ["initial", "mixed", "neutral", "neutral"],
    "OV-008": ["initial", "positive", "neutral", "neutral"],
    "OV-009": ["initial", "lost"],
    "OV-010": ["initial", "negative", "positive", "won"],
    "OV-011": ["initial", "unknown", "neutral", "neutral"],
    "OV-012": ["initial", "positive", "positive", "neutral"],
}

TERMINALS = {
    "OV-001": {"kind": "positive", "month": "2026-05", "index": 2},
    "OV-002": None,
    "OV-003": {"kind": "negative", "month": "2026-05", "index": 2},
    "OV-004": None,
    "OV-006": None,
    "OV-007": None,
    "OV-008": None,
    "OV-009": {"kind": "negative", "month": "2026-04", "index": 1},
    "OV-010": {"kind": "positive", "month": "2026-06", "index": 3},
    "OV-011": None,
    "OV-012": None,
}

EXPECTED_NORMALIZED = {
    "source_ids": [
        "OV-001",
        "OV-002",
        "OV-003",
        "OV-004",
        "OV-005",
        "OV-006",
        "OV-007",
        "OV-008",
        "OV-009",
        "OV-010",
        "OV-011",
        "OV-012",
    ],
    "included_ids": [
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
    ],
    "transitions": TRANSITIONS,
    "terminals": TERMINALS,
    "excluded": [{"id": "OV-005", "code": "insufficient_stages"}],
    "blank_month": {
        "key": "2026-04",
        "label": "Apr '26",
        "stage": "",
        "classification": "empty",
        "skipped_months": [],
    },
}

EXPECTED_VIEWS = {
    "wins": {
        "included_ids": ["OV-001", "OV-010"],
        "excluded": [
            {"id": "OV-005", "code": "insufficient_stages"},
            {"id": "OV-002", "code": "view_not_matched"},
            {"id": "OV-003", "code": "view_not_matched"},
            {"id": "OV-004", "code": "view_not_matched"},
            {"id": "OV-006", "code": "view_not_matched"},
            {"id": "OV-007", "code": "view_not_matched"},
            {"id": "OV-008", "code": "view_not_matched"},
            {"id": "OV-009", "code": "view_not_matched"},
            {"id": "OV-011", "code": "view_not_matched"},
            {"id": "OV-012", "code": "view_not_matched"},
        ],
        "transitions": {
            "OV-001": TRANSITIONS["OV-001"],
            "OV-010": TRANSITIONS["OV-010"],
        },
        "terminals": {
            "OV-001": TERMINALS["OV-001"],
            "OV-010": TERMINALS["OV-010"],
        },
    },
    "losses": {
        "included_ids": ["OV-003", "OV-009"],
        "excluded": [
            {"id": "OV-005", "code": "insufficient_stages"},
            {"id": "OV-001", "code": "view_not_matched"},
            {"id": "OV-002", "code": "view_not_matched"},
            {"id": "OV-004", "code": "view_not_matched"},
            {"id": "OV-006", "code": "view_not_matched"},
            {"id": "OV-007", "code": "view_not_matched"},
            {"id": "OV-008", "code": "view_not_matched"},
            {"id": "OV-010", "code": "view_not_matched"},
            {"id": "OV-011", "code": "view_not_matched"},
            {"id": "OV-012", "code": "view_not_matched"},
        ],
        "transitions": {
            "OV-003": TRANSITIONS["OV-003"],
            "OV-009": TRANSITIONS["OV-009"],
        },
        "terminals": {
            "OV-003": TERMINALS["OV-003"],
            "OV-009": TERMINALS["OV-009"],
        },
    },
    "all-progression": {
        "included_ids": EXPECTED_NORMALIZED["included_ids"],
        "excluded": [{"id": "OV-005", "code": "insufficient_stages"}],
        "transitions": {
            row_id: TRANSITIONS[row_id]
            for row_id in EXPECTED_NORMALIZED["included_ids"]
        },
        "terminals": {
            row_id: TERMINALS[row_id]
            for row_id in EXPECTED_NORMALIZED["included_ids"]
        },
    },
    "positive-progression": {
        "included_ids": ["OV-002", "OV-006", "OV-001", "OV-010", "OV-008", "OV-012"],
        "excluded": [
            {"id": "OV-005", "code": "insufficient_stages"},
            {"id": "OV-003", "code": "view_not_matched"},
            {"id": "OV-004", "code": "view_not_matched"},
            {"id": "OV-007", "code": "view_not_matched"},
            {"id": "OV-009", "code": "view_not_matched"},
            {"id": "OV-011", "code": "view_not_matched"},
        ],
        "transitions": {
            "OV-002": TRANSITIONS["OV-002"],
            "OV-006": TRANSITIONS["OV-006"],
            "OV-001": TRANSITIONS["OV-001"],
            "OV-010": TRANSITIONS["OV-010"],
            "OV-008": TRANSITIONS["OV-008"],
            "OV-012": TRANSITIONS["OV-012"],
        },
        "terminals": {
            "OV-002": TERMINALS["OV-002"],
            "OV-006": TERMINALS["OV-006"],
            "OV-001": TERMINALS["OV-001"],
            "OV-010": TERMINALS["OV-010"],
            "OV-008": TERMINALS["OV-008"],
            "OV-012": TERMINALS["OV-012"],
        },
    },
}

EXPECTED_RUN_SUMMARY = {
    "warnings": [
        {"id": "OV-006", "code": "skipped_blank_months"},
        {"id": "OV-007", "code": "mixed_signals"},
        {"id": "OV-011", "code": "unknown_transition"},
    ],
    "views": {
        "wins": {
            "included_rows": 2,
            "excluded_rows": 10,
            "warnings": 3,
            "pages": 1,
            "page_assignments": [
                {"number": 1, "row_ids": ["OV-001", "OV-010"]}
            ],
        },
        "losses": {
            "included_rows": 2,
            "excluded_rows": 10,
            "warnings": 3,
            "pages": 1,
            "page_assignments": [
                {"number": 1, "row_ids": ["OV-003", "OV-009"]}
            ],
        },
        "all-progression": {
            "included_rows": 11,
            "excluded_rows": 1,
            "warnings": 3,
            "pages": 1,
            "page_assignments": [
                {
                    "number": 1,
                    "row_ids": [
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
                    ],
                }
            ],
        },
        "positive-progression": {
            "included_rows": 6,
            "excluded_rows": 6,
            "warnings": 3,
            "pages": 1,
            "page_assignments": [
                {
                    "number": 1,
                    "row_ids": [
                        "OV-002",
                        "OV-006",
                        "OV-001",
                        "OV-010",
                        "OV-008",
                        "OV-012",
                    ],
                }
            ],
        },
    },
}


def _rows() -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    month_labels = ("Mar '26", "Apr '26", "May '26", "Jun '26")
    for row_id, (area, sub_area, name, tcv, probability) in BASE_FIELDS.items():
        row = {
            "ID": row_id,
            "Area": area,
            "Sub-area": sub_area,
            "Opportunity Name": name,
            "TCV": tcv,
            "Probability": probability,
        }
        for label, (stage, monthly_probability) in zip(
            month_labels, HISTORIES[row_id], strict=True
        ):
            row[label] = stage
            row[f"{label} Probability"] = monthly_probability
        rows.append(row)
    return rows


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=HEADERS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _canonical_xlsx_bytes(rows: list[dict[str, str]]) -> bytes:
    workbook = Workbook()
    worksheet = workbook.active
    worksheet.title = "Pipeline"
    worksheet.sheet_state = "visible"
    worksheet.append(HEADERS)
    for row in rows:
        worksheet.append([row[header] for header in HEADERS])
    fixed_time = datetime(2000, 1, 1, 0, 0, 0)
    workbook.properties.creator = "Synthetic Opportunity Visuals Fixture Builder"
    workbook.properties.lastModifiedBy = "Synthetic Opportunity Visuals Fixture Builder"
    workbook.properties.created = fixed_time
    workbook.properties.modified = fixed_time

    raw = BytesIO()
    workbook.save(raw)
    workbook.close()
    canonical = BytesIO()
    with zipfile.ZipFile(BytesIO(raw.getvalue()), "r") as source:
        with zipfile.ZipFile(
            canonical,
            "w",
            compression=zipfile.ZIP_DEFLATED,
            compresslevel=9,
        ) as target:
            for name in sorted(source.namelist()):
                contents = source.read(name)
                if name == "docProps/core.xml":
                    contents = re.sub(
                        rb"(<dcterms:modified[^>]*>)[^<]*(</dcterms:modified>)",
                        rb"\g<1>2000-01-01T00:00:00Z\g<2>",
                        contents,
                    )
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 0
                info.external_attr = 0
                target.writestr(
                    info,
                    contents,
                    compress_type=zipfile.ZIP_DEFLATED,
                    compresslevel=9,
                )
    return canonical.getvalue()


def build(output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    rows = _rows()
    _write_csv(output_dir / "showcase-opportunities.csv", rows)
    (output_dir / "showcase-opportunities.json").write_text(
        json.dumps(rows, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    (output_dir / "showcase-opportunities.xlsx").write_bytes(
        _canonical_xlsx_bytes(rows)
    )
    _write_json(output_dir / "stage-semantics.json", SEMANTICS)
    _write_json(output_dir / "expected-normalized.json", EXPECTED_NORMALIZED)
    _write_json(output_dir / "expected-run-summary.json", EXPECTED_RUN_SUMMARY)
    for view, expected in EXPECTED_VIEWS.items():
        _write_json(output_dir / f"expected-{view}.json", expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path(__file__).resolve().parent,
    )
    args = parser.parse_args()
    build(args.output_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
