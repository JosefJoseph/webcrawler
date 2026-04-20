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


HEADERS = {"User-Agent": "WebResearchTool/0.6 (+playwright prioritized crawler)"}

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
    url: str
    priority: int


@contextmanager
def _playwright_event_loop_policy():
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


def normalize_url(url: str) -> str:
    clean, _ = urldefrag(url.strip())
    split = urlsplit(clean)
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
    response = requests.get(url, headers=HEADERS, timeout=timeout)
    response.raise_for_status()
    return response.text


def fetch_html_playwright(url: str, timeout_ms: int = 20000) -> str:
    with _playwright_event_loop_policy():
        from playwright.sync_api import sync_playwright

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context(user_agent=HEADERS["User-Agent"])
            page = context.new_page()
            page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            try:
                page.wait_for_load_state("networkidle", timeout=5000)
            except Exception:
                pass
            try:
                page.wait_for_timeout(1500)
            except Exception:
                pass
            html = page.content()
            context.close()
            browser.close()
            return html


def fetch_html(url: str, use_playwright: bool = False, timeout: int = 15) -> tuple[str, str, str]:
    if use_playwright:
        try:
            return fetch_html_playwright(url, timeout_ms=timeout * 1000), "playwright", ""
        except Exception as exc:
            playwright_error = f"{type(exc).__name__}: {exc}"
            try:
                return (
                    fetch_html_requests(url, timeout=timeout),
                    "requests-fallback",
                    f"Playwright failed: {playwright_error}",
                )
            except Exception as fallback_exc:
                raise RuntimeError(
                    f"Playwright failed: {playwright_error}; requests fallback failed: {fallback_exc}"
                ) from fallback_exc
    return fetch_html_requests(url, timeout=timeout), "requests", ""


def _tag_class_tokens(tag: Tag | None) -> list[str]:
    if not tag:
        return []
    classes = tag.get("class") or []
    return [str(item).strip().lower() for item in classes if str(item).strip()]


def _looks_like_product_card(anchor: Tag) -> bool:
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
    path = urlparse(url).path.lower()
    return not any(path.endswith(extension) for extension in NON_HTML_EXTENSIONS)


def link_priority_score(url: str, anchor: Tag | None = None) -> int:
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
    return [candidate.url for candidate in extract_link_candidates(base_url, html)]


def is_same_domain(start_url: str, candidate_url: str) -> bool:
    return urlparse(start_url).netloc == urlparse(candidate_url).netloc


def sort_links_for_queue(links: list[str]) -> list[str]:
    return sorted(links, key=lambda link: link_priority_score(link))


def crawl_domain(
    start_url: str,
    max_pages: int = 20,
    max_depth: int = 2,
    use_playwright: bool = False,
) -> list[dict]:
    start_url = normalize_url(start_url)
    playwright_enabled = use_playwright
    visited: set[str] = set()
    queued: set[str] = {start_url}
    visit_order = count()
    queue: list[tuple[int, int, int, str]] = []
    heappush(queue, (0, 0, next(visit_order), start_url))
    results: list[dict] = []

    while queue and len(visited) < max_pages:
        _, depth, _, current_url = heappop(queue)

        if current_url in visited:
            continue

        visited.add(current_url)

        try:
            html, fetch_method, fetch_error = fetch_html(current_url, use_playwright=playwright_enabled)
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

            if depth < max_depth:
                internal_candidates = [
                    candidate for candidate in link_candidates
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

    return results
