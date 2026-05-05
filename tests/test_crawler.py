from app.crawler.crawler import (
    crawl_domain,
    extract_link_candidates,
    extract_links,
    fetch_html,
    is_same_domain,
    link_priority_score,
    normalize_url,
    sort_links_for_queue,
)


# ---------------------------------------------------------------------------
# normalize_url
# ---------------------------------------------------------------------------


def test_normalize_url_strips_fragment():
    assert normalize_url("https://example.com/page#section") == "https://example.com/page"


def test_normalize_url_strips_trailing_slash():
    assert normalize_url("https://example.com/page/") == "https://example.com/page"


def test_normalize_url_removes_tracking_params():
    url = "https://example.com/page?name=val&utm_source=google&fbclid=abc"
    assert normalize_url(url) == "https://example.com/page?name=val"


def test_normalize_url_preserves_meaningful_query():
    url = "https://example.com/search?q=food&page=2"
    assert normalize_url(url) == "https://example.com/search?q=food&page=2"


# ---------------------------------------------------------------------------
# is_same_domain
# ---------------------------------------------------------------------------


def test_is_same_domain_same():
    assert is_same_domain("https://example.com/a", "https://example.com/b") is True


def test_is_same_domain_different():
    assert is_same_domain("https://example.com/a", "https://other.com/b") is False


def test_is_same_domain_subdomain_differs():
    assert is_same_domain("https://www.example.com", "https://api.example.com") is False


# ---------------------------------------------------------------------------
# link_priority_score
# ---------------------------------------------------------------------------


def test_link_priority_score_product_page_lower():
    product_score = link_priority_score("https://example.com/product/123")
    generic_score = link_priority_score("https://example.com/about")
    assert product_score < generic_score


def test_link_priority_score_login_page_higher():
    login_score = link_priority_score("https://example.com/login")
    generic_score = link_priority_score("https://example.com/about")
    assert login_score > generic_score


def test_link_priority_score_navigation_page():
    nav_score = link_priority_score("https://example.com/privacy")
    generic_score = link_priority_score("https://example.com/about")
    assert nav_score > generic_score


# ---------------------------------------------------------------------------
# extract_links / extract_link_candidates
# ---------------------------------------------------------------------------
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
    monkeypatch.setattr("app.crawler.crawler.fetch_html_requests", lambda url, timeout=20: "<html></html>")

    html, fetch_method, fetch_error = fetch_html("https://example.com", use_playwright=True)

    assert html == "<html></html>"
    assert fetch_method == "requests-fallback"
    assert "Chromium failed" in fetch_error


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


# ---------------------------------------------------------------------------
# extract_links helper
# ---------------------------------------------------------------------------


def test_extract_links_returns_urls_only():
    html = '<html><body><a href="/a">A</a><a href="/b">B</a></body></html>'
    links = extract_links("https://example.com", html)
    assert "https://example.com/a" in links
    assert "https://example.com/b" in links


def test_extract_links_skips_non_html():
    html = '<html><body><a href="/photo.jpg">Img</a><a href="/page">Page</a></body></html>'
    links = extract_links("https://example.com", html)
    assert "https://example.com/photo.jpg" not in links
    assert "https://example.com/page" in links


def test_extract_links_skips_javascript_mailto():
    html = '<html><body><a href="javascript:void(0)">JS</a><a href="mailto:a@b.com">Mail</a></body></html>'
    links = extract_links("https://example.com", html)
    assert len(links) == 0


# ---------------------------------------------------------------------------
# sort_links_for_queue
# ---------------------------------------------------------------------------


def test_sort_links_for_queue_products_first():
    links = [
        "https://example.com/privacy",
        "https://example.com/product/123",
        "https://example.com/about",
    ]
    sorted_links = sort_links_for_queue(links)
    assert sorted_links[0] == "https://example.com/product/123"


# ---------------------------------------------------------------------------
# crawl_domain – max_pages limiting
# ---------------------------------------------------------------------------


def test_crawl_domain_respects_max_pages(monkeypatch):
    """Crawler must stop after visiting max_pages pages even if more links exist."""
    pages = {}
    for i in range(20):
        next_links = "".join(f'<a href="/{j}">Link {j}</a>' for j in range(i + 1, min(i + 5, 20)))
        pages[f"https://example.com/{i}"] = f"<html><body>{next_links}</body></html>"
    pages["https://example.com"] = '<html><body><a href="/0">Start</a></body></html>'

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://example.com", max_pages=5, max_depth=10)
    assert len(results) == 5


