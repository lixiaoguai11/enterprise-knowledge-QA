# 02 — 方案与调用流程

## 组件

- `backend/app/cli.py`：REPL、上下文生命周期和终端结果展示。
- `backend/app/qa_agent.py`：模型工具调用循环、结构化结果解析、引用校验和状态管理。
- `backend/app/knowledge_tools.py`：`search_documents` 和 `read_document` 两个只读工具。
- `backend/app/retrieval.py`：保留 BM25、向量召回、RRF 融合和可选重排。
- `backend/app/ingest.py`：将 Markdown 资料和元数据导入 SQLite 文档/片段表。

## 每轮调用

1. REPL 将当前问题与本会话可见的历史消息交给 Agent。
2. 模型通过 DeepSeek function calling 选择检索、读原文或直接结束/追问。
3. Agent 执行只读工具，将结果和调用记录回传模型，最多执行 6 轮模型决策。
4. 模型以 JSON 返回 answer/citations/gaps/status；解析器仅保留工具返回中完全匹配的文档 ID 和原文片段。
5. 无有效引用的 `answered` 自动降级为 `insufficient_evidence`；工具异常立即停止本轮并返回 `tool_error`，超过调用上限返回 `incomplete`。
6. REPL 展示引用、资料缺口和 Trace；`/new` 清空历史。

## 决策规则

- 检索结果用于定位证据；证据范围或语义不足时读取整份已索引文档。
- 若证据明确且无冲突，可依据引用回答。
- 若证据缺失，说明缺口并拒答。
- 若资料对同一属性给出不同值且没有适用范围/优先级依据，引用双方并追问用户。版本日期作为来源信息展示，本身不构成跨制度优先级。
- 达到工具轮数上限、模型响应不可解析或工具失败均不视为成功回答。

## 设计取舍

- 保留现有本地 SQLite 与混合检索，减少已有数据处理和中文召回能力的重写成本。
- 用只读搜索/读取工具替代旧版夹带写操作的业务工具，缩小 Agent 权限。
- 通过模型决策支持多轮查证；结构解析、引用白名单和工具失败处理由代码强制执行。
- 向量和重排模型可选加载，保持 BM25 降级路径；LLM 不可用时不生成答案。
- REPL 历史仅驻留当前进程，不持久化员工身份或会话数据。
