from __future__ import annotations

import re


def parse_keywords(raw_keywords: str) -> list[str]:
    keywords = [item.strip() for item in raw_keywords.split(",")]
    return [keyword for keyword in keywords if keyword]


def extract_match_contexts(
    text: str,
    keyword: str,
    window: int = 80,
    source_type: str = "text",
    context_override: str | None = None,
    tag: str = "",
    block_id: str = "",
) -> list[dict]:
    contexts: list[dict] = []
    if not text or not keyword:
        return contexts

    pattern = re.compile(re.escape(keyword), re.IGNORECASE)

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
    if len(text) <= max_length:
        return text
    return f"{text[:max_length - 3].rstrip()}..."


def _build_match_summary(matched_blocks: list[dict]) -> str:
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
