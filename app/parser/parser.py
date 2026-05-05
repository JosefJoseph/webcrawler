from __future__ import annotations

from bs4 import BeautifulSoup, Tag


ATTRIBUTE_FIELDS = [
    "alt",
    "title",
    "aria-label",
    "aria-description",
]

TEXT_BLOCK_TAGS = [
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "p",
    "li",
    "td",
    "th",
    "tr",
    "dd",
    "dt",
    "blockquote",
    "figcaption",
    "summary",
    "label",
    "div",
]

SHORT_TEXT_BLOCK_TAGS = {
    "h1",
    "h2",
    "h3",
    "h4",
    "h5",
    "h6",
    "label",
    "summary",
}

PASSAGE_HEADING_TAGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
PASSAGE_CONTENT_TAGS = ["p", "ul", "ol"]


def _normalize_text(text: str) -> str:
    """Collapse whitespace and strip a text string.

    Args:
        text: Raw text to normalize.

    Returns:
        Single-spaced, trimmed string.
    """
    return " ".join(text.split()).strip()


def _collect_attribute_texts(soup: BeautifulSoup) -> list[dict]:
    """Extract text from HTML attributes and meta tags.

    Collects values from ``alt``, ``title``, ``aria-label``, ``aria-description``
    attributes, plus ``<meta>`` tags for description, keywords, og:title, and
    og:description.

    Args:
        soup: Parsed BeautifulSoup document.

    Returns:
        List of dicts with ``source_type``, ``tag``, and ``text`` keys.
    """
    items: list[dict] = []

    for attr in ATTRIBUTE_FIELDS:
        for tag in soup.find_all(attrs={attr: True}):
            value = str(tag.get(attr, "")).strip()
            if value:
                items.append(
                    {
                        "source_type": f"attribute:{attr}",
                        "tag": tag.name,
                        "text": value,
                    }
                )

    for meta in soup.find_all("meta"):
        name = (meta.get("name") or "").strip().lower()
        prop = (meta.get("property") or "").strip().lower()
        content = str(meta.get("content") or "").strip()

        if not content:
            continue

        if name in {"description", "keywords"} or prop in {"og:title", "og:description"}:
            items.append(
                {
                    "source_type": "meta",
                    "tag": "meta",
                    "text": content,
                }
            )

    return items


def _is_leaf_div(tag: Tag) -> bool:
    """Check whether a ``<div>`` contains no nested block-level elements.

    Args:
        tag: A BeautifulSoup ``<div>`` tag.

    Returns:
        True if the div has no child tags matching ``TEXT_BLOCK_TAGS``.
    """
    return not any(
        isinstance(child, Tag) and child.name in TEXT_BLOCK_TAGS
        for child in tag.children
    )


def _has_non_div_block_ancestor(tag: Tag) -> bool:
    """Check whether the tag is nested inside a non-div block-level element.

    Prevents double-extraction of text that already belongs to a ``<p>``,
    ``<li>``, or similar parent.

    Args:
        tag: A BeautifulSoup tag to inspect.

    Returns:
        True if any ancestor (excluding ``<div>``) is in ``TEXT_BLOCK_TAGS``.
    """
    parent = tag.parent
    while isinstance(parent, Tag):
        if parent.name in TEXT_BLOCK_TAGS and parent.name != "div":
            return True
        parent = parent.parent
    return False


def _collect_text_blocks(soup: BeautifulSoup) -> list[dict]:
    """Extract meaningful text blocks from the HTML document.

    Iterates through block-level tags (``<p>``, ``<h1>``–``<h6>``, ``<li>``,
    ``<div>``, etc.), applies minimum length thresholds, and deduplicates.
    Falls back to the full visible document text if no blocks are found.

    Args:
        soup: Parsed BeautifulSoup document.

    Returns:
        List of dicts with ``block_id``, ``source_type``, ``tag``, and ``text``.
    """
    items: list[dict] = []
    seen: set[str] = set()
    block_index = 0

    for tag in soup.find_all(TEXT_BLOCK_TAGS):
        # Skip divs that contain nested block elements (their children will be extracted individually)
        if tag.name == "div" and not _is_leaf_div(tag):
            continue
        # Skip divs already inside a block-level parent to avoid double-extraction
        if tag.name == "div" and _has_non_div_block_ancestor(tag):
            continue

        text = _normalize_text(tag.get_text(separator=" ", strip=True))
        if not text:
            continue

        # Headings/labels need less text to be meaningful; body blocks need more
        min_length = 8 if tag.name in SHORT_TEXT_BLOCK_TAGS else 40
        if len(text) < min_length:
            continue

        # Overly long divs are typically layout wrappers, not content blocks
        if tag.name == "div" and len(text) > 1200:
            continue

        if text in seen:
            continue
        seen.add(text)

        items.append(
            {
                "block_id": f"block-{block_index}",
                "source_type": "text_block",
                "tag": tag.name,
                "text": text,
            }
        )
        block_index += 1

    if items:
        return items

    visible_text = _normalize_text(soup.get_text(separator=" ", strip=True))
    if not visible_text:
        return []

    return [
        {
            "block_id": "block-0",
            "source_type": "text_block",
            "tag": "document",
            "text": visible_text,
        }
    ]


