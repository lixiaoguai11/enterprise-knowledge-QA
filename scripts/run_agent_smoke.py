"""Run the QA orchestration offline with deterministic model/tool doubles.

This exercises the real AgentResult parsing, citation allow-list, conflict guard,
and tool failure path without importing the optional database/model packages.
It does not measure retrieval quality or real LLM behavior.
"""

from __future__ import annotations

import json
import re
import sys
import types
from datetime import date
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

# qa_agent imports these integration modules; replace only their external edges.
config = types.ModuleType("app.config")
config.DEEPSEEK_API_KEY = ""
config.DEEPSEEK_BASE_URL = ""
config.MODEL_NAME = "offline-scripted-model"
config.LLM_PROVIDER = "deepseek"
config.ANTHROPIC_API_KEY = ""
config.ANTHROPIC_BASE_URL = ""
config.ANTHROPIC_MODEL = "offline-scripted-model"
sys.modules["app.config"] = config
knowledge_tools = types.ModuleType("app.knowledge_tools")
knowledge_tools.TOOL_SPECS = [
    {"type": "function", "function": {"name": "search_documents"}},
    {"type": "function", "function": {"name": "read_document"}},
]
knowledge_tools.execute_tool = lambda *_: None
sys.modules["app.knowledge_tools"] = knowledge_tools

from app.qa_agent import run_question  # noqa: E402
from app.cli_output import format_result  # noqa: E402


def tool_call(name: str, arguments: dict, call_id: str = "call-1"):
    return SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(
                    name=name,
                    arguments=json.dumps(arguments, ensure_ascii=False),
                ),
            )
        ],
    )


def final(value: dict):
    return SimpleNamespace(content=json.dumps(value, ensure_ascii=False), tool_calls=[])


class Model:
    def __init__(self, responses):
        self.responses = list(responses)

    def __call__(self, _messages, _tools):
        return self.responses.pop(0)


def scenario(question, responses, executor, history=None):
    result = run_question(
        question,
        history,
        model=Model(responses),
        tool_executor=executor,
    )
    return {
        "input": question,
        "history": history or [],
        "output": result.to_dict(),
        "cli_output": format_result(result),
    }


