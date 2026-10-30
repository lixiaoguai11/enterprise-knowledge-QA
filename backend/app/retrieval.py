from __future__ import annotations

import json
import hashlib
import math
import os
import re
from pathlib import Path

import jieba
import numpy as np

from app.database import SessionLocal
from app.config import (
    EMBEDDING_API_KEY,
    EMBEDDING_BASE_URL,
    EMBEDDING_MODEL_NAME,
    RERANKER_PROVIDER,
)
from app.models import Chunk, Document
from app.reranker import Reranker, create_reranker

K1 = 1.5
B = 0.75
DEFAULT_TOP_K = 5
RRF_K = 60
HYBRID_CANDIDATES = 20
LOCAL_EMBEDDING_MODEL = "sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2"
EMBEDDING_BATCH_SIZE = 32
EMBEDDING_WINDOW_CHARS = 400
EMBEDDING_WINDOW_OVERLAP = 50
os.environ.setdefault("HF_ENDPOINT", "https://hf-mirror.com")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")

PUNCTUATION_ONLY = re.compile(r"^\W+$")
CACHE_DIR = Path(__file__).resolve().parent.parent / "data" / "embeddings"


class BM25Index:
    def __init__(self) -> None:
        self.loaded = False
        self.chunk_count = 0
        self.avgdl = 0.0
        self.chunk_len = {}
        self.chunk_meta = {}
        self.doc_freq = {}
        self.term_tf = {}

    def tokenize(self, text: str) -> list[str]:
        tokens = []
        for token in jieba.cut(text.lower()):
            token = token.strip()
            if not token or PUNCTUATION_ONLY.match(token):
                continue
            tokens.append(token)
        return tokens

    def load(self) -> None:
        db = SessionLocal()
        try:
            rows = (
                db.query(Chunk, Document)
                .join(Document, Chunk.document_id == Document.id)
            .order_by(Chunk.id)
                .all()
            )
        finally:
            db.close()

        self.chunk_count = 0
        total_len = 0
        self.chunk_len = {}
        self.chunk_meta = {}
        self.doc_freq = {}
        self.term_tf = {}

        for chunk, doc in rows:
            cid = chunk.id
            tokens = self.tokenize(chunk.content)
            tf = {}
            for token in tokens:
                tf[token] = tf.get(token, 0) + 1

            self.chunk_count += 1
            total_len += len(tokens)
            self.chunk_len[cid] = len(tokens)
            self.chunk_meta[cid] = {
                "chunk_id": cid,
                "doc_id": doc.doc_id,
                "title": doc.title,
                "category": doc.category,
                "update_date": doc.update_date,
                "source": doc.source,
                "heading": chunk.heading,
                "content": chunk.content,
                "char_count": chunk.char_count,
            }
            for token, count in tf.items():
                self.doc_freq[token] = self.doc_freq.get(token, 0) + 1
                self.term_tf.setdefault(token, {})[cid] = count

        self.avgdl = total_len / self.chunk_count if self.chunk_count else 0.0
        self.loaded = True

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.load()

    def _score_chunk(self, cid: int, query_tokens: list[str]) -> float:
        length = self.chunk_len.get(cid, 0)
        score = 0.0
        for token in query_tokens:
            posting = self.term_tf.get(token)
            if posting is None or cid not in posting:
                continue
            tf = posting[cid]
            df = self.doc_freq.get(token, 0)
            idf = math.log(1 + (self.chunk_count - df + 0.5) / (df + 0.5))
            if self.avgdl:
                denom = tf + K1 * (1 - B + B * length / self.avgdl)
            else:
                denom = tf + K1
            score += idf * (tf * (K1 + 1)) / denom
        return score

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        self.ensure_loaded()
        query_tokens = self.tokenize(query)
        scores = {}
        for cid in self.chunk_meta:
            score = self._score_chunk(cid, query_tokens)
            if score > 0:
                scores[cid] = score
        ranked = sorted(scores.items(), key=lambda item: item[1], reverse=True)[:top_k]
        results = []
        for cid, score in ranked:
            result = dict(self.chunk_meta[cid])
            result["score"] = round(score, 4)
            results.append(result)
        return results


