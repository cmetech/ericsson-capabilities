"""Read-only opportunity source inspection and field discovery."""

from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path


class DataContractError(ValueError):
    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


FIELD_ALIASES = {
    "area": {"area", "sales area"},
    "sub_area": {"sub area", "sub-area", "subarea"},
    "opportunity_name": {"opportunity name", "opportunity", "deal name"},
    "tcv": {"tcv", "total contract value"},
    "probability": {"probability", "current probability"},
}
MONTHS = {
    name.lower(): index
    for index, names in enumerate(
        (
            ("jan", "january"),
            ("feb", "february"),
            ("mar", "march"),
            ("apr", "april"),
            ("may",),
            ("jun", "june"),
            ("jul", "july"),
            ("aug", "august"),
            ("sep", "sept", "september"),
            ("oct", "october"),
            ("nov", "november"),
            ("dec", "december"),
        ),
        start=1,
    )
    for name in names
}

_FIXED_FIELDS = tuple(FIELD_ALIASES)
_MONTH_WORD_PATTERN = re.compile(r"^([a-z]+)\s*'?\s*(\d{2}|\d{4})$", re.IGNORECASE)
_ISO_MONTH_PATTERN = re.compile(r"^(\d{4})-(\d{2})$")


def _normalize_header(header: str) -> str:
    return " ".join(header.replace("’", "'").replace("_", " ").split()).casefold()


def _source_metadata(path: Path, row_count: int) -> dict[str, object]:
    return {
        "source": path.name,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "row_count": row_count,
    }


def _validate_table(
    headers: list[str],
    rows: list[dict[str, object]],
    *,
    malformed_rows: list[int] | None = None,
    first_row_number: int = 2,
) -> None:
    if not headers or not rows:
        raise DataContractError("empty_source", "source contains no rows")
    normalized = [_normalize_header(header) for header in headers]
    if any(not header for header in normalized):
        raise DataContractError("blank_header", "source contains a blank header")
    duplicates = sorted({header for header in normalized if normalized.count(header) > 1})
    if duplicates:
        raise DataContractError(
            "duplicate_header",
            "source contains a duplicate header",
            {"headers": duplicates},
        )

    expected = set(headers)
    malformed = set(malformed_rows or [])
    for row_number, row in enumerate(rows, start=first_row_number):
        if row_number in malformed or set(row) != expected:
            raise DataContractError(
                "invalid_row_shape",
                f"row {row_number} does not match headers",
                {"row": row_number},
            )


