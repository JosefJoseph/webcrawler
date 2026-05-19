import pytest
from app.services.result_formatting_service import (
    format_match_type,
    format_keyword_matches,
    format_semantic_line,
)


# ── format_match_type ─────────────────────────────────────────────────────────

def test_format_match_type_keyword_plus_semantic():
    assert format_match_type("keyword+semantic") == "Keyword + Semantik"


def test_format_match_type_semantic():
    assert format_match_type("semantic") == "Semantik"


def test_format_match_type_keyword():
    assert format_match_type("keyword") == "Keyword"


def test_format_match_type_unknown():
    assert format_match_type("something_else") == "something_else"


def test_format_match_type_empty():
    assert format_match_type("") == "Unbekannt"


# ── format_keyword_matches ────────────────────────────────────────────────────

def test_format_keyword_matches_list():
    result = {"keyword_matches": ["protein", "fat", "fiber"]}
    assert format_keyword_matches(result) == "protein, fat, fiber"


def test_format_keyword_matches_string_via_matched_terms():
    result = {"matched_terms": "protein, fat, fiber"}
    assert format_keyword_matches(result) == "protein, fat, fiber"


def test_format_keyword_matches_empty_list():
    result = {"keyword_matches": []}
    assert format_keyword_matches(result) == "keine"


def test_format_keyword_matches_no_keys():
    assert format_keyword_matches({}) == "keine"


def test_format_keyword_matches_prefers_keyword_matches_over_matched_terms():
    result = {"keyword_matches": ["protein"], "matched_terms": "fat"}
    assert format_keyword_matches(result) == "protein"


# ── format_semantic_line ──────────────────────────────────────────────────────

def test_format_semantic_line_no_score():
    result = {"semantic_score": None}
    assert format_semantic_line(result) == "Semantik: nicht berechnet"


def test_format_semantic_line_missing_score():
    result = {}
    assert format_semantic_line(result) == "Semantik: nicht berechnet"


def test_format_semantic_line_keyword_plus_semantic_with_hint():
    result = {
        "semantic_score": 0.38,
        "semantic_reason": "nutrition facts",
        "matched_by": "keyword+semantic",
    }
    line = format_semantic_line(result)
    assert "38%" in line
    assert "nutrition facts" in line
    assert "unter Schwellenwert" not in line


def test_format_semantic_line_semantic_only_with_hint():
    result = {
        "semantic_score": 0.42,
        "semantic_reason": "triple monitor angle setup",
        "matched_by": "semantic",
    }
    line = format_semantic_line(result)
    assert "42%" in line
    assert "triple monitor angle setup" in line
    assert "unter Schwellenwert" not in line


def test_format_semantic_line_below_threshold_shows_warning():
    result = {
        "semantic_score": 0.28,
        "semantic_reason": "nutrition facts",
        "matched_by": "keyword",
    }
    line = format_semantic_line(result, threshold=0.30)
    assert "28%" in line
    assert "unter Schwellenwert 30%" in line


def test_format_semantic_line_below_threshold_no_threshold_arg():
    result = {
        "semantic_score": 0.28,
        "matched_by": "keyword",
    }
    line = format_semantic_line(result)
    assert "28%" in line
    assert "unter Schwellenwert" not in line


def test_format_semantic_line_uses_matched_hints_fallback():
    result = {
        "semantic_score": 0.55,
        "matched_hints": "supply chain",
        "matched_by": "keyword+semantic",
    }
    line = format_semantic_line(result)
    assert "55%" in line
    assert "supply chain" in line


def test_format_semantic_only_keyword_treffer_returns_keine():
    result = {"matched_by": "semantic", "keyword_matches": []}
    assert format_keyword_matches(result) == "keine"


def test_format_semantic_line_no_hint_shows_percentage_only():
    result = {"semantic_score": 0.60, "matched_by": "keyword+semantic"}
    line = format_semantic_line(result)
    assert "60%" in line
    assert "ähnlich" not in line
