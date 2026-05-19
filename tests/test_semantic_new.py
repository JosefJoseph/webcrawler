"""Tests for new SemanticMatcher features: inference_mode, CPU fallback, error surfacing."""
import pytest
from unittest.mock import MagicMock, patch

from app.services.semantic_matcher import SemanticMatcher, SemanticMatchResult


# ---------------------------------------------------------------------------
# inference_mode: encoding is wrapped in torch.inference_mode
# ---------------------------------------------------------------------------


def test_encode_called_inside_inference_mode():
    """Encoding must happen inside torch.inference_mode context."""
    torch = pytest.importorskip("torch")

    matcher = SemanticMatcher(threshold=0.5)
    inference_mode_calls = []

    original_inference_mode = torch.inference_mode

    class _TrackingCtx:
        def __enter__(self):
            inference_mode_calls.append(True)
            return self

        def __exit__(self, *args):
            return False

    def _mock_inference_mode(*args, **kwargs):
        return _TrackingCtx()

    mock_model = MagicMock()
    mock_model.encode.return_value = torch.zeros(2, 8)
    matcher._model = mock_model
    matcher._device = "cpu"

    with patch("torch.inference_mode", side_effect=_mock_inference_mode):
        matcher.match("some text", ["some hint"])

    assert len(inference_mode_calls) > 0, "torch.inference_mode was not called during encoding"


# ---------------------------------------------------------------------------
# Shape validation
# ---------------------------------------------------------------------------


def test_match_raises_on_wrong_tensor_rank():
    """If encode() returns a 1-D tensor, _encode_with_fallback must raise."""
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.5)
    mock_model = MagicMock()
    # Return 1-D tensor — wrong shape
    mock_model.encode.return_value = torch.zeros(8)
    matcher._model = mock_model
    matcher._device = "cpu"

    result = matcher.match("text", ["hint"])
    # Should not crash the caller; error must be returned gracefully
    assert not result.matched
    assert result.error is not None


def test_match_handles_row_count_mismatch():
    """If encode() returns wrong number of rows, error must be surfaced."""
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.5)
    mock_model = MagicMock()
    # 1 row instead of 2 (1 text + 1 hint)
    mock_model.encode.return_value = torch.zeros(1, 8)
    matcher._model = mock_model
    matcher._device = "cpu"

    result = matcher.match("text", ["hint"])
    assert not result.matched
    assert result.error is not None


# ---------------------------------------------------------------------------
# GPU → CPU fallback
# ---------------------------------------------------------------------------


def test_match_cpu_fallback_when_gpu_raises():
    """If GPU inference raises, SemanticMatcher must retry on CPU."""
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.5)

    call_count = [0]

    def fake_encode(inputs, convert_to_tensor, show_progress_bar):
        call_count[0] += 1
        if call_count[0] == 1:
            raise RuntimeError("CUDA out of memory")
        # Second call (CPU) succeeds
        return torch.zeros(len(inputs), 8)

    mock_model = MagicMock()
    mock_model.to.return_value = mock_model  # model.to(device) must return the same mock
    mock_model.encode.side_effect = fake_encode
    matcher._model = mock_model
    matcher._device = "cuda"  # pretend we started on GPU

    result = matcher.match("text", ["hint"])
    # Must not crash; CPU fallback should have succeeded
    assert result.error is None or call_count[0] >= 2


# ---------------------------------------------------------------------------
# Error surfacing (not silent swallowing)
# ---------------------------------------------------------------------------


def test_match_error_is_returned_not_none():
    """When inference raises, the error field of SemanticMatchResult must be set."""
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.5)
    mock_model = MagicMock()
    mock_model.encode.side_effect = RuntimeError("forced error")
    matcher._model = mock_model
    matcher._device = "cpu"

    result = matcher.match("text", ["hint"])
    assert not result.matched
    assert result.score == 0.0
    assert result.error is not None
    assert "forced error" in result.error or "RuntimeError" in result.error


def test_batch_match_errors_surfaced_in_results():
    """When batch encode raises, each result in the batch must have error set."""
    torch = pytest.importorskip("torch")
    matcher = SemanticMatcher(threshold=0.5)
    mock_model = MagicMock()
    mock_model.encode.side_effect = RuntimeError("batch error")
    matcher._model = mock_model
    matcher._device = "cpu"

    results = matcher.match_batch(["t1", "t2", "t3"], ["hint"])
    assert len(results) == 3
    for r in results:
        assert not r.matched
        assert r.score == 0.0
        assert r.error is not None


# ---------------------------------------------------------------------------
# SemanticMatchResult.error field exists
# ---------------------------------------------------------------------------


def test_semantic_match_result_has_error_field():
    r = SemanticMatchResult(matched=False, score=0.0, error="test error")
    assert r.error == "test error"


def test_semantic_match_result_error_defaults_to_none():
    r = SemanticMatchResult(matched=True, score=0.9)
    assert r.error is None
