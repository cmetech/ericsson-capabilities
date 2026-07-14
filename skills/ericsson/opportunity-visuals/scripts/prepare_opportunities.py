#!/usr/bin/env python3
"""Inspect and prepare deterministic opportunity visual inputs."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

from opportunity_data import (
    DataContractError,
    apply_filters,
    inspect_source,
    load_source,
    normalize_rows,
    resolve_mapping,
    select_records,
    validate_semantics,
)


def _load_json_object(path: Path, kind: str) -> dict[str, object]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise DataContractError(
            f"invalid_{kind}", f"Unable to read {kind} JSON: {path.name}"
        ) from error
    if not isinstance(value, dict):
        raise DataContractError(f"invalid_{kind}", f"{kind.capitalize()} must be an object")
    return value


def _selected_mapping(
    mapping: dict[str, object], requested_months: list[str] | None
) -> tuple[dict[str, object], list[dict[str, str]], int]:
    available = list(mapping["months"])
    if not requested_months:
        selected = available
        first_index = 0
    else:
        requested = {month.casefold() for month in requested_months}
        selected = [
            month
            for month in available
            if str(month["label"]).casefold() in requested
            or str(month["key"]).casefold() in requested
        ]
        matched = {
            requested_value
            for requested_value in requested
            if any(
                requested_value
                in {str(month["label"]).casefold(), str(month["key"]).casefold()}
                for month in available
            )
        }
        missing = sorted(requested - matched)
        if missing:
            raise DataContractError(
                "month_not_found", "Requested month was not found", {"months": missing}
            )
        first_index = available.index(selected[0])
    if not selected:
        raise DataContractError("missing_months", "At least one month must be selected")
    selected_mapping = {**mapping, "months": selected}
    selected_months = [
        {"key": str(month["key"]), "label": str(month["label"])}
        for month in selected
    ]
    return selected_mapping, selected_months, first_index


def _row_id(row: dict[str, object], source_row: int) -> str:
    for header in ("ID", "Id"):
        if header in row and str(row[header]).strip():
            return str(row[header])
    return f"ROW-{source_row:04d}"


def _terminal_before_range_exclusions(
    rows: list[dict[str, object]],
    all_months: list[dict[str, object]],
    first_selected_index: int,
    semantics: dict[str, object],
) -> list[dict[str, object]]:
    positive = {str(stage).casefold() for stage in semantics["positive_terminals"]}
    negative = {str(stage).casefold() for stage in semantics["negative_terminals"]}
    excluded: list[dict[str, object]] = []
    for source_index, row in enumerate(rows):
        terminal = next(
            (
                str(row.get(str(month["stage"]), ""))
                for month in all_months[:first_selected_index]
                if str(row.get(str(month["stage"]), "")).casefold()
                in positive | negative
            ),
            None,
        )
        if terminal is not None:
            source_row = source_index + 2
            excluded.append(
                {
                    "id": _row_id(row, source_row),
                    "source_row": source_row,
                    "code": "terminal_before_range",
                    "message": "Row reached a terminal before the selected range",
                }
            )
    return excluded


def _atomic_json(path: Path, value: object) -> None:
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        temporary.replace(path)
    finally:
        if temporary.exists():
            temporary.unlink()


def _validate_output_destination(output_dir: Path) -> bool:
    """Return whether the destination must be created, rejecting unsafe reuse."""

    try:
        if output_dir.is_symlink():
            raise DataContractError(
                "output_exists", "Output destination already exists"
            )
        if output_dir.exists():
            if not output_dir.is_dir() or any(output_dir.iterdir()):
                raise DataContractError(
                    "output_exists", "Output destination already exists"
                )
            return False
    except DataContractError:
        raise
    except OSError:
        raise DataContractError(
            "output_exists", "Output destination already exists"
        ) from None
    return True


def _write_artifacts(
    output_dir: Path,
    artifacts: list[tuple[str, object]],
    create_output_dir: bool,
) -> None:
    written: list[Path] = []
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, value in artifacts:
            path = output_dir / name
            _atomic_json(path, value)
            written.append(path)
    except OSError:
        for path in written:
            try:
                path.unlink()
            except OSError:
                pass
        if create_output_dir:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        raise DataContractError(
            "output_unwritable", "Unable to write output artifacts"
        ) from None


def prepare(
    source: Path,
    view: str,
    semantics_path: Path,
    output_dir: Path,
    mapping_path: Path | None = None,
    sheet: str | None = None,
    json_key: str | None = None,
    months: list[str] | None = None,
    filters_path: Path | None = None,
) -> dict[str, object]:
    """Normalize, filter, select, and atomically write preparation artifacts."""

    source = Path(source)
    output_dir = Path(output_dir)
    create_output_dir = _validate_output_destination(output_dir)

    semantics_path = Path(semantics_path)
    semantics = validate_semantics(_load_json_object(semantics_path, "semantics"))
    semantics_sha256 = hashlib.sha256(semantics_path.read_bytes()).hexdigest()
    filters = _load_json_object(filters_path, "filters") if filters_path else {}
    rows, metadata = load_source(source, sheet, json_key)
    explicit_mapping = (
        _load_json_object(mapping_path, "mapping") if mapping_path is not None else None
    )
    mapping = resolve_mapping(list(rows[0]), explicit_mapping)
    selected_mapping, selected_months, first_selected_index = _selected_mapping(
        mapping, months
    )

    selected_headers = {
        str(mapping[field])
        for field in ("area", "sub_area", "opportunity_name", "tcv", "probability")
    }
    for month in selected_mapping["months"]:
        selected_headers.add(str(month["stage"]))
        if "probability" in month:
            selected_headers.add(str(month["probability"]))
    intersecting_formulas = [
        item
        for item in metadata.get("uncached_formulas", [])
        if item["header"] in selected_headers
    ]
    if intersecting_formulas:
        raise DataContractError(
            "formula_cache_missing",
            "A selected formula cell has no cached value",
            {"cells": intersecting_formulas},
        )

    range_exclusions = _terminal_before_range_exclusions(
        rows, list(mapping["months"]), first_selected_index, semantics
    )
    records, invalid_exclusions = normalize_rows(
        rows, selected_mapping, semantics
    )
    range_excluded_rows = {
        (item["id"], item["source_row"]) for item in range_exclusions
    }
    records = [
        record
        for record in records
        if (record["id"], record["source_row"]) not in range_excluded_rows
    ]
    invalid_exclusions = [
        item
        for item in invalid_exclusions
        if (item["id"], item["source_row"]) not in range_excluded_rows
    ]
    warnings = [
        {
            "id": record["id"],
            "source_row": record["source_row"],
            **warning,
        }
        for record in records
        for warning in record["warnings"]
    ]
    filtered_records, filter_exclusions = apply_filters(records, filters)
    selected_records, view_exclusions = select_records(filtered_records, view)
    exclusions = (
        range_exclusions + invalid_exclusions + filter_exclusions + view_exclusions
    )
    counts = {
        "source_rows": len(rows),
        "normalized_rows": len(records),
        "included_rows": len(selected_records),
        "excluded_rows": len(exclusions),
        "warnings": len(warnings),
    }
    source_summary = {
        "source": metadata["source"],
        "sha256": metadata["sha256"],
        "format": metadata["format"],
        "sheet": metadata.get("sheet"),
        "mapping": mapping,
        "semantics_sha256": semantics_sha256,
        "selected_months": selected_months,
        "view": view,
        "filters": filters,
        "counts": counts,
    }
    normalized_data = {
        "schema_version": 1,
        "view": view,
        "source": {
            "basename": metadata["source"],
            "sha256": metadata["sha256"],
            "sheet": metadata.get("sheet"),
        },
        "mapping": mapping,
        "semantics": semantics,
        "selected_months": selected_months,
        "filters": filters,
        "records": selected_records,
        "exclusions": exclusions,
        "warnings": warnings,
        "counts": counts,
    }

    _write_artifacts(
        output_dir,
        [
            ("source-summary.json", source_summary),
            ("normalized-data.json", normalized_data),
            ("exclusions.json", {"exclusions": exclusions}),
        ],
        create_output_dir,
    )
    return {
        "output_dir": str(output_dir),
        "artifacts": [
            "source-summary.json",
            "normalized-data.json",
            "exclusions.json",
        ],
        "counts": counts,
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="prepare_opportunities.py")
    subcommands = parser.add_subparsers(dest="command", required=True)
    inspect_parser = subcommands.add_parser("inspect")
    inspect_parser.add_argument("source", type=Path)
    inspect_parser.add_argument("--sheet")
    inspect_parser.add_argument("--json-key")
    prepare_parser = subcommands.add_parser("prepare")
    prepare_parser.add_argument("source", type=Path)
    prepare_parser.add_argument("--view", required=True)
    prepare_parser.add_argument("--semantics", required=True, type=Path)
    prepare_parser.add_argument("--mapping", type=Path)
    prepare_parser.add_argument("--output-dir", required=True, type=Path)
    prepare_parser.add_argument("--sheet")
    prepare_parser.add_argument("--json-key")
    prepare_parser.add_argument("--months", action="append")
    prepare_parser.add_argument("--filters", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "inspect":
            report = inspect_source(args.source, args.sheet, args.json_key)
            print(json.dumps({"ok": True, **report}, separators=(",", ":")))
            return 0
        if args.command == "prepare":
            report = prepare(
                args.source,
                args.view,
                args.semantics,
                args.output_dir,
                mapping_path=args.mapping,
                sheet=args.sheet,
                json_key=args.json_key,
                months=args.months,
                filters_path=args.filters,
            )
            print(json.dumps({"ok": True, **report}, separators=(",", ":")))
            return 0
    except DataContractError as error:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": error.code,
                        "message": str(error),
                        "details": error.details,
                    },
                },
                separators=(",", ":"),
            )
        )
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
