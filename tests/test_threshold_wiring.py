"""Regression tests for semantic threshold wiring.

Covers:
- Low threshold produces matches that high threshold rejects.
- Threshold is read from the matcher instance, not hardcoded.
- Below-threshold scores are preserved in unmatched results (needed for diagnostics).
- match_batch is called when matcher is ready and keywords are given.
- semantic_threshold_used field reflects the matcher's threshold.
- All unmatched scores visible so the diagnostic max-score computation works.
"""
from app.services.keyword_filter import filter_results_by_keywords
from app.services.semantic_matcher import SemanticMatchResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_results(n: int = 1) -> list[dict]:
    """Pages whose text does NOT contain the search keyword 'ergonomics'.

    This ensures keyword matching never fires, so semantic behaviour is
    testable in isolation.
    """
    return [
        {
            "url": f"https://example.com/page{i}",
            "title": f"Page {i}",
            "searchable_text": "racing simulator cockpit seat position display angle",
            "text": "racing simulator cockpit seat position display angle",
            "text_blocks": [],
            "attribute_texts": [],
        }
        for i in range(n)
    ]


# Keyword that never appears literally in _make_results() text
_KEYWORD = "ergonomics"


class _FixedScoreMatcher:
    """SemanticMatcher stub that always returns a fixed score and respects threshold."""

    def __init__(self, score: float, threshold: float) -> None:
        self.ready = True
        self.threshold = threshold
        self._score = score

    def match_batch(self, texts: list[str], hints: list[str]) -> list[SemanticMatchResult]:
        matched = self._score >= self.threshold
        return [
            SemanticMatchResult(
                matched=matched,
                score=self._score,
                matched_hint=hints[0] if matched else None,
            )
            for _ in texts
        ]


# ---------------------------------------------------------------------------
# Threshold controls match/no-match
# ---------------------------------------------------------------------------


def test_low_threshold_matches_moderate_score():
    """threshold=0.05: score 0.10 must produce a semantic match."""
    matcher = _FixedScoreMatcher(score=0.10, threshold=0.05)
    matched, unmatched = filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=matcher)
    assert len(matched) == 1
    assert matched[0]["matched_by"] == "semantic"
    assert matched[0]["semantic_score"] == 0.10
    assert len(unmatched) == 0


def test_high_threshold_rejects_moderate_score():
    """threshold=0.85: score 0.10 must NOT produce a match."""
    matcher = _FixedScoreMatcher(score=0.10, threshold=0.85)
    matched, unmatched = filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=matcher)
    assert len(matched) == 0
    assert len(unmatched) == 1


def test_exact_threshold_boundary_is_matched():
    """A score exactly equal to the threshold must be considered matched."""
    matcher = _FixedScoreMatcher(score=0.30, threshold=0.30)
    matched, unmatched = filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=matcher)
    assert len(matched) == 1
    assert matched[0]["matched_by"] == "semantic"


def test_just_below_threshold_is_not_matched():
    """A score just below the threshold must be rejected."""
    matcher = _FixedScoreMatcher(score=0.29, threshold=0.30)
    matched, unmatched = filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=matcher)
    assert len(matched) == 0
    assert len(unmatched) == 1


# ---------------------------------------------------------------------------
# Threshold from matcher, not hardcoded
# ---------------------------------------------------------------------------


def test_threshold_from_matcher_not_hardcoded():
    """filter_results_by_keywords must read threshold from the matcher instance.

    Same score (0.50) must match with threshold=0.30 but not with threshold=0.85.
    Uses _KEYWORD which does not appear literally in the test text, so only
    semantic scoring decides the outcome.
    """
    results = _make_results()
    keywords = [_KEYWORD]

    matched_low, _ = filter_results_by_keywords(
        results, keywords, semantic_matcher=_FixedScoreMatcher(score=0.50, threshold=0.30)
    )
    matched_high, _ = filter_results_by_keywords(
        results, keywords, semantic_matcher=_FixedScoreMatcher(score=0.50, threshold=0.85)
    )

    assert len(matched_low) == 1, "score=0.50 with threshold=0.30 must match"
    assert matched_low[0]["matched_by"] == "semantic"

    assert len(matched_high) == 0, "score=0.50 with threshold=0.85 must NOT match"


# ---------------------------------------------------------------------------
# Below-threshold scores preserved for diagnostic
# ---------------------------------------------------------------------------


def test_below_threshold_score_preserved_in_unmatched_single():
    """Unmatched results must retain semantic_score (not None) for diagnostic display."""
    matcher = _FixedScoreMatcher(score=0.10, threshold=0.85)
    _, unmatched = filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=matcher)
    assert len(unmatched) == 1
    assert unmatched[0]["semantic_score"] == 0.10, "score must be preserved even when below threshold"


