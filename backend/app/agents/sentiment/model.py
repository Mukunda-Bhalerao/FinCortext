"""Local financial sentiment model wrapper (FinBERT via Hugging Face).

Design rules:
- The model is loaded LAZILY on first inference — never at import or startup.
- Any failure (missing transformers/torch, download failure, load error,
  inference error) raises ModelUnavailableError; the caller (SentimentAgent)
  converts that into an explicit degraded/unavailable AgentOutput. The
  backend NEVER crashes because the sentiment model is unavailable.
- No paid API is involved; the model runs locally (default ProsusAI/finbert).
- Tests inject a fake implementing the same `analyze()` interface — the
  agent is decoupled from transformers.
"""

from __future__ import annotations

from threading import Lock

from app.core.config import Settings, settings
from app.core.exceptions import ModelUnavailableError
from app.core.logging import get_logger

logger = get_logger("agents.sentiment.model")

# Label order used by ProsusAI/finbert: 0=positive, 1=negative, 2=neutral.
# We resolve labels dynamically from model.config.id2label (lowercased) so a
# different checkpoint with a different order still works.
MAX_TEXT_CHARS = 4000  # pre-truncation guard; tokenizer truncates to 512 tokens


class FinBERTSentimentModel:
    """Lazy FinBERT wrapper. `analyze` returns per-text probability dicts."""

    def __init__(self, model_id: str | None = None, cache_dir=None, config: Settings | None = None):
        cfg = config or settings
        self.model_id = model_id or cfg.sentiment_model_id
        self.cache_dir = cache_dir if cache_dir is not None else cfg.sentiment_cache_dir
        self._model = None
        self._load_lock = Lock()

    # -- state -----------------------------------------------------------------

    @property
    def is_loaded(self) -> bool:
        return self._model is not None

    def _load(self):
        """Load tokenizer/model once. Raises ModelUnavailableError on failure."""
        with self._load_lock:
            if self._model is not None:
                return self._model
            try:
                import torch
                from transformers import (
                    AutoModelForSequenceClassification,
                    AutoTokenizer,
                )

                logger.info("Loading sentiment model %s (first use may download it)", self.model_id)
                tokenizer = AutoTokenizer.from_pretrained(
                    self.model_id, cache_dir=str(self.cache_dir)
                )
                model = AutoModelForSequenceClassification.from_pretrained(
                    self.model_id, cache_dir=str(self.cache_dir)
                )
                model.eval()
                self._id2label = {
                    int(i): str(label).lower()
                    for i, label in model.config.id2label.items()
                }
                self._torch = torch
                self._tokenizer = tokenizer
                self._model = model
                logger.info("Sentiment model %s loaded", self.model_id)
                return self._model
            except ModelUnavailableError:
                raise
            except Exception as exc:
                logger.error("Sentiment model load failed: %s", exc)
                raise ModelUnavailableError(
                    f"Sentiment model '{self.model_id}' could not be loaded: {exc}. "
                    "Sentiment analysis is unavailable; all other modules "
                    "continue to work.",
                    details={"model_id": self.model_id},
                ) from exc

    # -- inference ----------------------------------------------------------------

    def analyze(self, texts: list[str]) -> list[dict]:
        """Score texts -> [{label, positive, neutral, negative, confidence}].

        Deterministic given the same model files and inputs (model in eval
        mode, no sampling). Raises ModelUnavailableError on load/inference
        failure.
        """
        if not texts:
            return []
        try:
            model = self._load()
            torch = self._torch
            tokenizer = self._tokenizer
        except ModelUnavailableError:
            raise

        cleaned = [(t or "").strip()[:MAX_TEXT_CHARS] for t in texts]
        try:
            with torch.no_grad():
                encoded = tokenizer(
                    cleaned,
                    padding=True,
                    truncation=True,
                    max_length=512,
                    return_tensors="pt",
                )
                logits = model(**encoded).logits
                probabilities = torch.softmax(logits, dim=-1)
        except ModelUnavailableError:
            raise
        except Exception as exc:
            raise ModelUnavailableError(
                f"Sentiment inference failed: {exc}",
                details={"model_id": self.model_id},
            ) from exc

        results: list[dict] = []
        for row in probabilities:
            probs = {
                self._id2label.get(i, str(i)): float(p)
                for i, p in enumerate(row)
            }
            positive = probs.get("positive", 0.0)
            negative = probs.get("negative", 0.0)
            neutral = probs.get("neutral", 0.0)
            label = max(("positive", "neutral", "negative"), key=lambda k: probs.get(k, 0.0))
            results.append(
                {
                    "label": label,
                    "positive": positive,
                    "neutral": neutral,
                    "negative": negative,
                    "confidence": float(row.max()),
                }
            )
        return results


# Module-level singleton (the model files are large; load once per process).
_model_singleton: FinBERTSentimentModel | None = None
_singleton_lock = Lock()


def get_sentiment_model(config: Settings | None = None) -> FinBERTSentimentModel:
    """Return the process-wide sentiment model wrapper (lazy-loading)."""
    global _model_singleton
    with _singleton_lock:
        if _model_singleton is None:
            _model_singleton = FinBERTSentimentModel(config=config)
        return _model_singleton