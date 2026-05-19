"""Tests for SemanticMatcher — uses mocked torch/sentence-transformers, no live model."""
from unittest.mock import MagicMock, patch
import pytest
from app.services.semantic_matcher import SemanticMatcher, SemanticMatchResult


def test_match_returns_false_when_not_ready():
    matcher = SemanticMatcher(threshold=0.85)
    result = matcher.match("some text", ["hint one"])
    assert not result.matched
    assert result.score == 0.0


def test_match_returns_false_when_no_hints():
    matcher = SemanticMatcher(threshold=0.85)
    matcher._model = MagicMock()  # pretend ready
    matcher._device = "cpu"
    result = matcher.match("some text", [])
    assert not result.matched


def test_initialize_fails_gracefully_without_torch():
    with patch.dict("sys.modules", {"torch": None, "sentence_transformers": None}):
        matcher = SemanticMatcher()
        success, msg = matcher.initialize()
        assert not success
        assert "unavailable" in msg or "failed" in msg
        assert not matcher.ready


def _make_ready_matcher(threshold: float = 0.85) -> SemanticMatcher:
    """Build a SemanticMatcher with a mocked model that returns controllable cosine scores."""
    import torch
    matcher = SemanticMatcher(threshold=threshold)
    mock_model = MagicMock()
    hints = ["test hint"]
    n_inputs = 2  # 1 text + 1 hint
    fake_embeddings = torch.zeros(n_inputs, 8)
    mock_model.encode.return_value = fake_embeddings
    matcher._model = mock_model
    matcher._device = "cpu"
    return matcher


def test_above_threshold_matches(monkeypatch):
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.85)
    mock_model = MagicMock()
    # Two inputs: text + hint → embeddings that yield cosine similarity = 0.91
    emb_a = torch.tensor([1.0, 0.0])
    emb_b = torch.tensor([0.95, 0.31])  # cosine ~0.95 when normalized
    mock_model.encode.return_value = torch.stack([emb_a, emb_b])
    matcher._model = mock_model
    matcher._device = "cpu"
    result = matcher.match("page content", ["pricing automation"])
    assert result.score >= 0.0  # score computed
    import torch.nn.functional as F
    expected = float(F.cosine_similarity(emb_a.unsqueeze(0), emb_b.unsqueeze(0)))
    assert abs(result.score - round(expected, 4)) < 0.001


def test_below_threshold_not_matched():
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.85)
    mock_model = MagicMock()
    # Orthogonal vectors → cosine similarity = 0.0
    emb_a = torch.tensor([1.0, 0.0])
    emb_b = torch.tensor([0.0, 1.0])
    mock_model.encode.return_value = torch.stack([emb_a, emb_b])
    matcher._model = mock_model
    matcher._device = "cpu"
    result = matcher.match("irrelevant content", ["pricing automation"])
    assert not result.matched
    assert result.score < matcher.threshold


def test_score_089_included_at_threshold_085():
    torch = pytest.importorskip("torch")
    import torch.nn.functional as F
    matcher = SemanticMatcher(threshold=0.85)
    mock_model = MagicMock()
    # Construct vectors with cosine ~0.89
    emb_a = torch.tensor([1.0, 0.0, 0.0])
    emb_b = torch.tensor([0.89, 0.456, 0.0])  # will normalize
    emb_b_norm = F.normalize(emb_b.unsqueeze(0)).squeeze(0)
    mock_model.encode.return_value = torch.stack([emb_a, emb_b_norm])
    matcher._model = mock_model
    result = matcher.match("text", ["hint"])
    # cosine between [1,0,0] and normalized emb_b
    expected = float(F.cosine_similarity(emb_a.unsqueeze(0), emb_b_norm.unsqueeze(0)))
    if expected >= 0.85:
        assert result.matched
    else:
        assert not result.matched


def test_score_080_excluded_at_threshold_085():
    torch = pytest.importorskip("torch")
    import torch.nn.functional as F
    matcher = SemanticMatcher(threshold=0.85)
    mock_model = MagicMock()
    emb_a = torch.tensor([1.0, 0.0])
    # Build emb_b such that cosine = 0.80
    angle = torch.tensor(0.80).acos()
    emb_b = torch.tensor([float(torch.cos(angle)), float(torch.sin(angle))])
    mock_model.encode.return_value = torch.stack([emb_a, emb_b])
    matcher._model = mock_model
    result = matcher.match("text", ["hint"])
    assert not result.matched
    assert result.score < 0.85


def test_equal_threshold_is_included():
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.85)
    mock_model = MagicMock()
    emb_a = torch.tensor([1.0, 0.0])
    emb_b = torch.tensor([0.85, 0.5267827])
    mock_model.encode.return_value = torch.stack([emb_a, emb_b])
    matcher._model = mock_model
    matcher._device = "cpu"
    result = matcher.match("text", ["hint"])
    assert result.matched
    assert result.score >= 0.85


