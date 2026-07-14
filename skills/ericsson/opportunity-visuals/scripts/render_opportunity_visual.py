#!/usr/bin/env python3
"""Render normalized opportunity data as deterministic, local-only SVG pages."""

from __future__ import annotations

import argparse
import json
import math
from dataclasses import dataclass
from numbers import Real
from pathlib import Path
from xml.etree import ElementTree


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

SVG_NS = "http://www.w3.org/2000/svg"
_SVG = f"{{{SVG_NS}}}"
_FIXED_LABELS = {
    "area": "Area",
    "sub_area": "Sub-area",
    "opportunity_name": "Opportunity Name",
    "tcv": "TCV",
    "probability": "Probability",
}


class RenderError(ValueError):
    """A safe renderer contract error suitable for structured CLI output."""

    def __init__(
        self,
        code: str,
        message: str,
        details: dict[str, object] | None = None,
    ):
        super().__init__(message)
        self.code = code
        self.details = details or {}


@dataclass(frozen=True)
class PagePlan:
    number: int
    month_keys: tuple[str, ...]
    row_ids: tuple[str, ...]
    continued_areas: tuple[str, ...]
    horizontal_index: int
    width: int = 1920
    height: int = 1080


def _number(value: float | int) -> str:
    number = float(value)
    if number.is_integer():
        return str(int(number))
    return f"{number:.3f}".rstrip("0").rstrip(".")


def _scale(width: int) -> float:
    return width / 1920


def _require_dimensions(width: object, height: object) -> tuple[int, int]:
    if (
        isinstance(width, bool)
        or isinstance(height, bool)
        or not isinstance(width, int)
        or not isinstance(height, int)
        or width <= 0
        or height <= 0
    ):
        raise RenderError("invalid_dimensions", "Width and height must be positive integers")
    return width, height


def _validate_xml_text(value: str) -> str:
    if any(
        not (
            character in "\t\n\r"
            or "\x20" <= character <= "\ud7ff"
            or "\ue000" <= character <= "\ufffd"
            or "\U00010000" <= character <= "\U0010ffff"
        )
        for character in value
    ):
        raise RenderError("invalid_xml_text", "User value is not valid XML text")
    return value


def _validate_structure(
    document: object,
    *,
    require_records: bool = True,
    validate_render_values: bool = False,
) -> dict[str, object]:
    if not isinstance(document, dict):
        raise RenderError("invalid_document", "Normalized data must be a JSON object")
    if document.get("schema_version") != 1:
        raise RenderError("unsupported_schema", "Normalized schema version must be 1")
    view = document.get("view")
    if view not in VIEW_TITLES:
        raise RenderError("unsupported_view", "Normalized data contains an unsupported view")
    selected_months = document.get("selected_months")
    if not isinstance(selected_months, list) or not selected_months:
        raise RenderError("missing_months", "Normalized data must contain selected months")
    month_keys: list[str] = []
    for selected in selected_months:
        if (
            not isinstance(selected, dict)
            or not isinstance(selected.get("key"), str)
            or not selected["key"]
            or not isinstance(selected.get("label"), str)
        ):
            raise RenderError("invalid_month", "Selected month entries are invalid")
        month_keys.append(selected["key"])
        if validate_render_values:
            _validate_xml_text(selected["key"])
            _validate_xml_text(selected["label"])
    if len(set(month_keys)) != len(month_keys):
        raise RenderError("duplicate_month", "Selected month keys must be unique")

    records = document.get("records")
    if not isinstance(records, list):
        raise RenderError("invalid_records", "Normalized records must be a list")
    if require_records and not records:
        raise RenderError("empty_records", "Normalized records must not be empty")
    row_ids: list[str] = []
    for record in records:
        if not isinstance(record, dict) or not isinstance(record.get("id"), str) or not record["id"]:
            raise RenderError("invalid_record", "Normalized record is invalid")
        if (
            not isinstance(record.get("area"), str)
            or not isinstance(record.get("sub_area"), str)
            or not isinstance(record.get("opportunity_name"), str)
        ):
            raise RenderError("invalid_record", "Normalized record grouping is invalid")
        if not isinstance(record.get("months"), list):
            raise RenderError("invalid_record", "Normalized record months are invalid")
        if validate_render_values:
            for ranked_field in ("tcv", "probability"):
                ranked = record.get(ranked_field)
                if not isinstance(ranked, dict) or not isinstance(ranked.get("display"), str):
                    raise RenderError("invalid_record", "Normalized record values are invalid")
                _validate_xml_text(ranked["display"])
            _validate_xml_text(record["id"])
            _validate_xml_text(record["area"])
            _validate_xml_text(record["sub_area"])
            _validate_xml_text(record["opportunity_name"])
            record_month_keys: list[str] = []
            for month in record["months"]:
                if (
                    not isinstance(month, dict)
                    or not isinstance(month.get("key"), str)
                    or not isinstance(month.get("stage"), str)
                    or not isinstance(month.get("classification"), str)
                ):
                    raise RenderError("invalid_record", "Normalized record months are invalid")
                record_month_keys.append(_validate_xml_text(month["key"]))
                _validate_xml_text(month["stage"])
            if len(set(record_month_keys)) != len(record_month_keys):
                raise RenderError("invalid_record", "Normalized record month keys must be unique")
        row_ids.append(record["id"])
    if len(set(row_ids)) != len(row_ids):
        raise RenderError("duplicate_record", "Normalized record IDs must be unique")
    return document


