from __future__ import annotations

import asyncio
import sys
import time
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

# Maximum response body size to process (10 MB)
MAX_CONTENT_BYTES = 10 * 1024 * 1024
ALLOWED_CONTENT_TYPES = ("text/html", "application/xhtml+xml")

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

# Retry / back-off settings
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 1.0  # seconds; doubled each retry

# Minimum delay between requests to the same host (polite crawling)
DEFAULT_REQUEST_DELAY = 0.5  # seconds


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
    """Safely invoke the progress callback, suppressing any exceptions."""
    if not callable(on_progress):
        return
    try:
        on_progress(message, visited, total, current_url)
    except Exception:
        pass


def _emit_event(on_event, stage: str, message: str = "", **fields) -> None:
    """Safely invoke the structured event callback."""
    if callable(on_event):
        try:
            on_event(stage, message, **fields)
        except Exception:
            pass


def normalize_url(url: str) -> str:
    """Normalize a URL for consistent deduplication.

    - Lowercases scheme and host.
    - Removes default ports (80 for http, 443 for https).
    - Strips URL fragment.
    - Removes trailing slashes from path.
    - Strips UTM / known tracking query params.

    Args:
        url: Raw URL string to normalize.

    Returns:
        Cleaned, canonical URL string.
    """
    clean, _ = urldefrag(url.strip())
    split = urlsplit(clean)

    # Lowercase scheme and host
    scheme = split.scheme.lower()
    netloc = split.netloc.lower()

    # Remove default ports
    host = split.hostname or ""
    port = split.port
    if port and ((scheme == "http" and port == 80) or (scheme == "https" and port == 443)):
        netloc = host  # drop port
    else:
        netloc = netloc  # keep as-is (already lowercased)

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
    return urlunsplit((scheme, netloc, path, filtered_query, ""))


def fetch_html_requests(url: str, timeout: int = 15) -> tuple[str, str]:
    """Fetch page HTML using the requests library.

    Validates content-type and size. Returns the final (post-redirect) URL.

    Args:
        url: URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Tuple of (html_content, final_url).

    Raises:
        requests.HTTPError: If the server returns an error status code.
        ValueError: If content-type is not HTML or response is too large.
    """
    response = requests.get(
        url,
        headers=HEADERS,
        timeout=timeout,
        allow_redirects=True,
    )
    response.raise_for_status()

    final_url = response.url

    content_type = response.headers.get("Content-Type", "").lower().split(";")[0].strip()
    if content_type and not any(ct in content_type for ct in ALLOWED_CONTENT_TYPES):
        raise ValueError(f"Non-HTML content-type: {content_type!r}")

    content_length = len(response.content)
    if content_length > MAX_CONTENT_BYTES:
        raise ValueError(f"Response too large: {content_length} bytes")

    return response.text, final_url


def fetch_html_playwright(url: str, timeout_ms: int = 20000) -> tuple[str, str]:
    """Fetch page HTML using a headless Chromium browser via Playwright.

    Waits for ``networkidle`` first, falling back to ``domcontentloaded``.
    After navigation, waits for SPA content selectors to ensure JS-rendered
    links (e.g. food-detail tables) are present in the DOM.

    Returns:
        Tuple of (html_content, final_url). Browser/context/page are always
        closed in finally blocks.

    Raises:
        RuntimeError: If both navigation strategies fail.
    """
    with _playwright_event_loop_policy():
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            try:
                context = browser.new_context(
                    user_agent=HEADERS["User-Agent"],
                    locale=CRAWLER_LOCALE,
                    timezone_id=CRAWLER_TIMEZONE,
                    viewport=CRAWLER_VIEWPORT,
                    extra_http_headers={"Accept-Language": HEADERS["Accept-Language"]},
                )
                try:
                    page = context.new_page()
                    nav_error: Exception | None = None
                    try:
                        page.goto(url, wait_until="networkidle", timeout=timeout_ms)
                    except Exception as exc:
                        nav_error = exc
                        try:
                            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                            nav_error = None
                        except Exception as exc2:
                            # Both strategies failed — raise a descriptive error
                            raise RuntimeError(
                                f"Playwright navigation failed: networkidle: {nav_error}; "
                                f"domcontentloaded: {exc2}"
                            ) from exc2

                    _wait_for_spa_content(page)
                    html = page.content()
                    final_url = page.url
                finally:
                    # Close page and context in a single finally block
                    try:
                        page.close()
                    except Exception:
                        pass
                    try:
                        context.close()
                    except Exception:
                        pass
            finally:
                try:
                    browser.close()
                except Exception:
                    pass

            return html, final_url


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