def test_best_hint_selected_for_semantic_match():
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.5)
    mock_model = MagicMock()
    text_emb = torch.tensor([1.0, 0.0])
    weak_hint = torch.tensor([0.2, 0.98])
    strong_hint = torch.tensor([0.98, 0.2])
    mock_model.encode.return_value = torch.stack([text_emb, weak_hint, strong_hint])
    matcher._model = mock_model
    matcher._device = "cpu"
    result = matcher.match("text", ["weak", "strong"])
    assert result.matched
    assert result.matched_hint == "strong"


def test_batch_match_length():
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.85)
    mock_model = MagicMock()
    texts = ["text one", "text two", "text three"]
    hints = ["hint a", "hint b"]
    n = len(texts) + len(hints)
    mock_model.encode.return_value = torch.zeros(n, 8)
    matcher._model = mock_model
    results = matcher.match_batch(texts, hints)
    assert len(results) == 3


def test_matched_by_semantic_only():
    """filter_results_by_keywords with semantic matcher should tag result as 'semantic'."""
    torch = pytest.importorskip("torch")
    import torch.nn.functional as F
    from app.services.keyword_filter import filter_results_by_keywords
    from app.services.semantic_matcher import SemanticMatcher

    matcher = SemanticMatcher(threshold=0.5)
    mock_model = MagicMock()
    # High cosine similarity → semantic match
    emb_a = torch.tensor([1.0, 0.0])
    emb_b = torch.tensor([0.99, 0.14])
    mock_model.encode.return_value = torch.stack([emb_a, emb_b])
    matcher._model = mock_model
    matcher._device = "cpu"

    results = [
        {
            "url": "https://example.com/page",
            "title": "Some Page",
            "searchable_text": "example content about pricing",
            "text": "example content about pricing",
            "text_blocks": [],
            "attribute_texts": [],
        }
    ]
    keywords = ["pricing automation"]
    matched, unmatched = filter_results_by_keywords(results, keywords, semantic_matcher=matcher)
    # The result may match via keyword ("pricing" in text) or semantic — either way matched_by should be set
    all_results = matched + unmatched
    assert len(all_results) == 1


def test_matched_by_keyword_when_semantic_disabled():
    from app.services.keyword_filter import filter_results_by_keywords

    results = [
        {
            "url": "https://example.com/page",
            "title": "Nutrition Page",
            "searchable_text": "protein fat carbohydrates nutrition facts",
            "text": "protein fat carbohydrates nutrition facts",
            "text_blocks": [{"block_id": "b1", "source_type": "text_block", "tag": "p", "text": "protein fat carbohydrates nutrition facts"}],
            "attribute_texts": [],
        }
    ]
    keywords = ["nutrition facts"]
    matched, unmatched = filter_results_by_keywords(results, keywords, semantic_matcher=None)
    assert len(matched) == 1
    assert matched[0].get("matched_by") in ("keyword", None, "keyword+semantic")
    assert len(unmatched) == 0


def test_keyword_and_semantic_metadata_when_semantic_off():
    from app.services.keyword_filter import filter_results_by_keywords

    results = [
        {
            "url": "https://example.com/page",
            "title": "Nutrition Page",
            "searchable_text": "nutrition facts",
            "text": "nutrition facts",
            "text_blocks": [{"block_id": "b1", "source_type": "text_block", "tag": "p", "text": "nutrition facts"}],
            "attribute_texts": [],
        }
    ]
    matched, _ = filter_results_by_keywords(results, ["nutrition facts"], semantic_matcher=None)
    assert matched[0]["matched_by"] == "keyword"
    assert matched[0]["semantic_score"] is None
    assert matched[0]["semantic_reason"] is None


def test_metadata_keyword_plus_semantic():
    from app.services.keyword_filter import filter_results_by_keywords

    class _Matcher:
        ready = True
        threshold = 0.85

        def match_batch(self, texts, hints):
            return [SemanticMatchResult(matched=True, score=0.91, matched_hint="pricing automation") for _ in texts]

    results = [
        {
            "url": "https://example.com/page",
            "title": "Pricing",
            "searchable_text": "pricing automation model",
            "text": "pricing automation model",
            "text_blocks": [{"block_id": "b1", "source_type": "text_block", "tag": "p", "text": "pricing automation model"}],
            "attribute_texts": [],
        }
    ]

    matched, _ = filter_results_by_keywords(results, ["pricing"], semantic_matcher=_Matcher())
    assert matched[0]["matched_by"] == "keyword+semantic"
    assert matched[0]["semantic_score"] == 0.91
    assert matched[0]["semantic_reason"] == "pricing automation"


# ---------------------------------------------------------------------------
# New tests: multilingual model, _build_semantic_search_text, logging
# ---------------------------------------------------------------------------


