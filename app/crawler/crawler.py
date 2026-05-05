from __future__ import annotations

import asyncio
import sys
from contextlib import contextmanager
from dataclasses import dataclass
from heapq import heappop, heappush
from itertools import count
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlsplit, urlunsplit, urldefrag

import requests
from bs4 import BeautifulSoup, Tag


HEADERS = {
    "User-Agent": "WebResearchTool/0.7 (+standardized chromium crawler)",
    "Accept-Language": "de-DE,de;q=0.9,en;q=0.8",
}

CRAWLER_VIEWPORT = {"width": 1366, "height": 768}
CRAWLER_LOCALE = "de-DE"
CRAWLER_TIMEZONE = "Europe/Berlin"

HIGH_PRIORITY_PATTERNS = [
    "/product/",
    "/products/",
    "/product?",
    "/products?",
    "/category/",
    "/categories/",
    "/nutrition",
    "/ingredients",
    "/search",
]

NAVIGATION_PATTERNS = [
    "/discover",
    "/contribute",
    "/who-we-are",
    "/vision",
    "/mission",
    "/values",
    "/press",
    "/legal",
    "/privacy",
    "/terms",
    "/code-of-conduct",
    "/partners",
]

LOW_PRIORITY_PATTERNS = [
    "/session",
    "/sign-in",
    "/signin",
    "/login",
    "/logout",
    "/donate",
]

SKIPPED_SCHEMES = ("javascript:", "mailto:", "tel:", "data:")
NON_HTML_EXTENSIONS = (
    ".jpg",
    ".jpeg",
    ".png",
    ".gif",
    ".svg",
    ".webp",
    ".pdf",
    ".zip",
    ".xml",
    ".json",
)
TRACKING_QUERY_PARAMS = {"fbclid", "gclid", "mc_cid", "mc_eid"}


@dataclass(frozen=True)
class LinkCandidate:
    """Represents a discovered link with its crawl priority.

    Attributes:
        url: The absolute, normalized URL of the link.
        priority: Numeric priority score (lower = higher priority).
    """

    url: str
    priority: int


@contextmanager
def _playwright_event_loop_policy():
    """Context manager that ensures Windows uses the Proactor event loop policy.

    Required for Playwright compatibility on Windows. Restores the original
    policy on exit. No-op on non-Windows platforms.

    Yields:
        None
    """
    previous_policy = None
    restore_policy = False

    if sys.platform == "win32" and hasattr(asyncio, "WindowsProactorEventLoopPolicy"):
        current_policy = asyncio.get_event_loop_policy()
        if not isinstance(current_policy, asyncio.WindowsProactorEventLoopPolicy):
            previous_policy = current_policy
            asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())
            restore_policy = True

    try:
        yield
    finally:
        if restore_policy and previous_policy is not None:
            asyncio.set_event_loop_policy(previous_policy)


def _emit_progress(on_progress, message: str, visited: int = 0, total: int = 0, current_url: str = "") -> None:
    """Safely invoke the progress callback, suppressing any exceptions.

    Args:
        on_progress: Callback function to receive progress updates.
        message: Human-readable status message.
        visited: Number of pages visited so far.
        total: Maximum number of pages to crawl.
        current_url: URL currently being processed.
    """
    if not callable(on_progress):
        return
    try:
        on_progress(message, visited, total, current_url)
    except Exception:
        pass


def normalize_url(url: str) -> str:
    """Normalize a URL by removing fragments, trailing slashes, and tracking parameters.

    Strips UTM parameters, known tracking query params (fbclid, gclid, etc.),
    and normalizes the path for consistent deduplication.

    Args:
        url: Raw URL string to normalize.

    Returns:
        Cleaned, canonical URL string.
    """
    clean, _ = urldefrag(url.strip())
    split = urlsplit(clean)
    # Strip tracking params (utm_*, fbclid, etc.) so the same page isn't crawled twice
    filtered_query = urlencode(
        [
            (key, value)
            for key, value in parse_qsl(split.query, keep_blank_values=True)
            if key.lower() not in TRACKING_QUERY_PARAMS and not key.lower().startswith("utm_")
        ],
        doseq=True,
    )
    path = split.path.rstrip("/")
    return urlunsplit((split.scheme, split.netloc, path, filtered_query, ""))


