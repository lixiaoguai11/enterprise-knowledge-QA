from __future__ import annotations

import json

import pytest

from app import reranker
from app.reranker import EmbeddingSimilarityReranker, QwenAPIReranker


def test_bge_similarity_reranker_uses_existing_embedding_score():
    candidates = [
        {"chunk_id": 1, "content": "first", "embedding_score": 0.25},
        {"chunk_id": 2, "content": "second", "embedding_score": 0.9},
    ]

    ranked = EmbeddingSimilarityReranker().rerank("query", candidates)

    assert [item["rerank_score"] for item in ranked] == [0.25, 0.9]
    assert candidates[0].get("rerank_score") is None


def test_qwen_api_reranker_maps_remote_order_and_scores(monkeypatch):
    monkeypatch.setattr(reranker, "RERANK_API_KEY", "unit-test-key")
    monkeypatch.setattr(reranker, "RERANK_MODEL_NAME", "Qwen/Qwen3-Reranker-8B")
    monkeypatch.setattr(reranker, "RERANK_BASE_URL", "http://localhost:16385/rerank")
    response_body = {
        "results": [
            {"index": 1, "relevance_score": 0.9},
            {"index": 0, "relevance_score": 0.2},
        ]
    }

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return json.dumps(response_body).encode("utf-8")

    def fake_urlopen(request, timeout):
        assert request.full_url == "http://localhost:16385/rerank"
        assert request.get_header("Authorization") == "Bearer unit-test-key"
        assert timeout == 60
        body = json.loads(request.data.decode("utf-8"))
        assert body["model"] == "Qwen/Qwen3-Reranker-8B"
        assert body["query"] == "query"
        assert body["documents"] == ["first", "second"]
        assert body["top_n"] == 2
        return Response()

    monkeypatch.setattr(reranker, "urlopen", fake_urlopen)
    candidates = [
        {"chunk_id": 1, "content": "first"},
        {"chunk_id": 2, "content": "second"},
    ]

    ranked = QwenAPIReranker().rerank("query", candidates)

    assert [(item["chunk_id"], item["rerank_score"]) for item in ranked] == [
        (2, 0.9),
        (1, 0.2),
    ]


def test_qwen_api_reranker_rejects_incomplete_scores(monkeypatch):
    monkeypatch.setattr(reranker, "RERANK_API_KEY", "unit-test-key")
    monkeypatch.setattr(reranker, "RERANK_MODEL_NAME", "Qwen/Qwen3-Reranker-8B")
    monkeypatch.setattr(reranker, "RERANK_BASE_URL", "http://localhost:16385/rerank")

    class Response:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return False

        def read(self):
            return b'{"results":[{"index":0,"relevance_score":0.2}]}'

    monkeypatch.setattr(reranker, "urlopen", lambda *_args, **_kwargs: Response())
    candidates = [
        {"chunk_id": 1, "content": "first"},
        {"chunk_id": 2, "content": "second"},
    ]

    with pytest.raises(RuntimeError, match="scored 1 of 2 candidates"):
        QwenAPIReranker().rerank("query", candidates)