# ---------------------------------------------------------------------------
# crawl_domain – max_depth limiting
# ---------------------------------------------------------------------------


def test_crawl_domain_respects_max_depth(monkeypatch):
    """Links beyond max_depth should not be followed."""
    pages = {
        "https://example.com": '<a href="/level1">L1</a>',
        "https://example.com/level1": '<a href="/level2">L2</a>',
        "https://example.com/level2": '<a href="/level3">L3</a>',
        "https://example.com/level3": "<html><body>Deep</body></html>",
    }

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://example.com", max_pages=100, max_depth=2)
    visited_urls = [r["url"] for r in results]

    # depth 0: start_url, depth 1: /level1, depth 2: /level2 (visited but links not followed)
    assert "https://example.com" in visited_urls
    assert "https://example.com/level1" in visited_urls
    assert "https://example.com/level2" in visited_urls
    assert "https://example.com/level3" not in visited_urls


# ---------------------------------------------------------------------------
# crawl_domain – deep crawling with high max_pages
# ---------------------------------------------------------------------------


def test_crawl_domain_reaches_deep_pages_with_high_max_pages(monkeypatch):
    """When max_pages is high and max_depth is high, the crawler must traverse
    deep link chains instead of stopping prematurely."""
    chain_length = 50
    pages = {}
    for i in range(chain_length):
        next_page = f'<a href="/page{i + 1}">Next</a>' if i < chain_length - 1 else ""
        pages[f"https://example.com/page{i}"] = f"<html><body>Page {i}{next_page}</body></html>"
    pages["https://example.com"] = '<html><body><a href="/page0">Start</a></body></html>'

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://example.com", max_pages=100, max_depth=60)
    # Should visit all 51 pages (start + 50 chain pages)
    assert len(results) == chain_length + 1


def test_crawl_domain_shallow_depth_limits_reachable_pages(monkeypatch):
    """With max_depth=2 and a deep chain, only 3 pages should be reached.
    This verifies the former bug where max_pages=500 had no effect."""
    chain_length = 10
    pages = {}
    for i in range(chain_length):
        next_page = f'<a href="/page{i + 1}">Next</a>' if i < chain_length - 1 else ""
        pages[f"https://example.com/page{i}"] = f"<html><body>Page {i}{next_page}</body></html>"
    pages["https://example.com"] = '<html><body><a href="/page0">Start</a></body></html>'

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://example.com", max_pages=500, max_depth=2)
    # depth 0: start, depth 1: page0, depth 2: page1 → only 3 pages
    assert len(results) == 3


# ---------------------------------------------------------------------------
# crawl_domain – wide crawling (many links per page)
# ---------------------------------------------------------------------------


def test_crawl_domain_wide_site_with_high_max_pages(monkeypatch):
    """A wide site (many links from start page) should be fully crawled
    when max_pages is high enough."""
    num_children = 100
    child_links = "".join(f'<a href="/child{i}">C{i}</a>' for i in range(num_children))
    pages = {"https://example.com": f"<html><body>{child_links}</body></html>"}
    for i in range(num_children):
        pages[f"https://example.com/child{i}"] = f"<html><body>Child {i}</body></html>"

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://example.com", max_pages=200, max_depth=5)
    # 1 start + 100 children = 101
    assert len(results) == num_children + 1


# ---------------------------------------------------------------------------
# crawl_domain – external links not followed
# ---------------------------------------------------------------------------


def test_crawl_domain_ignores_external_links(monkeypatch):
    pages = {
        "https://example.com": '<a href="https://other.com/page">External</a><a href="/internal">Int</a>',
        "https://example.com/internal": "<html><body>Internal</body></html>",
    }

    def fake_fetch_html(url, use_playwright=False, timeout=15):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://example.com", max_pages=10, max_depth=5)
    urls = [r["url"] for r in results]
    assert "https://other.com/page" not in urls
    assert "https://example.com/internal" in urls


# ---------------------------------------------------------------------------
# crawl_domain – error handling
# ---------------------------------------------------------------------------


def test_crawl_domain_records_error_on_fetch_failure(monkeypatch):
    def failing_fetch(url, use_playwright=False, timeout=15):
        if url == "https://example.com":
            return '<a href="/broken">Link</a>', "mock", ""
        raise ConnectionError("Connection refused")

    monkeypatch.setattr("app.crawler.crawler.fetch_html", failing_fetch)

    results = crawl_domain("https://example.com", max_pages=5, max_depth=5)
    error_results = [r for r in results if r["status"] == "error"]
    assert len(error_results) == 1
    assert "Connection refused" in error_results[0]["error"]


