from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from typing import Any, Callable

from app.config import (
    ANTHROPIC_API_KEY,
    ANTHROPIC_BASE_URL,
    ANTHROPIC_MODEL,
    DEEPSEEK_API_KEY,
    DEEPSEEK_BASE_URL,
    LLM_PROVIDER,
    MODEL_NAME,
)
from app.knowledge_tools import TOOL_SPECS, execute_tool

MAX_TOOL_ROUNDS = 6
MAX_TOOL_CALLS = 8
STATUSES = {"answered", "needs_clarification", "insufficient_evidence"}

SYSTEM_PROMPT = """你是企业知识问答 Agent，只能依据工具返回的知识库证据回答制度和产品问题。
你可以动态决定调用 search_documents 补充检索、调用 read_document 核验原文、直接追问，或基于充分证据结束。
必须遵守：
- 不得使用模型自身常识补齐资料缺口；没有相关证据时返回 insufficient_evidence。
- 检索片段不足以核验范围或完整上下文时，读取原文。用户追问可使用本轮之前的对话上下文。
- 对同一问题属性，若不同文档的证据给出不一致值，且没有明确适用范围/优先级可消解冲突，必须返回 needs_clarification；列出冲突双方、文档 ID、版本日期和原句，询问适用制度。不得擅自选择一项。
- 引用 doc_id 必须来自工具输出；不允许改写或杜撰引用原文。宁可少答，也不能无依据作答。
- 最终回复必须是单个 JSON 对象，字段为 answer（字符串）、citations（数组，元素含 doc_id/title/version_date/quote）、gaps（字符串数组）、status（answered/needs_clarification/insufficient_evidence）。
- citations.quote 必须逐字复制工具返回的原文片段；answer 使用中文。
"""


@dataclass
class AgentResult:
    answer: str
    citations: list[dict[str, str]] = field(default_factory=list)
    gaps: list[str] = field(default_factory=list)
    status: str = "insufficient_evidence"
    trace: list[dict[str, Any]] = field(default_factory=list)
    tools_used: list[str] = field(default_factory=list)
    rounds: int = 0

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def call_model(messages: list[dict[str, Any]], tools: list[dict]) -> Any:
    if LLM_PROVIDER == "deepseek":
        if not DEEPSEEK_API_KEY:
            raise RuntimeError("LLM_PROVIDER=deepseek 时必须配置 DEEPSEEK_API_KEY")
        from openai import OpenAI

        client = OpenAI(api_key=DEEPSEEK_API_KEY, base_url=DEEPSEEK_BASE_URL)
        response = client.chat.completions.create(
            model=MODEL_NAME,
            messages=messages,
            tools=tools,
            tool_choice="auto",
            temperature=0.1,
        )
        return response.choices[0].message

    if LLM_PROVIDER == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise RuntimeError("LLM_PROVIDER=anthropic 时必须配置 ANTHROPIC_API_KEY")
        from anthropic import Anthropic

        system, anthropic_messages = _to_anthropic_messages(messages)
        anthropic_base_url = ANTHROPIC_BASE_URL.rstrip("/")
        # The Anthropic SDK appends /v1/messages. OpenAI-compatible gateways
        # commonly store a /v1 suffix in their base URL; remove that suffix
        # before using the same gateway with the native Messages protocol.
        if anthropic_base_url.endswith("/v1"):
            anthropic_base_url = anthropic_base_url[:-3]
        response = Anthropic(
            api_key=ANTHROPIC_API_KEY,
            base_url=anthropic_base_url,
        ).messages.create(
            model=ANTHROPIC_MODEL,
            system=system,
            messages=anthropic_messages,
            tools=_to_anthropic_tools(tools),
            max_tokens=2048,
        )
        return _from_anthropic_response(response)

    raise RuntimeError(
        f"不支持的 LLM_PROVIDER={LLM_PROVIDER!r}；可选值为 deepseek 或 anthropic"
    )


