"""Run end-to-end conflict and clear-answer scenarios against real APIs.

This is deliberately separate from the fast offline tests. It uses the local
SQLite corpus, the configured embedding endpoint (when enabled), and the
configured LLM provider. Use ``--run-live`` to acknowledge network/API usage.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app import retrieval  # noqa: E402
from app.cli import initialize  # noqa: E402
from app.config import (  # noqa: E402
    ANTHROPIC_API_KEY,
    ANTHROPIC_MODEL,
    DEEPSEEK_API_KEY,
    EMBEDDING_API_KEY,
    EMBEDDING_MODEL_NAME,
    LLM_PROVIDER,
    MODEL_NAME,
    RERANKER_PROVIDER,
)
from app.qa_agent import run_question  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--run-live",
        action="store_true",
        help="confirm that this command may call configured model/embedding APIs",
    )
    args = parser.parse_args()
    if not args.run_live:
        parser.error("real API usage requires --run-live")

    llm_key = ANTHROPIC_API_KEY if LLM_PROVIDER == "anthropic" else DEEPSEEK_API_KEY
    if not llm_key:
        parser.error(f"缺少 {LLM_PROVIDER} 模型 API Key，请检查仓库根目录 .env")
    if not EMBEDDING_API_KEY:
        parser.error("缺少 EMBEDDING_API_KEY；本 smoke 检查需要验证真实 Embedding API")

    initialize()
    question = "报销期限多久？"
    retrieval_error = None
    try:
        ranked = retrieval.search(question, top_k=10)
    except Exception as exc:
        ranked = []
        retrieval_error = str(exc)
    result = run_question(question, [])
    ranked_doc_ids = {item.get("doc_id") for item in ranked}
    payload = {
        "run_mode": "live_end_to_end_conflict_and_reranking",
        "date": date.today().isoformat(),
        "llm_provider": LLM_PROVIDER,
        "llm_model": ANTHROPIC_MODEL if LLM_PROVIDER == "anthropic" else MODEL_NAME,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "reranker_provider": RERANKER_PROVIDER,
        "input": question,
        "retrieval": {
            "error": retrieval_error,
            "embedding_dimensions": (
                int(retrieval.index.vector.matrix.shape[1])
                if retrieval.index.vector.matrix is not None
                else None
            ),
            "ranked_candidates": [
                {
                    "rank": rank,
                    "doc_id": item.get("doc_id"),
                    "score": item.get("score"),
                    "rerank_score": item.get("rerank_score"),
                }
                for rank, item in enumerate(ranked, start=1)
            ],
            "both_conflicting_documents_retrieved": {"D01", "D02"}.issubset(
                ranked_doc_ids
            ),
        },
        "result": result.to_dict(),
        "assertions": {
            "live_reranking_ran": bool(ranked)
            and retrieval.index.vector.matrix is not None,
            "both_conflicting_documents_retrieved": {"D01", "D02"}.issubset(
                ranked_doc_ids
            ),
            "status_needs_clarification": result.status == "needs_clarification",
            "both_conflicting_documents_cited": {"D01", "D02"}.issubset(
                {item.get("doc_id") for item in result.citations}
            ),
            "search_and_read_tools_used": {
                "search_documents",
                "read_document",
            }.issubset(set(result.tools_used)),
        },
    }
    trace_path = ROOT / "examples" / "08-live-qwen-reranker.json"
    trace_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    print(f"Live trace: {trace_path.relative_to(ROOT)}")

    clear_question = "云启 API 网关支持哪些认证鉴权方式？"
    clear_result = run_question(clear_question, [])
    clear_payload = {
        "run_mode": "live_end_to_end_product_question_and_reranking",
        "date": date.today().isoformat(),
        "llm_provider": LLM_PROVIDER,
        "llm_model": ANTHROPIC_MODEL if LLM_PROVIDER == "anthropic" else MODEL_NAME,
        "embedding_model": EMBEDDING_MODEL_NAME,
        "reranker_provider": RERANKER_PROVIDER,
        "input": clear_question,
        "result": clear_result.to_dict(),
        "assertions": {
            "status_answered": clear_result.status == "answered",
            "has_citation": bool(clear_result.citations),
            "search_tool_used": "search_documents" in clear_result.tools_used,
            "model_selected_final_action": any(
                item.get("action") == "model_final" for item in clear_result.trace
            ),
        },
        "trace_note": "本记录展示明确资料问题的真实模型工具选择、观察摘要和结束动作；decision_basis 是可观察动作摘要，不是模型内部思维过程。",
    }
    clear_trace_path = ROOT / "examples" / "09-live-product-question.json"
    clear_trace_path.write_text(
        json.dumps(clear_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(clear_payload, ensure_ascii=False, indent=2))
    print(f"Live trace: {clear_trace_path.relative_to(ROOT)}")
    return 0 if all(payload["assertions"].values()) and all(clear_payload["assertions"].values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