def _probability_color(record: dict[str, object]) -> str:
    probability = record.get("probability")
    if not isinstance(probability, dict):
        raise RenderError("invalid_probability", "Normalized probability is invalid")
    display = probability.get("display")
    kind = probability.get("kind")
    rank = probability.get("sort")
    if not isinstance(display, str):
        raise RenderError("invalid_probability", "Normalized probability is invalid")
    if kind == "numeric":
        if isinstance(rank, bool) or not isinstance(rank, Real) or not math.isfinite(float(rank)):
            raise RenderError("invalid_probability", "Normalized probability is invalid")
        numeric = float(rank)
        if not 0 <= numeric <= 100:
            raise RenderError(
                "invalid_probability",
                "Numeric probability must be between 0 and 100",
            )
        if numeric < 40:
            return "#E65D6A"
        if numeric < 70:
            return "#A6A6A6"
        return "#23969A"
    if kind != "categorical":
        raise RenderError("invalid_probability", "Normalized probability kind is invalid")
    return PROBABILITY_COLORS.get(display.casefold(), "#A6A6A6")


def paginate(document: dict[str, object], width: int, height: int) -> list[PagePlan]:
    """Plan contiguous horizontal month slices and complete vertical row slices."""

    document = _validate_structure(document)
    width, height = _require_dimensions(width, height)
    scale = _scale(width)
    fixed_width = sum(column_width for _, column_width in FIXED_COLUMNS) * scale
    available_month_width = width - 2 * MARGIN * scale - fixed_width
    minimum_month_width = MIN_MONTH_WIDTH * scale
    months_per_slice = math.floor((available_month_width + 1e-9) / minimum_month_width)
    if months_per_slice < 1:
        raise RenderError("dimensions_too_small", "Page width cannot fit one month column")

    selected_months = document["selected_months"]
    month_slices = [
        tuple(month["key"] for month in selected_months[start : start + months_per_slice])
        for start in range(0, len(selected_months), months_per_slice)
    ]
    records = document["records"]
    content_top = (MARGIN + TITLE_HEIGHT + HEADER_HEIGHT) * scale
    content_bottom = height - (MARGIN + FOOTER_HEIGHT) * scale
    area_height = AREA_HEIGHT * scale
    row_height = ROW_HEIGHT * scale
    if content_top + area_height + row_height > content_bottom + 1e-9:
        raise RenderError("dimensions_too_small", "Page height cannot fit one opportunity row")

    pages: list[PagePlan] = []
    for horizontal_index, month_keys in enumerate(month_slices):
        start = 0
        while start < len(records):
            y = content_top
            row_ids: list[str] = []
            last_area: str | None = None
            continued: tuple[str, ...] = ()
            if start > 0 and records[start - 1]["area"] == records[start]["area"]:
                continued = (str(records[start]["area"]),)

            index = start
            while index < len(records):
                area = str(records[index]["area"])
                required = row_height + (area_height if last_area != area else 0)
                if y + required > content_bottom + 1e-9:
                    break
                if last_area != area:
                    y += area_height
                    last_area = area
                row_ids.append(str(records[index]["id"]))
                y += row_height
                index += 1

            if not row_ids:
                raise RenderError("dimensions_too_small", "Page height cannot fit one opportunity row")
            pages.append(
                PagePlan(
                    number=len(pages) + 1,
                    month_keys=month_keys,
                    row_ids=tuple(row_ids),
                    continued_areas=continued,
                    horizontal_index=horizontal_index,
                    width=width,
                    height=height,
                )
            )
            start = index
    return pages