class VectorIndex:
    def __init__(self) -> None:
        self.loaded = False
        self.chunk_ids: list[int] = []
        self.matrix: np.ndarray | None = None
        self._model = None
        self._client = None

    def _cache_metadata(self) -> dict[str, str]:
        if EMBEDDING_API_KEY:
            base_hash = hashlib.sha256(EMBEDDING_BASE_URL.rstrip("/").encode("utf-8")).hexdigest()
            return {
                "backend": "openai-compatible-api",
                "model": EMBEDDING_MODEL_NAME,
                "base_url_sha256": base_hash,
                "text_strategy": f"sliding-{EMBEDDING_WINDOW_CHARS}-overlap-{EMBEDDING_WINDOW_OVERLAP}-v1",
            }
        return {"backend": "fastembed", "model": LOCAL_EMBEDDING_MODEL}

    def _get_local_model(self):
        if self._model is None:
            from fastembed import TextEmbedding

            self._model = TextEmbedding(model_name=LOCAL_EMBEDDING_MODEL)
        return self._model

    def _api_embed(self, texts: list[str]) -> np.ndarray:
        if not texts:
            return np.empty((0, 0), dtype=np.float32)
        from openai import OpenAI

        if self._client is None:
            self._client = OpenAI(api_key=EMBEDDING_API_KEY, base_url=EMBEDDING_BASE_URL)
        vectors: list[list[float] | None] = [None] * len(texts)
        for start in range(0, len(texts), EMBEDDING_BATCH_SIZE):
            batch = texts[start : start + EMBEDDING_BATCH_SIZE]
            response = self._client.embeddings.create(model=EMBEDDING_MODEL_NAME, input=batch)
            for item in response.data:
                local_index = getattr(item, "index", None)
                if local_index is None:
                    raise RuntimeError("Embedding API 响应缺少向量序号 index")
                vectors[start + local_index] = item.embedding
        if any(vector is None for vector in vectors):
            raise RuntimeError("Embedding API 返回的向量数量与输入文本数量不一致")
        return np.asarray(vectors, dtype=np.float32)

    def _embed(self, texts: list[str]) -> np.ndarray:
        if EMBEDDING_API_KEY:
            windows: list[str] = []
            owners: list[int] = []
            stride = EMBEDDING_WINDOW_CHARS - EMBEDDING_WINDOW_OVERLAP
            for owner, text in enumerate(texts):
                if len(text) <= EMBEDDING_WINDOW_CHARS:
                    windows.append(text)
                    owners.append(owner)
                    continue
                for start in range(0, len(text), stride):
                    window = text[start : start + EMBEDDING_WINDOW_CHARS]
                    if window:
                        windows.append(window)
                        owners.append(owner)
                    if start + EMBEDDING_WINDOW_CHARS >= len(text):
                        break
            window_vectors = self._api_embed(windows)
            grouped: list[list[np.ndarray]] = [[] for _ in texts]
            for owner, vector in zip(owners, window_vectors):
                grouped[owner].append(vector)
            return np.asarray(
                [np.mean(group, axis=0) for group in grouped], dtype=np.float32
            )
        model = self._get_local_model()
        return np.asarray(list(model.embed(texts)), dtype=np.float32)

    def _embed_query(self, query: str) -> np.ndarray:
        if EMBEDDING_API_KEY:
            return self._embed([query])[0]
        model = self._get_local_model()
        return np.asarray(list(model.query_embed(query)), dtype=np.float32)[0]

    def _collect_chunks(self) -> list[tuple[int, str]]:
        db = SessionLocal()
        try:
            rows = db.query(Chunk.id, Chunk.content).all()
        finally:
            db.close()
        return [(cid, content) for cid, content in rows]

    def load(self) -> None:
        chunks = self._collect_chunks()
        ids = [cid for cid, _ in chunks]
        cache_path = CACHE_DIR / "chunks.npy"
        ids_path = CACHE_DIR / "chunk_ids.json"
        meta_path = CACHE_DIR / "embedding_meta.json"
        expected_meta = self._cache_metadata()

        if cache_path.exists() and ids_path.exists() and meta_path.exists():
            cached_ids = json.loads(ids_path.read_text(encoding="utf-8"))
            cached_meta = json.loads(meta_path.read_text(encoding="utf-8"))
            if cached_ids == ids and cached_meta == expected_meta:
                self.chunk_ids = ids
                self.matrix = np.load(cache_path)
                self.loaded = True
                return

        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        contents = [content for _, content in chunks]
        if contents:
            self.matrix = self._embed(contents)
        else:
            self.matrix = None
        self.chunk_ids = ids
        if self.matrix is not None:
            np.save(cache_path, self.matrix)
        ids_path.write_text(json.dumps(ids), encoding="utf-8")
        meta_path.write_text(json.dumps(expected_meta, ensure_ascii=False, indent=2), encoding="utf-8")
        self.loaded = True

    def _cosine_scores(self, query_vec: np.ndarray) -> np.ndarray:
        if self.matrix is None or self.matrix.shape[0] == 0:
            return np.empty((0,), dtype=np.float32)
        q_norm = np.linalg.norm(query_vec)
        if q_norm == 0:
            return np.zeros((self.matrix.shape[0],), dtype=np.float32)
        norms = np.linalg.norm(self.matrix, axis=1)
        return (self.matrix @ query_vec) / (norms * q_norm + 1e-9)

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        if not self.loaded or self.matrix is None or self.matrix.shape[0] == 0:
            return []
        query_vec = self._embed_query(query)
        scores = self._cosine_scores(query_vec)
        order = np.argsort(-scores)[:top_k]
        results = []
        for pos in order:
            results.append(
                {
                    "chunk_id": int(self.chunk_ids[pos]),
                    "score": float(scores[pos]),
                }
            )
        return results