def fetch_html_requests(url: str, timeout: int = 15) -> str:
    """Fetch page HTML using the requests library.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Raw HTML content as a string.

    Raises:
        requests.HTTPError: If the server returns an error status code.
    """
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()
    return response.text


def fetch_html_playwright(url: str, timeout_ms: int = 20000) -> str:
    """Fetch page HTML using a headless Chromium browser via Playwright.

    Waits for ``networkidle`` first, falling back to ``domcontentloaded``.
    After navigation, waits for SPA content selectors to ensure JS-rendered
    links (e.g. food-detail tables) are present in the DOM.

    Args:
        url: URL to fetch.
        timeout_ms: Navigation timeout in milliseconds.

    Returns:
        Fully rendered HTML content as a string.
    """
    with _playwright_event_loop_policy():
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(
                user_agent=HEADERS["User-Agent"],
                locale=CRAWLER_LOCALE,
                timezone_id=CRAWLER_TIMEZONE,
                viewport=CRAWLER_VIEWPORT,
                extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
            )
            page = context.new_page()
            # networkidle waits for no inflight requests; fall back to domcontentloaded
            # if the page never becomes fully idle (e.g. long-polling, websockets)
            try:
                page.goto(url, wait_until="networkidle", timeout=timeout_ms)
            except Exception:
                try:
                    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                except Exception:
                    pass

            _wait_for_spa_content(page)

            html = page.content()
            context.close()
            browser.close()
            return html


SPA_CONTENT_SELECTORS = [
    "table a[href]",
    "a[href*='/product']",
    "a[href*='/food-details']",
    "a[href*='/item']",
    "[class*='product'] a",
    "[class*='result'] a",
    "main a[href]",
]

SPA_WAIT_TIMEOUT_MS = 5000


def _wait_for_spa_content(page) -> None:
    """Wait for JS frameworks to finish rendering dynamic content.

    Iterates through ``SPA_CONTENT_SELECTORS`` and returns as soon as any
    selector is found in the DOM. Falls back to a short 1.5 s delay if
    none of the selectors appear within ``SPA_WAIT_TIMEOUT_MS``.

    Args:
        page: Playwright Page object to wait on.
    """
    for selector in SPA_CONTENT_SELECTORS:
        try:
            page.wait_for_selector(selector, timeout=SPA_WAIT_TIMEOUT_MS)
            return
        except Exception:
            continue
    # None of the SPA selectors appeared; give JS frameworks a last chance to render
    try:
        page.wait_for_timeout(1500)
    except Exception:
        pass


def fetch_html(url: str, use_playwright: bool = False, timeout: int = 20) -> tuple[str, str, str]:
    """Fetch HTML content from a URL with automatic fallback.

    When ``use_playwright`` is True, attempts Playwright first. If that fails,
    falls back to the requests library. Reports the fetch method used.

    Args:
        url: URL to fetch.
        use_playwright: Whether to try Playwright (headless Chromium) first.
        timeout: Timeout in seconds (converted to ms for Playwright).

    Returns:
        Tuple of (html_content, fetch_method, fetch_error_message).
        ``fetch_method`` is one of ``"chromium-standardized"``,
        ``"requests-fallback"``, or ``"requests"``.

    Raises:
        RuntimeError: If all fetch strategies fail.
    """
    if use_playwright:
        try:
            html = fetch_html_playwright(url, timeout_ms=timeout * 1000)
            if not html.strip():
                raise RuntimeError("Empty HTML returned by standardized Chromium crawler")
            return html, "chromium-standardized", ""
        except Exception as exc:
            playwright_error = f"{type(exc).__name__}: {exc}"
            try:
                html = fetch_html_requests(url, timeout=timeout)
                if not html.strip():
                    raise RuntimeError("Empty HTML returned by requests fallback")
                return html, "requests-fallback", f"Chromium failed: {playwright_error}"
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Chromium failed: {playwright_error}; requests fallback failed: {fallback_exc}"
                ) from fallback_exc

    html = fetch_html_requests(url, timeout=timeout)
    if not html.strip():
        raise RuntimeError("Empty HTML returned by requests-only mode")
    return html, "requests", ""


def _tag_class_tokens(tag: Tag | None) -> list[str]:
    """Extract lowercased CSS class tokens from a BeautifulSoup tag.

    Args:
        tag: A BeautifulSoup ``Tag`` or ``None``.

    Returns:
        List of lowercase, trimmed class name strings.
    """
    if not tag:
        return []
    classes = tag.get("class") or []
    return [str(item).strip().lower() for item in classes if str(item).strip()]