def ellipsize(value: str, max_width: float, font_size: float = 16) -> str:
    """Return a deterministic single-line approximation that fits the width."""

    if max_width <= 0 or font_size <= 0:
        return "…" if value else value
    max_characters = max(1, math.floor(max_width / (font_size * 0.56)))
    if len(value) <= max_characters:
        return value
    if max_characters == 1:
        return "…"
    return value[: max_characters - 1] + "…"


def add_rect(
    parent: ElementTree.Element,
    x: float,
    y: float,
    width: float,
    height: float,
    *,
    fill: str,
    class_name: str | None = None,
    metadata: dict[str, str] | None = None,
    radius: float | None = None,
) -> ElementTree.Element:
    attributes: dict[str, str] = dict(metadata or {})
    attributes.update(
        {
            "x": _number(x),
            "y": _number(y),
            "width": _number(width),
            "height": _number(height),
            "fill": fill,
        }
    )
    if class_name is not None:
        attributes["class"] = class_name
    if radius is not None:
        attributes["rx"] = _number(radius)
        attributes["ry"] = _number(radius)
    return ElementTree.SubElement(parent, f"{_SVG}rect", attributes)


def add_text(
    parent: ElementTree.Element,
    x: float,
    y: float,
    value: str,
    *,
    class_name: str,
    max_width: float | None = None,
    font_size: float = 16,
    attributes: dict[str, str] | None = None,
) -> ElementTree.Element:
    element_attributes = {
        "x": _number(x),
        "y": _number(y),
        "class": class_name,
        **(attributes or {}),
    }
    displayed = value
    if max_width is not None:
        displayed = ellipsize(value, max_width, font_size)
        if displayed != value:
            element_attributes["data-full-value"] = value
    element = ElementTree.SubElement(parent, f"{_SVG}text", element_attributes)
    element.text = displayed
    return element


def add_line(
    parent: ElementTree.Element,
    x1: float,
    y1: float,
    x2: float,
    y2: float,
    *,
    class_name: str = "grid",
) -> ElementTree.Element:
    return ElementTree.SubElement(
        parent,
        f"{_SVG}line",
        {
            "x1": _number(x1),
            "y1": _number(y1),
            "x2": _number(x2),
            "y2": _number(y2),
            "class": class_name,
        },
    )


def add_stage_pill(
    parent: ElementTree.Element,
    x: float,
    y: float,
    width: float,
    height: float,
    stage: str,
    classification: str,
    *,
    font_size: float,
    opportunity_id: str,
    month_key: str,
) -> ElementTree.Element:
    if classification not in STAGE_COLORS:
        raise RenderError("invalid_classification", "Normalized stage classification is invalid")
    group = ElementTree.SubElement(
        parent,
        f"{_SVG}g",
        {
            "data-opportunity-id": opportunity_id,
            "data-month": month_key,
            "data-classification": classification,
        },
    )
    add_rect(
        group,
        x,
        y,
        width,
        height,
        fill=STAGE_COLORS[classification],
        radius=height / 2,
    )
    add_text(
        group,
        x + width / 2,
        y + height / 2 + font_size * 0.35,
        stage,
        class_name="stage",
        max_width=max(1, width - 16 * (font_size / 16)),
        font_size=font_size,
        attributes={
            "text-anchor": "middle",
            "style": f"font-size:{_number(font_size)}px",
        },
    )
    return group


