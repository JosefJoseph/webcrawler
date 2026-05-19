from __future__ import annotations

import re
from typing import Optional

try:
    from app.services.semantic_matcher import SemanticMatcher
except ImportError:
    SemanticMatcher = None  # type: ignore[assignment,misc]

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
    """Normalize a keyword by lowercasing and collapsing whitespace."""
    return re.sub(r"\s+", " ", keyword.strip().lower())


def normalize_keywords(keywords: list[str]) -> list[str]:
    """Normalize and deduplicate a list of keywords."""
    normalized = [normalize_keyword(keyword) for keyword in keywords if keyword and keyword.strip()]
    return list(dict.fromkeys(normalized))


def get_available_keyword_groups() -> dict[str, list[str]]:
    """Return the built-in keyword group definitions."""
    return KEYWORD_GROUPS


def get_keywords_from_groups(selected_groups: list[str]) -> list[str]:
    """Collect and normalize keywords from the selected keyword groups."""
    group_keywords: list[str] = []
    for group in selected_groups:
        group_keywords.extend(KEYWORD_GROUPS.get(group, []))
    return normalize_keywords(group_keywords)


def merge_keywords(raw_keywords: str = "", selected_groups: list[str] | None = None) -> list[str]:
    """Merge custom keywords with group-based keywords."""
    selected_groups = selected_groups or []
    custom_keywords = parse_keywords(raw_keywords)
    group_keywords = get_keywords_from_groups(selected_groups)
    return normalize_keywords(custom_keywords + group_keywords)


def _build_semantic_search_text(item: dict, max_chars: int = 2048) -> str:
    """Build a representative text for semantic matching from a parsed page result.

    Merges title + substantive text blocks (>= 40 chars) from both text_blocks
    and passage_blocks. Falls back to searchable_text when content is sparse.
    """
    parts: list[str] = []
    title = (item.get("title") or "").strip()
    if title:
        parts.append(title)

    seen_texts: set[str] = set()
    for block in list(item.get("text_blocks", [])) + list(item.get("passage_blocks", [])):
        text = (block.get("text") or "").strip()
        if len(text) >= 40 and text not in seen_texts:
            parts.append(text)
            seen_texts.add(text)

    combined = " ".join(parts)
    if len(combined) < 100:
        combined = ((item.get("searchable_text") or item.get("text") or "")).strip()
    return combined[:max_chars]


def parse_keywords(raw_keywords: str) -> list[str]:
    """Parse a raw keyword string into a normalized keyword list."""
    if not raw_keywords:
        return []
    keywords = re.split(r"[,;\n]+", raw_keywords)
    return normalize_keywords(keywords)