def main() -> None:
    clear = [
        {
            "doc_id": "D03",
            "title": "报销流程 FAQ",
            "version_date": "2026-03-01",
            "quote": "员工在费用系统创建报销单，并上传发票及付款凭证。",
        }
    ]
    normal = scenario(
        "报销时要上传什么？",
        [
            tool_call("search_documents", {"query": "报销要上传什么"}),
            final({"answer": "提交报销时上传发票及付款凭证。", "citations": [{"doc_id": "D03", "quote": clear[0]["quote"]}], "gaps": [], "status": "answered"}),
        ],
        lambda *_: clear,
    )
    rephrased = scenario(
        "断网了，票据之后怎么交？",
        [
            tool_call("search_documents", {"query": "没有网络时如何补交报销票据"}),
            final({"answer": "网络恢复后在线提交。", "citations": [{"doc_id": "D03", "quote": "网络恢复后在线提交。"}], "gaps": [], "status": "answered"}),
        ],
        lambda *_: [{"doc_id": "D03", "title": "报销流程 FAQ", "version_date": "2026-03-01", "quote": "网络恢复后在线提交。"}],
    )
    history = [{"role": "user", "content": "报销怎么提交？"}, {"role": "assistant", "content": "填写报销单并上传票据。"}]
    follow_up = scenario(
        "提交前还要核对什么？",
        [
            tool_call("search_documents", {"query": "报销提交前核对什么"}),
            final({"answer": "提交前核对部门和成本中心。", "citations": [{"doc_id": "D03", "quote": "提交前核对部门和成本中心。"}], "gaps": [], "status": "answered"}),
        ],
        lambda *_: [{"doc_id": "D03", "title": "报销流程 FAQ", "version_date": "2026-03-01", "quote": "提交前核对部门和成本中心。"}],
        history,
    )
    conflict_sources = [
        {"doc_id": "D01", "title": "报销制度 D01", "version_date": "2026-01-10", "quote": "员工应在费用发生后 30 天内提交报销申请。"},
        {"doc_id": "D02", "title": "报销规则 D02", "version_date": "2026-02-01", "quote": "员工应在费用发生后 15 天内提交报销申请。"},
    ]

    def conflict_tools(name, _arguments):
        if name == "search_documents":
            return conflict_sources
        return {"doc_id": "D01", "title": "报销制度 D01", "version_date": "2026-01-10", "sections": [{"heading": "报销期限", "text": conflict_sources[0]["quote"]}]}

    conflict = scenario(
        "报销期限多久？",
        [
            tool_call("search_documents", {"query": "报销期限"}),
            tool_call("read_document", {"doc_id": "D01"}, "call-2"),
            final({"answer": "报销期限是 15 天。", "citations": [{"doc_id": "D02", "quote": conflict_sources[1]["quote"]}], "gaps": [], "status": "answered"}),
        ],
        conflict_tools,
    )
    gaps = scenario(
        "火星天气如何？",
        [
            tool_call("search_documents", {"query": "火星天气"}),
            final({"answer": "现有知识库没有相关资料，无法可靠回答。", "citations": [], "gaps": ["缺少火星天气资料"], "status": "insufficient_evidence"}),
        ],
        lambda *_: [],
    )

    def failing_tool(*_):
        raise OSError("index unavailable")

    failure = scenario(
        "报销期限多久？",
        [tool_call("search_documents", {"query": "报销期限"})],
        failing_tool,
    )
    source_path = ROOT / "data" / "clean" / "synthetic" / "D01-报销制度.md"
    original_text = source_path.read_text(encoding="utf-8")

    def answer_from_source(source_text):
        quote = re.search(r"员工应在费用发生后 \d+ 天内提交报销申请。", source_text).group(0)
        value = re.search(r"(\d+) 天内", quote).group(1)

        def evidence_tool(_name, _arguments):
            return [{"doc_id": "D01", "title": "报销制度 D01", "version_date": "2026-01-10", "quote": quote}]

        def evidence_model(messages, _tools):
            if len(messages) <= 2:
                return tool_call("search_documents", {"query": "报销期限"})
            return final({"answer": f"依据 D01，报销期限为 {value} 天。", "citations": [{"doc_id": "D01", "quote": quote}], "gaps": [], "status": "answered"})

        return run_question("报销期限多久？", model=evidence_model, tool_executor=evidence_tool)

    before = answer_from_source(original_text)
    after = answer_from_source(original_text.replace("30 天", "20 天"))
    mutation_check = {
        "file": "data/clean/synthetic/D01-报销制度.md",
        "before": before.to_dict(),
        "after_replacing_30_with_20_days": after.to_dict(),
    }
    assert normal["output"]["status"] == "answered" and normal["output"]["citations"]
    assert rephrased["output"]["status"] == "answered"
    assert follow_up["output"]["status"] == "answered"
    assert conflict["output"]["status"] == "needs_clarification"
    assert {item["doc_id"] for item in conflict["output"]["citations"]} == {"D01", "D02"}
    assert gaps["output"]["status"] == "insufficient_evidence"
    assert failure["output"]["status"] == "tool_error"
    groups = [
        ("01-normal-context.json", [normal, rephrased, follow_up]),
        ("02-conflict.json", [conflict]),
        ("03-gaps-and-failure.json", [gaps, failure]),
    ]
    for filename, scenarios in groups:
        payload = {
            "run_mode": "脚本化模型和知识工具响应；真实 QA Agent 编排代码；不代表 DeepSeek 实际推理或检索质量",
            "generated_at": date.today().isoformat(),
            "scenarios": scenarios,
        }
        if filename == "03-gaps-and-failure.json":
            assert before.answer != after.answer
            assert before.citations[0]["quote"] != after.citations[0]["quote"]
            payload["mutation_check"] = mutation_check
        (ROOT / "examples" / filename).write_text(
            json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    print("Offline Agent smoke scenarios passed: 6")
    print("Trace files: examples/01-normal-context.json, examples/02-conflict.json, examples/03-gaps-and-failure.json")


if __name__ == "__main__":
    main()
