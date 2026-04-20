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


def _normalize_text(text: str) -> str:
    return " ".join(text.split()).strip()


def _collect_attribute_texts(soup: BeautifulSoup) -> list[dict]:
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
    return not any(
        isinstance(child, Tag) and child.name in TEXT_BLOCK_TAGS
        for child in tag.children
    )


def _has_non_div_block_ancestor(tag: Tag) -> bool:
    parent = tag.parent
    while isinstance(parent, Tag):
        if parent.name in TEXT_BLOCK_TAGS and parent.name != "div":
            return True
        parent = parent.parent
    return False


def _collect_text_blocks(soup: BeautifulSoup) -> list[dict]:
    items: list[dict] = []
    seen: set[str] = set()
    block_index = 0

    for tag in soup.find_all(TEXT_BLOCK_TAGS):
        if tag.name == "div" and not _is_leaf_div(tag):
            continue
        if tag.name == "div" and _has_non_div_block_ancestor(tag):
            continue

        text = _normalize_text(tag.get_text(separator=" ", strip=True))
        if not text:
            continue

        min_length = 8 if tag.name in SHORT_TEXT_BLOCK_TAGS else 40
        if len(text) < min_length:
            continue

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


def parse_page(html: str) -> dict:
    soup = BeautifulSoup(html, "lxml")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()

    title = soup.title.get_text(strip=True) if soup.title else "Ohne Titel"
    attribute_texts = _collect_attribute_texts(soup)
    text_blocks = _collect_text_blocks(soup)
    visible_text = _normalize_text(soup.get_text(separator=" ", strip=True))
    searchable_parts = [visible_text]
    searchable_parts.extend(item["text"] for item in attribute_texts)
    searchable_text = " ".join(part for part in searchable_parts if part).strip()

    return {
        "title": title,
        "visible_text": visible_text,
        "searchable_text": searchable_text,
        "attribute_texts": attribute_texts,
        "text_blocks": text_blocks,
    }


def build_page_result(page: dict) -> dict:
    parsed = parse_page(page.get("html", "")) if page.get("html") else {
        "title": "Fehler",
        "visible_text": "",
        "searchable_text": "",
        "attribute_texts": [],
        "text_blocks": [],
    }

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
        "text_blocks": parsed["text_blocks"],
        "link_count": len(page.get("links", [])),
        "links": page.get("links", []),
    }
