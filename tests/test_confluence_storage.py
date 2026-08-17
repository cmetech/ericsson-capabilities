"""Storage format (XHTML) -> Markdown.

Ported from skills/ericsson/confluence-research/scripts/storage_to_md.py,
which shipped without tests. These pin the behaviour the connector relies on.
"""

import sys
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1] / "plugins" / "ericsson-confluence"
sys.path.insert(0, str(PLUGIN))

from storage import storage_to_markdown  # noqa: E402


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
