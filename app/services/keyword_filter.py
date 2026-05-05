from __future__ import annotations

import re

KEYWORD_GROUPS: dict[str, list[str]] = {
    "inhaltsstoffe": [
        "ingredient",
        "ingredients",
        "inhaltsstoff",
        "inhaltsstoffe",
        "zutat",
        "zutaten",
        "nutrition facts",
        "allergens",
        "allergen",
        "additives",
        "zusatzstoffe",
    ],
    "lieferkette": [
        "supplier",
        "suppliers",
        "supply chain",
        "lieferkette",
        "herkunft",
        "origin",
        "source",
        "traceability",
        "producer",
        "manufacturing",
    ],
    "nachhaltigkeit": [
        "sustainability",
        "sustainable",
        "nachhaltigkeit",
        "co2",
        "carbon footprint",
        "recycling",
        "klimaneutral",
        "climate",
        "environment",
        "umwelt",
        "fair trade",
    ],
}


def normalize_keyword(keyword: str) -> str:
    """Normalize a keyword by lowercasing and collapsing whitespace.

    Args:
        keyword: Raw keyword string.

    Returns:
        Lowercase, single-spaced, trimmed keyword.
    """
    return re.sub(r"\s+", " ", keyword.strip().lower())


def normalize_keywords(keywords: list[str]) -> list[str]:
    """Normalize and deduplicate a list of keywords.

    Removes empty entries, lowercases, collapses whitespace, and preserves
    insertion order while eliminating duplicates.

    Args:
        keywords: List of raw keyword strings.

    Returns:
        Deduplicated list of normalized keywords.
    """
    normalized = [normalize_keyword(keyword) for keyword in keywords if keyword and keyword.strip()]
    # dict.fromkeys preserves insertion order while removing duplicates (Python 3.7+)
    return list(dict.fromkeys(normalized))


def get_available_keyword_groups() -> dict[str, list[str]]:
    """Return the built-in keyword group definitions.

    Returns:
        Dict mapping group names to lists of keywords.
    """
    return KEYWORD_GROUPS


def get_keywords_from_groups(selected_groups: list[str]) -> list[str]:
    """Collect and normalize keywords from the selected keyword groups.

    Args:
        selected_groups: List of group names (e.g. ``["inhaltsstoffe"]``).

    Returns:
        Deduplicated, normalized list of keywords from all selected groups.
    """
    group_keywords: list[str] = []

    for group in selected_groups:
        group_keywords.extend(KEYWORD_GROUPS.get(group, []))

    return normalize_keywords(group_keywords)


def merge_keywords(raw_keywords: str = "", selected_groups: list[str] | None = None) -> list[str]:
    """Merge custom keywords with group-based keywords.

    Parses the raw keyword string, combines it with keywords from the selected
    groups, and returns a deduplicated, normalized list.

    Args:
        raw_keywords: Comma/semicolon-separated keyword input string.
        selected_groups: Optional list of keyword group names to include.

    Returns:
        Merged, deduplicated list of normalized keywords.
    """
    selected_groups = selected_groups or []

    custom_keywords = parse_keywords(raw_keywords)
    group_keywords = get_keywords_from_groups(selected_groups)

    return normalize_keywords(custom_keywords + group_keywords)

def parse_keywords(raw_keywords: str) -> list[str]:
    """Parse a raw keyword string into a normalized keyword list.

    Splits on commas, semicolons, and newlines.

    Args:
        raw_keywords: Raw input string with delimited keywords.

    Returns:
        List of normalized, non-empty keywords.
    """
    if not raw_keywords:
        return []

    keywords = re.split(r"[,;\n]+", raw_keywords)
    return normalize_keywords(keywords)