class HybridIndex:
    def __init__(self) -> None:
        self.bm25 = BM25Index()
        self.vector = VectorIndex()
        self.vector_enabled = False
        self.reranker: Reranker | None = create_reranker(RERANKER_PROVIDER)
        self.loaded = False

    def load(self) -> None:
        self.bm25.load()
        try:
            self.vector.load()
            self.vector_enabled = True
        except Exception as exc:
            print(f"[hybrid] vector search disabled: {exc}")
            self.vector_enabled = False
        self.loaded = True

    def ensure_loaded(self) -> None:
        if not self.loaded:
            self.load()

    def _rrf_merge(self, bm25_hits: list[dict], vec_hits: list[dict], top_k: int) -> list[dict]:
        scores = {}
        for rank, item in enumerate(bm25_hits):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        for rank, item in enumerate(vec_hits):
            cid = item["chunk_id"]
            scores[cid] = scores.get(cid, 0.0) + 1.0 / (RRF_K + rank + 1)
        ranked = sorted(scores.items(), key=lambda pair: pair[1], reverse=True)[:top_k]
        results = []
        for cid, score in ranked:
            meta = self.bm25.chunk_meta.get(cid)
            if meta is None:
                continue
            result = dict(meta)
            result["score"] = round(score, 6)
            results.append(result)
        return results

    def _fuse_scores(self, items: list[dict]) -> list[dict]:
        if not items:
            return items
        rrf_scores = [item["score"] for item in items]
        rerank_scores = [item["rerank_score"] for item in items]
        rrf_min, rrf_max = min(rrf_scores), max(rrf_scores)
        rr_min, rr_max = min(rerank_scores), max(rerank_scores)

        def normalize(value: float, low: float, high: float) -> float:
            if high > low:
                return (value - low) / (high - low)
            return 1.0

        for item, rrf_score, rr_score in zip(items, rrf_scores, rerank_scores):
            item["score"] = round(
                0.5 * normalize(rrf_score, rrf_min, rrf_max)
                + 0.5 * normalize(rr_score, rr_min, rr_max),
                6,
            )
        items.sort(key=lambda item: item["score"], reverse=True)
        return items

    def search(self, query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
        self.ensure_loaded()
        bm25_hits = self.bm25.search(query, top_k=HYBRID_CANDIDATES)
        if not self.vector_enabled:
            return bm25_hits[:top_k]
        if not self.vector.loaded or self.vector.matrix is None or not len(self.vector.chunk_ids):
            return bm25_hits[:top_k]
        # Embed once, then reuse this vector both for vector recall and for
        # scoring every fused candidate, including BM25-only candidates.
        query_vec = self.vector._embed_query(query)
        similarity_scores = self.vector._cosine_scores(query_vec)
        order = np.argsort(-similarity_scores)[:HYBRID_CANDIDATES]
        vec_hits = [
            {"chunk_id": int(self.vector.chunk_ids[pos]), "score": float(similarity_scores[pos])}
            for pos in order
        ]
        merged = self._rrf_merge(bm25_hits, vec_hits, HYBRID_CANDIDATES)
        if self.reranker is not None and merged:
            score_by_id = {
                int(chunk_id): float(similarity_scores[position])
                for position, chunk_id in enumerate(self.vector.chunk_ids)
            }
            for item in merged:
                item["embedding_score"] = score_by_id.get(int(item["chunk_id"]), 0.0)
            merged = self.reranker.rerank(query, merged)
            merged = self._fuse_scores(merged)
        return merged[:top_k]


index = HybridIndex()


def build_index() -> HybridIndex:
    index.load()
    return index


def search(query: str, top_k: int = DEFAULT_TOP_K) -> list[dict]:
    return index.search(query, top_k)
