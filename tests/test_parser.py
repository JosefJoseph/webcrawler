from app.parser.parser import build_page_result, parse_page


def test_parse_page_extracts_meaningful_list_item_blocks():
    html = """
    <html>
        <body>
            <ul>
                <li>
                    <a
                        href="https://world.openfoodfacts.org/product/6111246721261/fromage-blanc-nature-milky-food-professional"
                        class="list_product_a"
                        title="Fromage Blanc Nature - Milky Food Professional - 1 kg"
                    >
                        <div class="list_product_content">
                            <div class="list_product_name">Fromage Blanc Nature - Milky Food Professional - 1 kg</div>
                            <div class="list_product_sc">Nutri-Score unknown Processed foods Green-Score B</div>
                        </div>
                    </a>
                </li>
            </ul>
        </body>
    </html>
    """

    parsed = parse_page(html)

    assert parsed["text_blocks"]
    assert any(
        block["tag"] == "li" and "Fromage Blanc Nature - Milky Food Professional - 1 kg" in block["text"]
        for block in parsed["text_blocks"]
    )


# ---------------------------------------------------------------------------
# parse_page – title extraction
# ---------------------------------------------------------------------------


def test_parse_page_extracts_title():
    html = "<html><head><title>Test Page Title</title></head><body><p>Content here for testing purposes with enough text length.</p></body></html>"
    parsed = parse_page(html)
    assert parsed["title"] == "Test Page Title"


def test_parse_page_no_title():
    html = "<html><body><p>Content here for testing purposes with enough text for a block.</p></body></html>"
    parsed = parse_page(html)
    assert parsed["title"] == "Ohne Titel"


# ---------------------------------------------------------------------------
# parse_page – meta / attribute extraction
# ---------------------------------------------------------------------------


def test_parse_page_extracts_meta_description():
    html = '<html><head><meta name="description" content="A fine description"></head><body><p>Text</p></body></html>'
    parsed = parse_page(html)
    assert any(item["text"] == "A fine description" for item in parsed["attribute_texts"])


def test_parse_page_extracts_alt_text():
    html = '<html><body><img alt="Logo image" /><p>Some placeholder text for the parser block.</p></body></html>'
    parsed = parse_page(html)
    assert any(item["text"] == "Logo image" for item in parsed["attribute_texts"])


# ---------------------------------------------------------------------------
# parse_page – searchable_text
# ---------------------------------------------------------------------------


def test_parse_page_searchable_text_includes_visible_and_attrs():
    html = '<html><head><meta name="description" content="meta desc"></head><body><p>Visible text content.</p></body></html>'
    parsed = parse_page(html)
    assert "Visible text content" in parsed["searchable_text"]
    assert "meta desc" in parsed["searchable_text"]


# ---------------------------------------------------------------------------
# parse_page – script/style removal
# ---------------------------------------------------------------------------


def test_parse_page_removes_script_and_style():
    html = "<html><body><script>var x=1;</script><style>.a{}</style><p>Clean content for testing the parser extraction logic.</p></body></html>"
    parsed = parse_page(html)
    assert "var x" not in parsed["visible_text"]
    assert ".a{}" not in parsed["visible_text"]
    assert "Clean content" in parsed["visible_text"]


# ---------------------------------------------------------------------------
# build_page_result
# ---------------------------------------------------------------------------


def test_build_page_result_from_ok_page():
    page = {
        "url": "https://example.com",
        "depth": 1,
        "html": "<html><head><title>Example</title></head><body><p>Hello World from the example page content.</p></body></html>",
        "links": ["https://example.com/a"],
        "status": "ok",
        "error": "",
        "fetch_method": "requests",
        "fetch_error": "",
    }
    result = build_page_result(page)
    assert result["url"] == "https://example.com"
    assert result["title"] == "Example"
    assert result["depth"] == 1
    assert result["link_count"] == 1


def test_build_page_result_from_error_page():
    page = {
        "url": "https://example.com/bad",
        "depth": 2,
        "html": "",
        "links": [],
        "status": "error",
        "error": "Timeout",
        "fetch_method": "error",
        "fetch_error": "",
    }
    result = build_page_result(page)
    assert result["title"] == "Fehler"
    assert result["status"] == "error"
