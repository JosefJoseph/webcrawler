from app.parser.parser import parse_page


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
