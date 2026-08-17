"""Storage format (XHTML) -> Markdown.

Ported from skills/ericsson/confluence-research/scripts/storage_to_md.py,
which shipped without tests. These pin the behaviour the connector relies on.
"""

import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-confluence"
sys.path.insert(0, str(PLUGIN))

from storage import markdown_to_storage, storage_to_markdown  # noqa: E402


class TestMarkdownToStorage:
    def test_paragraphs(self):
        assert markdown_to_storage("hello") == "<p>hello</p>"

    def test_blank_line_separates_paragraphs(self):
        out = markdown_to_storage("one\n\ntwo")
        assert out == "<p>one</p><p>two</p>"

    def test_headings(self):
        assert "<h2>Title</h2>" in markdown_to_storage("## Title")

    def test_bullet_list(self):
        out = markdown_to_storage("- a\n- b")
        assert "<ul>" in out and "<li>a</li>" in out and "<li>b</li>" in out

    def test_numbered_list(self):
        out = markdown_to_storage("1. a\n2. b")
        assert "<ol>" in out and "<li>a</li>" in out


class TestNestedLists:
    def test_nested_list_is_emitted_inside_the_parent_li(self):
        """XHTML nests a child list inside its parent <li>, so the parent's
        </li> must come after the nested </ul>."""
        out = markdown_to_storage("- outer\n  - inner")
        assert out == "<ul><li>outer<ul><li>inner</li></ul></li></ul>"

    def test_four_space_indentation_also_nests(self):
        out = markdown_to_storage("- outer\n    - inner")
        assert out == "<ul><li>outer<ul><li>inner</li></ul></li></ul>"

    def test_tab_indentation_also_nests(self):
        out = markdown_to_storage("- outer\n\t- inner")
        assert "<ul><li>outer<ul><li>inner</li>" in out

    def test_three_levels(self):
        out = markdown_to_storage("- a\n  - b\n    - c")
        assert out == (
            "<ul><li>a<ul><li>b<ul><li>c</li></ul></li></ul></li></ul>"
        )

    def test_dedent_returns_to_the_outer_level(self):
        out = markdown_to_storage("- a\n  - b\n- c")
        assert out == "<ul><li>a<ul><li>b</li></ul></li><li>c</li></ul>"

    def test_mixed_bullet_and_numbered_nesting(self):
        out = markdown_to_storage("- outer\n  1. one\n  2. two")
        assert "<ul><li>outer<ol><li>one</li><li>two</li></ol></li></ul>" == out

    def test_marker_change_at_the_same_level_swaps_the_container(self):
        out = markdown_to_storage("- a\n1. b")
        assert "</ul>" in out and "<ol>" in out

    def test_all_levels_close_before_a_following_paragraph(self):
        out = markdown_to_storage("- a\n  - b\n\nafter")
        assert out.endswith("<p>after</p>")
        assert out.count("<ul>") == out.count("</ul>")
        assert out.count("<li>") == out.count("</li>")

    def test_tags_are_balanced_for_ragged_indentation(self):
        """Half-indented and over-indented lines are lenient, but must never
        leave an unclosed tag in the page."""
        out = markdown_to_storage("- a\n   - b\n  - c\n- d")
        assert out.count("<ul>") == out.count("</ul>")
        assert out.count("<ol>") == out.count("</ol>")
        assert out.count("<li>") == out.count("</li>")

    def test_deeply_nested_input_stays_balanced(self):
        source = "\n".join("  " * depth + "- item" for depth in range(12))
        out = markdown_to_storage(source)
        assert out.count("<ul>") == out.count("</ul>")
        assert out.count("<li>") == out.count("</li>")

    def test_fenced_code_becomes_a_code_macro(self):
        out = markdown_to_storage("```python\nprint(1)\n```")
        assert 'ac:name="code"' in out
        assert "CDATA[print(1)]" in out

    def test_inline_link(self):
        out = markdown_to_storage("see [docs](https://x.test)")
        assert '<a href="https://x.test">docs</a>' in out

    def test_link_with_hostile_href_is_dropped_to_text(self):
        """A javascript: URL must never become a live link."""
        out = markdown_to_storage("[click](javascript:alert(1))")
        assert "javascript:" not in out
        assert "click" in out


class TestWriteEscaping:
    def test_raw_macro_markup_is_escaped_not_interpreted(self):
        """The security property: a model must not be able to inject a
        Confluence macro by writing one into the body text."""
        out = markdown_to_storage('<ac:structured-macro ac:name="html"/>')
        assert "<ac:structured-macro" not in out
        assert "&lt;ac:structured-macro" in out

    def test_html_tags_are_escaped(self):
        out = markdown_to_storage("<script>alert(1)</script>")
        assert "<script>" not in out
        assert "&lt;script&gt;" in out

    def test_ampersands_are_escaped(self):
        assert "&amp;" in markdown_to_storage("a & b")

    def test_code_block_content_is_cdata_safe(self):
        """A ]]> inside code would otherwise terminate the CDATA section
        early and break the page."""
        out = markdown_to_storage("```\na ]]> b\n```")
        assert "]]]]><![CDATA[>" in out

    def test_link_text_is_escaped(self):
        out = markdown_to_storage("[<b>x</b>](https://x.test)")
        assert "<b>" not in out
        assert "&lt;b&gt;" in out


