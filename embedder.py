# embedder.py
"""Local sentence embedding model + cosine matcher.

The first model load downloads weights (cached under ~/.cache/huggingface/).
For production use we pin mxbai-embed-xsmall-v1 (Apache 2.0, ~22M params,
MiniLM-successor quality). Tests use all-MiniLM-L6-v2 because it's ubiquitous.
"""
from __future__ import annotations

import numpy as np
from typing import Iterable


DEFAULT_MODEL = "mixedbread-ai/mxbai-embed-xsmall-v1"


class Embedder:
    def __init__(self, model_name: str = DEFAULT_MODEL):
        # Lazy import so `import embedder` stays fast and testable
        from sentence_transformers import SentenceTransformer
        self.model_name = model_name
        self._model = SentenceTransformer(model_name)
        self.dim = self._model.get_sentence_embedding_dimension()

    def encode(self, text: str) -> np.ndarray:
        vec = self._model.encode(text, convert_to_numpy=True, normalize_embeddings=True)
        return vec.astype(np.float32)

    def encode_batch(self, texts: Iterable[str]) -> np.ndarray:
        vecs = self._model.encode(list(texts), convert_to_numpy=True, normalize_embeddings=True)
        return vecs.astype(np.float32)

    @staticmethod
    def cosine(a: np.ndarray, b: np.ndarray) -> float:
        # Inputs are expected to be normalized — dot product is cosine similarity
        return float(np.dot(a, b))

    def match(self, query: str, cache: dict[int, np.ndarray], k: int = 5) -> list[tuple[int, float]]:
        """Rank cache entries against the query by cosine similarity. Returns top k."""
        if not cache:
            return []
        qvec = self.encode(query)
        scored = [(sid, self.cosine(qvec, vec)) for sid, vec in cache.items()]
        scored.sort(key=lambda x: x[1], reverse=True)
        return scored[:k]

    @staticmethod
    def blob_to_array(blob: bytes, dim: int) -> np.ndarray:
        return np.frombuffer(blob, dtype=np.float32, count=dim)

    @staticmethod
    def array_to_blob(arr: np.ndarray) -> bytes:
        return arr.astype(np.float32).tobytes()
