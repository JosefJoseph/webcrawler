"""Formatting helpers for match result display in UI and exports."""

from __future__ import annotations


def format_match_type(matched_by: str) -> str:
    if matched_by == "keyword+semantic":
        return "Keyword + Semantik"
    if matched_by == "semantic":
        return "Semantik"
    if matched_by == "keyword":
        return "Keyword"
    return matched_by or "Unbekannt"


def format_keyword_matches(result: dict) -> str:
    keywords = (
        result.get("keyword_matches")
        or result.get("matched_terms")
        or []
    )
    if isinstance(keywords, str):
        keywords = [k.strip() for k in keywords.split(",") if k.strip()]
    return ", ".join(str(k) for k in keywords if str(k).strip()) if keywords else "keine"


def format_semantic_line(result: dict, threshold: float | None = None) -> str:
    score = result.get("semantic_score")
    hint = (
        result.get("semantic_reason")
        or result.get("matched_hints")
        or result.get("semantic_best_hint")
        or result.get("best_hint")
        or result.get("semantic_hint")
    )
    matched_by = str(result.get("matched_by") or "").strip()
    semantic_matched = matched_by in {"semantic", "keyword+semantic"}

    if score is None:
        return "Semantik: nicht berechnet"

    try:
        pct = round(float(score) * 100)
    except (TypeError, ValueError):
        return "Semantik: nicht berechnet"

    base = f'Semantik: {pct}% ähnlich zu "{hint}"' if hint else f"Semantik: {pct}%"

    if not semantic_matched and threshold is not None:
        try:
            thr_pct = round(float(threshold) * 100)
            return f"{base} — unter Schwellenwert {thr_pct}%"
        except (TypeError, ValueError):
            pass

    return base
