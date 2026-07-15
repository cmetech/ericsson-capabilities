import hashlib
import json
import os
import subprocess
import sys
from collections import Counter, defaultdict
from copy import deepcopy
from html.parser import HTMLParser
from pathlib import Path
from unittest.mock import Mock
from xml.etree import ElementTree

import pytest
from openpyxl import Workbook


REPO = Path(__file__).resolve().parents[1]
SKILL_DIR = REPO / "skills/ericsson/opportunity-visuals"
SCRIPTS = SKILL_DIR / "scripts"
TEMPLATE = SKILL_DIR / "templates/opportunity-visual.svg"
sys.path.insert(0, str(SCRIPTS))

import render_opportunity_visual as renderer  # noqa: E402
from prepare_opportunities import prepare  # noqa: E402
from render_opportunity_visual import (  # noqa: E402
    RasterUnavailable,
    RenderError,
    atomic_write_text,
    paginate,
    preflight,
    rasterize_html,
    render_document,
    render_svg_page,
    write_html,
    write_render_manifest,
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
        "source": {"basename": "showcase.json", "sha256": "a" * 64},
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


@pytest.mark.parametrize(
    ("width", "height", "title_font", "header_font", "body_font", "stage_font", "pill_height"),
    [
        (960, 540, "15", "8.5", "8", "8", "16"),
        (3840, 2160, "60", "34", "32", "32", "64"),
    ],
)
def test_entire_svg_frame_and_typography_scale_with_page(
    normalized_document,
    width,
    height,
    title_font,
    header_font,
    body_font,
    stage_font,
    pill_height,
):
    page = paginate(normalized_document, width, height)[0]
    svg = render_svg_page(normalized_document, page, TEMPLATE)
    root = ElementTree.fromstring(svg)
    namespace = {"svg": "http://www.w3.org/2000/svg"}
    background = root.find("svg:rect[@id='background']", namespace)
    visible_title = root.find(".//svg:g[@id='content']/svg:text[@class='title']", namespace)
    stage_text = root.find(".//svg:text[@class='stage']", namespace)
    stage_pill = root.find(".//svg:g[@data-classification='initial']/svg:rect", namespace)

    assert root.attrib == {
        "width": str(width),
        "height": str(height),
        "viewBox": f"0 0 {width} {height}",
        "role": "img",
        "aria-labelledby": "title desc",
    }
    assert background is not None
    assert background.attrib["width"] == str(width)
    assert background.attrib["height"] == str(height)
    assert visible_title is not None
    assert visible_title.attrib["style"] == f"font-size:{title_font}px"
    assert f'style="font-size:{header_font}px;fill:#FFFFFF"' in svg
    assert f'style="font-size:{body_font}px"' in svg
    assert stage_text is not None
    assert stage_text.attrib["style"] == f"font-size:{stage_font}px"
    assert stage_pill is not None
    assert stage_pill.attrib["height"] == pill_height


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


def test_atomic_write_text_cannot_overwrite_target_created_during_publish(
    tmp_path, monkeypatch
):
    output = tmp_path / "page.svg"
    real_link = os.link

    def competing_publish(source, target):
        Path(target).write_text("competitor\n", encoding="utf-8")
        return real_link(source, target)

    monkeypatch.setattr(os, "link", competing_publish)

    with pytest.raises(RenderError, match="already exists"):
        atomic_write_text(output, "renderer\n")
    assert output.read_text(encoding="utf-8") == "competitor\n"
    assert not (tmp_path / ".page.svg.tmp").exists()


def test_html_is_self_contained(tmp_path, normalized_document):
    page = paginate(normalized_document, 1920, 1080)[0]
    svg_text = render_svg_page(normalized_document, page, TEMPLATE)
    output = tmp_path / "page.html"

    write_html(svg_text, output)

    html = output.read_text(encoding="utf-8")
    canonical_svg = ElementTree.tostring(
        ElementTree.fromstring(svg_text), encoding="unicode"
    )
    assert canonical_svg in html
    assert "<script" not in html.lower()
    assert "https://" not in html
    assert html.count("http://") == 1
    assert 'xmlns="http://www.w3.org/2000/svg"' in html
    assert 'href="http' not in html and 'href="https' not in html
    assert "iframe" not in html.lower()
    assert not (tmp_path / ".page.html.tmp").exists()


class _TagCollector(HTMLParser):
    def __init__(self):
        super().__init__()
        self.tags = []
        self.remote_values = []

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag.casefold())
        self.remote_values.extend(
            value for _, value in attrs if value and "https://" in value.casefold()
        )


@pytest.mark.parametrize(
    ("svg_text", "active_tag"),
    [
        (
            '<?before ><script src="https://example.test/x.js"></script>?>'
            '<svg xmlns="http://www.w3.org/2000/svg"/>',
            "script",
        ),
        (
            '<svg xmlns="http://www.w3.org/2000/svg"/>'
            '<?after ><iframe src="https://example.test/frame"></iframe>?>',
            "iframe",
        ),
        (
            '<?before ><img src="https://example.test/pixel.png">?>'
            '<svg xmlns="http://www.w3.org/2000/svg"/>',
            "img",
        ),
    ],
)
def test_html_canonicalizes_away_processing_instruction_breakouts(
    tmp_path, svg_text, active_tag
):
    output = tmp_path / "page.html"

    write_html(svg_text, output)

    html = output.read_text(encoding="utf-8")
    parser = _TagCollector()
    parser.feed(html)
    assert active_tag not in parser.tags
    assert parser.remote_values == []
    assert "https://example.test" not in html
    assert "<?before" not in html and "<?after" not in html


