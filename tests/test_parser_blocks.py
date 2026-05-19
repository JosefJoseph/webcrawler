"""Tests that parser preserves both text_blocks and passage_blocks."""
import pytest
from app.parser.parser import build_page_result, parse_page


HTML_WITH_CONTENT = """
<html>
<body>
    <h2>Ingredients</h2>
    <p>Water, Sugar, Salt, Natural Flavours, Citric Acid, Ascorbic Acid and Vitamin D3.</p>
    <table>
        <tr><td>Calories per serving</td><td>120 kcal per 100 g product</td></tr>
        <tr><td>Total Protein content</td><td>5 g per 100 g product</td></tr>
    </table>
    <ul>
        <li>Organic apples from certified sustainable farms</li>
        <li>Ground cinnamon from Sri Lanka</li>
    </ul>
</body>
</html>
"""


def test_parse_page_returns_both_block_types():
    """parse_page must return non-empty text_blocks AND passage_blocks when content warrants both."""
    result = parse_page(HTML_WITH_CONTENT)
    # text_blocks should capture table cells, list items etc.
    assert len(result["text_blocks"]) > 0
    # passage_blocks should capture heading-grouped content
    assert len(result["passage_blocks"]) > 0


def test_build_page_result_preserves_text_blocks():
    """build_page_result must not replace text_blocks with passage_blocks."""
    raw_page = {
        "url": "https://example.com",
        "final_url": "https://example.com",
        "depth": 0,
        "html": HTML_WITH_CONTENT,
        "links": [],
        "status": "ok",
        "error": "",
        "fetch_method": "requests",
        "fetch_error": "",
    }
    result = build_page_result(raw_page)
    # Both must be present and non-empty
    assert result["text_blocks"], "text_blocks should not be empty"
    assert result["passage_blocks"], "passage_blocks should not be empty"


def test_build_page_result_text_blocks_not_replaced_by_passage_blocks():
    """The text in text_blocks must include content (e.g. table cells) not in passage_blocks."""
    raw_page = {
        "url": "https://example.com",
        "final_url": "https://example.com",
        "depth": 0,
        "html": HTML_WITH_CONTENT,
        "links": [],
        "status": "ok",
        "error": "",
        "fetch_method": "requests",
        "fetch_error": "",
    }
    result = build_page_result(raw_page)
    all_block_texts = " ".join(b["text"] for b in result["text_blocks"])
    # Table content or paragraph content should appear in text_blocks
    assert (
        "Calories" in all_block_texts
        or "Protein" in all_block_texts
        or "Water" in all_block_texts
        or "Organic" in all_block_texts
        or "Cinnamon" in all_block_texts
        or "Ingredients" in all_block_texts
    )


def test_build_page_result_includes_final_url():
    """build_page_result must propagate final_url from the raw page dict."""
    raw_page = {
        "url": "https://example.com/original",
        "final_url": "https://example.com/redirected",
        "depth": 0,
        "html": "<html><body>Content</body></html>",
        "links": [],
        "status": "ok",
        "error": "",
        "fetch_method": "requests",
        "fetch_error": "",
    }
    result = build_page_result(raw_page)
    assert result["final_url"] == "https://example.com/redirected"


def test_build_page_result_final_url_defaults_to_url():
    """If final_url is absent, build_page_result must fall back to url."""
    raw_page = {
        "url": "https://example.com/page",
        "depth": 0,
        "html": "<html><body>Content</body></html>",
        "links": [],
        "status": "ok",
        "error": "",
        "fetch_method": "requests",
        "fetch_error": "",
    }
    result = build_page_result(raw_page)
    assert result["final_url"] == "https://example.com/page"
