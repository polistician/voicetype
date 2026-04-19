# test_embedder.py
import numpy as np
import pytest

from embedder import Embedder


@pytest.fixture(scope="module")
def embedder():
    # Using a tiny model so tests stay under a minute
    return Embedder(model_name="sentence-transformers/all-MiniLM-L6-v2")


def test_encode_returns_vector(embedder):
    vec = embedder.encode("hello world")
    assert isinstance(vec, np.ndarray)
    assert vec.dtype == np.float32
    assert vec.ndim == 1
    assert vec.shape[0] > 0


def test_encode_batch(embedder):
    vecs = embedder.encode_batch(["foo", "bar", "baz"])
    assert vecs.shape[0] == 3
    assert vecs.shape[1] == embedder.dim


def test_cosine_similarity_self(embedder):
    v = embedder.encode("deploy the v3 production system")
    sim = embedder.cosine(v, v)
    assert abs(sim - 1.0) < 1e-5


def test_semantic_match_ranks_related_higher(embedder):
    queries_close = ("deploy production", "ship the app to prod")
    queries_far = ("deploy production", "make a sandwich")
    v_a = embedder.encode(queries_close[0])
    v_b = embedder.encode(queries_close[1])
    v_far = embedder.encode(queries_far[1])
    sim_close = embedder.cosine(v_a, v_b)
    sim_far = embedder.cosine(v_a, v_far)
    assert sim_close > sim_far


def test_match_ranks(embedder):
    # Build a mini cache and search
    cache = {
        1: embedder.encode("deploy v3 production to server"),
        2: embedder.encode("brew cleanup the machine"),
        3: embedder.encode("run pytest in watch mode"),
    }
    hits = embedder.match("push v3 to prod", cache, k=3)
    # Top hit should be id=1
    assert hits[0][0] == 1


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