def _record_lookup(document: dict[str, object], page: PagePlan) -> list[dict[str, object]]:
    by_id = {record["id"]: record for record in document["records"]}
    try:
        return [by_id[row_id] for row_id in page.row_ids]
    except KeyError:
        raise RenderError("invalid_page", "Page references an unknown record") from None


def _month_lookup(document: dict[str, object], page: PagePlan) -> list[dict[str, object]]:
    by_key = {month["key"]: month for month in document["selected_months"]}
    try:
        return [by_key[key] for key in page.month_keys]
    except KeyError:
        raise RenderError("invalid_page", "Page references an unknown month") from None


def _load_template(template_path: Path) -> ElementTree.Element:
    try:
        root = ElementTree.parse(template_path).getroot()
    except (OSError, ElementTree.ParseError):
        raise RenderError("invalid_template", "SVG template is unavailable or invalid") from None
    if root.tag != f"{_SVG}svg":
        raise RenderError("invalid_template", "SVG template root is invalid")
    return root


def render_svg_page(
    document: dict[str, object],
    page: PagePlan,
    template_path: Path,
) -> str:
    """Populate the reviewed XML template using ElementTree-only data insertion."""

    document = _validate_structure(document, validate_render_values=True)
    width, height = _require_dimensions(page.width, page.height)
    records = _record_lookup(document, page)
    selected_months = _month_lookup(document, page)
    for record in records:
        _probability_color(record)

    root = _load_template(Path(template_path))
    root.set("width", str(width))
    root.set("height", str(height))
    root.set("viewBox", f"0 0 {width} {height}")
    title = root.find(f"{_SVG}title")
    description = root.find(f"{_SVG}desc")
    content = root.find(f"{_SVG}g[@id='content']")
    if title is None or description is None or content is None:
        raise RenderError("invalid_template", "SVG template is missing required elements")
    title.text = VIEW_TITLES[str(document["view"])]
    description.text = f"Opportunity stage progression table, page {page.number}"
    content.clear()
    content.set("id", "content")

    scale = _scale(width)
    margin = MARGIN * scale
    title_height = TITLE_HEIGHT * scale
    header_height = HEADER_HEIGHT * scale
    area_height = AREA_HEIGHT * scale
    row_height = ROW_HEIGHT * scale
    footer_height = FOOTER_HEIGHT * scale
    body_font = max(16, 16 * scale) if width >= 1920 else 16 * scale
    header_font = 17 * scale
    stage_font = max(16, 16 * scale) if width >= 1920 else 16 * scale
    fixed_columns = [(key, value * scale) for key, value in FIXED_COLUMNS]
    fixed_width = sum(value for _, value in fixed_columns)
    table_width = width - 2 * margin
    month_width = (table_width - fixed_width) / len(selected_months)

    add_text(
        content,
        margin,
        margin + 34 * scale,
        VIEW_TITLES[str(document["view"])],
        class_name="title",
        max_width=table_width - 180 * scale,
        font_size=30 * scale,
    )
    add_text(
        content,
        width - margin,
        margin + 30 * scale,
        f"Page {page.number}",
        class_name="header",
        font_size=header_font,
        attributes={"text-anchor": "end", "style": f"font-size:{_number(header_font)}px"},
    )

    header_y = margin + title_height
    add_rect(content, margin, header_y, table_width, header_height, fill="#1174E6")
    x = margin
    for key, column_width in fixed_columns:
        add_text(
            content,
            x + 8 * scale,
            header_y + header_height / 2 + header_font * 0.35,
            _FIXED_LABELS[key],
            class_name="header",
            max_width=column_width - 16 * scale,
            font_size=header_font,
            attributes={"fill": "#FFFFFF", "style": f"font-size:{_number(header_font)}px;fill:#FFFFFF"},
        )
        x += column_width
    for selected in selected_months:
        add_text(
            content,
            x + month_width / 2,
            header_y + header_height / 2 + header_font * 0.35,
            str(selected["label"]),
            class_name="header",
            max_width=month_width - 12 * scale,
            font_size=header_font,
            attributes={
                "text-anchor": "middle",
                "fill": "#FFFFFF",
                "style": f"font-size:{_number(header_font)}px;fill:#FFFFFF",
            },
        )
        x += month_width

    y = header_y + header_height
    last_area: str | None = None
    for record in records:
        area = str(record["area"])
        if area != last_area:
            add_rect(
                content,
                margin,
                y,
                table_width,
                area_height,
                fill="#F2F2F2",
                class_name="grid",
                metadata={"data-area": area},
            )
            continuation = " (continued)" if area in page.continued_areas else ""
            add_text(
                content,
                margin + 8 * scale,
                y + area_height / 2 + body_font * 0.35,
                f"Area: {area}{continuation}",
                class_name="body",
                max_width=table_width - 16 * scale,
                font_size=body_font,
                attributes={"style": f"font-size:{_number(body_font)}px;font-weight:600"},
            )
            y += area_height
            last_area = area

        row_group = ElementTree.SubElement(
            content,
            f"{_SVG}g",
            {
                "data-opportunity-id": str(record["id"]),
                "data-area": area,
                "data-sub-area": str(record["sub_area"]),
            },
        )
        x = margin
        fixed_values = {
            "area": area,
            "sub_area": str(record["sub_area"]),
            "opportunity_name": str(record["opportunity_name"]),
            "tcv": str(record["tcv"]["display"]),
            "probability": str(record["probability"]["display"]),
        }
        for key, column_width in fixed_columns:
            add_rect(row_group, x, y, column_width, row_height, fill="#FFFFFF", class_name="grid")
            text_x = x + 8 * scale
            if key == "probability":
                ElementTree.SubElement(
                    row_group,
                    f"{_SVG}circle",
                    {
                        "class": "probability-bullet",
                        "fill": _probability_color(record),
                        "cx": _number(x + 12 * scale),
                        "cy": _number(y + row_height / 2),
                        "r": _number(4 * scale),
                    },
                )
                text_x = x + 22 * scale
            add_text(
                row_group,
                text_x,
                y + row_height / 2 + body_font * 0.35,
                fixed_values[key],
                class_name="body",
                max_width=column_width - (30 if key == "probability" else 16) * scale,
                font_size=body_font,
                attributes={"style": f"font-size:{_number(body_font)}px"},
            )
            x += column_width

        record_months = {
            entry["key"]: entry for entry in record["months"] if isinstance(entry, dict)
        }
        for selected in selected_months:
            key = str(selected["key"])
            entry = record_months.get(key)
            metadata = None
            if entry is not None and not str(entry.get("stage", "")).strip():
                metadata = {
                    "data-opportunity-id": str(record["id"]),
                    "data-month": key,
                    "data-empty": "true",
                }
            add_rect(
                row_group,
                x,
                y,
                month_width,
                row_height,
                fill="#FFFFFF",
                class_name="grid",
                metadata=metadata,
            )
            if entry is not None and str(entry.get("stage", "")).strip():
                inset_x = 6 * scale
                inset_y = 7 * scale
                add_stage_pill(
                    row_group,
                    x + inset_x,
                    y + inset_y,
                    month_width - 2 * inset_x,
                    row_height - 2 * inset_y,
                    str(entry["stage"]),
                    str(entry.get("classification", "")),
                    font_size=stage_font,
                    opportunity_id=str(record["id"]),
                    month_key=key,
                )
            x += month_width
        y += row_height

    footer_y = height - margin - footer_height / 2
    add_line(content, margin, footer_y - 10 * scale, width - margin, footer_y - 10 * scale)
    add_text(
        content,
        width - margin,
        footer_y + body_font * 0.35,
        f"Page {page.number} · Month set {page.horizontal_index + 1}",
        class_name="body",
        font_size=body_font,
        attributes={"text-anchor": "end", "style": f"font-size:{_number(body_font)}px"},
    )

    ElementTree.register_namespace("", SVG_NS)
    serialized = ElementTree.tostring(root, encoding="unicode", short_empty_elements=True)
    return '<?xml version="1.0" encoding="UTF-8"?>\n' + serialized + "\n"


