"""Regression tests for new keyword_filter features:
word-boundary matching, no in-place mutation, deterministic ranking,
semantic evidence snippets, passage_block handling.
"""
import pytest
from app.services.keyword_filter import (
    extract_match_contexts,
    filter_results_by_keywords,
    _rank_key,
    _extract_semantic_snippet,
)
from app.services.semantic_matcher import SemanticMatchResult


# ---------------------------------------------------------------------------
# Word-boundary matching
# ---------------------------------------------------------------------------


def test_word_boundary_single_token_no_substring_match():
    """'fat' must NOT match inside 'fatigue'."""
    contexts = extract_match_contexts("fatigue and other symptoms", "fat")
    assert len(contexts) == 0


def test_word_boundary_single_token_matches_whole_word():
    """'fat' must match the standalone word 'fat'."""
    contexts = extract_match_contexts("total fat 5g per serving", "fat")
    assert len(contexts) == 1
    assert contexts[0]["match_text"].lower() == "fat"


def test_word_boundary_multi_word_phrase_matches_substring():
    """Multi-word keywords still use plain substring match."""
    contexts = extract_match_contexts("nutrition facts panel", "nutrition facts")
    assert len(contexts) == 1


def test_word_boundary_does_not_block_plural():
    """'fat' should not match 'fats' since boundary is after 't'."""
    contexts = extract_match_contexts("saturated fats in food", "fat")
    assert len(contexts) == 0, "word-boundary: 'fat' must not match 'fats'"


def test_word_boundary_matches_at_start_of_string():
    contexts = extract_match_contexts("fat content: 10g", "fat")
    assert len(contexts) == 1


def test_word_boundary_matches_at_end_of_string():
    contexts = extract_match_contexts("content: fat", "fat")
    assert len(contexts) == 1


# ---------------------------------------------------------------------------
# No in-place mutation of input dicts
# ---------------------------------------------------------------------------


def test_filter_results_does_not_mutate_input():
    """filter_results_by_keywords must return new dicts, not modify originals."""
    original = {
        "url": "https://example.com/page",
        "title": "Nutrition Page",
        "searchable_text": "protein fat carbohydrates nutrition facts",
        "text": "protein fat carbohydrates nutrition facts",
        "text_blocks": [
            {"block_id": "b1", "source_type": "text_block", "tag": "p",
             "text": "protein fat carbohydrates nutrition facts"},
        ],
        "attribute_texts": [],
    }
    original_copy = dict(original)
    original_copy["text_blocks"] = list(original["text_blocks"])

    filter_results_by_keywords([original], ["nutrition"])

    # Original dict must not have been enriched in-place
    assert "keyword_matches" not in original
    assert "matched_blocks" not in original
    assert original.get("text_blocks") == original_copy["text_blocks"]


# ---------------------------------------------------------------------------
# Deterministic ranking
# ---------------------------------------------------------------------------


def test_ranking_keyword_plus_semantic_before_keyword_only():
    both = {"matched_by": "keyword+semantic", "semantic_score": 0.90,
            "match_occurrence_count": 2, "matched_block_count": 1, "url": "a"}
    kw = {"matched_by": "keyword", "semantic_score": None,
          "match_occurrence_count": 5, "matched_block_count": 2, "url": "b"}
    assert _rank_key(both) < _rank_key(kw)


def test_ranking_keyword_before_semantic_only():
    kw = {"matched_by": "keyword", "semantic_score": None,
          "match_occurrence_count": 1, "matched_block_count": 1, "url": "a"}
    sem = {"matched_by": "semantic", "semantic_score": 0.95,
           "match_occurrence_count": 0, "matched_block_count": 0, "url": "b"}
    assert _rank_key(kw) < _rank_key(sem)


def test_ranking_higher_semantic_score_ranked_first():
    high = {"matched_by": "semantic", "semantic_score": 0.95,
            "match_occurrence_count": 0, "matched_block_count": 0, "url": "a"}
    low = {"matched_by": "semantic", "semantic_score": 0.60,
           "match_occurrence_count": 0, "matched_block_count": 0, "url": "b"}
    assert _rank_key(high) < _rank_key(low)


def test_ranking_higher_occurrence_count_ranked_first():
    more = {"matched_by": "keyword", "semantic_score": None,
            "match_occurrence_count": 10, "matched_block_count": 3, "url": "a"}
    fewer = {"matched_by": "keyword", "semantic_score": None,
             "match_occurrence_count": 2, "matched_block_count": 1, "url": "b"}
    assert _rank_key(more) < _rank_key(fewer)


def test_ranking_stable_url_tiebreaker():
    a = {"matched_by": "keyword", "semantic_score": None,
         "match_occurrence_count": 1, "matched_block_count": 1, "url": "a"}
    b = {"matched_by": "keyword", "semantic_score": None,
         "match_occurrence_count": 1, "matched_block_count": 1, "url": "b"}
    assert _rank_key(a) < _rank_key(b)