def test_html_rejects_doctype_and_strips_xml_comments(tmp_path):
    with pytest.raises(RenderError, match="safe local SVG"):
        write_html(
            '<!DOCTYPE svg><svg xmlns="http://www.w3.org/2000/svg"/>',
            tmp_path / "doctype.html",
        )

    output = tmp_path / "comment.html"
    write_html(
        '<svg xmlns="http://www.w3.org/2000/svg"><!-- untrusted comment --><rect /></svg>',
        output,
    )
    assert "untrusted comment" not in output.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "unsafe_svg",
    [
        '<svg xmlns="http://www.w3.org/2000/svg"><script>bad()</script></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><iframe /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><image href="data:image/png;base64,AA" /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><foreignObject /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><use href="#shape" /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><a href="#shape" /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect onclick="bad()" /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect fill="url(https://example.test/x)" /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect data-x="javascript:bad()" /></svg>',
        '<svg xmlns="http://www.w3.org/2000/svg"><rect data-x="//example.test/x" /></svg>',
    ],
)
def test_html_rejects_network_capable_or_executable_svg(tmp_path, unsafe_svg):
    with pytest.raises(RenderError, match="safe local SVG"):
        write_html(unsafe_svg, tmp_path / "page.html")
    assert list(tmp_path.iterdir()) == []


def test_html_accepts_fragment_only_attribute_reference(tmp_path):
    svg = (
        '<svg xmlns="http://www.w3.org/2000/svg">'
        '<defs><linearGradient id="local" /></defs>'
        '<rect fill="url(#local)" />'
        "</svg>"
    )
    output = tmp_path / "page.html"

    write_html(svg, output)

    assert "url(#local)" in output.read_text(encoding="utf-8")


class _FakeRoute:
    def __init__(self, url):
        self.request = type("Request", (), {"url": url})()
        self.action = None

    def continue_(self):
        self.action = "continue"

    def abort(self):
        self.action = "abort"


class _FakeLocator:
    def __init__(self, calls):
        self.calls = calls

    def screenshot(self, *, path):
        self.calls["screenshot"] = path
        Path(path).write_bytes(b"fake-png")


class _FakePage:
    def __init__(self, calls):
        self.calls = calls

    def route(self, pattern, handler):
        self.calls["route"] = pattern
        self.calls["handler"] = handler

    def goto(self, url, *, wait_until):
        self.calls["goto"] = (url, wait_until)

    def locator(self, selector):
        self.calls["locator"] = selector
        return _FakeLocator(self.calls)


class _FakeBrowser:
    def __init__(self, calls):
        self.calls = calls

    def new_page(self, *, viewport):
        self.calls["viewport"] = viewport
        return _FakePage(self.calls)

    def close(self):
        self.calls["closed"] = True


class _FakePlaywright:
    def __init__(self, calls):
        self.calls = calls
        self.chromium = self

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return None

    def launch(self, *, headless):
        self.calls["headless"] = headless
        return _FakeBrowser(self.calls)


def test_rasterize_uses_exact_viewport_local_uri_and_denies_network(tmp_path):
    html_path = tmp_path / "page.html"
    html_path.write_text("<html><body>local</body></html>", encoding="utf-8")
    png_path = tmp_path / "page.png"
    calls = {}

    rasterize_html(
        html_path,
        png_path,
        1234,
        678,
        playwright_factory=lambda: _FakePlaywright(calls),
    )

    https_route = _FakeRoute("https://example.test/secret")
    file_route = _FakeRoute(html_path.resolve().as_uri())
    calls["handler"](https_route)
    calls["handler"](file_route)
    assert calls["route"] == "**/*"
    assert https_route.action == "abort"
    assert file_route.action == "continue"
    assert calls["viewport"] == {"width": 1234, "height": 678}
    assert calls["goto"] == (html_path.resolve().as_uri(), "load")
    assert calls["locator"] == "body"
    assert calls["screenshot"] == str(png_path)
    assert calls["headless"] is True
    assert calls["closed"] is True
    assert png_path.read_bytes() == b"fake-png"


def test_rasterize_reports_generic_unavailability_without_raw_exception(tmp_path):
    class BrokenPlaywright:
        def __enter__(self):
            raise RasterUnavailable("sensitive /private/source and bearer token")

        def __exit__(self, *args):
            return None

    with pytest.raises(RasterUnavailable) as caught:
        rasterize_html(
            tmp_path / "page.html",
            tmp_path / "page.png",
            1920,
            1080,
            playwright_factory=BrokenPlaywright,
        )
    assert str(caught.value) == "Install playwright>=1.52 and Chromium to enable PNG output"


def test_preflight_reports_independent_capabilities_and_removes_probe(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, "_module_available", lambda name: name == "openpyxl")
    monkeypatch.setattr(
        renderer,
        "_probe_chromium",
        lambda: {"status": "unavailable", "reason": "Chromium is unavailable"},
    )
    before = set(tmp_path.iterdir())

    result = preflight(tmp_path)

    assert set(result) == {
        "csv_json",
        "xlsx",
        "svg_html",
        "png_package",
        "chromium",
        "output_directory",
    }
    assert result["csv_json"]["status"] == "available"
    assert result["xlsx"]["status"] == "available"
    assert result["svg_html"]["status"] == "available"
    assert result["png_package"]["status"] == "unavailable"
    assert result["chromium"] == {
        "status": "unavailable",
        "reason": "Chromium is unavailable",
    }
    assert result["output_directory"]["status"] == "available"
    assert set(tmp_path.iterdir()) == before


