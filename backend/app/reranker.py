from __future__ import annotations

import json
import math
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen
from typing import Protocol

from app.config import RERANK_API_KEY, RERANK_BASE_URL, RERANK_MODEL_NAME


class Reranker(Protocol):
    """Backend contract for second-stage candidate ranking.

    A backend receives the original query and metadata-rich retrieval candidates,
    and returns those candidates with a numeric ``rerank_score``. Remote rerank
    adapters (for example Jina) can implement this contract without changing the
    hybrid retrieval pipeline.
    """

    provider: str

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]: ...


class EmbeddingSimilarityReranker:
    """Rerank candidates using cosine similarity from the BGE embedding index."""

    provider = "bge_similarity"

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        # VectorIndex computes these scores for every fused candidate from the
        # same query vector used in vector retrieval; this makes reranking local,
        # deterministic, and avoids a second embedding API call per candidate.
        ranked = []
        for candidate in candidates:
            if "embedding_score" not in candidate:
                raise ValueError("BGE similarity reranker requires embedding_score")
            result = dict(candidate)
            result["rerank_score"] = float(candidate["embedding_score"])
            ranked.append(result)
        return ranked


class QwenAPIReranker:
    """Call a Cohere-style Qwen rerank endpoint and map scores to candidates."""

    provider = "qwen_api"

    def __init__(self) -> None:
        if not RERANK_API_KEY:
            raise RuntimeError("RERANKER_PROVIDER=qwen_api 时必须配置 RERANK_API_KEY")
        if not RERANK_BASE_URL:
            raise RuntimeError("RERANKER_PROVIDER=qwen_api 时必须配置 RERANK_BASE_URL")

    def rerank(self, query: str, candidates: list[dict]) -> list[dict]:
        if not candidates:
            return []
        body = {
            "model": RERANK_MODEL_NAME,
            "query": query,
            "documents": [str(item["content"]) for item in candidates],
            "top_n": len(candidates),
        }
        request = Request(
            RERANK_BASE_URL,
            data=json.dumps(body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {RERANK_API_KEY}",
                "Content-Type": "application/json",
                "Accept": "application/json",
            },
            method="POST",
        )
        try:
            with urlopen(request, timeout=60) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as exc:
            detail = exc.read().decode("utf-8", errors="replace")[:500]
            raise RuntimeError(f"Rerank API returned HTTP {exc.code}: {detail}") from exc
        except (URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            raise RuntimeError(
                f"Rerank API request failed: {type(reason).__name__}"
            ) from exc
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise RuntimeError("Rerank API returned invalid JSON") from exc

        results = payload.get("results")
        if results is None and isinstance(payload.get("output"), dict):
            results = payload["output"].get("results")
        if results is None:
            results = payload.get("data")
        if not isinstance(results, list):
            raise RuntimeError("Rerank API response must contain a results array")

        scored: list[tuple[int, float]] = []
        seen: set[int] = set()
        for result in results:
            try:
                index = int(result["index"])
                score = float(
                    result.get("relevance_score", result.get("score"))
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise RuntimeError("Rerank API result needs index and numeric score") from exc
            if index < 0 or index >= len(candidates) or index in seen:
                raise RuntimeError("Rerank API returned an invalid or duplicate candidate index")
            if not math.isfinite(score):
                raise RuntimeError("Rerank API returned a non-finite score")
            seen.add(index)
            scored.append((index, score))

        if len(scored) != len(candidates):
            raise RuntimeError(
                f"Rerank API scored {len(scored)} of {len(candidates)} candidates"
            )
        return [
            {**candidates[index], "rerank_score": score}
            for index, score in scored
        ]


def create_reranker(provider: str) -> Reranker | None:
    """Create a configured reranker; ``none`` disables the second stage."""
    normalized = provider.strip().lower()
    if normalized in {"", "none", "off"}:
        return None
    if normalized in {"bge_similarity", "bge", "embedding_similarity"}:
        return EmbeddingSimilarityReranker()
    if normalized in {"qwen_api", "rerank_api", "api"}:
        return QwenAPIReranker()
    raise ValueError(
        f"Unsupported RERANKER_PROVIDER={provider!r}; "
        "supported providers: bge_similarity, qwen_api, none"
    )