def _looks_like_product_card(anchor: Tag) -> bool:
    """Heuristically determine whether an anchor element is part of a product card.

    Inspects CSS class names on the anchor, its parent, and up to 12 descendants
    for product-related keywords such as ``product-card`` or ``list_product``.

    Args:
        anchor: An ``<a>`` tag from BeautifulSoup.

    Returns:
        True if the anchor likely represents a product listing card.
    """
    # Collect CSS classes from the anchor, its parent, and up to 12 descendants
    # to catch product-card patterns regardless of nesting depth
    class_tokens = _tag_class_tokens(anchor)
    if isinstance(anchor.parent, Tag):
        class_tokens.extend(_tag_class_tokens(anchor.parent))

    for descendant in anchor.find_all(class_=True, limit=12):
        class_tokens.extend(_tag_class_tokens(descendant))

    return any(
        "list_product" in token
        or "product-card" in token
        or "product_card" in token
        or ("product" in token and any(part in token for part in ("list", "card", "item", "grid", "result")))
        for token in class_tokens
    )


def _is_probably_html_link(url: str) -> bool:
    """Check whether a URL likely points to an HTML page.

    Rejects URLs whose path ends with known non-HTML extensions
    (images, PDFs, archives, etc.).

    Args:
        url: Absolute URL to inspect.

    Returns:
        True if the URL is probably an HTML page.
    """
    path = urlparse(url).path.lower()
    return not any(path.endswith(extension) for extension in NON_HTML_EXTENSIONS)


def link_priority_score(url: str, anchor: Tag | None = None) -> int:
    """Compute a numeric priority score for a discovered link.

    Lower scores indicate higher crawl priority. Product pages and
    product-card anchors receive the lowest scores, while login/session
    pages receive the highest.

    Args:
        url: Absolute URL of the link.
        anchor: Optional BeautifulSoup ``<a>`` tag for product-card heuristics.

    Returns:
        Integer priority score (lower = crawl sooner).
    """
    # Lower score = higher crawl priority. Base 100, adjusted by URL patterns.
    url_lower = url.lower()
    parsed = urlparse(url_lower)
    path = parsed.path.strip("/")
    score = 100

    for pattern in LOW_PRIORITY_PATTERNS:
        if pattern in url_lower:
            score += 160

    for pattern in NAVIGATION_PATTERNS:
        if pattern in url_lower:
            score += 70

    # Numeric-only paths (e.g. /12345) are likely detail page IDs
    if path.isdigit():
        score -= 60

    for pattern in HIGH_PRIORITY_PATTERNS:
        if pattern in url_lower:
            score -= 40
            break

    if "/product/" in url_lower:
        score -= 80

    if parsed.query:
        score += 10

    if anchor and _looks_like_product_card(anchor):
        score -= 70

    return score


def extract_link_candidates(base_url: str, html: str) -> list[LinkCandidate]:
    """Extract and prioritize all internal link candidates from an HTML page.

    Resolves relative URLs, normalizes them, deduplicates, filters out
    non-HTML resources and skipped schemes, then sorts by priority score.

    Args:
        base_url: The page URL used to resolve relative hrefs.
        html: Raw HTML content of the page.

    Returns:
        List of ``LinkCandidate`` objects sorted by priority (lowest first).
    """
    soup = BeautifulSoup(html, "lxml")
    candidates: list[tuple[int, LinkCandidate]] = []
    seen: set[str] = set()

    for index, anchor in enumerate(soup.find_all("a", href=True)):
        href = str(anchor.get("href", "")).strip()
        if not href or href.lower().startswith(SKIPPED_SCHEMES):
            continue

        absolute = urljoin(base_url, href)
        absolute = normalize_url(absolute)

        if not absolute.startswith(("http://", "https://")):
            continue

        if not _is_probably_html_link(absolute):
            continue

        if absolute in seen:
            continue

        seen.add(absolute)
        candidates.append((index, LinkCandidate(url=absolute, priority=link_priority_score(absolute, anchor=anchor))))

    # Sort by priority; use original DOM order (index) as tiebreaker for stability
    candidates.sort(key=lambda item: (item[1].priority, item[0]))
    return [candidate for _, candidate in candidates]