def test_filter_returns_results_sorted_by_matched_by():
    """keyword+semantic results must come before keyword-only in matched list."""
    class _Matcher:
        ready = True
        threshold = 0.5

        def match_batch(self, texts, hints):
            # First page: semantic match; second page: no semantic match
            return [
                SemanticMatchResult(matched=True, score=0.91, matched_hint="nutrition"),
                SemanticMatchResult(matched=False, score=0.30),
            ]

    results = [
        {
            "url": "https://example.com/a",
            "title": "Page A",
            "searchable_text": "nutrition facts",
            "text": "nutrition facts",
            "text_blocks": [{"block_id": "b1", "source_type": "text_block", "tag": "p",
                              "text": "nutrition facts"}],
            "attribute_texts": [],
        },
        {
            "url": "https://example.com/b",
            "title": "Page B",
            "searchable_text": "nutrition label",
            "text": "nutrition label",
            "text_blocks": [{"block_id": "b2", "source_type": "text_block", "tag": "p",
                              "text": "nutrition label"}],
            "attribute_texts": [],
        },
    ]
    matched, _ = filter_results_by_keywords(results, ["nutrition"], semantic_matcher=_Matcher())
    assert matched[0]["matched_by"] == "keyword+semantic"
    assert matched[1]["matched_by"] == "keyword"


# ---------------------------------------------------------------------------
# Semantic evidence snippets for semantic-only matches
# ---------------------------------------------------------------------------


def test_semantic_only_match_gets_snippet():
    """A semantic-only match must have semantic_snippet set to non-empty text."""
    class _AlwaysMatch:
        ready = True
        threshold = 0.5

        def match_batch(self, texts, hints):
            return [SemanticMatchResult(matched=True, score=0.88, matched_hint="supply chain")]

    results = [
        {
            "url": "https://example.com/page",
            "title": "Logistics overview",
            "searchable_text": "Our company sources materials responsibly from certified suppliers.",
            "text": "Our company sources materials responsibly from certified suppliers.",
            "text_blocks": [
                {"block_id": "b1", "source_type": "text_block", "tag": "p",
                 "text": "Our company sources materials responsibly from certified suppliers."},
            ],
            "attribute_texts": [],
        }
    ]
    matched, _ = filter_results_by_keywords(results, ["supply chain"], semantic_matcher=_AlwaysMatch())
    assert len(matched) == 1
    assert matched[0]["matched_by"] == "semantic"
    assert matched[0]["semantic_snippet"]  # must be non-empty
    assert len(matched[0]["semantic_snippet"]) >= 10


def test_extract_semantic_snippet_prefers_passage_blocks():
    item = {
        "text_blocks": [{"text": "Short."}],
        "passage_blocks": [{"text": "This is a much longer and more informative passage block for testing purposes here."}],
        "searchable_text": "fallback text",
    }
    snippet = _extract_semantic_snippet(item)
    assert "passage block" in snippet


def test_extract_semantic_snippet_falls_back_to_text_blocks():
    item = {
        "text_blocks": [{"text": "This is a substantive text block with enough characters."}],
        "passage_blocks": [],
        "searchable_text": "fallback text",
    }
    snippet = _extract_semantic_snippet(item)
    assert "text block" in snippet


def test_extract_semantic_snippet_falls_back_to_searchable():
    item = {
        "text_blocks": [{"text": "Hi"}],
        "passage_blocks": [],
        "searchable_text": "fallback searchable text is used here",
    }
    snippet = _extract_semantic_snippet(item)
    assert "fallback" in snippet


# ---------------------------------------------------------------------------
# passage_blocks are searched for keyword matches
# ---------------------------------------------------------------------------


def test_passage_blocks_searched_for_keywords():
    """Keywords in passage_blocks must trigger a match even if text_blocks are empty."""
    results = [
        {
            "url": "https://example.com/p",
            "title": "Supply Chain",
            "searchable_text": "",
            "text": "",
            "text_blocks": [],
            "passage_blocks": [
                {
                    "block_id": "passage-0",
                    "source_type": "passage_block",
                    "tag": "section",
                    "heading": "Our Supply Chain",
                    "text": "We source ingredients from certified organic farmers worldwide.",
                }
            ],
            "attribute_texts": [],
        }
    ]
    matched, unmatched = filter_results_by_keywords(results, ["ingredients"])
    assert len(matched) == 1
    assert len(unmatched) == 0
    assert "ingredients" in matched[0]["keyword_matches"]


# ---------------------------------------------------------------------------
# below-threshold semantic score is preserved in unmatched
# ---------------------------------------------------------------------------


def test_below_threshold_score_preserved_in_unmatched():
    """Pages that fail the semantic threshold should have semantic_score set (not None)."""
    class _LowScoreMatcher:
        ready = True
        threshold = 0.85

        def match_batch(self, texts, hints):
            return [SemanticMatchResult(matched=False, score=0.45)]

    results = [
        {
            "url": "https://example.com/page",
            "title": "Irrelevant Page",
            "searchable_text": "unrelated content here",
            "text": "unrelated content here",
            "text_blocks": [],
            "attribute_texts": [],
        }
    ]
    _, unmatched = filter_results_by_keywords(results, ["nutrition"], semantic_matcher=_LowScoreMatcher())
    assert len(unmatched) == 1
    # Score must be preserved for diagnostic display
    assert unmatched[0]["semantic_score"] == 0.45
