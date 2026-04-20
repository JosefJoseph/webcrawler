from app.crawler.crawler import crawl_domain, extract_link_candidates, fetch_html


def test_extract_link_candidates_prioritize_openfoodfacts_product_cards():
    html = """
    <html>
        <body>
            <a href="/discover">Discover</a>
            <li>
                <a
                    href="https://world.openfoodfacts.org/product/6111246721261/fromage-blanc-nature-milky-food-professional"
                    class="list_product_a"
                    title="Fromage Blanc Nature - Milky Food Professional - 1 kg"
                >
                    <div class="list_product_content">
                        <div class="list_product_name">Fromage Blanc Nature</div>
                    </div>
                </a>
            </li>
        </body>
    </html>
    """

    candidates = extract_link_candidates("https://world.openfoodfacts.org", html)

    assert candidates[0].url == (
        "https://world.openfoodfacts.org/product/6111246721261/fromage-blanc-nature-milky-food-professional"
    )
    assert candidates[0].priority < candidates[1].priority


def test_crawl_domain_prioritizes_new_product_pages_globally(monkeypatch):
    pages = {
        "https://world.openfoodfacts.org": """
            <a href="/discover">Discover</a>
            <a href="/2">2</a>
        """,
        "https://world.openfoodfacts.org/2": """
            <a
                href="https://world.openfoodfacts.org/product/6111246721261/fromage-blanc-nature-milky-food-professional"
                class="list_product_a"
            >
                Product card
            </a>
        """,
        "https://world.openfoodfacts.org/product/6111246721261/fromage-blanc-nature-milky-food-professional": """
            <html><body>Nutrition facts</body></html>
        """,
        "https://world.openfoodfacts.org/discover": """
            <html><body>Discover</body></html>
        """,
    }

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        return pages[url], "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain(
        start_url="https://world.openfoodfacts.org",
        max_pages=3,
        max_depth=2,
        use_playwright=False,
    )

    assert [item["url"] for item in results] == [
        "https://world.openfoodfacts.org",
        "https://world.openfoodfacts.org/2",
        "https://world.openfoodfacts.org/product/6111246721261/fromage-blanc-nature-milky-food-professional",
    ]


def test_fetch_html_reports_playwright_fallback(monkeypatch):
    monkeypatch.setattr(
        "app.crawler.crawler.fetch_html_playwright",
        lambda url, timeout_ms=20000: (_ for _ in ()).throw(PermissionError("Access is denied")),
    )
    monkeypatch.setattr("app.crawler.crawler.fetch_html_requests", lambda url, timeout=15: "<html></html>")

    html, fetch_method, fetch_error = fetch_html("https://example.com", use_playwright=True)

    assert html == "<html></html>"
    assert fetch_method == "requests-fallback"
    assert "Playwright failed" in fetch_error


def test_crawl_domain_disables_playwright_after_first_fallback(monkeypatch):
    calls = []
    pages = {
        "https://example.com": '<a href="/next">Next</a>',
        "https://example.com/next": "<html><body>Next page</body></html>",
    }

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        calls.append((url, use_playwright))
        if url == "https://example.com":
            return pages[url], "requests-fallback", "Playwright failed: NotImplementedError"
        return pages[url], "requests", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    crawl_domain("https://example.com", max_pages=2, max_depth=1, use_playwright=True)

    assert calls == [
        ("https://example.com", True),
        ("https://example.com/next", False),
    ]