def load_source(
    path: Path,
    sheet: str | None = None,
    json_key: str | None = None,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    """Load a supported source without evaluating formulas or mutating the file."""

    path = Path(path)
    suffix = path.suffix.lower()
    if suffix == ".csv":
        with path.open("r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            raw_headers = reader.fieldnames or []
            headers = [header if header is not None else "" for header in raw_headers]
            raw_rows = list(reader)

        malformed_rows = [
            row_number
            for row_number, row in enumerate(raw_rows, start=2)
            if None in row or any(value is None for value in row.values())
        ]
        rows = [dict(row) for row in raw_rows]
        _validate_table(headers, rows, malformed_rows=malformed_rows)
        return rows, {
            "format": "csv",
            "sheet": None,
            **_source_metadata(path, len(rows)),
        }

    if suffix == ".json":
        payload = json.loads(path.read_text(encoding="utf-8"))
        selected_key: str | None = None
        array_keys: list[str] = []
        if isinstance(payload, list):
            rows = payload
        elif isinstance(payload, dict):
            arrays = [(key, value) for key, value in payload.items() if isinstance(value, list)]
            array_keys = [key for key, _ in arrays]
            if not arrays:
                raise DataContractError("invalid_json_shape", "JSON object contains no row array")
            if json_key is None and len(arrays) != 1:
                raise DataContractError(
                    "json_key_required",
                    "JSON array key is required",
                    {"array_keys": array_keys},
                )
            selected_key = json_key or arrays[0][0]
            if selected_key not in payload or not isinstance(payload[selected_key], list):
                raise DataContractError(
                    "json_key_not_found",
                    f"JSON row array not found: {selected_key}",
                )
            rows = payload[selected_key]
        else:
            raise DataContractError(
                "invalid_json_shape",
                "JSON must be a row array or contain one row array",
            )

        if not all(isinstance(row, dict) for row in rows):
            raise DataContractError("invalid_json_row", "Every JSON row must be an object")
        headers = [str(header) for header in rows[0]] if rows else []
        normalized_rows = [dict(row) for row in rows]
        _validate_table(headers, normalized_rows, first_row_number=1)
        return normalized_rows, {
            "format": "json",
            "sheet": None,
            "json_key": selected_key,
            "array_keys": array_keys,
            **_source_metadata(path, len(normalized_rows)),
        }

    if suffix == ".xlsx":
        from openpyxl import load_workbook

        workbook = load_workbook(path, read_only=True, data_only=True)
        formulas = load_workbook(path, read_only=True, data_only=False)
        try:
            available_sheets = list(workbook.sheetnames)
            if sheet is None:
                if len(available_sheets) != 1:
                    raise DataContractError(
                        "sheet_required",
                        "XLSX contains multiple worksheets",
                        {"sheets": available_sheets},
                    )
                sheet = available_sheets[0]
            if sheet not in available_sheets:
                raise DataContractError(
                    "sheet_not_found",
                    f"Worksheet not found: {sheet}",
                    {"sheets": available_sheets},
                )

            values = workbook[sheet].iter_rows(values_only=True)
            formula_values = formulas[sheet].iter_rows(values_only=True)
            try:
                header_row = next(values)
                next(formula_values)
            except StopIteration as error:
                raise DataContractError("empty_source", "source contains no rows") from error
            headers = [str(value) if value is not None else "" for value in header_row]
            rows: list[dict[str, object]] = []
            uncached_formulas: list[dict[str, object]] = []
            for row_number, (row, formula_row) in enumerate(
                zip(values, formula_values, strict=True),
                start=2,
            ):
                if len(row) != len(headers) or len(formula_row) != len(headers):
                    raise DataContractError(
                        "invalid_row_shape",
                        f"row {row_number} does not match headers",
                        {"row": row_number},
                    )
                for index, formula in enumerate(formula_row):
                    if isinstance(formula, str) and formula.startswith("=") and row[index] is None:
                        uncached_formulas.append({"row": row_number, "header": headers[index]})
                rows.append(dict(zip(headers, row, strict=True)))
            _validate_table(headers, rows)
            return rows, {
                "format": "xlsx",
                "sheet": sheet,
                "sheets": available_sheets,
                "uncached_formulas": uncached_formulas,
                **_source_metadata(path, len(rows)),
            }
        finally:
            workbook.close()
            formulas.close()

    raise DataContractError("unsupported_format", f"Unsupported source format: {suffix}")


def parse_month_header(header: str) -> tuple[str, str] | None:
    """Return a chronological month key and stage/probability column kind."""

    normalized = _normalize_header(header)
    kind = "probability" if re.search(r"\bprobability\b", normalized) else "stage"
    without_kind = re.sub(r"\b(?:stage|status|probability)\b", " ", normalized)
    candidate = " ".join(without_kind.split())

    iso_match = _ISO_MONTH_PATTERN.fullmatch(candidate)
    if iso_match:
        year, month = (int(part) for part in iso_match.groups())
        if 1 <= month <= 12:
            return f"{year:04d}-{month:02d}", kind
        return None

    word_match = _MONTH_WORD_PATTERN.fullmatch(candidate)
    if not word_match:
        return None
    month_name, year_text = word_match.groups()
    month = MONTHS.get(month_name.casefold())
    if month is None:
        return None
    year = int(year_text)
    if len(year_text) == 2:
        year += 2000
    return f"{year:04d}-{month:02d}", kind


def _field_candidates(headers: list[str]) -> dict[str, list[str]]:
    return {
        field: [header for header in headers if _normalize_header(header) in aliases]
        for field, aliases in FIELD_ALIASES.items()
    }


def _validate_explicit_month(
    month: object,
    headers: list[str],
    seen_keys: set[str],
    used_headers: dict[str, dict[str, str]],
) -> dict[str, object]:
    if not isinstance(month, dict):
        raise DataContractError("invalid_mapping", "Every explicit month must be an object")
    required = ("key", "label", "stage")
    if any(not isinstance(month.get(field), str) or not month[field] for field in required):
        raise DataContractError(
            "invalid_mapping",
            "Explicit month requires key, label, and stage",
        )

    key = str(month["key"])
    stage = str(month["stage"])
    if key in seen_keys:
        raise DataContractError("duplicate_stage_month", f"ambiguous stage month {key}")
    if not _ISO_MONTH_PATTERN.fullmatch(key) or not 1 <= int(key[-2:]) <= 12:
        raise DataContractError("invalid_mapping", f"Invalid month key: {key}")
    if stage not in headers:
        raise DataContractError("mapping_header_not_found", f"Mapped header not found: {stage}")
    _claim_month_header(used_headers, stage, key, "stage")

    result: dict[str, object] = {"key": key, "label": month["label"], "stage": stage}
    probability = month.get("probability")
    if probability is not None:
        if not isinstance(probability, str) or probability not in headers:
            raise DataContractError(
                "mapping_header_not_found",
                f"Mapped header not found: {probability}",
            )
        _claim_month_header(used_headers, probability, key, "probability")
        result["probability"] = probability
    seen_keys.add(key)
    return result


def _claim_month_header(
    used_headers: dict[str, dict[str, str]],
    header: str,
    key: str,
    role: str,
) -> None:
    use = {"key": key, "role": role}
    if header in used_headers:
        raise DataContractError(
            "invalid_mapping",
            f"reused month header: {header}",
            {"header": header, "first": used_headers[header], "second": use},
        )
    used_headers[header] = use


def resolve_mapping(
    headers: list[str],
    explicit: dict[str, object] | None,
) -> dict[str, object]:
    """Resolve fixed aliases and chronological stage/probability columns."""

    if explicit is not None:
        if not isinstance(explicit, dict):
            raise DataContractError("invalid_mapping", "Explicit mapping must be an object")
        mapping: dict[str, object] = {}
        for field in _FIXED_FIELDS:
            header = explicit.get(field)
            if not isinstance(header, str) or not header:
                raise DataContractError("missing_mapping", f"missing field {field}")
            if header not in headers:
                raise DataContractError(
                    "mapping_header_not_found",
                    f"Mapped header not found: {header}",
                )
            mapping[field] = header
        explicit_months = explicit.get("months")
        if not isinstance(explicit_months, list):
            raise DataContractError("invalid_mapping", "Explicit mapping requires months")
        seen_keys: set[str] = set()
        used_headers: dict[str, dict[str, str]] = {}
        months = [
            _validate_explicit_month(month, headers, seen_keys, used_headers)
            for month in explicit_months
        ]
        mapping["months"] = sorted(months, key=lambda month: str(month["key"]))
        return mapping

    mapping = {}
    for field, candidates in _field_candidates(headers).items():
        if not candidates:
            raise DataContractError(
                "missing_field",
                f"missing field {field}",
                {"field": field},
            )
        if len(candidates) > 1:
            raise DataContractError(
                "ambiguous_field",
                f"ambiguous field {field}",
                {"field": field, "headers": candidates},
            )
        mapping[field] = candidates[0]

    by_month: dict[str, dict[str, list[str]]] = {}
    for header in headers:
        parsed = parse_month_header(header)
        if parsed is None:
            continue
        key, kind = parsed
        by_month.setdefault(key, {"stage": [], "probability": []})[kind].append(header)

    months: list[dict[str, object]] = []
    for key in sorted(by_month):
        stage_headers = by_month[key]["stage"]
        probability_headers = by_month[key]["probability"]
        if len(stage_headers) > 1:
            raise DataContractError(
                "duplicate_stage_month",
                f"ambiguous stage month {key}",
                {"key": key, "headers": stage_headers},
            )
        if len(probability_headers) > 1:
            raise DataContractError(
                "duplicate_probability_month",
                f"ambiguous probability month {key}",
                {"key": key, "headers": probability_headers},
            )
        if probability_headers and not stage_headers:
            raise DataContractError(
                "unpaired_probability_month",
                f"probability month has no stage: {key}",
                {"key": key, "headers": probability_headers},
            )
        if not stage_headers:
            continue
        month: dict[str, object] = {
            "key": key,
            "label": stage_headers[0],
            "stage": stage_headers[0],
        }
        if probability_headers:
            month["probability"] = probability_headers[0]
        months.append(month)
    mapping["months"] = months
    return mapping


def inspect_source(
    path: Path,
    sheet: str | None = None,
    json_key: str | None = None,
) -> dict[str, object]:
    """Return safe source metadata and deterministic mapping candidates."""

    rows, metadata = load_source(path, sheet, json_key)
    headers = list(rows[0])
    month_candidates = []
    for header in headers:
        parsed = parse_month_header(header)
        if parsed is not None:
            key, kind = parsed
            month_candidates.append({"key": key, "label": header, "kind": kind})
    month_candidates.sort(key=lambda month: (str(month["key"]), str(month["kind"])))

    ambiguities: list[dict[str, object]] = []
    mapping: dict[str, object] | None
    try:
        mapping = resolve_mapping(headers, None)
    except DataContractError as error:
        mapping = None
        ambiguities.append(
            {"code": error.code, "message": str(error), "details": error.details}
        )

    return {
        **metadata,
        "headers": headers,
        "field_candidates": _field_candidates(headers),
        "month_candidates": month_candidates,
        "mapping": mapping,
        "ambiguities": ambiguities,
    }