def test_preflight_keeps_package_and_chromium_statuses_independent(tmp_path, monkeypatch):
    monkeypatch.setattr(renderer, "_module_available", lambda name: True)
    monkeypatch.setattr(
        renderer,
        "_probe_chromium",
        lambda: {"status": "available", "reason": ""},
    )
    monkeypatch.setattr(
        renderer,
        "_probe_output_directory",
        lambda output_dir: {"status": "unavailable", "reason": "Output directory is not writable"},
    )

    result = preflight(tmp_path)

    assert result["png_package"]["status"] == "available"
    assert result["chromium"]["status"] == "available"
    assert result["output_directory"]["status"] == "unavailable"


def test_preflight_accepts_nested_nonexistent_destination_without_residue(tmp_path):
    output_dir = tmp_path / "one" / "two" / "rendered"
    before = set(tmp_path.iterdir())

    result = preflight(output_dir)

    assert result["output_directory"] == {"status": "available", "reason": ""}
    assert not output_dir.exists()
    assert set(tmp_path.iterdir()) == before


def test_preflight_follows_directory_symlink_ancestor_without_residue(tmp_path):
    real_parent = tmp_path / "real-parent"
    real_parent.mkdir()
    linked_parent = tmp_path / "linked-parent"
    linked_parent.symlink_to(real_parent, target_is_directory=True)
    output_dir = linked_parent / "nested" / "rendered"
    before = set(real_parent.iterdir())

    result = preflight(output_dir)

    assert result["output_directory"] == {"status": "available", "reason": ""}
    assert not output_dir.exists()
    assert set(real_parent.iterdir()) == before


def test_preflight_rejects_requested_output_path_symlink(tmp_path):
    real_output = tmp_path / "real-output"
    real_output.mkdir()
    output_dir = tmp_path / "rendered"
    output_dir.symlink_to(real_output, target_is_directory=True)

    result = preflight(output_dir)

    assert result["output_directory"] == {
        "status": "unavailable",
        "reason": "Output directory is not writable",
    }
    assert list(real_output.iterdir()) == []


@pytest.mark.parametrize("kind", ["broken", "loop"])
def test_preflight_rejects_unusable_symlink_ancestor_without_residue(tmp_path, kind):
    linked_parent = tmp_path / "linked-parent"
    if kind == "broken":
        linked_parent.symlink_to(tmp_path / "missing-target", target_is_directory=True)
    else:
        other = tmp_path / "other-link"
        linked_parent.symlink_to(other, target_is_directory=True)
        other.symlink_to(linked_parent, target_is_directory=True)
    before = set(tmp_path.iterdir())

    result = preflight(linked_parent / "nested" / "rendered")

    assert result["output_directory"] == {
        "status": "unavailable",
        "reason": "Output directory is not writable",
    }
    assert set(tmp_path.iterdir()) == before


def test_preflight_unwritable_probe_failure_leaves_no_residue(tmp_path, monkeypatch):
    monkeypatch.setattr(
        renderer.tempfile,
        "mkdtemp",
        Mock(side_effect=PermissionError("private path")),
    )
    before = set(tmp_path.iterdir())

    result = renderer._probe_output_directory(tmp_path / "nested" / "rendered")

    assert result == {
        "status": "unavailable",
        "reason": "Output directory is not writable",
    }
    assert set(tmp_path.iterdir()) == before


def test_preflight_cleans_probe_if_descriptor_close_reports_failure(
    tmp_path, monkeypatch
):
    real_close = os.close

    def close_then_fail(descriptor):
        real_close(descriptor)
        raise OSError("private close detail")

    monkeypatch.setattr(os, "close", close_then_fail)
    before = set(tmp_path.iterdir())

    result = renderer._probe_output_directory(tmp_path / "nested" / "rendered")

    assert result["status"] == "unavailable"
    assert set(tmp_path.iterdir()) == before


def test_preflight_handles_real_name_too_long_with_complete_safe_statuses(tmp_path):
    output_dir = tmp_path / ("x" * 5000)
    expected_keys = {
        "csv_json",
        "xlsx",
        "svg_html",
        "png_package",
        "chromium",
        "output_directory",
    }
    before = set(tmp_path.iterdir())

    direct = preflight(output_dir)
    command = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_opportunity_visual.py"),
            "--preflight",
            "--output-dir",
            str(output_dir),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert set(direct) == expected_keys
    assert direct["output_directory"] == {
        "status": "unavailable",
        "reason": "Output directory is not writable",
    }
    assert command.returncode == 0
    assert command.stderr == ""
    assert command.stdout.count("\n") == 1
    payload = json.loads(command.stdout)
    assert payload["ok"] is True
    assert set(payload["preflight"]) == expected_keys
    assert payload["preflight"]["output_directory"] == direct["output_directory"]
    assert str(output_dir) not in command.stdout
    assert set(tmp_path.iterdir()) == before


def test_preflight_handles_permission_denied_path_metadata_without_raising(
    tmp_path, monkeypatch
):
    output_dir = tmp_path / "denied" / "rendered"
    real_lstat = Path.lstat

    def permission_denied_stat(path):
        if path == output_dir:
            raise PermissionError("secret /private/denied")
        return real_lstat(path)

    monkeypatch.setattr(Path, "lstat", permission_denied_stat)
    monkeypatch.setattr(renderer, "_module_available", lambda name: False)
    monkeypatch.setattr(
        renderer,
        "_probe_chromium",
        lambda: {"status": "unavailable", "reason": "Chromium is unavailable"},
    )

    result = preflight(output_dir)

    assert set(result) == {
        "csv_json",
        "xlsx",
        "svg_html",
        "png_package",
        "chromium",
        "output_directory",
    }
    assert result["output_directory"] == {
        "status": "unavailable",
        "reason": "Output directory is not writable",
    }
    assert not (tmp_path / "denied").is_dir()