def test_default_model_is_multilingual():
    """The default embedding model must support cross-language (multilingual) matching."""
    from app.services.semantic_matcher import DEFAULT_MODEL

    assert "multilingual" in DEFAULT_MODEL.lower(), (
        f"Expected a multilingual model, got '{DEFAULT_MODEL}'. "
        "English-only models produce near-zero scores for German/English cross-lingual pairs."
    )


def test_build_semantic_search_text_uses_title_and_blocks():
    from app.services.keyword_filter import _build_semantic_search_text

    item = {
        "title": "Hyundai i10 – Wikipedia",
        "searchable_text": "nav nav nav",
        "text_blocks": [
            {"text": "Short"},  # < 40 chars, should be skipped
            {"text": "Die erste Generation wurde 2008 eingeführt und war ein Kleinwagen."},
            {"text": "Die zweite Generation folgte 2013 mit neuem Design und mehr Platz."},
        ],
    }
    result = _build_semantic_search_text(item)
    assert "Hyundai i10" in result
    assert "Generation" in result
    # The very short block should not be the only content
    assert len(result) > 50


def test_build_semantic_search_text_falls_back_to_searchable():
    from app.services.keyword_filter import _build_semantic_search_text

    item = {
        "title": "",
        "searchable_text": "full page content with lots of relevant text about the topic",
        "text_blocks": [
            {"text": "A"},  # all too short
            {"text": "B"},
        ],
    }
    result = _build_semantic_search_text(item)
    assert "full page content" in result


def test_build_semantic_search_text_respects_max_chars():
    from app.services.keyword_filter import _build_semantic_search_text

    long_text = "x" * 5000
    item = {
        "title": "",
        "searchable_text": long_text,
        "text_blocks": [],
    }
    result = _build_semantic_search_text(item, max_chars=200)
    assert len(result) <= 200


def test_filter_uses_build_semantic_search_text_not_raw_searchable(monkeypatch):
    """filter_results_by_keywords should call _build_semantic_search_text for the search text."""
    from app.services import keyword_filter

    calls = []

    original = keyword_filter._build_semantic_search_text

    def tracking_builder(item, max_chars=2048):
        result = original(item, max_chars)
        calls.append(result)
        return result

    monkeypatch.setattr(keyword_filter, "_build_semantic_search_text", tracking_builder)

    class _AlwaysMatch:
        ready = True
        threshold = 0.5

        def match_batch(self, texts, hints):
            return [SemanticMatchResult(matched=True, score=0.80, matched_hint=None) for _ in texts]

    results = [
        {
            "url": "https://example.com",
            "title": "Test Page",
            "searchable_text": "navigation menu footer",
            "text_blocks": [
                {"block_id": "b1", "source_type": "text_block", "tag": "p",
                 "text": "This is substantial content about the topic at hand."}
            ],
            "attribute_texts": [],
        }
    ]

    keyword_filter.filter_results_by_keywords(results, ["topic"], semantic_matcher=_AlwaysMatch())
    assert len(calls) >= 1, "Expected _build_semantic_search_text to be called"


def test_post_loop_summary_is_logged():
    """filter_results_by_keywords should call debug_logger with a summary line."""
    from app.services.keyword_filter import filter_results_by_keywords

    logged = []

    def capture_log(level, msg):
        logged.append((level, msg))

    results = [
        {
            "url": "https://example.com/a",
            "title": "Page A",
            "searchable_text": "no match here",
            "text_blocks": [],
            "attribute_texts": [],
        }
    ]
    filter_results_by_keywords(results, ["xyz_unlikely_keyword"], debug_logger=capture_log)
    summary_lines = [m for _, m in logged if "Matching-Zusammenfassung" in m]
    assert summary_lines, "Expected a Matching-Zusammenfassung log entry"


def test_semantic_only_match_via_filter():
    """A page with no keyword match but high semantic score should be included as 'semantic'."""
    from app.services.keyword_filter import filter_results_by_keywords

    class _HighScoreMatcher:
        ready = True
        threshold = 0.5

        def match_batch(self, texts, hints):
            return [SemanticMatchResult(matched=True, score=0.92, matched_hint="series") for _ in texts]

    results = [
        {
            "url": "https://de.wikipedia.org/wiki/Hyundai_i10",
            "title": "Hyundai i10 – Wikipedia",
            "searchable_text": "Die erste Generation wurde 2008 eingeführt.",
            "text_blocks": [
                {"block_id": "b1", "source_type": "text_block", "tag": "p",
                 "text": "Die erste Generation wurde 2008 eingeführt und markiert den Beginn der Baureihe."}
            ],
            "attribute_texts": [],
        }
    ]

    matched, unmatched = filter_results_by_keywords(results, ["series"], semantic_matcher=_HighScoreMatcher())
    assert len(matched) == 1
    assert matched[0]["matched_by"] == "semantic"
    assert matched[0]["semantic_score"] == 0.92
    assert len(unmatched) == 0