def atomic_write_text(path: Path, text: str) -> None:
    """Write through a sibling temporary file without replacing existing output."""

    path = Path(path)
    temporary = path.with_name(f".{path.name}.tmp")
    if path.exists() or path.is_symlink() or temporary.exists() or temporary.is_symlink():
        raise RenderError("output_exists", "Output artifact already exists")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            handle.write(text)
        temporary.replace(path)
    finally:
        if temporary.exists() or temporary.is_symlink():
            try:
                temporary.unlink()
            except OSError:
                pass


def _load_document(path: Path) -> dict[str, object]:
    try:
        document = json.loads(Path(path).read_text(encoding="utf-8"))
    except FileNotFoundError:
        raise RenderError("input_not_found", "Normalized data file was not found") from None
    except (OSError, UnicodeDecodeError):
        raise RenderError("input_unreadable", "Normalized data file could not be read") from None
    except json.JSONDecodeError:
        raise RenderError("invalid_json", "Normalized data JSON is malformed") from None
    return _validate_structure(document, validate_render_values=True)


def _write_svg_pages(
    document: dict[str, object],
    output_dir: Path,
    width: int,
    height: int,
    template_path: Path,
) -> list[str]:
    pages = paginate(document, width, height)
    names = [f"opportunity-visual-p{page.number:02d}.svg" for page in pages]
    output_dir = Path(output_dir)
    if output_dir.is_symlink():
        raise RenderError("output_exists", "Output destination already exists")
    if output_dir.exists() and not output_dir.is_dir():
        raise RenderError("output_exists", "Output destination already exists")
    for name in names:
        target = output_dir / name
        temporary = target.with_name(f".{target.name}.tmp")
        if target.exists() or target.is_symlink() or temporary.exists() or temporary.is_symlink():
            raise RenderError("output_exists", "Output artifact already exists")

    svg_pages = [render_svg_page(document, page, template_path) for page in pages]
    created_directory = not output_dir.exists()
    written: list[Path] = []
    try:
        output_dir.mkdir(parents=True, exist_ok=True)
        for name, svg in zip(names, svg_pages, strict=True):
            target = output_dir / name
            atomic_write_text(target, svg)
            written.append(target)
    except RenderError:
        for target in written:
            try:
                target.unlink()
            except OSError:
                pass
        if created_directory:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        raise
    except OSError:
        for target in written:
            try:
                target.unlink()
            except OSError:
                pass
        for target in (output_dir / name for name in names):
            temporary = target.with_name(f".{target.name}.tmp")
            try:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
            except OSError:
                pass
        if created_directory:
            try:
                output_dir.rmdir()
            except OSError:
                pass
        raise RenderError("output_unwritable", "Unable to write SVG artifacts") from None
    return names


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="render_opportunity_visual.py")
    parser.add_argument("normalized_data", type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--width", type=int, default=1920)
    parser.add_argument("--height", type=int, default=1080)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        document = _load_document(args.normalized_data)
        template = Path(__file__).resolve().parents[1] / "templates/opportunity-visual.svg"
        names = _write_svg_pages(
            document,
            args.output_dir,
            args.width,
            args.height,
            template,
        )
        print(
            json.dumps(
                {"ok": True, "pages": len(names), "files": names},
                separators=(",", ":"),
            )
        )
        return 0
    except RenderError as error:
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
    except OSError:
        print(
            json.dumps(
                {
                    "ok": False,
                    "error": {
                        "code": "output_unwritable",
                        "message": "Unable to write SVG artifacts",
                        "details": {},
                    },
                },
                separators=(",", ":"),
            )
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