def _write_normalized(tmp_path, document):
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(document), encoding="utf-8")
    return normalized_path


def test_png_auto_falls_back_without_failing_svg_html(
    tmp_path, normalized_document, monkeypatch
):
    normalized_path = _write_normalized(tmp_path, normalized_document)

    def unavailable(*args, **kwargs):
        raise RasterUnavailable("sensitive missing binary detail")

    monkeypatch.setattr(renderer, "rasterize_html", unavailable)
    output_dir = tmp_path / "rendered"

    result = render_document(normalized_path, output_dir, png_mode="auto")

    assert result["ok"] is True
    assert result["png"] == {
        "status": "unavailable",
        "reason": "Install playwright>=1.52 and Chromium to enable PNG output",
    }
    assert list(output_dir.glob("*.svg"))
    assert list(output_dir.glob("*.html"))
    assert not list(output_dir.glob("*.png"))
    assert (output_dir / "render-manifest.json").is_file()
    assert "sensitive missing binary detail" not in (output_dir / "render-manifest.json").read_text()


def test_png_auto_removes_earlier_png_if_later_page_is_unavailable(
    tmp_path, normalized_document, monkeypatch
):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    normalized_path = _write_normalized(tmp_path, document)
    calls = 0

    def unavailable_on_second(html_path, png_path, width, height, playwright_factory=None):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise RasterUnavailable("missing")
        Path(png_path).write_bytes(b"first-png")

    monkeypatch.setattr(renderer, "rasterize_html", unavailable_on_second)
    output_dir = tmp_path / "rendered"

    result = render_document(
        normalized_path,
        output_dir,
        width=960,
        height=540,
        png_mode="auto",
    )

    assert result["ok"] is True
    assert result["png"]["status"] == "unavailable"
    assert len(list(output_dir.glob("*.svg"))) == 2
    assert len(list(output_dir.glob("*.html"))) == 2
    assert not list(output_dir.glob("*.png"))
    assert not list(output_dir.glob(".*.tmp"))


def test_png_required_uses_safe_error_and_leaves_no_partial_artifacts(
    tmp_path, normalized_document, monkeypatch
):
    normalized_path = _write_normalized(tmp_path, normalized_document)
    monkeypatch.setattr(
        renderer,
        "rasterize_html",
        Mock(side_effect=RasterUnavailable("sensitive /private/source")),
    )
    output_dir = tmp_path / "rendered"

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, output_dir, png_mode="required")

    assert caught.value.code == "png_unavailable"
    assert str(caught.value) == "Install playwright>=1.52 and Chromium for required PNG output"
    assert "/private/source" not in str(caught.value)
    assert not output_dir.exists() or list(output_dir.iterdir()) == []


def test_png_never_does_not_invoke_rasterizer(tmp_path, normalized_document, monkeypatch):
    normalized_path = _write_normalized(tmp_path, normalized_document)
    rasterizer = Mock(side_effect=AssertionError("must not be called"))
    monkeypatch.setattr(renderer, "rasterize_html", rasterizer)

    result = render_document(normalized_path, tmp_path / "rendered", png_mode="never")

    assert result["png"] == {"status": "disabled", "reason": "PNG output disabled"}
    assert all(page["png"] is None for page in result["pages"])
    rasterizer.assert_not_called()