def _fetch_with_retry(
    url: str,
    use_playwright: bool,
    timeout: int,
    max_retries: int = MAX_RETRIES,
) -> tuple[str, str, str, str]:
    """Fetch HTML with exponential back-off retries.

    Args:
        url: URL to fetch.
        use_playwright: Whether to try Playwright first.
        timeout: Timeout in seconds.
        max_retries: Maximum number of attempts.

    Returns:
        Tuple of (html_content, final_url, fetch_method, fetch_error).

    Raises:
        RuntimeError: If all retries are exhausted.
    """
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        if attempt > 0:
            delay = RETRY_BACKOFF_BASE * (2 ** (attempt - 1))
            time.sleep(delay)
        try:
            html, final_url, method, error = fetch_html(url, use_playwright=use_playwright, timeout=timeout)
            return html, final_url, method, error
        except Exception as exc:
            last_exc = exc

    raise RuntimeError(f"All {max_retries} retries failed for {url}: {last_exc}") from last_exc


def fetch_html(url: str, use_playwright: bool = False, timeout: int = 20) -> tuple[str, str, str, str]:
    """Fetch HTML content from a URL with automatic fallback.

    When ``use_playwright`` is True, attempts Playwright first. If that fails,
    falls back to the requests library. Reports the fetch method used.

    Args:
        url: URL to fetch.
        use_playwright: Whether to try Playwright (headless Chromium) first.
        timeout: Timeout in seconds (converted to ms for Playwright).

    Returns:
        Tuple of (html_content, final_url, fetch_method, fetch_error_message).
        ``fetch_method`` is one of ``"chromium-standardized"``,
        ``"requests-fallback"``, or ``"requests"``.

    Raises:
        RuntimeError: If all fetch strategies fail.
    """
    if use_playwright:
        try:
            html, final_url = fetch_html_playwright(url, timeout_ms=timeout * 1000)
            if not html.strip():
                raise RuntimeError("Empty HTML returned by standardized Chromium crawler")
            return html, final_url, "chromium-standardized", ""
        except Exception as exc:
            playwright_error = f"{type(exc).__name__}: {exc}"
            try:
                html, final_url = fetch_html_requests(url, timeout=timeout)
                if not html.strip():
                    raise RuntimeError("Empty HTML returned by requests fallback")
                return html, final_url, "requests-fallback", f"Chromium failed: {playwright_error}"
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Chromium failed: {playwright_error}; requests fallback failed: {fallback_exc}"
                ) from fallback_exc

    html, final_url = fetch_html_requests(url, timeout=timeout)
    if not html.strip():
        raise RuntimeError("Empty HTML returned by requests-only mode")
    return html, final_url, "requests", ""


def _tag_class_tokens(tag: Tag | None) -> list[str]:
    """Extract lowercased CSS class tokens from a BeautifulSoup tag."""
    if not tag:
        return []
    classes = tag.get("class") or []
    return [str(item).strip().lower() for item in classes if str(item).strip()]


def _looks_like_product_card(anchor: Tag) -> bool:
    """Heuristically determine whether an anchor element is part of a product card."""
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
    """Check whether a URL likely points to an HTML page."""
    path = urlparse(url).path.lower()
    return not any(path.endswith(extension) for extension in NON_HTML_EXTENSIONS)


def link_priority_score(url: str, anchor: Tag | None = None) -> int:
    """Compute a numeric priority score for a discovered link."""
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
    """Extract and prioritize all internal link candidates from an HTML page."""
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

    candidates.sort(key=lambda item: (item[1].priority, item[0]))
    return [candidate for _, candidate in candidates]


def extract_links(base_url: str, html: str) -> list[str]:
    """Extract all link URLs from an HTML page, sorted by priority."""
    return [candidate.url for candidate in extract_link_candidates(base_url, html)]


def is_same_domain(start_url: str, candidate_url: str) -> bool:
    """Check whether two URLs share the same domain (netloc)."""
    return urlparse(start_url).netloc == urlparse(candidate_url).netloc


def sort_links_for_queue(links: list[str]) -> list[str]:
    """Sort a list of URLs by their crawl priority score."""
    return sorted(links, key=lambda link: link_priority_score(link))





