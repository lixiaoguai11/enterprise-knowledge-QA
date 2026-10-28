from __future__ import annotations

from typing import Any

from app import retrieval
from app.database import SessionLocal
from app.models import Chunk, Document


def search_documents(query: str, top_k: int = 5) -> list[dict[str, Any]]:
    """Search the indexed corpus and return citable excerpts."""
    if not query.strip():
        raise ValueError("检索词不能为空")
    results = retrieval.search(query.strip(), top_k=max(1, min(top_k, 10)))
    return [
        {
            "doc_id": item["doc_id"],
            "title": item["title"],
            "version_date": item.get("update_date", ""),
            "heading": item.get("heading", ""),
            "quote": item["content"],
            "score": item.get("score", 0),
        }
        for item in results
    ]


def read_document(doc_id: str) -> dict[str, Any] | None:
    """Read original indexed text for one document ID."""
    db = SessionLocal()
    try:
        document = db.query(Document).filter(Document.doc_id == doc_id).first()
        if document is None:
            return None
        chunks = (
            db.query(Chunk)
            .filter(Chunk.document_id == document.id)
            .order_by(Chunk.chunk_index)
            .all()
        )
        return {
            "doc_id": document.doc_id,
            "title": document.title,
            "version_date": document.update_date,
            "sections": [
                {"heading": chunk.heading, "text": chunk.content}
                for chunk in chunks
            ],
        }
    finally:
        db.close()


TOOL_SPECS = [
    {
        "type": "function",
        "function": {
            "name": "search_documents",
            "description": "按问题检索知识库，返回含文档 ID、版本日期和原文片段的候选证据。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {"type": "string", "description": "要检索的问题或关键词"},
                    "top_k": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_document",
            "description": "按文档 ID 读取文档的完整已索引原文，用于核验检索片段、适用范围和优先级。",
            "parameters": {
                "type": "object",
                "properties": {"doc_id": {"type": "string"}},
                "required": ["doc_id"],
            },
        },
    },
]


def execute_tool(name: str, arguments: dict[str, Any]) -> Any:
    if name == "search_documents":
        return search_documents(
            str(arguments.get("query", "")), int(arguments.get("top_k", 5))
        )
    if name == "read_document":
        result = read_document(str(arguments.get("doc_id", "")))
        if result is None:
            return {"error": "未找到该文档 ID"}
        return result
    raise ValueError(f"未知工具：{name}")