def test_manifest_contains_complete_deterministic_audit_without_source_path(
    tmp_path, normalized_document
):
    normalized_document["source"] = {
        "basename": "showcase.json",
        "sha256": "a" * 64,
        "path": "/private/confidential/showcase.json",
        "sheet": "Pipeline",
    }
    normalized_document["mapping"] = {"area": "Area"}
    normalized_document["filters"] = {"areas": ["Core Group"]}
    normalized_document["exclusions"] = [
        {
            "id": "OV-X",
            "source_row": 99,
            "code": "view_not_matched",
            "message": "Row does not match view",
        }
    ]
    normalized_document["warnings"] = [
        {
            "id": "OV-008",
            "source_row": 4,
            "code": "unknown_transition",
            "message": "Transition stage order is unknown",
            "month": "2026-04",
        }
    ]
    normalized_path = _write_normalized(tmp_path, normalized_document)
    output_dir = tmp_path / "rendered"

    result = render_document(normalized_path, output_dir, png_mode="never")
    manifest_path = Path(result["manifest"])
    manifest_text = manifest_path.read_text(encoding="utf-8")
    manifest = json.loads(manifest_text)

    expected_semantics_hash = hashlib.sha256(
        json.dumps({}, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    assert manifest["renderer_version"] == 1
    assert manifest["view"] == "all-progression"
    assert manifest["range"] == {
        "start": "2026-03",
        "end": "2026-06",
        "months": MONTHS,
    }
    assert manifest["mapping"] == {"area": "Area"}
    assert manifest["filters"] == {"areas": ["Core Group"]}
    assert manifest["dimensions"] == {"width": 1920, "height": 1080}
    assert manifest["semantics_sha256"] == expected_semantics_hash
    assert manifest["source"] == {
        "basename": "showcase.json",
        "sha256": "a" * 64,
        "sheet": "Pipeline",
    }
    assert manifest["included_rows"] == [
        {"id": record["id"], "source_row": record["source_row"]}
        for record in normalized_document["records"]
    ]
    assert manifest["excluded_rows"] == [
        {"id": "OV-X", "source_row": 99, "code": "view_not_matched"}
    ]
    assert manifest["warnings"][0]["code"] == "unknown_transition"
    transition = next(item for item in manifest["transitions"] if item["id"] == "OV-008")
    assert transition["months"][1] == {
        "key": "2026-04",
        "classification": "positive",
        "skipped_months": [],
    }
    assert transition["warning_codes"] == []
    assert manifest["png"] == {"status": "disabled", "reason": "PNG output disabled"}
    assert manifest["pages"][0]["row_ids"] == [
        record["id"] for record in normalized_document["records"]
    ]
    assert manifest["pages"][0]["month_keys"] == [item["key"] for item in MONTHS]
    assert manifest["pages"][0]["dimensions"] == {"width": 1920, "height": 1080}
    assert manifest["pages"][0]["files"]["png"] is None
    for kind in ("svg", "html"):
        artifact = output_dir / manifest["pages"][0]["files"][kind]
        assert manifest["pages"][0]["sha256"][kind] == hashlib.sha256(
            artifact.read_bytes()
        ).hexdigest()
    assert manifest["pages"][0]["sha256"]["png"] is None
    assert "render-manifest.json" not in json.dumps(manifest["pages"])
    assert "/private/confidential" not in manifest_text
    assert "timestamp" not in manifest
    assert manifest_text == json.dumps(manifest, indent=2, sort_keys=True) + "\n"
    second = render_document(
        normalized_path,
        tmp_path / "rendered-again",
        png_mode="never",
    )
    assert Path(second["manifest"]).read_bytes() == manifest_path.read_bytes()


@pytest.mark.parametrize(
    "basename",
    ["/private/confidential/showcase.json", r"C:\\private\\showcase.json"],
)
def test_manifest_rejects_source_metadata_disguised_as_a_basename(
    tmp_path, normalized_document, basename
):
    normalized_document["source"]["basename"] = basename
    normalized_path = _write_normalized(tmp_path, normalized_document)

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, tmp_path / "rendered", png_mode="never")

    assert caught.value.code == "invalid_document"
    assert basename not in str(caught.value)
    assert not (tmp_path / "rendered").exists()


def test_manifest_rejects_path_like_sheet_metadata(tmp_path, normalized_document):
    normalized_document["source"]["sheet"] = "/private/confidential/Pipeline"
    normalized_path = _write_normalized(tmp_path, normalized_document)

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, tmp_path / "rendered", png_mode="never")

    assert caught.value.code == "invalid_document"
    assert "/private/confidential" not in str(caught.value)
    assert not (tmp_path / "rendered").exists()


def test_manifest_requires_auditable_integer_source_rows(tmp_path, normalized_document):
    del normalized_document["records"][0]["source_row"]
    normalized_path = _write_normalized(tmp_path, normalized_document)

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, tmp_path / "rendered", png_mode="never")

    assert caught.value.code == "invalid_record"
    assert not (tmp_path / "rendered").exists()


def test_write_render_manifest_refuses_to_hash_or_overwrite_itself(
    tmp_path, normalized_document
):
    page = paginate(normalized_document, 1920, 1080)[0]
    svg = tmp_path / "opportunity-visual-p01.svg"
    html = tmp_path / "opportunity-visual-p01.html"
    svg.write_text("svg", encoding="utf-8")
    html.write_text("html", encoding="utf-8")
    artifacts = [{"page": 1, "svg": svg, "html": html, "png": None}]
    png_status = {"status": "disabled", "reason": "PNG output disabled"}

    manifest_path = write_render_manifest(
        normalized_document,
        [page],
        artifacts,
        tmp_path,
        1920,
        1080,
        png_status,
    )

    assert manifest_path == tmp_path / "render-manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert "render-manifest.json" not in json.dumps(manifest["pages"])
    with pytest.raises(RenderError, match="already exists"):
        write_render_manifest(
            normalized_document,
            [page],
            artifacts,
            tmp_path,
            1920,
            1080,
            png_status,
        )


def test_write_render_manifest_ignores_caller_supplied_digest_keys(
    tmp_path, normalized_document
):
    page = paginate(normalized_document, 1920, 1080)[0]
    svg = tmp_path / "opportunity-visual-p01.svg"
    html = tmp_path / "opportunity-visual-p01.html"
    png = tmp_path / "opportunity-visual-p01.png"
    svg.write_bytes(b"actual-svg")
    html.write_bytes(b"actual-html")
    png.write_bytes(b"actual-png")
    artifacts = [
        {
            "page": 1,
            "svg": svg,
            "html": html,
            "png": png,
            "svg_sha256": "0" * 64,
            "html_sha256": "1" * 64,
            "png_sha256": "0" * 64,
        }
    ]

    manifest_path = write_render_manifest(
        normalized_document,
        [page],
        artifacts,
        tmp_path,
        1920,
        1080,
        {"status": "available", "reason": ""},
    )

    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["pages"][0]["sha256"] == {
        "svg": hashlib.sha256(svg.read_bytes()).hexdigest(),
        "html": hashlib.sha256(html.read_bytes()).hexdigest(),
        "png": hashlib.sha256(png.read_bytes()).hexdigest(),
    }


def test_render_document_refuses_any_planned_artifact_without_writing_others(
    tmp_path, normalized_document
):
    normalized_path = _write_normalized(tmp_path, normalized_document)
    output_dir = tmp_path / "rendered"
    output_dir.mkdir()
    existing = output_dir / "opportunity-visual-p01.html"
    existing.write_text("competitor", encoding="utf-8")

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, output_dir, png_mode="never")

    assert caught.value.code == "output_exists"
    assert existing.read_text(encoding="utf-8") == "competitor"
    assert list(output_dir.iterdir()) == [existing]