def extract_match_contexts(
    text: str,
    keyword: str,
    window: int = 80,
    source_type: str = "text",
    context_override: str | None = None,
    tag: str = "",
    block_id: str = "",
) -> list[dict]:
    """Find all occurrences of a keyword in text and extract surrounding context.

    Args:
        text: The text to search within.
        keyword: The keyword to match (case-insensitive).
        window: Number of characters before/after the match for context.
        source_type: Label for the text source (e.g. ``"text_block"``).
        context_override: If provided, replaces the windowed context snippet.
        tag: HTML tag name where the match was found.
        block_id: Identifier of the containing text block.

    Returns:
        List of match context dicts with ``keyword``, ``match_text``, ``start``,
        ``end``, ``context``, ``source_type``, ``tag``, and ``block_id``.
    """
    contexts: list[dict] = []
    if not text or not keyword:
        return contexts

    pattern = re.compile(re.escape(keyword), re.IGNORECASE)

    for match in pattern.finditer(text):
        start = match.start()
        end = match.end()
        # Extract a window of surrounding characters for context snippet
        context_start = max(0, start - window)
        context_end = min(len(text), end + window)
        context = context_override if context_override is not None else text[context_start:context_end].strip()
        contexts.append(
            {
                "keyword": keyword,
                "match_text": text[start:end],
                "start": start,
                "end": end,
                "context": context,
                "source_type": source_type,
                "tag": tag,
                "block_id": block_id,
            }
        )

    return contexts


def _dedupe_contexts(contexts: list[dict]) -> list[dict]:
    """Remove duplicate match contexts based on a composite key.

    Args:
        contexts: List of match context dicts.

    Returns:
        Deduplicated list preserving original order.
    """
    seen = set()
    deduped = []
    for ctx in contexts:
        key = (
            ctx["keyword"],
            ctx["match_text"],
            ctx["context"],
            ctx["source_type"],
            ctx.get("tag", ""),
            ctx.get("block_id", ""),
            ctx["start"],
            ctx["end"],
        )
        if key not in seen:
            seen.add(key)
            deduped.append(ctx)
    return deduped


def _truncate_text(text: str, max_length: int = 220) -> str:
    """Truncate text to a maximum length, appending ellipsis if needed.

    Args:
        text: Text to truncate.
        max_length: Maximum allowed length including ellipsis.

    Returns:
        Original text or truncated version with trailing ``...``.
    """
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3].rstrip()}..."


def _build_match_summary(matched_blocks: list[dict]) -> str:
    """Build a human-readable summary string from matched text blocks.

    Shows up to 3 blocks with their keywords and a text snippet,
    plus a count of remaining blocks.

    Args:
        matched_blocks: List of matched block dicts with ``keywords`` and ``text``.

    Returns:
        Formatted summary string, e.g. ``[nutrition] Nutrition facts... | +2 weitere``.
    """
    if not matched_blocks:
        return ""

    parts = []
    for block in matched_blocks[:3]:
        keywords = ", ".join(block.get("keywords", []))
        snippet = _truncate_text(block.get("text", ""))
        parts.append(f"[{keywords}] {snippet}")

    remaining_blocks = len(matched_blocks) - len(parts)
    if remaining_blocks > 0:
        parts.append(f"+{remaining_blocks} weitere Trefferblöcke")

    return " | ".join(parts)


