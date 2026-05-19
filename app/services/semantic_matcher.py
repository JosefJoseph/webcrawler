from __future__ import annotations

import logging
import os
import warnings
from dataclasses import dataclass
from functools import lru_cache
from typing import Optional

# paraphrase-multilingual-MiniLM-L12-v2 supports 50+ languages (including German+English).
# all-MiniLM-L6-v2 is English-only and produces near-zero scores for cross-lingual pairs.
DEFAULT_MODEL = "paraphrase-multilingual-MiniLM-L12-v2"

# Local/dev defaults: no Hugging Face API key is required.  Suppress noisy
# hub/transformers warnings so Streamlit logs stay readable.
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
logging.getLogger("huggingface_hub").setLevel(logging.ERROR)
logging.getLogger("transformers").setLevel(logging.ERROR)
warnings.filterwarnings("ignore", message=r"Accessing `__path__`.*", module=r"transformers\..*")

_log = logging.getLogger(__name__)


@dataclass
class SemanticMatchResult:
    matched: bool
    score: float
    matched_hint: Optional[str] = None
    error: Optional[str] = None  # non-None when inference failed


class SemanticMatcher:
    """Lazy-loading semantic similarity matcher using sentence-transformers + PyTorch.

    Device priority: CUDA > MPS (Apple Silicon) > CPU.
    Automatic CPU fallback if GPU inference fails.
    Call initialize() once before using match() or match_batch().
    """

    def __init__(self, threshold: float = 0.85) -> None:
        self.threshold = max(0.0, min(1.0, float(threshold)))
        self._model = None
        self._device: Optional[str] = None
        self._load_error: Optional[str] = None

    @property
    def ready(self) -> bool:
        return self._model is not None

    @property
    def device(self) -> Optional[str]:
        return self._device

    @property
    def load_error(self) -> Optional[str]:
        return self._load_error

    def initialize(self) -> tuple[bool, str]:
        """Lazy initialization with CPU fallback.

        Returns (success, message) suitable for logging / UI display.
        """
        if self.ready:
            return True, f"already initialized on {self._device}"
        try:
            import torch
            from sentence_transformers import SentenceTransformer

            # Device selection with explicit CPU fallback
            if torch.cuda.is_available():
                device = "cuda"
            elif hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
                device = "mps"
            else:
                device = "cpu"

            try:
                self._model = SentenceTransformer(DEFAULT_MODEL, device=device)
                self._device = device
                return True, f"model={DEFAULT_MODEL}, device={device}"
            except Exception as gpu_exc:
                if device != "cpu":
                    _log.warning("GPU model load failed (%s), falling back to CPU: %s", device, gpu_exc)
                    self._model = SentenceTransformer(DEFAULT_MODEL, device="cpu")
                    self._device = "cpu"
                    return True, f"model={DEFAULT_MODEL}, device=cpu (fallback from {device}: {gpu_exc})"
                raise

        except ImportError as exc:
            msg = f"sentence-transformers unavailable: {exc}"
            self._load_error = msg
            return False, msg
        except Exception as exc:
            msg = f"model load failed: {type(exc).__name__}: {exc}"
            self._load_error = msg
            return False, msg

    @staticmethod
    @lru_cache(maxsize=4096)
    def _clip_text(value: str, limit: int) -> str:
        return (value or "")[:limit]

    def _encode_with_fallback(self, inputs: list[str]) -> "torch.Tensor":
        """Encode inputs, falling back to CPU if GPU inference fails.

        Wraps encoding in torch.inference_mode() for memory efficiency.
        Validates the returned tensor shape.

        Returns:
            2-D float tensor of shape (len(inputs), embedding_dim).

        Raises:
            RuntimeError: If encoding fails even on CPU.
        """
        import torch

        def _do_encode(device_override: Optional[str] = None) -> "torch.Tensor":
            model = self._model
            if device_override is not None:
                try:
                    import torch as _torch
                    model = model.to(_torch.device(device_override))
                except Exception:
                    pass

            with torch.inference_mode():
                embeddings = model.encode(
                    inputs,
                    convert_to_tensor=True,
                    show_progress_bar=False,
                )

            # Validate output shape
            if not isinstance(embeddings, torch.Tensor):
                raise RuntimeError(
                    f"encode() returned {type(embeddings).__name__}, expected torch.Tensor"
                )
            if embeddings.ndim != 2:
                raise RuntimeError(
                    f"Expected 2-D embedding tensor, got shape {tuple(embeddings.shape)}"
                )
            if embeddings.shape[0] != len(inputs):
                raise RuntimeError(
                    f"Embedding row count {embeddings.shape[0]} != input count {len(inputs)}"
                )
            return embeddings

        try:
            return _do_encode()
        except (RuntimeError, Exception) as exc:
            if self._device and self._device != "cpu":
                _log.warning(
                    "GPU inference failed (%s: %s), retrying on CPU", type(exc).__name__, exc
                )
                return _do_encode(device_override="cpu")
            raise

    def match(self, text: str, hints: list[str]) -> SemanticMatchResult:
        """Match a single text against a list of search hints."""
        if not self.ready or not hints or not text.strip():
            return SemanticMatchResult(matched=False, score=0.0)
        try:
            import torch.nn.functional as F

            cleaned_text = self._clip_text(text, 2048)
            cleaned_hints = [self._clip_text(h, 256) for h in hints]
            inputs = [cleaned_text] + cleaned_hints
            embeddings = self._encode_with_fallback(inputs)
            text_emb = embeddings[0].unsqueeze(0)
            hint_embs = embeddings[1:]
            scores = F.cosine_similarity(text_emb, hint_embs)
            best_idx = int(scores.argmax())
            best_score = float(scores[best_idx])
            return SemanticMatchResult(
                matched=best_score >= self.threshold,
                score=round(best_score, 4),
                matched_hint=cleaned_hints[best_idx] if best_score >= self.threshold else None,
            )
        except Exception as exc:
            msg = f"semantic match error: {type(exc).__name__}: {exc}"
            _log.warning(msg)
            return SemanticMatchResult(matched=False, score=0.0, error=msg)

    def match_batch(self, texts: list[str], hints: list[str]) -> list[SemanticMatchResult]:
        """Batch-match multiple texts against hints (one encode call for all)."""
        if not self.ready or not hints or not texts:
            return [SemanticMatchResult(matched=False, score=0.0) for _ in texts]
        try:
            import torch.nn.functional as F

            cleaned_texts = [self._clip_text(t, 2048) for t in texts]
            cleaned_hints = [self._clip_text(h, 256) for h in hints]
            all_inputs = cleaned_texts + cleaned_hints
            all_embs = self._encode_with_fallback(all_inputs)
            text_embs = all_embs[: len(texts)]
            hint_embs = all_embs[len(texts):]
            results = []
            for emb in text_embs:
                scores = F.cosine_similarity(emb.unsqueeze(0), hint_embs)
                best_idx = int(scores.argmax())
                best_score = float(scores[best_idx])
                results.append(
                    SemanticMatchResult(
                        matched=best_score >= self.threshold,
                        score=round(best_score, 4),
                        matched_hint=cleaned_hints[best_idx] if best_score >= self.threshold else None,
                    )
                )
            return results
        except Exception as exc:
            msg = f"semantic batch match error: {type(exc).__name__}: {exc}"
            _log.warning(msg)
            # Surface the error in each result rather than silently returning zeros
            return [SemanticMatchResult(matched=False, score=0.0, error=msg) for _ in texts]