def test_manifest_collision_rolls_back_owned_outputs_and_preserves_competitors(
    tmp_path, normalized_document, monkeypatch
):
    normalized_path = _write_normalized(tmp_path, normalized_document)
    output_dir = tmp_path / "rendered"
    real_link = os.link
    calls = 0

    def competitors_replace_html_and_claim_manifest(source, target, **kwargs):
        nonlocal calls
        calls += 1
        target = Path(target)
        if calls == 3:
            html = output_dir / "opportunity-visual-p01.html"
            html.unlink()
            html.write_text("competitor-html\n", encoding="utf-8")
            target.write_text("competitor-manifest\n", encoding="utf-8")
        return real_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", competitors_replace_html_and_claim_manifest)

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, output_dir, png_mode="never")

    assert caught.value.code == "output_exists"
    assert not (output_dir / "opportunity-visual-p01.svg").exists()
    assert (output_dir / "opportunity-visual-p01.html").read_text() == "competitor-html\n"
    assert (output_dir / "render-manifest.json").read_text() == "competitor-manifest\n"
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "opportunity-visual-p01.html",
        "render-manifest.json",
    ]


@pytest.mark.parametrize("kind", ["svg", "html", "png"])
def test_success_path_detects_artifact_replaced_between_hash_and_manifest_publish(
    tmp_path, normalized_document, monkeypatch, kind
):
    normalized_path = _write_normalized(tmp_path, normalized_document)
    output_dir = tmp_path / "rendered"
    if kind == "png":
        def fake_rasterize(html_path, png_path, width, height, playwright_factory=None):
            Path(png_path).write_bytes(b"renderer-png")

        monkeypatch.setattr(renderer, "rasterize_html", fake_rasterize)
        png_mode = "required"
    else:
        png_mode = "never"
    victim = output_dir / f"opportunity-visual-p01.{kind}"
    competitor = b"competitor-bytes"
    competitor_hash = hashlib.sha256(competitor).hexdigest()
    real_link = os.link
    staged_manifest = []

    def replace_after_hash(source, target, **kwargs):
        target = Path(target)
        if target.name == "render-manifest.json":
            staged_manifest.append(Path(source).read_text(encoding="utf-8"))
            victim.unlink()
            victim.write_bytes(competitor)
        return real_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", replace_after_hash)

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, output_dir, png_mode=png_mode)

    assert caught.value.code == "output_changed"
    assert victim.read_bytes() == competitor
    assert staged_manifest and competitor_hash not in staged_manifest[0]
    assert not (output_dir / "render-manifest.json").exists()
    assert not list(output_dir.glob(".*.tmp"))


@pytest.mark.parametrize("kind", ["svg", "html", "png"])
@pytest.mark.parametrize("moment", ["before_first_verification", "before_manifest_publish"])
def test_transaction_detects_same_inode_content_mutation(
    tmp_path, normalized_document, monkeypatch, kind, moment
):
    normalized_path = _write_normalized(tmp_path, normalized_document)
    output_dir = tmp_path / "rendered"
    if kind == "png":
        def fake_rasterize(html_path, png_path, width, height, playwright_factory=None):
            Path(png_path).write_bytes(b"renderer-png")

        monkeypatch.setattr(renderer, "rasterize_html", fake_rasterize)
        png_mode = "required"
    else:
        png_mode = "never"
    victim = output_dir / f"opportunity-visual-p01.{kind}"
    corrupt = b"same-inode-corrupt-content /private/source"
    corrupt_hash = hashlib.sha256(corrupt).hexdigest()
    staged_manifest = []

    if moment == "before_first_verification":
        real_verify = renderer._verify_publications
        calls = 0

        def mutate_then_verify(publications):
            nonlocal calls
            calls += 1
            if calls == 1:
                victim.write_bytes(corrupt)
            return real_verify(publications)

        monkeypatch.setattr(renderer, "_verify_publications", mutate_then_verify)
    else:
        real_link = os.link

        def mutate_before_manifest_link(source, target, **kwargs):
            target = Path(target)
            if target.name == "render-manifest.json":
                staged_manifest.append(Path(source).read_text(encoding="utf-8"))
                victim.write_bytes(corrupt)
            return real_link(source, target, **kwargs)

        monkeypatch.setattr(os, "link", mutate_before_manifest_link)

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, output_dir, png_mode=png_mode)

    assert caught.value.code == "output_changed"
    assert "/private/source" not in str(caught.value)
    assert not output_dir.exists() or list(output_dir.iterdir()) == []
    if staged_manifest:
        assert corrupt_hash not in staged_manifest[0]


@pytest.mark.parametrize(
    "mutate",
    [
        lambda document: document["records"][0]["months"][0].update(skipped_months=None),
        lambda document: document["source"].update(sha256="not-a-sha256"),
        lambda document: document["exclusions"].append(
            {"id": "BAD", "source_row": True, "code": "view_not_matched"}
        ),
        lambda document: document["exclusions"].append(
            {"id": "BAD", "source_row": 0, "code": "view_not_matched"}
        ),
        lambda document: document["exclusions"].append(
            {"id": "BAD", "source_row": 9, "code": "view_not_matched"}
        ),
    ],
)
def test_cli_rejects_malformed_audit_fields_before_any_artifact(
    tmp_path, normalized_document, mutate
):
    mutate(normalized_document)
    normalized_path = _write_normalized(tmp_path, normalized_document)
    output_dir = tmp_path / "rendered"

    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_opportunity_visual.py"),
            str(normalized_path),
            "--output-dir",
            str(output_dir),
            "--png",
            "never",
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
    assert payload["error"]["code"] in {"invalid_document", "invalid_record"}
    assert str(normalized_path) not in result.stdout
    assert not output_dir.exists()