def _build_matched_blocks(results_item: dict, keywords: list[str]) -> tuple[list[dict], list[dict]]:
    """Identify text blocks and attributes that match any of the given keywords.

    Searches through ``text_blocks``, ``attribute_texts``, and falls back to
    ``searchable_text`` if no block-level matches are found.

    Args:
        results_item: A parsed page result dict.
        keywords: Normalized keywords to search for.

    Returns:
        Tuple of (matched_blocks, page_contexts). Each matched block contains
        ``block_id``, ``source_type``, ``tag``, ``text``, ``keywords``,
        ``match_count``, and ``matches``.
    """
    matched_blocks: list[dict] = []
    page_contexts: list[dict] = []
    seen_blocks: set[tuple[str, str, str]] = set()

    for block in results_item.get("text_blocks", []):
        block_contexts: list[dict] = []
        block_text = block.get("text", "")
        block_source_type = block.get("source_type", "text_block")
        block_tag = block.get("tag", "")
        block_id = block.get("block_id", "")

        for keyword in keywords:
            block_contexts.extend(
                extract_match_contexts(
                    block_text,
                    keyword,
                    source_type=block_source_type,
                    context_override=block_text,
                    tag=block_tag,
                    block_id=block_id,
                )
            )

        block_contexts = _dedupe_contexts(block_contexts)
        if not block_contexts:
            continue

        block_key = (block_source_type, block_tag, block_text)
        if block_key in seen_blocks:
            continue
        seen_blocks.add(block_key)

        matched_blocks.append(
            {
                "block_id": block_id,
                "source_type": block_source_type,
                "tag": block_tag,
                "text": block_text,
                "keywords": list(dict.fromkeys(ctx["keyword"] for ctx in block_contexts)),
                "match_count": len(block_contexts),
                "matches": block_contexts,
            }
        )
        page_contexts.extend(block_contexts)

    for index, attr_item in enumerate(results_item.get("attribute_texts", []), start=1):
        attr_contexts: list[dict] = []
        attr_text = attr_item.get("text", "")
        attr_source_type = attr_item.get("source_type", "attribute")
        attr_tag = attr_item.get("tag", "")
        attr_block_id = f"attr-{index}"

        for keyword in keywords:
            attr_contexts.extend(
                extract_match_contexts(
                    attr_text,
                    keyword,
                    source_type=attr_source_type,
                    context_override=attr_text,
                    tag=attr_tag,
                    block_id=attr_block_id,
                )
            )

        attr_contexts = _dedupe_contexts(attr_contexts)
        if not attr_contexts:
            continue

        block_key = (attr_source_type, attr_tag, attr_text)
        if block_key in seen_blocks:
            continue
        seen_blocks.add(block_key)

        matched_blocks.append(
            {
                "block_id": attr_block_id,
                "source_type": attr_source_type,
                "tag": attr_tag,
                "text": attr_text,
                "keywords": list(dict.fromkeys(ctx["keyword"] for ctx in attr_contexts)),
                "match_count": len(attr_contexts),
                "matches": attr_contexts,
            }
        )
        page_contexts.extend(attr_contexts)

    # Fallback: if no block-level matches, search the combined full-page text
    if not matched_blocks and results_item.get("searchable_text"):
        fallback_contexts: list[dict] = []
        fallback_text = results_item.get("searchable_text", "")
        for keyword in keywords:
            fallback_contexts.extend(
                extract_match_contexts(
                    fallback_text,
                    keyword,
                    source_type="combined_text",
                )
            )

        fallback_contexts = _dedupe_contexts(fallback_contexts)
        if fallback_contexts:
            matched_blocks.append(
                {
                    "block_id": "fallback-document",
                    "source_type": "combined_text",
                    "tag": "document",
                    "text": fallback_text,
                    "keywords": list(dict.fromkeys(ctx["keyword"] for ctx in fallback_contexts)),
                    "match_count": len(fallback_contexts),
                    "matches": fallback_contexts,
                }
            )
            page_contexts.extend(fallback_contexts)

    return matched_blocks, _dedupe_contexts(page_contexts)


def filter_results_by_keywords(results: list[dict], keywords: list[str]) -> tuple[list[dict], list[dict]]:
    """Filter crawl results by keyword matches and enrich with match metadata.

    Each result is annotated with ``keyword_matches``, ``matched_blocks``,
    ``match_contexts``, ``match_summary``, and count fields. Results are
    split into matched and unmatched lists.

    Args:
        results: List of parsed page result dicts.
        keywords: Raw keywords to search for (will be normalized).

    Returns:
        Tuple of (matched_results, unmatched_results).
    """
    keywords = normalize_keywords(keywords)
    if not keywords:
        for item in results:
            item["keyword_matches"] = []
            item["matched_blocks"] = []
            item["match_contexts"] = []
            item["match_summary"] = ""
            item["matched_block_count"] = 0
            item["match_occurrence_count"] = 0
            item["match_count"] = 0
        return results, []

    matched_results: list[dict] = []
    unmatched_results: list[dict] = []

    for item in results:
        matched_blocks, page_contexts = _build_matched_blocks(item, keywords)

        item["matched_blocks"] = matched_blocks
        item["match_contexts"] = page_contexts
        item["keyword_matches"] = list(
            dict.fromkeys(
                keyword
                for block in matched_blocks
                for keyword in block.get("keywords", [])
            )
        )
        item["match_summary"] = _build_match_summary(matched_blocks)
        item["matched_block_count"] = len(matched_blocks)
        item["match_occurrence_count"] = len(page_contexts)
        item["match_count"] = len(matched_blocks)

        if matched_blocks:
            matched_results.append(item)
        else:
            unmatched_results.append(item)

    return matched_results, unmatched_results