def extract_links(base_url: str, html: str) -> list[str]:
    """Extract all link URLs from an HTML page, sorted by priority.

    Args:
        base_url: The page URL used to resolve relative hrefs.
        html: Raw HTML content of the page.

    Returns:
        List of absolute, normalized URL strings.
    """
    return [candidate.url for candidate in extract_link_candidates(base_url, html)]


def is_same_domain(start_url: str, candidate_url: str) -> bool:
    """Check whether two URLs share the same domain (netloc).

    Args:
        start_url: The reference URL (typically the crawl start URL).
        candidate_url: The URL to compare against.

    Returns:
        True if both URLs have the same network location.
    """
    return urlparse(start_url).netloc == urlparse(candidate_url).netloc


def sort_links_for_queue(links: list[str]) -> list[str]:
    """Sort a list of URLs by their crawl priority score.

    Args:
        links: List of absolute URL strings.

    Returns:
        New list sorted by priority (lowest score / highest priority first).
    """
    return sorted(links, key=lambda link: link_priority_score(link))


def crawl_domain(
    start_url: str,
    max_pages: int = 20,
    max_depth: int = 10,
    use_playwright: bool = False,
    on_progress=None,
) -> list[dict]:
    """Crawl a domain starting from the given URL using BFS with priority queue.

    Discovers and follows internal links up to ``max_pages`` visited pages and
    ``max_depth`` link hops. Uses a min-heap ordered by link priority so that
    product and content pages are visited before navigation/login pages.

    Args:
        start_url: The seed URL to begin crawling.
        max_pages: Maximum number of pages to visit.
        max_depth: Maximum link depth from the start URL.
        use_playwright: Whether to use headless Chromium for JS-rendered pages.
        on_progress: Optional callback ``(message, visited, total, current_url)``
            invoked after each page fetch.

    Returns:
        List of result dicts, each containing ``url``, ``depth``, ``html``,
        ``links``, ``status``, ``error``, ``fetch_method``, and ``fetch_error``.
    """
    start_url = normalize_url(start_url)
    playwright_enabled = use_playwright
    visited: set[str] = set()
    queued: set[str] = {start_url}
    visit_order = count()
    # Min-heap entries: (priority, depth, insertion_order, url)
    # insertion_order breaks ties so heapq never compares url strings
    queue: list[tuple[int, int, int, str]] = []
    heappush(queue, (0, 0, next(visit_order), start_url))
    results: list[dict] = []

    while queue and len(visited) < max_pages:
        _, depth, _, current_url = heappop(queue)

        if current_url in visited:
            continue

        visited.add(current_url)
        _emit_progress(on_progress, f"Besuche: {current_url}", visited=len(visited), total=max_pages, current_url=current_url)

        try:
            html, fetch_method, fetch_error = fetch_html(current_url, use_playwright=playwright_enabled, timeout=20)

            # If Playwright already failed once, stop retrying it for remaining pages
            if fetch_method == "requests-fallback" and fetch_error:
                playwright_enabled = False

            link_candidates = extract_link_candidates(current_url, html)
            links = [candidate.url for candidate in link_candidates]

            results.append(
                {
                    "url": current_url,
                    "depth": depth,
                    "html": html,
                    "links": links,
                    "status": "ok",
                    "error": "",
                    "fetch_method": fetch_method,
                    "fetch_error": fetch_error,
                }
            )

            _emit_progress(on_progress, f"Fertig: {current_url} ({fetch_method})", visited=len(visited), total=max_pages, current_url=current_url)

            if depth < max_depth:
                internal_candidates = [
                    candidate
                    for candidate in link_candidates
                    if is_same_domain(start_url, candidate.url)
                    and candidate.url not in visited
                    and candidate.url not in queued
                ]

                for candidate in internal_candidates:
                    heappush(queue, (candidate.priority, depth + 1, next(visit_order), candidate.url))
                    queued.add(candidate.url)

        except Exception as exc:
            results.append(
                {
                    "url": current_url,
                    "depth": depth,
                    "html": "",
                    "links": [],
                    "status": "error",
                    "error": str(exc),
                    "fetch_method": "error",
                    "fetch_error": "",
                }
            )
            _emit_progress(on_progress, f"Fehler bei {current_url}: {exc}", visited=len(visited), total=max_pages, current_url=current_url)

    return results