def test_main_masks_unexpected_exception_without_masking_process_controls(
    tmp_path, monkeypatch, capsys
):
    monkeypatch.setattr(
        renderer,
        "render_document",
        Mock(side_effect=RuntimeError("secret /private/source detail")),
    )

    exit_code = renderer.main(
        ["normalized-data.json", "--output-dir", str(tmp_path / "rendered")]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.err == ""
    assert json.loads(captured.out) == {
        "ok": False,
        "error": {
            "code": "internal_error",
            "message": "Unexpected renderer failure",
            "details": {},
        },
    }
    assert "/private/source" not in captured.out

    monkeypatch.setattr(renderer, "render_document", Mock(side_effect=KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        renderer.main(
            ["normalized-data.json", "--output-dir", str(tmp_path / "rendered")]
        )


def test_prepared_xlsx_sheet_is_preserved_in_render_manifest(tmp_path):
    source = tmp_path / "pipeline.xlsx"
    workbook = Workbook()
    sheet = workbook.active
    sheet.title = "Pipeline Review"
    sheet.append(
        [
            "Area",
            "Sub-area",
            "Opportunity Name",
            "TCV",
            "Probability",
            "Mar '26",
            "Apr '26",
        ]
    )
    sheet.append(["Area", "Sub", "Synthetic", "Large", "High", "Idea", "Won"])
    workbook.save(source)
    semantics = tmp_path / "semantics.json"
    semantics.write_text(
        json.dumps(
            {
                "positive_terminals": ["Won"],
                "negative_terminals": ["Lost"],
                "stage_paths": [["Idea", "Won"]],
                "positive_transitions": [],
                "tcv_order": ["Large"],
                "probability_order": ["High"],
            }
        ),
        encoding="utf-8",
    )
    prepared = tmp_path / "prepared"
    prepare(
        source,
        "wins",
        semantics,
        prepared,
        sheet="Pipeline Review",
    )

    result = render_document(
        prepared / "normalized-data.json",
        prepared,
        png_mode="never",
    )
    manifest = json.loads(Path(result["manifest"]).read_text(encoding="utf-8"))

    assert manifest["source"]["sheet"] == "Pipeline Review"


def test_preflight_cli_prints_one_json_and_leaves_no_probe(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(SCRIPTS / "render_opportunity_visual.py"),
            "--preflight",
            "--output-dir",
            str(tmp_path),
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert set(payload["preflight"]) == {
        "csv_json",
        "xlsx",
        "svg_html",
        "png_package",
        "chromium",
        "output_directory",
    }
    assert list(tmp_path.iterdir()) == []


def test_png_required_cli_returns_two_one_safe_json_and_no_partials(
    tmp_path, normalized_document, monkeypatch, capsys
):
    normalized_path = _write_normalized(tmp_path, normalized_document)
    output_dir = tmp_path / "rendered"
    monkeypatch.setattr(
        renderer,
        "rasterize_html",
        Mock(side_effect=RasterUnavailable("secret /private/browser detail")),
    )

    exit_code = renderer.main(
        [
            str(normalized_path),
            "--output-dir",
            str(output_dir),
            "--png",
            "required",
        ]
    )
    captured = capsys.readouterr()

    assert exit_code == 2
    assert captured.err == ""
    assert captured.out.count("\n") == 1
    assert json.loads(captured.out) == {
        "ok": False,
        "error": {
            "code": "png_unavailable",
            "message": "Install playwright>=1.52 and Chromium for required PNG output",
            "details": {},
        },
    }
    assert "/private/browser" not in captured.out
    assert not output_dir.exists() or list(output_dir.iterdir()) == []


def test_renderer_rejects_nonstandard_json_numeric_constants(
    tmp_path, normalized_document
):
    normalized_path = tmp_path / "normalized-data.json"
    text = json.dumps(normalized_document, sort_keys=True)
    normalized_path.write_text(text.replace('"sort": 3', '"sort": NaN', 1), encoding="utf-8")
    output_dir = tmp_path / "rendered"

    with pytest.raises(RenderError) as caught:
        render_document(normalized_path, output_dir, png_mode="never")

    assert caught.value.code == "invalid_json"
    assert not output_dir.exists()


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
            "--png",
            "never",
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
        "manifest": str(output_dir / "render-manifest.json"),
        "pages": [
            {
                "svg": str(output_dir / "opportunity-visual-p01.svg"),
                "html": str(output_dir / "opportunity-visual-p01.html"),
                "png": None,
            },
            {
                "svg": str(output_dir / "opportunity-visual-p02.svg"),
                "html": str(output_dir / "opportunity-visual-p02.html"),
                "png": None,
            },
        ],
        "png": {"status": "disabled", "reason": "PNG output disabled"},
    }
    assert sorted(path.name for path in output_dir.glob("*.svg")) == [
        "opportunity-visual-p01.svg",
        "opportunity-visual-p02.svg",
    ]
    assert sorted(path.name for path in output_dir.glob("*.html")) == [
        "opportunity-visual-p01.html",
        "opportunity-visual-p02.html",
    ]
    assert (output_dir / "render-manifest.json").is_file()
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


def test_cli_rolls_back_all_pages_when_an_atomic_publish_fails(
    tmp_path, normalized_document, monkeypatch, capsys
):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    real_link = os.link
    calls = 0

    def fail_second_publish(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("sensitive /private/data")
        return real_link(source, target)

    monkeypatch.setattr(os, "link", fail_second_publish)
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
                "message": "Unable to write render artifacts",
                "details": {},
        },
    }
    assert "/private/data" not in captured.out
    assert not output_dir.exists() or list(output_dir.iterdir()) == []


def test_cli_rolls_back_only_its_pages_when_competitor_wins_later_page(
    tmp_path, normalized_document, monkeypatch, capsys
):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    real_link = os.link
    calls = 0

    def compete_on_second_page(source, target):
        nonlocal calls
        calls += 1
        if calls == 2:
            Path(target).write_text("competitor\n", encoding="utf-8")
        return real_link(source, target)

    monkeypatch.setattr(os, "link", compete_on_second_page)
    result = renderer.main(
        [str(normalized_path), "--output-dir", str(output_dir), "--width", "960", "--height", "540"]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["code"] == "output_exists"
    assert not (output_dir / "opportunity-visual-p01.svg").exists()
    competitor = output_dir / "opportunity-visual-p02.svg"
    assert competitor.read_text(encoding="utf-8") == "competitor\n"
    assert sorted(path.name for path in output_dir.iterdir()) == [competitor.name]


def test_cli_rollback_preserves_competitors_that_replace_owned_and_later_pages(
    tmp_path, normalized_document, monkeypatch, capsys
):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    real_link = os.link
    calls = 0

    def competitors_replace_first_and_claim_second(source, target, **kwargs):
        nonlocal calls
        calls += 1
        target = Path(target)
        if calls == 2:
            first = output_dir / "opportunity-visual-p01.svg"
            first.unlink()
            first.write_text("competitor-first\n", encoding="utf-8")
            target.write_text("competitor-second\n", encoding="utf-8")
        return real_link(source, target, **kwargs)

    monkeypatch.setattr(os, "link", competitors_replace_first_and_claim_second)
    result = renderer.main(
        [str(normalized_path), "--output-dir", str(output_dir), "--width", "960", "--height", "540"]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["code"] == "output_exists"
    assert (output_dir / "opportunity-visual-p01.svg").read_text(encoding="utf-8") == (
        "competitor-first\n"
    )
    assert (output_dir / "opportunity-visual-p02.svg").read_text(encoding="utf-8") == (
        "competitor-second\n"
    )
    assert sorted(path.name for path in output_dir.iterdir()) == [
        "opportunity-visual-p01.svg",
        "opportunity-visual-p02.svg",
    ]


def test_cli_rollback_retains_recovery_if_restored_competitor_is_replaced_again(
    tmp_path, normalized_document, monkeypatch, capsys
):
    document = expanded_document(normalized_document, record_count=4, month_count=10)
    normalized_path = tmp_path / "normalized-data.json"
    normalized_path.write_text(json.dumps(document), encoding="utf-8")
    output_dir = tmp_path / "rendered"
    real_link = os.link
    calls = 0

    def three_competitors(source, target, **kwargs):
        nonlocal calls
        calls += 1
        target = Path(target)
        if calls == 2:
            first = output_dir / "opportunity-visual-p01.svg"
            first.unlink()
            first.write_text("competitor-first\n", encoding="utf-8")
            target.write_text("competitor-second\n", encoding="utf-8")
        result = real_link(source, target, **kwargs)
        if calls == 3:
            target.unlink()
            target.write_text("competitor-third\n", encoding="utf-8")
        return result

    monkeypatch.setattr(os, "link", three_competitors)
    result = renderer.main(
        [str(normalized_path), "--output-dir", str(output_dir), "--width", "960", "--height", "540"]
    )
    captured = capsys.readouterr()

    assert result == 2
    assert captured.err == ""
    assert json.loads(captured.out)["error"]["code"] == "output_exists"
    assert (output_dir / "opportunity-visual-p01.svg").read_text(encoding="utf-8") == (
        "competitor-third\n"
    )
    assert (output_dir / "opportunity-visual-p02.svg").read_text(encoding="utf-8") == (
        "competitor-second\n"
    )
    recovery_dirs = list(output_dir.glob(".opportunity-visual-p01.svg.rollback-*"))
    assert len(recovery_dirs) == 1
    assert (recovery_dirs[0] / "candidate").read_text(encoding="utf-8") == (
        "competitor-first\n"
    )
    assert not list(output_dir.glob("*.tmp"))


@pytest.mark.parametrize(
    "arguments",
    [
        ["normalized-data.json", "--output-dir", "rendered", "--width", "wide"],
        ["normalized-data.json"],
        ["normalized-data.json", "--output-dir", "rendered", "--unknown"],
    ],
)
def test_cli_argument_errors_are_one_safe_json_object(arguments):
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / "render_opportunity_visual.py"), *arguments],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout) == {
        "ok": False,
        "error": {
            "code": "invalid_arguments",
            "message": "Invalid command arguments",
            "details": {},
        },
    }


@pytest.mark.parametrize("dimension", ["--width", "--height"])
def test_cli_rejects_huge_dimensions_before_float_conversion(
    tmp_path, normalized_document, dimension
):
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
            dimension,
            "9" * 400,
        ],
        check=False,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert result.stderr == ""
    assert result.stdout.count("\n") == 1
    assert json.loads(result.stdout) == {
        "ok": False,
        "error": {
            "code": "invalid_dimensions",
            "message": "Width and height must be between 1 and 16384 pixels",
            "details": {},
        },
    }
    assert not output_dir.exists()