# ---------------------------------------------------------------------------
# crawl_domain – default max_depth regression test
# ---------------------------------------------------------------------------


def test_crawl_domain_default_max_depth_is_10():
    """Ensures the default max_depth has been raised from 2 to 10."""
    import inspect

    sig = inspect.signature(crawl_domain)
    assert sig.parameters["max_depth"].default == 10


# ---------------------------------------------------------------------------
# fetch_html – default timeout regression test
# ---------------------------------------------------------------------------


def test_fetch_html_default_timeout_is_20():
    """Default timeout was raised from 15 to 20 for SPA support."""
    import inspect

    sig = inspect.signature(fetch_html)
    assert sig.parameters["timeout"].default == 20


# ---------------------------------------------------------------------------
# SPA content selectors are defined
# ---------------------------------------------------------------------------


def test_spa_content_selectors_exist():
    from app.crawler.crawler import SPA_CONTENT_SELECTORS

    assert isinstance(SPA_CONTENT_SELECTORS, list)
    assert len(SPA_CONTENT_SELECTORS) > 0
    # Must include food-details selector for fdc.nal.usda.gov
    assert any("food-details" in s for s in SPA_CONTENT_SELECTORS)


# ---------------------------------------------------------------------------
# crawl_domain – discovers SPA-rendered links
# ---------------------------------------------------------------------------


def test_crawl_domain_discovers_js_rendered_food_detail_links(monkeypatch):
    """Simulates an SPA where JS-rendered page contains food-detail links
    that only appear after Playwright renders the page."""
    pages = {
        "https://fdc.nal.usda.gov": """
            <html><body>
                <a href="/food-search">Food Search</a>
                <a href="/faq">FAQ</a>
            </body></html>
        """,
        "https://fdc.nal.usda.gov/food-search": """
            <html><body>
                <table>
                    <tr><td><a href="/food-details/123/nutrients">Almond Butter</a></td></tr>
                    <tr><td><a href="/food-details/456/nutrients">Bananas</a></td></tr>
                    <tr><td><a href="/food-details/789/nutrients">Chicken</a></td></tr>
                </table>
            </body></html>
        """,
        "https://fdc.nal.usda.gov/faq": "<html><body>FAQ content</body></html>",
        "https://fdc.nal.usda.gov/food-details/123/nutrients": "<html><body>Almond details</body></html>",
        "https://fdc.nal.usda.gov/food-details/456/nutrients": "<html><body>Banana details</body></html>",
        "https://fdc.nal.usda.gov/food-details/789/nutrients": "<html><body>Chicken details</body></html>",
    }

    def fake_fetch_html(url, use_playwright=False, timeout=20):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://fdc.nal.usda.gov", max_pages=10, max_depth=5)
    visited_urls = [r["url"] for r in results]

    # Must reach food-details pages
    assert "https://fdc.nal.usda.gov/food-details/123/nutrients" in visited_urls
    assert "https://fdc.nal.usda.gov/food-details/456/nutrients" in visited_urls
    assert "https://fdc.nal.usda.gov/food-details/789/nutrients" in visited_urls


# ---------------------------------------------------------------------------
# crawl_domain – on_progress callback
# ---------------------------------------------------------------------------


def test_crawl_domain_calls_on_progress(monkeypatch):
    pages = {
        "https://example.com": "<html><body>Hello</body></html>",
    }

    def fake_fetch_html(url, use_playwright=False, timeout=20):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    messages = []

    def collect_progress(message, visited=0, total=0, current_url=""):
        messages.append(message)

    crawl_domain("https://example.com", max_pages=1, max_depth=1, on_progress=collect_progress)

    assert len(messages) >= 1
    assert any("Besuche" in m for m in messages)


# ---------------------------------------------------------------------------
# crawl_domain – duplicate URLs not visited twice
# ---------------------------------------------------------------------------


def test_crawl_domain_skips_duplicate_urls(monkeypatch):
    """Same link appearing on multiple pages should only be visited once."""
    pages = {
        "https://example.com": '<a href="/a">A</a><a href="/b">B</a>',
        "https://example.com/a": '<a href="/b">B again</a>',
        "https://example.com/b": "<html><body>B</body></html>",
    }

    def fake_fetch_html(url, use_playwright=False, timeout=20):
        return pages.get(url, "<html></html>"), "mock", ""

    monkeypatch.setattr("app.crawler.crawler.fetch_html", fake_fetch_html)

    results = crawl_domain("https://example.com", max_pages=10, max_depth=5)
    urls = [r["url"] for r in results]
    assert urls.count("https://example.com/b") == 1
