from __future__ import annotations

from epub2m4b.epub.cleaner import html_to_text
from epub2m4b.generation.normalize import normalize_text


def clean(markup: str) -> str:
    return normalize_text(html_to_text(markup))


def test_empty_and_plain_text() -> None:
    assert clean("") == ""
    assert clean("Hello, world!") == "Hello, world!"


def test_markup_entities_and_punctuation() -> None:
    assert clean("<p>‘Hello&nbsp;&amp; goodbye.’</p>") == "‘Hello & goodbye.’"
    assert clean('<img alt="do not narrate">Visible') == "Visible"


def test_blocks_dialogue_quote_list_and_pre() -> None:
    assert (
        clean(
            "<h1>Title</h1><p>Hi <em>there</em>.</p><blockquote>‘Yes.’</blockquote><ul><li>One</li><li>Two</li></ul><pre>A  B</pre>"
        )
        == "Title\n\nHi there.\n\n‘Yes.’\n\nOne\n\nTwo\n\nA  B"
    )


def test_line_break_and_scene_break() -> None:
    assert clean("A<br>B<hr>C") == "A\nB\n\n* * *\n\nC"


def test_document_boundary_comment() -> None:
    assert clean("A<!-- epub2m4b:document-boundary -->B") == "A\n\nB"


def test_skipped_tags_and_nested_hidden_regions() -> None:
    markup = "<p>A<script><b>secret</script><p>visible</p><style>x</style><span hidden><b>no</b></span>B</p><nav>menu</nav>"
    assert clean(markup) == "A\n\nvisible\n\nB"


def test_hidden_styles_and_following_siblings() -> None:
    markup = '<span style="color:red; display : none !important">no</span><span>yes</span><span style="visibility: hidden; color: red">no</span><span>done</span>'
    assert clean(markup) == "yesdone"


def test_hidden_void_element_does_not_hide_following_text() -> None:
    assert clean('<img hidden alt="secret">Visible<br>next') == "Visible\nnext"


def test_unclosed_hidden_child_preserves_visible_parent_boundary() -> None:
    assert clean("<p>A<span hidden>secret</p><p>B</p>") == "A\n\nB"


def test_aria_hidden_boolean_and_page_markers() -> None:
    markup = '<p>A<span aria-hidden="true">x</span><span class="page_number">3</span><span id="doc-pagebreak-4">x</span>B</p>'
    assert clean(markup) == "AB"


def test_malformed_html_tolerance() -> None:
    assert clean("<p>One <b>two<p>Three") == "One two\n\nThree"


def test_unicode_newlines_whitespace_and_composition() -> None:
    value = "  e\u0301\r\n\u2028\u2029\t\u00a0x\u202f  "
    assert normalize_text(value) == "é\n\nx"


def test_soft_hyphen_zero_width_and_duplicate_blanks() -> None:
    value = "\u200bA\u00adB\u200c\n\n\n\n C\ufeff"
    assert normalize_text(value) == "AB\n\nC"


def test_normalization_is_idempotent() -> None:
    value = "  A\r\n\r\n\r\n B\u00a0C  "
    assert normalize_text(normalize_text(value)) == normalize_text(value)
