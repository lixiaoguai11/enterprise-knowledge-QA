from __future__ import annotations

import sys

from app import retrieval
from app.cli_output import format_result
from app.database import SessionLocal, init_db
from app.ingest import import_clean_docs
from app.qa_agent import next_history, run_question
from app.models import Document


def initialize() -> None:
    init_db()
    db = SessionLocal()
    try:
        has_documents = db.query(Document).first() is not None
    finally:
        db.close()
    if not has_documents:
        imported = import_clean_docs()
        if not imported["documents"]:
            raise RuntimeError("没有导入任何知识文档，请检查 data/meta/manifest.csv")
    retrieval.build_index()


def render(result) -> None:
    print(format_result(result), end="")


def repl() -> int:
    try:
        initialize()
    except Exception as exc:
        print(f"初始化失败：{exc}", file=sys.stderr)
        return 1
    print("企业知识问答 Agent（输入 /help 查看命令，/exit 退出）")
    history = []
    while True:
        try:
            line = input("\n你：").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n再见。")
            return 0
        if not line:
            continue
        if line == "/exit":
            print("再见。")
            return 0
        if line == "/help":
            print("输入问题开始对话；/new 清空当前对话上下文；/exit 退出。")
            continue
        if line == "/new":
            history = []
            print("已开始新对话。")
            continue
        try:
            result = run_question(line, history)
        except ValueError as exc:
            print(f"输入错误：{exc}")
            continue
        render(result)
        history = next_history(history, line, result)


def main() -> int:
    return repl()


if __name__ == "__main__":
    raise SystemExit(main())