def crawl_domain(
    start_url: str,
    max_pages: int = 20,
    max_depth: int = 10,
    use_playwright: bool = False,
    on_progress=None,
    on_event=None,
    request_delay: float = DEFAULT_REQUEST_DELAY,
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
        request_delay: Minimum seconds to wait between requests (polite crawling).

    Returns:
        List of result dicts, each containing ``url``, ``final_url``, ``depth``,
        ``html``, ``links``, ``status``, ``error``, ``fetch_method``,
        and ``fetch_error``.
    """
    start_url = normalize_url(start_url)
    playwright_enabled = use_playwright

    visited: set[str] = set()
    queued: set[str] = {start_url}
    visit_order = count()
    queue: list[tuple[int, int, int, str]] = []
    heappush(queue, (0, 0, next(visit_order), start_url))
    results: list[dict] = []
    last_request_time: float = 0.0

    _emit_event(
        on_event, "CRAWLER", "start",
        start_url=start_url,
        max_pages=max_pages,
        max_depth=max_depth,
        use_playwright=use_playwright,
    )

    while queue and len(visited) < max_pages:
        _, depth, _, current_url = heappop(queue)

        _emit_event(
            on_event, "QUEUE", "pop",
            url=current_url,
            depth=depth,
            queue_size=len(queue),
            visited=len(visited),
        )

        if current_url in visited:
            _emit_event(on_event, "QUEUE", "skip_duplicate", url=current_url)
            continue

        visited.add(current_url)
        _emit_progress(on_progress, f"Besuche: {current_url}", visited=len(visited), total=max_pages, current_url=current_url)

        # Polite delay between requests
        now = time.monotonic()
        wait = request_delay - (now - last_request_time)
        if wait > 0:
            time.sleep(wait)
        last_request_time = time.monotonic()

        _emit_event(
            on_event, "FETCH_START", "",
            url=current_url,
            depth=depth,
            method_preference="playwright" if playwright_enabled else "requests",
        )

        try:
            html, final_url, fetch_method, fetch_error = fetch_html(
                current_url, use_playwright=playwright_enabled, timeout=20
            )

            # If the final URL after redirect was normalized differently, record it
            final_url_normalized = normalize_url(final_url) if final_url else current_url

            # If Playwright already failed once, stop retrying it for remaining pages
            if fetch_method == "requests-fallback" and fetch_error:
                playwright_enabled = False

            link_candidates = extract_link_candidates(final_url_normalized, html)
            links = [candidate.url for candidate in link_candidates]

            _emit_event(
                on_event, "FETCH_OK", "",
                url=current_url,
                final_url=final_url_normalized,
                method=fetch_method,
                html_chars=len(html),
                links=len(links),
                depth=depth,
            )

            results.append(
                {
                    "url": current_url,
                    "final_url": final_url_normalized,
                    "depth": depth,
                    "html": html,
                    "links": links,
                    "status": "ok",
                    "error": "",
                    "fetch_method": fetch_method,
                    "fetch_error": fetch_error,
                    "status_code": 0,
                    "content_type": "",
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
                    _emit_event(
                        on_event, "QUEUE", "enqueue",
                        url=candidate.url,
                        depth=depth + 1,
                        priority=candidate.priority,
                    )

                # Log links skipped due to external domain or already visited
                for candidate in link_candidates:
                    if not is_same_domain(start_url, candidate.url):
                        _emit_event(
                            on_event, "QUEUE", "skip_external",
                            url=candidate.url,
                            reason="different_domain",
                        )
            else:
                for candidate in link_candidates:
                    if is_same_domain(start_url, candidate.url) and candidate.url not in visited:
                        _emit_event(
                            on_event, "QUEUE", "skip_depth",
                            url=candidate.url,
                            depth=depth + 1,
                            max_depth=max_depth,
                        )

        except Exception as exc:
            _emit_event(
                on_event, "FETCH_ERROR", "",
                url=current_url,
                depth=depth,
                error_type=type(exc).__name__,
                error=str(exc)[:200],
            )
            results.append(
                {
                    "url": current_url,
                    "final_url": current_url,
                    "depth": depth,
                    "html": "",
                    "links": [],
                    "status": "error",
                    "error": str(exc),
                    "fetch_method": "error",
                    "fetch_error": "",
                    "status_code": 0,
                    "content_type": "",
                }
            )
            _emit_progress(on_progress, f"Fehler bei {current_url}: {exc}", visited=len(visited), total=max_pages, current_url=current_url)

    ok_count = sum(1 for r in results if r.get("status") == "ok")
    err_count = sum(1 for r in results if r.get("status") == "error")
    _emit_event(
        on_event, "CRAWLER", "done",
        attempted=len(results),
        ok=ok_count,
        failed=err_count,
        queued_remaining=len(queue),
    )

    return results
