import json
from types import SimpleNamespace

from app.qa_agent import next_history, run_question
from app.cli_output import format_result


def tool_call(name, arguments, call_id="call-1"):
    return SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(
                id=call_id,
                function=SimpleNamespace(
                    name=name, arguments=json.dumps(arguments, ensure_ascii=False)
                ),
            )
        ],
    )


def final(value):
    return SimpleNamespace(content=json.dumps(value, ensure_ascii=False), tool_calls=[])


class ScriptedModel:
    def __init__(self, outputs):
        self.outputs = list(outputs)
        self.messages_seen = []

    def __call__(self, messages, tools):
        self.messages_seen.append(messages)
        return self.outputs.pop(0)


def test_clear_answer_has_exact_citation():
    evidence = [{"doc_id": "D03", "title": "报销流程 FAQ", "version_date": "2026-03-01", "quote": "上传发票及付款凭证。"}]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "报销要上传什么"}),
        final({"answer": "提交报销时上传发票及付款凭证。", "citations": [{"doc_id": "D03", "quote": evidence[0]["quote"]}], "gaps": [], "status": "answered"}),
    ])
    result = run_question("报销要上传什么", model=model, tool_executor=lambda *_: evidence)
    assert result.status == "answered"
    assert result.citations[0]["quote"] == evidence[0]["quote"]
    assert any(item["action"] == "search_documents" for item in result.trace)


def test_conflicting_documents_are_both_cited_and_require_clarification():
    evidence = [
        {"doc_id": "D01", "title": "制度", "version_date": "2026-01-10", "quote": "报销申请须在 30 天内提交。"},
        {"doc_id": "D02", "title": "规则", "version_date": "2026-02-01", "quote": "报销申请须在 15 天内提交。"},
    ]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "报销期限"}),
        tool_call("read_document", {"doc_id": "D01"}, "call-2"),
        final({"answer": "报销期限是 15 天。", "citations": [{"doc_id": "D02", "quote": evidence[1]["quote"]}], "gaps": [], "status": "answered"}),
    ])
    def execute(name, _):
        return evidence if name == "search_documents" else {"doc_id": "D01", "title": "制度", "version_date": "2026-01-10", "sections": [{"heading": "期限", "text": evidence[0]["quote"]}]}
    result = run_question("报销期限多久", model=model, tool_executor=execute)
    assert result.status == "needs_clarification"
    assert {item["doc_id"] for item in result.citations} == {"D01", "D02"}
    assert any(item["action"] == "read_document" for item in result.trace)
    assert result.trace[-1]["action"] == "conflict_guard"


def test_out_of_scope_question_is_insufficient():
    model = ScriptedModel([
        tool_call("search_documents", {"query": "火星天气"}),
        final({"answer": "现有知识库没有相关资料，无法可靠回答。", "citations": [], "gaps": ["缺少火星天气资料"], "status": "insufficient_evidence"}),
    ])
    result = run_question("火星天气如何", model=model, tool_executor=lambda *_: [])
    assert result.status == "insufficient_evidence"
    assert result.citations == []


def test_rephrased_similar_question_is_retrieved():
    searched = []
    evidence = [{"doc_id": "D03", "title": "流程", "version_date": "2026-03-01", "quote": "网络恢复后在线提交。"}]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "没有网络时如何补交报销票据"}),
        final({"answer": "网络恢复后在线提交。", "citations": [{"doc_id": "D03", "quote": evidence[0]["quote"]}], "gaps": [], "status": "answered"}),
    ])
    def execute(name, args):
        searched.append(args["query"])
        return evidence
    result = run_question("断网了，票据之后怎么交？", model=model, tool_executor=execute)
    assert result.status == "answered"
    assert searched == ["没有网络时如何补交报销票据"]


def test_follow_up_uses_prior_conversation_context():
    history = [{"role": "user", "content": "报销怎么提交？"}, {"role": "assistant", "content": "填写报销单并上传票据。"}]
    evidence = [{"doc_id": "D03", "title": "流程", "version_date": "2026-03-01", "quote": "提交前核对部门和成本中心。"}]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "报销提交前核对什么"}),
        final({"answer": "提交前核对部门和成本中心。", "citations": [{"doc_id": "D03", "quote": evidence[0]["quote"]}], "gaps": [], "status": "answered"}),
    ])
    result = run_question("提交前还要核对什么？", history, model=model, tool_executor=lambda *_: evidence)
    assert result.status == "answered"
    assert model.messages_seen[0][1:3] == history
    assert next_history(history, "提交前还要核对什么？", result)[-2]["role"] == "user"


def test_tool_failure_returns_failed_status_and_trace():
    model = ScriptedModel([tool_call("search_documents", {"query": "报销"})])
    def fail(*_):
        raise OSError("index unavailable")
    result = run_question("报销期限多久", model=model, tool_executor=fail)
    assert result.status == "tool_error"
    assert next(item for item in result.trace if "error" in item)["error"] == "index unavailable"
    assert result.citations == []