class TestRoundTrip:
    def test_markdown_survives_a_round_trip(self):
        source = "## Heading\n\nsome text\n\n- one\n- two"
        rendered = storage_to_markdown(markdown_to_storage(source))
        assert "Heading" in rendered
        assert "some text" in rendered
        assert "- one" in rendered

    def test_nesting_survives_a_round_trip(self):
        """The read side has always preserved nesting. A write side that
        flattened it would silently lose a level on every edit — read a
        nested list, write it back, and the structure is gone."""
        rendered = storage_to_markdown(markdown_to_storage("- outer\n  - inner"))
        assert "- outer" in rendered
        assert "  - inner" in rendered

    def test_escaped_markup_survives_as_visible_text(self):
        rendered = storage_to_markdown(markdown_to_storage("<b>literal</b>"))
        assert "<b>literal</b>" in rendered


class TestBlockStructure:
    def test_paragraphs_are_separated(self):
        assert "First" in storage_to_markdown("<p>First</p><p>Second</p>")
        assert "Second" in storage_to_markdown("<p>First</p><p>Second</p>")

    def test_headings_become_atx(self):
        assert "# Title" in storage_to_markdown("<h1>Title</h1>")
        assert "### Sub" in storage_to_markdown("<h3>Sub</h3>")

    def test_unordered_lists(self):
        md = storage_to_markdown("<ul><li>one</li><li>two</li></ul>")
        assert "- one" in md
        assert "- two" in md

    def test_ordered_lists_are_numbered(self):
        md = storage_to_markdown("<ol><li>first</li><li>second</li></ol>")
        assert "1. first" in md
        assert "2. second" in md

    def test_nested_lists_are_indented(self):
        md = storage_to_markdown(
            "<ul><li>outer<ul><li>inner</li></ul></li></ul>"
        )
        assert "- outer" in md
        assert "  - inner" in md

    def test_empty_input(self):
        assert storage_to_markdown("") == ""


class TestLinksAndTables:
    def test_links_become_markdown(self):
        md = storage_to_markdown('<p><a href="https://x.test">click</a></p>')
        assert "[click](https://x.test)" in md

    def test_table_rows_and_header(self):
        md = storage_to_markdown(
            "<table><tbody>"
            "<tr><th>Name</th><th>Value</th></tr>"
            "<tr><td>a</td><td>1</td></tr>"
            "</tbody></table>"
        )
        assert "Name" in md and "Value" in md
        assert "a" in md and "1" in md
        assert "---" in md, "a header separator row is expected"


class TestMacros:
    def test_code_macro_cdata_survives(self):
        """Code bodies arrive wrapped in CDATA, handled by unknown_decl."""
        md = storage_to_markdown(
            '<ac:structured-macro ac:name="code">'
            "<ac:plain-text-body><![CDATA[print(1)]]></ac:plain-text-body>"
            "</ac:structured-macro>"
        )
        assert "print(1)" in md

    def test_macro_parameters_never_leak_as_text(self):
        """A naive tag-strip emits 'title' and 'Heads up' as bare words that
        read as content and are not."""
        md = storage_to_markdown(
            '<ac:structured-macro ac:name="info">'
            '<ac:parameter ac:name="title">Heads up</ac:parameter>'
            "<ac:rich-text-body><p>Real content</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        assert "Real content" in md
        assert "Heads up" not in md

    def test_callout_body_is_kept(self):
        md = storage_to_markdown(
            '<ac:structured-macro ac:name="warning">'
            "<ac:rich-text-body><p>Careful</p></ac:rich-text-body>"
            "</ac:structured-macro>"
        )
        assert "Careful" in md


class TestTasks:
    def test_incomplete_task_is_an_unchecked_box(self):
        md = storage_to_markdown(
            "<ac:task-list><ac:task>"
            "<ac:task-id>1</ac:task-id>"
            "<ac:task-status>incomplete</ac:task-status>"
            "<ac:task-body>Do the thing</ac:task-body>"
            "</ac:task></ac:task-list>"
        )
        assert "[ ]" in md
        assert "Do the thing" in md

    def test_complete_task_is_a_checked_box(self):
        md = storage_to_markdown(
            "<ac:task-list><ac:task>"
            "<ac:task-status>complete</ac:task-status>"
            "<ac:task-body>Done already</ac:task-body>"
            "</ac:task></ac:task-list>"
        )
        assert "[x]" in md

    def test_task_metadata_never_appears(self):
        """task-id and task-uuid are bookkeeping, not content."""
        md = storage_to_markdown(
            "<ac:task-list><ac:task>"
            "<ac:task-id>987654</ac:task-id>"
            "<ac:task-status>incomplete</ac:task-status>"
            "<ac:task-body>Visible</ac:task-body>"
            "</ac:task></ac:task-list>"
        )
        assert "987654" not in md
        assert "incomplete" not in md


class TestRobustness:
    def test_malformed_markup_does_not_raise(self):
        """Wiki content is user-authored and frequently invalid XHTML;
        losing a whole page to one unclosed tag would be worse than
        imperfect output."""
        assert isinstance(storage_to_markdown("<p>unclosed <b>bold"), str)

    def test_deep_nesting_does_not_blow_up(self):
        assert isinstance(
            storage_to_markdown("<div>" * 400 + "x" + "</div>" * 400), str
        )

    def test_entities_are_unescaped(self):
        assert "a & b" in storage_to_markdown("<p>a &amp; b</p>")

    def test_excess_blank_lines_collapse(self):
        md = storage_to_markdown("<p>a</p><p></p><p></p><p>b</p>")
        assert "\n\n\n" not in md

    def test_script_and_style_content_is_dropped(self):
        md = storage_to_markdown("<p>keep</p><script>evil()</script>")
        assert "keep" in md
        assert "evil()" not in md