def _extract_list_items(tag: Tag) -> list[str]:
    """Extract text content from ``<li>`` children of a list element.

    Tries direct children first (``recursive=False``), then falls back
    to all nested ``<li>`` elements.

    Args:
        tag: A ``<ul>`` or ``<ol>`` BeautifulSoup tag.

    Returns:
        List of non-empty, normalized text strings.
    """
    items = [
        _normalize_text(li.get_text(separator=" ", strip=True))
        for li in tag.find_all("li", recursive=False)
    ]

    if not items:
        items = [
            _normalize_text(li.get_text(separator=" ", strip=True))
            for li in tag.find_all("li")
        ]

    return [item for item in items if item]


def _collect_passage_blocks(soup: BeautifulSoup) -> list[dict]:
    """Extract heading-delimited passage blocks from the document.

    Groups consecutive paragraphs and lists under their preceding heading
    to form structured passage blocks. Each block captures the heading text,
    heading level, and combined content.

    Args:
        soup: Parsed BeautifulSoup document.

    Returns:
        List of passage dicts with ``block_id``, ``source_type``, ``tag``,
        ``heading``, ``heading_level``, and ``text``.
    """
    root = soup.body or soup
    items: list[dict] = []
    block_index = 0

    current_heading = ""
    current_heading_level: int | None = None
    current_parts: list[str] = []

    def flush_current_passage() -> None:
        nonlocal block_index, current_parts, current_heading, current_heading_level

        text = "\n".join(part for part in current_parts if part).strip()
        if not text:
            return

        items.append(
            {
                "block_id": f"passage-{block_index}",
                "source_type": "passage_block",
                "tag": "section",
                "heading": current_heading,
                "heading_level": current_heading_level,
                "text": text,
            }
        )
        block_index += 1
        current_parts = []

    for tag in root.find_all(PASSAGE_HEADING_TAGS + PASSAGE_CONTENT_TAGS):
        if not isinstance(tag, Tag):
            continue

        tag_name = tag.name.lower()

        if tag_name in PASSAGE_HEADING_TAGS:
            heading_text = _normalize_text(tag.get_text(separator=" ", strip=True))
            if not heading_text:
                continue

            flush_current_passage()
            current_heading = heading_text
            current_heading_level = int(tag_name[1])
            continue

        if tag_name == "p":
            paragraph_text = _normalize_text(tag.get_text(separator=" ", strip=True))
            if paragraph_text:
                current_parts.append(paragraph_text)
            continue

        if tag_name in {"ul", "ol"}:
            list_items = _extract_list_items(tag)
            if not list_items:
                continue

            if tag_name == "ul":
                current_parts.extend(f"- {item}" for item in list_items)
            else:
                current_parts.extend(f"{index}. {item}" for index, item in enumerate(list_items, start=1))

    flush_current_passage()
    return items


def parse_page(html: str) -> dict:
    """Parse an HTML page into structured text components.

    Removes ``<script>``, ``<style>``, and ``<noscript>`` tags, then extracts
    the page title, attribute texts, text blocks, passage blocks, and the
    full visible text.

    Args:
        html: Raw HTML string.

    Returns:
        Dict with keys ``title``, ``visible_text``, ``searchable_text``,
        ``attribute_texts``, ``text_blocks``, and ``passage_blocks``.
    """
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else "Ohne Titel"
    attribute_texts = _collect_attribute_texts(soup)
    raw_text_blocks = _collect_text_blocks(soup)
    passage_blocks = _collect_passage_blocks(soup)
    visible_text = _normalize_text(soup.get_text(separator=" ", strip=True))

    searchable_parts = [visible_text]
    searchable_parts.extend(item["text"] for item in attribute_texts)
    searchable_text = " ".join(part for part in searchable_parts if part).strip()

    return {
        "title": title,
        "visible_text": visible_text,
        "searchable_text": searchable_text,
        "attribute_texts": attribute_texts,
        "text_blocks": raw_text_blocks,
        "passage_blocks": passage_blocks,
    }


def build_page_result(page: dict) -> dict:
    """Build a unified page result from a raw crawl output dict.

    Parses the HTML (if available), extracts structured text, and merges it
    with crawl metadata (URL, depth, status, fetch method). Prefers passage
    blocks over raw text blocks when available.

    Args:
        page: Raw crawl result dict with ``html``, ``url``, ``depth``, etc.

    Returns:
        Enriched result dict ready for keyword filtering and export.
    """
    parsed = parse_page(page.get("html", "")) if page.get("html") else {
        "title": "Fehler",
        "visible_text": "",
        "searchable_text": "",
        "attribute_texts": [],
        "text_blocks": [],
        "passage_blocks": [],
    }

    # Prefer passage blocks (heading-grouped) over raw text blocks for richer structure
    effective_text_blocks = parsed["passage_blocks"] if parsed["passage_blocks"] else parsed["text_blocks"]

    return {
        "url": page.get("url", ""),
        "depth": page.get("depth", 0),
        "status": page.get("status", ""),
        "error": page.get("error", ""),
        "fetch_method": page.get("fetch_method", ""),
        "fetch_error": page.get("fetch_error", ""),
        "title": parsed["title"],
        "text": parsed["visible_text"],
        "searchable_text": parsed["searchable_text"],
        "attribute_texts": parsed["attribute_texts"],
        "text_blocks": effective_text_blocks,
        "passage_blocks": parsed["passage_blocks"],
        "link_count": len(page.get("links", [])),
        "links": page.get("links", []),
    }