def test_tool_round_limit_is_reported_as_incomplete():
    model = ScriptedModel([tool_call("search_documents", {"query": "报销"})])
    result = run_question("报销期限多久", model=model, tool_executor=lambda *_: [], max_rounds=1)
    assert result.status == "incomplete"
    assert result.trace[-1]["action"] == "agent_limit"


def test_tool_call_limit_is_enforced_even_for_parallel_model_calls():
    response = SimpleNamespace(
        content=None,
        tool_calls=[
            SimpleNamespace(id=f"call-{index}", function=SimpleNamespace(
                name="search_documents", arguments=json.dumps({"query": f"q{index}"})
            ))
            for index in range(3)
        ],
    )
    executed = []
    result = run_question(
        "报销期限多久",
        model=ScriptedModel([response]),
        tool_executor=lambda name, args: executed.append((name, args)) or [],
        max_tool_calls=1,
    )
    assert result.status == "incomplete"
    assert len(executed) == 1
    assert result.trace[-1] == {"action": "agent_limit", "max_tool_calls": 1}


def test_replacing_source_value_changes_supported_answer():
    def answer_for(value):
        evidence = [{"doc_id": "D01", "title": "制度", "version_date": "2026-01-10", "quote": f"报销须在 {value} 天内提交。"}]
        model = ScriptedModel([
            tool_call("search_documents", {"query": "报销期限"}),
            final({"answer": f"报销期限为 {value} 天。", "citations": [{"doc_id": "D01", "quote": evidence[0]["quote"]}], "gaps": [], "status": "answered"}),
        ])
        return run_question("报销期限多久", model=model, tool_executor=lambda *_: evidence)
    assert answer_for(30).answer != answer_for(20).answer


def test_fabricated_quote_is_removed_and_answer_is_downgraded():
    evidence = [{"doc_id": "D03", "title": "流程", "version_date": "2026-03-01", "quote": "提交前核对部门。"}]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "报销提交前"}),
        final({"answer": "提交前核对财务总监。", "citations": [{"doc_id": "FAKE", "quote": "财务总监必须签字。"}], "gaps": [], "status": "answered"}),
    ])
    result = run_question("报销提交前需要谁签字", model=model, tool_executor=lambda *_: evidence)
    assert result.status == "insufficient_evidence"
    assert result.citations == []


def test_unrelated_numeric_statements_do_not_trigger_conflict_guard():
    evidence = [
        {"doc_id": "D01", "title": "制度", "version_date": "2026-01-10", "quote": "报销申请须在 30 天内提交。"},
        {"doc_id": "D02", "title": "规则", "version_date": "2026-02-01", "quote": "报销申请须在 15 天内提交。"},
    ]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "会议室如何预订"}),
        final({"answer": "资料没有会议室预订说明。", "citations": [], "gaps": ["缺少会议室预订资料"], "status": "insufficient_evidence"}),
    ])
    result = run_question("会议室如何预订", model=model, tool_executor=lambda *_: evidence)
    assert result.status == "insufficient_evidence"
    assert all(step["action"] != "conflict_guard" for step in result.trace)


def test_cli_output_displays_citations_gaps_status_and_trace():
    evidence = [{"doc_id": "D03", "title": "流程", "version_date": "2026-03-01", "quote": "提交前核对部门。"}]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "报销"}),
        final({"answer": "提交前核对部门。", "citations": [{"doc_id": "D03", "quote": evidence[0]["quote"]}], "gaps": ["成本中心未说明"], "status": "answered"}),
    ])
    result = run_question("报销怎么做", model=model, tool_executor=lambda *_: evidence)
    rendered = format_result(result)
    assert "状态：answered" in rendered
    assert "D03" in rendered and "提交前核对部门。" in rendered
    assert "成本中心未说明" in rendered and "search_documents" in rendered


def test_trace_has_model_choice_basis_and_observation_summary():
    evidence = [{"doc_id": "D03", "title": "流程", "version_date": "2026-03-01", "quote": "提交前核对部门。"}]
    model = ScriptedModel([
        tool_call("search_documents", {"query": "报销"}),
        final({"answer": "提交前核对部门。", "citations": [{"doc_id": "D03", "quote": evidence[0]["quote"]}], "gaps": [], "status": "answered"}),
    ])
    result = run_question("报销怎么做", model=model, tool_executor=lambda *_: evidence)
    choice = next(item for item in result.trace if item["action"] == "model_tool_choice")
    observation = next(item for item in result.trace if item["action"] == "search_documents")
    assert choice["tool"] == "search_documents"
    assert choice["decision_basis"]
    assert observation["result_summary"]["documents"][0]["doc_id"] == "D03"
    assert result.trace[-1]["action"] == "model_final"