def _make_keyword_pattern(keyword: str) -> re.Pattern:
    """Build a regex pattern for a keyword.

    - Single-token keywords (no whitespace): word-boundary match to avoid
      matching substrings (e.g. ``fat`` should not match inside ``fatigue``).
    - Multi-word phrases: simple case-insensitive substring match.
    """
    escaped = re.escape(keyword)
    if " " not in keyword:
        return re.compile(rf"\b{escaped}\b", re.IGNORECASE)
    return re.compile(escaped, re.IGNORECASE)


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

    Uses word-boundary matching for single-token keywords to avoid false
    positives such as matching 'fat' inside 'fatigue'.

    Args:
        text: The text to search within.
        keyword: The keyword to match (case-insensitive).
        window: Number of characters before/after the match for context.
        source_type: Label for the text source.
        context_override: If provided, replaces the windowed context snippet.
        tag: HTML tag name where the match was found.
        block_id: Identifier of the containing text block.

    Returns:
        List of match context dicts.
    """
    contexts: list[dict] = []
    if not text or not keyword:
        return contexts

    pattern = _make_keyword_pattern(keyword)

    for match in pattern.finditer(text):
        start = match.start()
        end = match.end()
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
    """Remove duplicate match contexts based on a composite key."""
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
    """Truncate text to a maximum length, appending ellipsis if needed."""
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3].rstrip()}..."


def _build_match_summary(matched_blocks: list[dict]) -> str:
    """Build a human-readable summary string from matched text blocks."""
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


def _iter_all_blocks(results_item: dict):
    """Yield (block, source) for text_blocks and passage_blocks without duplication.

    Deduplicates by block text so content appearing in both lists is only
    matched once.
    """
    seen_texts: set[str] = set()
    for block in results_item.get("text_blocks", []):
        text = block.get("text", "")
        if text and text not in seen_texts:
            seen_texts.add(text)
            yield block
    for block in results_item.get("passage_blocks", []):
        text = block.get("text", "")
        if text and text not in seen_texts:
            seen_texts.add(text)
            yield block


def _build_matched_blocks(results_item: dict, keywords: list[str]) -> tuple[list[dict], list[dict]]:
    """Identify text/passage blocks and attributes matching any keyword.

    Searches ``text_blocks``, ``passage_blocks``, ``attribute_texts``, then
    falls back to ``searchable_text`` if nothing found.

    Returns:
        Tuple of (matched_blocks, page_contexts).
    """
    matched_blocks: list[dict] = []
    page_contexts: list[dict] = []
    seen_blocks: set[tuple[str, str, str]] = set()

    for block in _iter_all_blocks(results_item):
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

    # Fallback: full-page searchable_text
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


def _extract_semantic_snippet(item: dict, max_length: int = 300) -> str:
    """Extract the best available text snippet for a semantic-only match.

    Tries passage_blocks first (richer context), then text_blocks, then
    falls back to the first characters of searchable_text.
    """
    for block in list(item.get("passage_blocks", [])) + list(item.get("text_blocks", [])):
        text = (block.get("text") or "").strip()
        if len(text) >= 40:
            return text[:max_length]
    fallback = (item.get("searchable_text") or item.get("text") or "").strip()
    return fallback[:max_length]


def _rank_key(item: dict) -> tuple:
    """Deterministic ranking key for matched results.

    Priority (ascending = better rank):
    1. matched_by: keyword+semantic > keyword > semantic > None
    2. semantic_score (descending, None → 0.0)
    3. match_occurrence_count (descending)
    4. matched_block_count (descending)
    5. URL (ascending, for stable tie-breaking)
    """
    matched_by = item.get("matched_by") or ""
    by_order = {"keyword+semantic": 0, "keyword": 1, "semantic": 2, "": 3}
    by_rank = by_order.get(matched_by, 3)
    sem_score = -(item.get("semantic_score") or 0.0)
    occ = -(item.get("match_occurrence_count") or 0)
    blocks = -(item.get("matched_block_count") or 0)
    url = item.get("url") or ""
    return (by_rank, sem_score, occ, blocks, url)


def filter_results_by_keywords(
    results: list[dict],
    keywords: list[str],
    semantic_matcher: Optional["SemanticMatcher"] = None,
    debug_logger=None,
) -> tuple[list[dict], list[dict]]:
    """Filter crawl results by keyword matches and enrich with match metadata.

    Does NOT mutate the input dicts. Returns new enriched copies.

    Each result is annotated with ``keyword_matches``, ``matched_blocks``,
    ``match_contexts``, ``match_summary``, count fields, ``matched_by``,
    ``semantic_score``, ``semantic_reason``, and ``semantic_snippet``.

    Results are sorted deterministically: keyword+semantic > keyword > semantic,
    then by semantic score descending, then by occurrence count descending.

    Args:
        results: List of parsed page result dicts (not mutated).
        keywords: Raw keywords to search for (will be normalized).
        semantic_matcher: Optional initialized SemanticMatcher instance.
        debug_logger: Optional callback(level, message) for diagnostics.

    Returns:
        Tuple of (matched_results, unmatched_results), both sorted.
    """
    keywords = normalize_keywords(keywords)
    use_semantic = semantic_matcher is not None and semantic_matcher.ready and bool(keywords)
    semantic_threshold_used = getattr(semantic_matcher, "threshold", None) if use_semantic else None

    def _log(level: str, message: str) -> None:
        if callable(debug_logger):
            debug_logger(level, message)

    if use_semantic:
        _log("DEBUG", f"Semantic Query: {keywords}")
        _log("DEBUG", f"Semantic threshold={semantic_threshold_used:.2f}")

    # Empty keywords → return all results unenriched (no matches)
    if not keywords:
        enriched = []
        for item in results:
            copy = dict(item)
            copy["keyword_matches"] = []
            copy["matched_blocks"] = []
            copy["match_contexts"] = []
            copy["match_summary"] = ""
            copy["matched_block_count"] = 0
            copy["match_occurrence_count"] = 0
            copy["match_count"] = 0
            copy["matched_by"] = None
            copy["semantic_score"] = None
            copy["semantic_reason"] = None
            copy["semantic_snippet"] = ""
            copy["semantic_threshold_used"] = semantic_threshold_used
            copy["semantic_enabled"] = bool(use_semantic)
            copy["semantic_backend_ready"] = bool(use_semantic)
            copy["matched_terms"] = []
            enriched.append(copy)
        return enriched, []

    matched_results: list[dict] = []
    unmatched_results: list[dict] = []
    all_semantic_scores: list[float] = []

    # Phase 1: keyword matching — build enriched copies (no mutation of originals)
    enriched_items: list[dict] = []
    for item in results:
        matched_blocks, page_contexts = _build_matched_blocks(item, keywords)

        copy = dict(item)
        copy["matched_blocks"] = matched_blocks
        copy["match_contexts"] = page_contexts
        copy["keyword_matches"] = list(
            dict.fromkeys(
                keyword
                for block in matched_blocks
                for keyword in block.get("keywords", [])
            )
        )
        copy["match_summary"] = _build_match_summary(matched_blocks)
        copy["matched_block_count"] = len(matched_blocks)
        copy["match_occurrence_count"] = len(page_contexts)
        copy["match_count"] = len(matched_blocks)
        copy["semantic_threshold_used"] = semantic_threshold_used
        copy["semantic_enabled"] = bool(use_semantic)
        copy["semantic_backend_ready"] = bool(use_semantic)
        copy["semantic_reason"] = None
        copy["semantic_snippet"] = ""
        copy["matched_terms"] = list(copy["keyword_matches"])
        copy["semantic_score"] = None
        copy["matched_by"] = None
        enriched_items.append(copy)

    # Phase 2: batch semantic scoring
    if use_semantic:
        search_texts = [_build_semantic_search_text(item) for item in enriched_items]
        try:
            sem_batch = semantic_matcher.match_batch(search_texts, keywords)
        except Exception as exc:
            _log("ERROR", f"Semantic batch match raised: {type(exc).__name__}: {exc}")
            sem_batch = None

        for item, sem_result, search_text in zip(
            enriched_items,
            sem_batch if sem_batch else [None] * len(enriched_items),
            search_texts,
        ):
            has_keyword = bool(item["matched_blocks"])

            if sem_result is None:
                # Semantic inference failed; treat as no semantic match
                item["semantic_score"] = None
                if has_keyword:
                    item["matched_by"] = "keyword"
                    matched_results.append(item)
                else:
                    unmatched_results.append(item)
                continue

            _log(
                "DEBUG",
                f'Semantic ({"keyword-matched" if has_keyword else "no keyword"}): '
                f'{item.get("url", "")} text_len={len(search_text)}',
            )
            if sem_result.score > 0.0:
                all_semantic_scores.append(sem_result.score)

            if has_keyword:
                item["semantic_score"] = sem_result.score if sem_result.score > 0.0 else None
                item["matched_by"] = "keyword+semantic" if sem_result.matched else "keyword"
                item["semantic_reason"] = sem_result.matched_hint if sem_result.matched else None
                if sem_result.matched and sem_result.matched_hint:
                    item["matched_terms"] = list(dict.fromkeys(item["matched_terms"] + [sem_result.matched_hint]))
                    _log(
                        "DEBUG",
                        f'Semantic match: {item.get("url", "")} score={sem_result.score:.2f} hint="{sem_result.matched_hint}"',
                    )
                elif sem_result.score > 0.0 and semantic_threshold_used is not None:
                    _log(
                        "DEBUG",
                        f'Keyword match, semantic below threshold: {item.get("url", "")} score={sem_result.score:.2f} threshold={semantic_threshold_used:.2f}',
                    )
                matched_results.append(item)
            else:
                if sem_result.matched:
                    item["matched_by"] = "semantic"
                    item["semantic_score"] = sem_result.score
                    item["semantic_reason"] = sem_result.matched_hint
                    # Provide a concrete evidence snippet for semantic-only matches
                    item["semantic_snippet"] = _extract_semantic_snippet(item)
                    if sem_result.matched_hint:
                        item["matched_terms"] = list(dict.fromkeys(item["matched_terms"] + [sem_result.matched_hint]))
                    _log(
                        "DEBUG",
                        f'Semantic match: {item.get("url", "")} score={sem_result.score:.2f} hint="{sem_result.matched_hint or "-"}"',
                    )
                    matched_results.append(item)
                else:
                    item["matched_by"] = None
                    # Preserve score even for below-threshold results (useful for diagnostics)
                    item["semantic_score"] = sem_result.score if sem_result.score > 0.0 else None
                    item["semantic_reason"] = None
                    _log(
                        "DEBUG",
                        f'Verworfen: {item.get("url", "")} keyword=false, semantic_score={sem_result.score:.2f}, threshold={semantic_threshold_used:.2f}',
                    )
                    unmatched_results.append(item)
    else:
        # No semantic: keyword-only partition
        for item in enriched_items:
            if item["matched_blocks"]:
                item["matched_by"] = "keyword"
                matched_results.append(item)
            else:
                unmatched_results.append(item)

    # Post-loop diagnostics
    kw_only = sum(1 for r in matched_results if r.get("matched_by") == "keyword")
    sem_only = sum(1 for r in matched_results if r.get("matched_by") == "semantic")
    both = sum(1 for r in matched_results if r.get("matched_by") == "keyword+semantic")
    _log(
        "INFO",
        f"Matching-Zusammenfassung: gecrawlt={len(results)}, "
        f"keyword={kw_only}, semantic={sem_only}, beide={both}, "
        f"verworfen={len(unmatched_results)}",
    )
    if use_semantic and all_semantic_scores:
        max_s = max(all_semantic_scores)
        avg_s = sum(all_semantic_scores) / len(all_semantic_scores)
        min_s = min(all_semantic_scores)
        _log(
            "DEBUG",
            f"Semantic Scores: max={max_s:.2f}, avg={avg_s:.2f}, min={min_s:.2f}, n={len(all_semantic_scores)}",
        )
        if max_s < 0.25 and semantic_threshold_used is not None:
            _log(
                "WARNING",
                f"Alle Semantic Scores ungewöhnlich niedrig (max={max_s:.2f}). "
                "Mögliche Ursachen: Modell läuft noch ohne Warmup, falscher Textinhalt oder "
                f"Threshold={semantic_threshold_used:.2f} ist zu hoch für diesen Seitentyp.",
            )
    elif use_semantic and not all_semantic_scores:
        _log("WARNING", "Keine Semantic Scores berechnet — Semantic Matcher lieferte keine Ergebnisse.")

    # Deterministic ranking: keyword+semantic > keyword > semantic; then score, count, url
    matched_results.sort(key=_rank_key)
    unmatched_results.sort(key=_rank_key)

    return matched_results, unmatched_results