def _to_anthropic_tools(tools: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Translate OpenAI function tool schemas to Anthropic Messages tools."""
    converted = []
    for item in tools:
        function = item.get("function", item)
        converted.append(
            {
                "name": function["name"],
                "description": function.get("description", ""),
                "input_schema": function.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return converted


def _to_anthropic_messages(
    messages: list[dict[str, Any]],
) -> tuple[str, list[dict[str, Any]]]:
    """Translate the agent's provider-neutral conversation to Messages format."""
    system_parts = [str(item.get("content", "")) for item in messages if item.get("role") == "system"]
    converted: list[dict[str, Any]] = []
    for index, item in enumerate(messages):
        role = item.get("role")
        if role in {"system", "tool"}:
            continue
        if role == "assistant" and item.get("tool_calls"):
            blocks: list[dict[str, Any]] = []
            text = item.get("content")
            if text:
                blocks.append({"type": "text", "text": str(text)})
            for call in item["tool_calls"]:
                function = call.get("function", {})
                try:
                    arguments = json.loads(function.get("arguments") or "{}")
                except json.JSONDecodeError:
                    arguments = {}
                blocks.append(
                    {
                        "type": "tool_use",
                        "id": call["id"],
                        "name": function["name"],
                        "input": arguments,
                    }
                )
            converted.append({"role": "assistant", "content": blocks})
        elif role in {"user", "assistant"}:
            converted.append({"role": role, "content": str(item.get("content") or "")})
        else:
            raise ValueError(f"无法转换到 Anthropic Messages API 的消息角色：{role!r}")

        # OpenAI tool replies are represented as separate role=tool messages.
        # Attach them to a user message containing Anthropic tool_result blocks.
        tool_results = []
        for reply in messages[index + 1 :]:
            if reply.get("role") != "tool":
                break
            tool_results.append(
                {
                    "type": "tool_result",
                    "tool_use_id": reply["tool_call_id"],
                    "content": str(reply.get("content", "")),
                }
            )
        if tool_results:
            converted.append({"role": "user", "content": tool_results})

    return "\n\n".join(part for part in system_parts if part), converted


def _from_anthropic_response(response: Any) -> Any:
    """Normalize Anthropic content blocks to the shape used by the agent loop."""
    from types import SimpleNamespace

    text_parts = []
    tool_calls = []
    for block in response.content:
        if block.type == "text":
            text_parts.append(block.text)
        elif block.type == "tool_use":
            tool_calls.append(
                SimpleNamespace(
                    id=block.id,
                    type="function",
                    function=SimpleNamespace(
                        name=block.name,
                        arguments=json.dumps(block.input, ensure_ascii=False),
                    ),
                )
            )
    return SimpleNamespace(content="\n".join(text_parts) or None, tool_calls=tool_calls)


def _message_dict(message: Any) -> dict[str, Any]:
    calls = []
    for call in getattr(message, "tool_calls", None) or []:
        calls.append(
            {
                "id": call.id,
                "type": "function",
                "function": {
                    "name": call.function.name,
                    "arguments": call.function.arguments,
                },
            }
        )
    result: dict[str, Any] = {"role": "assistant", "content": getattr(message, "content", None)}
    if calls:
        result["tool_calls"] = calls
    return result


def _fallback(status: str, answer: str, trace: list[dict], used: list[str], rounds: int) -> AgentResult:
    return AgentResult(answer=answer, status=status, trace=trace, tools_used=used, rounds=rounds)


def _summarize_tool_result(name: str, result: Any) -> dict[str, Any]:
    """Keep a compact, inspectable observation in the run trace."""
    if name == "search_documents" and isinstance(result, list):
        return {
            "count": len(result),
            "documents": [
                {
                    "doc_id": str(item.get("doc_id", "")),
                    "title": str(item.get("title", "")),
                    "version_date": str(item.get("version_date", "")),
                    "quote_preview": str(item.get("quote", ""))[:240],
                }
                for item in result[:10]
                if isinstance(item, dict)
            ],
        }
    if name == "read_document" and isinstance(result, dict):
        sections = result.get("sections", [])
        return {
            "doc_id": str(result.get("doc_id", "")),
            "section_count": len(sections) if isinstance(sections, list) else 0,
            "sections": [
                {
                    "heading": str(section.get("heading", "")),
                    "quote_preview": str(section.get("text", ""))[:240],
                }
                for section in sections[:10]
                if isinstance(section, dict)
            ] if isinstance(sections, list) else [],
        }
    return {"type": type(result).__name__}


def _decision_basis(name: str, arguments: dict[str, Any], trace: list[dict]) -> str:
    """Summarize observable inputs to a model-selected action, never model CoT."""
    previous = next(
        (item for item in reversed(trace) if item.get("action") in {"search_documents", "read_document"}),
        None,
    )
    if previous is None:
        return "根据当前问题，模型选择先从知识库获取证据。"
    if previous["action"] == "search_documents":
        count = previous.get("result_count", 0)
        if count == 0 and name == "search_documents":
            return "上次检索没有候选，模型选择使用新查询补充检索。"
        if name == "read_document":
            return f"上次检索返回 {count} 条候选片段，模型选择读取 {arguments.get('doc_id', '指定文档')} 原文核对上下文。"
        if name == "search_documents":
            return f"上次检索返回 {count} 条候选后，模型选择用新查询继续补充检索。"
    doc_id = previous.get("arguments", {}).get("doc_id", "文档")
    if name == "search_documents":
        return f"读取 {doc_id} 原文后，模型选择继续检索以补充证据。"
    return f"读取 {doc_id} 原文后，模型选择再核验 {arguments.get('doc_id', '其他文档')}。"


def _parse_final(question: str, content: str | None, evidence: list[dict], trace: list[dict], used: list[str], rounds: int) -> AgentResult:
    try:
        payload = json.loads(content or "")
    except json.JSONDecodeError:
        return _fallback(
            "tool_error",
            "模型未返回可验证的结构化结果，本轮未提供知识库答案。",
            trace,
            used,
            rounds,
        )
    if not isinstance(payload, dict):
        return _fallback("tool_error", "模型返回结果不是 JSON 对象，本轮未提供答案。", trace, used, rounds)
    status = payload.get("status")
    if status not in STATUSES:
        return _fallback("tool_error", "模型返回了无效任务状态，本轮未提供答案。", trace, used, rounds)
    evidence_by_doc: dict[str, list[dict]] = {}
    for item in evidence:
        evidence_by_doc.setdefault(str(item["doc_id"]), []).append(item)
    citations = []
    requested_citations = payload.get("citations", [])
    if not isinstance(requested_citations, list):
        requested_citations = []
    for item in requested_citations:
        if not isinstance(item, dict):
            continue
        doc_id = str(item.get("doc_id", ""))
        quote = str(item.get("quote", "")).strip()
        source = next(
            (
                candidate
                for candidate in evidence_by_doc.get(doc_id, [])
                if quote and quote in str(candidate.get("quote", ""))
            ),
            None,
        )
        if source:
            citations.append(
                {
                    "doc_id": source["doc_id"],
                    "title": source.get("title", ""),
                    "version_date": source.get("version_date", ""),
                    "quote": quote,
                }
            )
    answer_value = payload.get("answer", "")
    answer = answer_value.strip() if isinstance(answer_value, str) else ""
    gap_values = payload.get("gaps", [])
    gaps = [str(item) for item in gap_values if str(item).strip()] if isinstance(gap_values, list) else []
    if status == "answered" and not citations:
        return _fallback(
            "insufficient_evidence",
            "检索结果没有提供可核验引用，无法可靠回答。",
            trace,
            used,
            rounds,
        )
    if not answer:
        return _fallback("tool_error", "模型返回了空答案，本轮未完成。", trace, used, rounds)
    conflicts = _numeric_conflicts(evidence, question)
    if conflicts:
        conflict_citations = []
        statements = []
        for left, right in conflicts:
            for source in (left, right):
                citation = {
                    "doc_id": source["doc_id"],
                    "title": source.get("title", ""),
                    "version_date": source.get("version_date", ""),
                    "quote": source["quote"],
                }
                if citation not in conflict_citations:
                    conflict_citations.append(citation)
                statements.append(
                    f"{source['doc_id']}（版本 {source.get('version_date') or '未注明'}）："
                    f"‘{source['quote']}’"
                )
        trace.append({"action": "conflict_guard", "conflicts_found": len(conflicts)})
        return AgentResult(
            answer=(
                "检索到互相矛盾的资料：" + "；".join(statements)
                + "。现有资料未能确定适用范围或优先级，请确认应按哪项制度处理。"
            ),
            citations=conflict_citations,
            gaps=["缺少能够判定冲突资料适用范围或优先级的信息"],
            status="needs_clarification",
            trace=trace,
            tools_used=used,
            rounds=rounds,
        )
    return AgentResult(answer, citations, gaps, status, trace, used, rounds)


def _numeric_conflicts(evidence: list[dict], question: str = "") -> list[tuple[dict, dict]]:
    """Fail closed on different numeric values in otherwise identical statements."""
    units = r"工作日|小时|分钟|万元|天|日|元|个|次|%|％|GB|MB|月|年"
    pattern = re.compile(rf"(?P<value>\d+(?:\.\d+)?)\s*(?P<unit>{units})", re.IGNORECASE)
    grouped: dict[tuple[str, str], dict[str, dict[str, Any]]] = {}
    query_terms = re.findall(r"[A-Za-z0-9]{2,}|[\u4e00-\u9fff]{2,}", question.casefold())
    query_ngrams = {
        term[index : index + 2]
        for term in query_terms
        for index in range(max(1, len(term) - 1))
    }
    for source in evidence:
        quote = str(source.get("quote", ""))
        for sentence in re.split(r"[。！？；;\n]+", quote):
            label = f"{source.get('title', '')}{source.get('heading', '')}{sentence}".casefold()
            if query_ngrams and not any(term in label for term in query_ngrams):
                continue
            for match in pattern.finditer(sentence):
                context = pattern.sub("<VALUE>", sentence)
                context = re.sub(r"[\s\W_]+", "", context).casefold()
                key = (context, match.group("unit").casefold())
                grouped.setdefault(key, {})[str(source.get("doc_id", ""))] = {
                    **source,
                    "fact_value": match.group("value"),
                    "fact_unit": match.group("unit"),
                }
    conflicts = []
    for documents in grouped.values():
        if len(documents) < 2:
            continue
        values = {item["fact_value"] for item in documents.values()}
        if len(values) > 1:
            sources = list(documents.values())
            conflicts.extend((sources[0], item) for item in sources[1:])
    return conflicts


def run_question(
    question: str,
    history: list[dict[str, Any]] | None = None,
    *,
    model: Callable[[list[dict[str, Any]], list[dict]], Any] | None = None,
    tool_executor: Callable[[str, dict[str, Any]], Any] | None = None,
    max_rounds: int = MAX_TOOL_ROUNDS,
    max_tool_calls: int = MAX_TOOL_CALLS,
) -> AgentResult:
    if not question.strip():
        raise ValueError("问题不能为空")
    invoke_model = model or call_model
    execute = tool_executor or execute_tool
    messages = [
        {"role": "system", "content": SYSTEM_PROMPT},
        *(history or []),
        {"role": "user", "content": question.strip()},
    ]
    evidence: list[dict] = []
    trace: list[dict] = []
    used: list[str] = []
    tool_call_count = 0
    for round_number in range(1, max_rounds + 1):
        try:
            message = invoke_model(messages, TOOL_SPECS)
        except Exception as exc:
            trace.append({"action": "model_error", "error": str(exc)})
            return _fallback("tool_error", f"模型调用失败：{exc}", trace, used, round_number)
        messages.append(_message_dict(message))
        calls = getattr(message, "tool_calls", None) or []
        if not calls:
            trace.append({
                "action": "model_final",
                "decision_basis": "模型本轮未请求更多工具，返回最终结构化结果。",
            })
            return _parse_final(question, getattr(message, "content", None), evidence, trace, used, round_number)
        for call in calls:
            if tool_call_count >= max_tool_calls:
                trace.append({"action": "agent_limit", "max_tool_calls": max_tool_calls})
                return _fallback(
                    "incomplete",
                    "达到单轮工具调用次数上限，任务未完成；请补充或简化问题后重试。",
                    trace,
                    used,
                    round_number,
                )
            name = call.function.name
            tool_call_count += 1
            used.append(name)
            try:
                arguments = json.loads(call.function.arguments or "{}")
                trace.append({
                    "action": "model_tool_choice",
                    "tool": name,
                    "arguments": arguments,
                    "decision_basis": _decision_basis(name, arguments, trace),
                    "note": "基于可观察到的工具结果与实际工具调用生成的摘要，不包含模型内部思维过程。",
                })
                result = execute(name, arguments)
                if name == "search_documents" and isinstance(result, list):
                    evidence.extend(result)
                elif name == "read_document" and isinstance(result, dict):
                    for section in result.get("sections", []):
                        evidence.append(
                            {
                                "doc_id": result["doc_id"],
                                "title": result.get("title", ""),
                                "version_date": result.get("version_date", ""),
                                "heading": section.get("heading", ""),
                                "quote": section.get("text", ""),
                            }
                        )
                if isinstance(result, list):
                    result_count = len(result)
                elif name == "read_document" and isinstance(result, dict):
                    result_count = len(result.get("sections", []))
                else:
                    result_count = None
                trace.append({
                    "action": name,
                    "arguments": arguments,
                    "result_count": result_count,
                    "result_summary": _summarize_tool_result(name, result),
                })
                content = json.dumps(result, ensure_ascii=False)
            except Exception as exc:
                trace.append({"action": name, "error": str(exc)})
                return _fallback(
                    "tool_error",
                    f"知识库工具 {name} 执行失败；本轮停止，未根据不完整资料作答。",
                    trace,
                    used,
                    round_number,
                )
            messages.append({"role": "tool", "tool_call_id": call.id, "content": content})
    trace.append({"action": "agent_limit", "max_tool_rounds": max_rounds})
    return _fallback(
        "incomplete",
        "达到单轮工具调用上限，任务未完成；请补充或简化问题后重试。",
        trace,
        used,
        max_rounds,
    )


def next_history(history: list[dict[str, Any]], question: str, result: AgentResult) -> list[dict[str, Any]]:
    """Keep user-visible turns only; tool traces stay attached to each result."""
    return [
        *history,
        {"role": "user", "content": question.strip()},
        {"role": "assistant", "content": result.answer},
    ]