def test_max_score_computable_from_unmatched_results():
    """When no pages match, max score must still be derivable from unmatched for diagnostics."""
    matcher = _FixedScoreMatcher(score=0.42, threshold=0.85)
    _, unmatched = filter_results_by_keywords(_make_results(3), [_KEYWORD], semantic_matcher=matcher)
    scores = [r["semantic_score"] for r in unmatched if r.get("semantic_score") is not None]
    assert len(scores) == 3
    assert max(scores) == 0.42


# ---------------------------------------------------------------------------
# match_batch is called when expected
# ---------------------------------------------------------------------------


def test_match_batch_called_when_matcher_ready_and_keywords_given():
    """match_batch must be invoked when matcher.ready=True and keywords are non-empty."""
    call_count = [0]

    class _TrackingMatcher:
        ready = True
        threshold = 0.30

        def match_batch(self, texts: list[str], hints: list[str]) -> list[SemanticMatchResult]:
            call_count[0] += 1
            return [SemanticMatchResult(matched=True, score=0.80, matched_hint=hints[0]) for _ in texts]

    filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=_TrackingMatcher())
    assert call_count[0] >= 1, "match_batch must be called when keywords and a ready matcher are provided"


def test_match_batch_not_called_without_keywords():
    """match_batch must NOT be called when keyword list is empty."""
    call_count = [0]

    class _TrackingMatcher:
        ready = True
        threshold = 0.30

        def match_batch(self, texts: list[str], hints: list[str]) -> list[SemanticMatchResult]:
            call_count[0] += 1
            return []

    filter_results_by_keywords(_make_results(), [], semantic_matcher=_TrackingMatcher())
    assert call_count[0] == 0, "match_batch must NOT be called when there are no keywords"


def test_match_batch_not_called_when_matcher_not_ready():
    """match_batch must NOT be called when matcher.ready=False."""
    call_count = [0]

    class _NotReadyMatcher:
        ready = False
        threshold = 0.30

        def match_batch(self, texts: list[str], hints: list[str]) -> list[SemanticMatchResult]:
            call_count[0] += 1
            return []

    filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=_NotReadyMatcher())
    assert call_count[0] == 0, "match_batch must NOT be called when matcher.ready=False"


# ---------------------------------------------------------------------------
# semantic_threshold_used metadata field
# ---------------------------------------------------------------------------


def test_semantic_threshold_used_field_set_in_matched():
    """Matched results must carry semantic_threshold_used equal to the matcher's threshold."""
    matcher = _FixedScoreMatcher(score=0.80, threshold=0.30)
    matched, _ = filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=matcher)
    assert len(matched) == 1
    assert matched[0]["semantic_threshold_used"] == 0.30


def test_semantic_threshold_used_field_set_in_unmatched():
    """Unmatched results must also carry semantic_threshold_used for diagnostic use."""
    matcher = _FixedScoreMatcher(score=0.10, threshold=0.85)
    _, unmatched = filter_results_by_keywords(_make_results(), [_KEYWORD], semantic_matcher=matcher)
    assert len(unmatched) == 1
    assert unmatched[0]["semantic_threshold_used"] == 0.85


def test_semantic_threshold_used_none_when_no_matcher():
    """When no matcher is provided, semantic_threshold_used must be None."""
    results = [
        {
            "url": "https://example.com",
            "title": "Test",
            "searchable_text": "view content",
            "text": "view content",
            "text_blocks": [{"block_id": "b1", "source_type": "text_block", "tag": "p", "text": "view content"}],
            "attribute_texts": [],
        }
    ]
    matched, _ = filter_results_by_keywords(results, ["view"], semantic_matcher=None)
    assert len(matched) == 1
    assert matched[0]["semantic_threshold_used"] is None


# ---------------------------------------------------------------------------
# Multiple pages: only above-threshold pages match
# ---------------------------------------------------------------------------


def test_threshold_filters_subset_of_pages():
    """With multiple pages at different scores, only those >= threshold match.

    Uses _KEYWORD which does not appear in test text so keyword matching
    never fires and semantic scores alone determine the outcome.
    """

    class _VariableScoreMatcher:
        ready = True
        threshold = 0.50
        _scores = [0.80, 0.30, 0.60]

        def match_batch(self, texts: list[str], hints: list[str]) -> list[SemanticMatchResult]:
            results = []
            for score in self._scores[: len(texts)]:
                results.append(SemanticMatchResult(matched=score >= self.threshold, score=score))
            return results

    matched, unmatched = filter_results_by_keywords(
        _make_results(3), [_KEYWORD], semantic_matcher=_VariableScoreMatcher()
    )
    assert len(matched) == 2, f"scores 0.80 and 0.60 should pass threshold 0.50; matched={[r['semantic_score'] for r in matched]}"
    assert len(unmatched) == 1  # score 0.30 below threshold
    matched_scores = {r["semantic_score"] for r in matched}
    assert 0.80 in matched_scores
    assert 0.60 in matched_scores
    assert unmatched[0]["semantic_score"] == 0.30
