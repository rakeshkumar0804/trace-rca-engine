from abc import ABC, abstractmethod
import math
import os
import re
from typing import ClassVar

EMBEDDING_DIM = 384


class EmbeddingProvider(ABC):
    """Abstract interface for text embedding providers in TRACE."""

    @property
    @abstractmethod
    def dimension(self) -> int:
        """Returns the embedding vector dimensionality."""
        pass

    @abstractmethod
    def embed_text(self, text: str) -> list[float]:
        """Generates a dense embedding vector for a given text string."""
        pass

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Generates dense embedding vectors for a list of text strings."""
        return [self.embed_text(t) for t in texts]


_fastembed_singleton = None


class FastEmbedProvider(EmbeddingProvider):
    """Production embedding provider using a local ONNX-based neural embedding model
    (BAAI/bge-small-en-v1.5, 384-dim) via FastEmbed. Runs fully locally, no API key,
    no network calls after the model is downloaded once.
    """

    def __init__(self, model_name: str = "BAAI/bge-small-en-v1.5"):
        global _fastembed_singleton
        if _fastembed_singleton is None:
            import logging
            logging.getLogger("app.embeddings").info(f"Loading FastEmbed ONNX model singleton ({model_name}) with threads=1...")
            from fastembed import TextEmbedding
            _fastembed_singleton = TextEmbedding(model_name=model_name, threads=1)
        self._model = _fastembed_singleton
        self._dim = 384

    @property
    def dimension(self) -> int:
        return self._dim

    def embed_text(self, text: str) -> list[float]:
        return list(self._model.embed([text]))[0].tolist()

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        """Native batch inference passing the full list of strings to the ONNX runtime."""
        if not texts:
            return []
        return [e.tolist() for e in self._model.embed(texts)]


class DeterministicEmbeddingProvider(EmbeddingProvider):
    """Deterministic token/n-gram hashing projection provider for fast offline unit tests and CI.
    
    NOTE: This is NOT a learned ML/deep-learning embedding model. It uses deterministic subword 
    n-gram hash projections onto a hypersphere with L2 normalization. Kept exclusively for fast, 
    isolated unit tests without model loading overhead.
    """

    STOPWORDS: ClassVar[set[str]] = {
        "a", "an", "the", "in", "on", "at", "to", "for", "of", "and", "or", "is", "was", "with",
    }

    def __init__(self, dim: int = EMBEDDING_DIM):
        self._dim = dim

    @property
    def dimension(self) -> int:
        return self._dim

    def _tokenize(self, text: str) -> list[str]:
        cleaned = re.sub(r"[^a-zA-Z0-9_\-]", " ", text.lower())
        tokens = [w for w in cleaned.split() if w and w not in self.STOPWORDS]
        
        features = list(tokens)
        for tok in tokens:
            if len(tok) >= 4:
                for i in range(len(tok) - 2):
                    features.append(tok[i:i+3])
        return features

    def embed_text(self, text: str) -> list[float]:
        vec = [0.0] * self._dim
        tokens = self._tokenize(text)
        if not tokens:
            return vec

        for tok in tokens:
            h = hash(tok)
            idx1 = abs(h) % self._dim
            idx2 = abs(hash(tok + "_alt")) % self._dim
            idx3 = abs(hash(tok + "_3rd")) % self._dim

            weight1 = 1.0 if (h & 1) else -1.0
            weight2 = 0.6 if (h & 2) else -0.6
            weight3 = 0.3 if (h & 4) else -0.3

            vec[idx1] += weight1
            vec[idx2] += weight2
            vec[idx3] += weight3

        norm = math.sqrt(sum(x * x for x in vec))
        if norm > 1e-9:
            vec = [round(x / norm, 6) for x in vec]
        return vec


_DEFAULT_DETERMINISTIC_PROVIDER = DeterministicEmbeddingProvider(dim=EMBEDDING_DIM)
_FASTEMBED_SINGLETON: FastEmbedProvider | None = None


def _get_or_create_fastembed_singleton() -> FastEmbedProvider:
    global _FASTEMBED_SINGLETON
    if _FASTEMBED_SINGLETON is None:
        _FASTEMBED_SINGLETON = FastEmbedProvider()
    return _FASTEMBED_SINGLETON


def get_embedding_provider() -> EmbeddingProvider:
    """Returns the configured embedding provider. Defaults to FastEmbed for production."""
    provider_type = os.getenv("EMBEDDING_PROVIDER", "fastembed").lower()
    if provider_type == "fastembed":
        return _get_or_create_fastembed_singleton()
    return _DEFAULT_DETERMINISTIC_PROVIDER


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Computes cosine similarity between two float vectors."""
    dot = sum(a * b for a, b in zip(vec_a, vec_b, strict=False))
    norm_a = math.sqrt(sum(a * a for a in vec_a))
    norm_b = math.sqrt(sum(b * b for b in vec_b))
    if norm_a < 1e-9 or norm_b < 1e-9:
        return 0.0
    return dot / (norm_a * norm_b)
