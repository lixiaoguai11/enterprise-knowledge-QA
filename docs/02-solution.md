# 02 — 方案、调用流程与关键决策

一次问答依次经过 CLI 初始化、模型工具循环、检索排序、证据校验和终端输出。以下代码链接对应各环节的实现。

## 总体结构

```mermaid
flowchart TD
    A[员工在 CLI 输入问题] --> B[qa_agent.run_question]
    B --> C{LLM_PROVIDER}
    C -->|deepseek| C1[OpenAI兼容 Chat Completions]
    C -->|anthropic| C2[Anthropic Messages API]
    C1 --> M[模型决定下一步]
    C2 --> M
    M -->|search_documents| D[BM25 + 可选向量召回]
    D --> E[可选 RRF + 配置的 reranker]
    M -->|read_document| F[SQLite 文档切片]
    E --> G[工具结果追加到对话]
    F --> G
    G -->|最多 6 次模型请求 / 8 次工具调用| C
    M -->|最终 JSON| I[JSON 解析与引用校验]
    I --> J[数字冲突守卫]
    J --> K[CLI 打印 answer/citations/gaps/status/trace]
```

| 阶段 | 输入 | 主要处理 | 输出/副作用 | 代码入口 |
|---|---|---|---|---|
| 初始化 | `data/clean/`、`data/meta/manifest.csv`、SQLite | 创建表；数据库为空时导入文档；构造检索索引 | `backend/knowledge.db`、进程内索引、可选向量缓存 | `cli.initialize()`、`ingest.import_clean_docs()` |
| 对话 | 当前问题和 user/assistant 历史 | 组装 provider-neutral 的内部消息 | 本轮模型请求 | `cli.repl()`、`qa_agent.run_question()` |
| 检索/读原文 | 模型工具调用参数 | 搜索 top-k 片段或按文档 ID 读出全部已索引切片 | 带 `doc_id`、日期、标题、原文片段的工具结果 | `knowledge_tools.py` |
| 决策与验证 | 模型响应、工具结果 | 最多 6 轮模型请求、8 次工具调用；解析 JSON；检查引用和数字冲突 | `AgentResult`，包含状态、引用、缺口和可观察决策 Trace | `qa_agent.py` |
| 展示 | `AgentResult` | 按终端格式渲染 | 终端文本；历史仅保存 user/assistant 答案 | `cli_output.format_result()`、`cli.next_history()` |

源码快速跳转：[CLI 初始化与 REPL](../backend/app/cli.py#L13)、[Markdown 切片与导入](../backend/app/ingest.py#L124)、[模型请求](../backend/app/qa_agent.py#L40)、[最终解析与引用过滤](../backend/app/qa_agent.py#L79)、[Agent 主循环](../backend/app/qa_agent.py#L209)、[BM25/向量/RRF](../backend/app/retrieval.py#L30)。

## 启动：为什么先导入和建索引

CLI 在 `backend/app/cli.py` 的 `initialize()` 中先调用 `init_db()`。随后检查 `documents` 表：如果表里没有文档，才调用 `import_clean_docs()`；若已经存在文档，则跳过重新导入。最后执行 `retrieval.build_index()`，构建 BM25 和可选向量索引。默认相似度重排没有单独模型要加载；使用远端 Embedding 时，建索引会调用配置的向量服务。

导入流程位于 `backend/app/ingest.py`：读取 manifest 的 `文件名` 字段，将路径解析到 `data/clean/`；从 Markdown 文件和元数据注释读取 ID、标题、类别、来源、更新日期；去掉 front matter/HTML 注释；按标题和段落分段；普通片段最大约 800 字符；保存到 SQLite 的 `documents` 与 `chunks` 表。模型引用的是切片，因此 quote 不一定包含原文件整页文本。

资料的生成、公开来源和清洗记录见[数据来源、加工与入库](07-data-provenance.md)。

### 数据库与缓存状态

- SQLite 默认位置是 `backend/knowledge.db`。它一旦有任意文档，CLI 不会自动检查 manifest 后再导入新文件。
- 向量缓存位于 `backend/data/embeddings/`，包含向量矩阵、chunk ID 列表和模型/后端元数据。切换本地与远端后端、模型名或远端 URL 会使缓存失效并重新生成；API Key 不写入缓存元数据。
- 缓存以 chunk ID 列表判断资料变化，未记录原文哈希。原文改动但 ID 列表不变时，向量可能过期。更新资料后同时重建 SQLite 与 `backend/data/embeddings/`；BM25 会在进程启动时从 SQLite 重建。
- 本地 FastEmbed 首次使用可能需要下载。默认重排不再加载或下载 CrossEncoder，而是复用向量矩阵。远端 Embedding API 在建索引时需要服务可达；初始化异常会关闭向量功能并回退 BM25，后续单次查询请求失败则按工具失败处理。
- 当前远端 BGE 服务限制输入为 512 token。API 路径将超过 400 字符的片段拆成重叠 50 字符的窗口，再平均窗口向量；查询使用相同策略。400 字符是针对该服务的保守长度控制，不是精确 token 计数。
- 远端模式会将 SQLite 中已导入的文档片段和检索 query 发送到 `EMBEDDING_BASE_URL` 指定的服务；API Key 不进入 Trace 或缓存元数据。部署者需确认服务端的数据处理和网络边界适合这些文档。

## 一轮问题：消息如何组装

`run_question(question, history)` 首先拒绝空白问题，然后创建以下实际协议形态的消息：

```python
[
  {"role": "system", "content": SYSTEM_PROMPT},
  # 之前每轮只保留的 user/assistant 文本消息
  {"role": "user", "content": "当前问题"},
]
```

`SYSTEM_PROMPT` 要求模型依据工具证据作答、按需补充搜索或读原文、冲突时请求确认，并以 JSON 返回 `answer/citations/gaps/status`。OpenAI 兼容路径通过 `tools` 参数提供工具规格，`tool_choice="auto"` 允许模型选择动作，temperature 为 0.1。上面的代码展示内部消息形状。

模型发出工具调用时，Agent 内部统一为 Assistant 消息的 `tool_calls`，程序逐个执行工具，并把 JSON 工具结果回传模型。下一轮模型请求会继续携带 system、历史、当前问题、assistant tool call 和 tool result。完成本轮后，CLI 的 `next_history()` 只加入 user 问题和 assistant 最终答案，不把内部工具 JSON 作为长期对话历史保存。

`AgentResult.trace` 按执行顺序记录 `model_tool_choice`（模型实际选的工具、参数和基于可见结果的简短摘要）、工具事件（结果条数及文档/原文摘要）和 `model_final`。`decision_basis` 由程序依据上一个工具事件和本次真实工具调用生成，只描述可观察的动作依据，不记录或声称代表模型内部思维过程。它让评审者能回答“工具返回了什么，模型之后做了什么”。真实运行对照见 [05-live-anthropic-success.json](../examples/05-live-anthropic-success.json)、[08-live-qwen-reranker.json](../examples/08-live-qwen-reranker.json) 和 [09-live-product-question.json](../examples/09-live-product-question.json)。

## 模型 Provider 切换与协议适配

由仓库根目录 `.env` 的 `LLM_PROVIDER` 选择模型协议：`deepseek`（默认）或 `anthropic`。两者共用 Agent 的决策循环、知识库工具、引用验证和冲突守卫，但各自使用对应 SDK 和线协议。修改 `.env` 后需重启 CLI。

- `deepseek`：使用 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`MODEL_NAME`，通过 OpenAI SDK 的 `chat.completions.create` 调用。内部工具规格直接按 OpenAI function tool 形状发送。
- `anthropic`：使用 `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL`、`ANTHROPIC_MODEL`，通过 Anthropic SDK 的 `messages.create` 调用。`ANTHROPIC_BASE_URL` 可指向实现 Anthropic Messages API 形状的兼容网关；若 URL 结尾带 `/v1`，适配器会去掉该后缀，因为 SDK 会自行请求 `/v1/messages`。请求把 system 提示单独传入，将 function 参数 schema 转为 `input_schema`，响应的 `tool_use` 转成 Agent 内部工具调用；工具执行结果再转为 user 消息中的 `tool_result` 块。
- Anthropic 专用的 API Key、URL、模型名优先；若未填写，Anthropic 配置会回退到现有 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL`、`MODEL_NAME`，方便对同时支持两种协议的同一网关切换。未知 `LLM_PROVIDER` 会报明确错误，不自动回退，以免请求协议与用户选择不一致。
- Anthropic Messages API 要求 `max_tokens`，本项目适配器设为 2048；当前适配器不发送 `temperature`，使用服务端/模型默认采样设置。若所选模型或网关不接受 token 上限，可在适配器中调整。这里对 Anthropic 兼容性的含义是“使用 Anthropic 原生请求/响应结构”，不是任意自定义 HTTP API 都会兼容。

SDK 负责鉴权、HTTP 请求和响应对象解析；`_to_anthropic_messages()`、`_to_anthropic_tools()` 与 `_from_anthropic_response()` 负责两种协议间的边界映射。映射集中在 `qa_agent.py`，保持检索和证据校验逻辑与模型厂商无关。

## 动态决策与工具边界

### `search_documents`

- 参数：`query` 必填、`top_k` 可选；执行时限制为 1 到 10，默认 5。
- 检索以工具调用中的 query 为准。代码不会在调用前自动改写用户问题；改写检索词由模型根据原问题和对话上下文决定。
- 返回对象含 `doc_id/title/version_date/heading/quote/score`。`quote` 是检索到的 chunk 原文。

### `read_document`

- 参数：`doc_id`。
- 从 SQLite 取该文档全部切片，按 `chunk_index` 排列，返回标题、版本日期和各段文本。它不重新读取磁盘上的 Markdown 文件，所以磁盘改动必须先重新导入数据库。
- 若 doc_id 不存在，`execute_tool()` 返回 `{"error": "未找到该文档 ID"}`，Agent 将其作为工具结果回传模型；该结果不提供可引用证据。当前 Trace 不把这种业务错误标为 `tool_error`。
- 模型应在候选片段不足以判断范围、例外或优先级时读取原文。是否读取由模型判断，不是代码无条件触发。

### 检索排序

1. Jieba 对小写问题和 chunk 分词。BM25 用 `k1=1.5`、`b=0.75` 对每段计分，取前 20 个候选（`retrieval.py` 的 `HYBRID_CANDIDATES`）。标点单独 token 会过滤。
2. 设置 `EMBEDDING_API_KEY` 时，通过 OpenAI 兼容 Embedding API（`EMBEDDING_BASE_URL`、`EMBEDDING_MODEL_NAME`）批量生成 chunk 向量，并用同一模型生成 query 向量；未设置 Key 时使用本地 FastEmbed 模型 `paraphrase-multilingual-MiniLM-L12-v2`。远端输入超过 400 字符时分为 400 字符窗口、50 字符重叠并平均窗口向量。向量候选按余弦相似度取最多 20 项。它补充同义表达和语义相近内容，但高相似度不等于事实正确。
3. 如果向量索引可用，BM25 和向量排名用 RRF 融合，常数 `RRF_K=60`。如果向量不可用，直接使用 BM25 排名。
4. `RERANKER_PROVIDER` 选择第二阶段排序器。`bge_similarity` 复用 query embedding，给 RRF 候选（含 BM25-only 项）计算余弦相似度；`qwen_api` 把候选文本发到 `RERANK_BASE_URL`，根据 API 返回的 relevance score 重排；`none` 关闭第二阶段。当前 RRF 分和 rerank 分各自按本轮候选 min-max 归一化后等权组合，再取最终 `top_k`。

### 重排接口与后续 provider

`backend/app/reranker.py` 定义 `Reranker` Protocol：输入 query 与候选列表，输出保留候选元数据并带 `rerank_score` 的列表。`EmbeddingSimilarityReranker` 消费向量余弦分，不发起额外请求；`QwenAPIReranker` 调用完整 `RERANK_BASE_URL`，请求形状为 `model/query/documents/top_n`，将响应的 `results` 或 `output.results` 中的 `index`、`relevance_score` 映射回候选。请求格式参照 [Qwen 官方 Reranking 文档](https://docs.qwencloud.com/developer-guides/embeddings/reranking) 的兼容接口示例；自建服务仍可能采用不同 schema，需先用真实 endpoint 验证。对其他兼容服务可以实现同一接口并注册 provider。API 错误沿检索工具失败路径返回，不静默沿用未经重排的结果。

当前没有相似度硬阈值。空结果表示本次检索未命中，不能证明资料库中不存在答案；排序分数也不是答案置信度。

## 最终答案的代码校验

模型无工具调用时，Agent 将其 `content` 解析为 JSON：

1. 非 JSON、非对象、未知状态或空答案返回 `tool_error`。
2. `citations` 的 `doc_id` 必须出现于本轮工具结果；`quote` 必须是对应工具 quote 的子串。违反条件的引用被丢弃。
3. 若模型声称 `answered` 但没有任何剩余引用，降级为 `insufficient_evidence`。
4. 对“与问题相关且多份材料中归一化后句式相同、单位相同、数值不同”的有限数字冲突，代码无视模型选择，改成 `needs_clarification`，引用双方并询问适用范围/优先级。
5. 其他语义冲突主要依赖模型提示词判断。引用子串校验只证明原文里存在这段字，不证明答案的所有结论都能从该引用推出。

工具执行抛异常会立刻以 `tool_error` 结束，避免基于部分证据继续回答。模型 API 异常也走 `tool_error`。单轮最多发起 6 次模型请求，最多执行 8 次工具调用；达到任一上限时返回 `incomplete`，Trace 标明触发的是哪个上限。若模型在一次响应中并行请求多个工具，也会逐一计入 8 次上限。

## 状态表：用户应如何理解结果

| 状态 | 含义 | 常见原因 | 对用户的下一步 |
|---|---|---|---|
| `answered` | 有至少一条通过引用白名单的证据，模型完成作答 | 单一、相关证据；无已识别冲突 | 检查原文与问题范围是否吻合 |
| `needs_clarification` | 资料存在未解决冲突，或模型判定需要补充范围 | D01/D02 期限不同且没有优先级 | 指明适用制度/部门；资料管理员补充范围规则 |
| `insufficient_evidence` | 没有可核验的支持引用，不能可靠回答 | 资料外问题、空检索、模型给了无效引用 | 补充权威资料或重新描述问题 |
| `tool_error` | 本轮调用模型或工具失败，不能依赖本轮答案 | Key/网络/模型服务/SQLite/检索异常 | 查看 Trace 中的错误并修复后重试 |
| `incomplete` | 达到最大决策轮数仍未产生最终答案 | 模型持续调用工具 | 简化问题或检查工具结果是否无助于决策 |

## 冲突例子：为什么不能只按日期挑一个

D01（2026-01-10）写“30 天”，D02（2026-02-01）写“15 天”。两份资料均未写适用部门，也未指定互相冲突时的优先级。较新的版本日期只是来源元数据，不足以证明 D02 适用全部员工。正确输出应并列陈述两份原文，列出“缺少适用范围/优先级”，并请求确认制度；不得仅因为 15 天版本日期较新就作答 15 天。

离线示例中的模型故意只回答 15 天，用来验证应用层的数字冲突守卫会覆盖这个不安全结论。示例见 [02-conflict.json](../examples/02-conflict.json)。这证明守卫能处理这一种句式，并不代表通用的矛盾检测已经解决。

## 关键设计决策与取舍

| 决策 | 选择与理由 | 放弃/代价 | 什么时候需要改变 |
|---|---|---|---|
| 只保留 CLI | 用户要求只有一种入口；REPL 可直接展示 Trace，部署路径短 | 不支持多人、浏览器共享、服务集成 | 需要多用户服务时，再设计 API 和身份边界，不要直接把 REPL 包进未授权接口 |
| 本地 SQLite | 单机演示容易安装、可复现、适合少量合成资料 | 并发能力、备份和权限较弱；现有迁移能力有限 | 数据量、协作或审计要求提高时评估 PostgreSQL 和迁移工具 |
| 本地原文 + manifest | 文件可审阅、文档 ID/日期能随检索返回，替换资料容易 | 内容质量、元数据和路径需要人工维护；文档扫描/解析有限 | 输入变成 Office/PDF 或管理量变大时，增加经过校验的解析导入流程 |
| BM25 作为基础，向量与相似度重排为可选增强 | 中文关键词命中可离线/本地运行，向量可选本地 FastEmbed 或 OpenAI 兼容 Embedding 服务；复用 query embedding 做候选重排，避免逐候选 API 请求 | 远端向量依赖网络和服务；本地模式有模型下载成本；min-max 融合分数受候选集合影响；缓存仍需在资料更新后重建 | 需要质量指标时先建固定测试集，对 BM25、混合和重排做可复现对照；再评估独立 CrossEncoder/Jina 的准确率、延迟与成本 |
| LLM 用 function calling 选工具，并提供协议适配 | DeepSeek 兼容接口与 Anthropic 原生 Messages API 都映射到同一工具循环，模型仍可根据证据搜索、读原文或结束 | 多维护一套依赖与协议映射；兼容网关的 URL、模型名、Key 和 token 限制需要按服务商配置 | 增加 provider 时先定义内部消息/工具调用契约，再实现单独适配器，避免把厂商条件散落在 Agent 主循环 |
| 直接使用 OpenAI Python SDK，不再引入 Agent 框架 | DeepSeek 提供 OpenAI 兼容 Chat Completions；当前只有两个工具和一个短循环，直接 SDK 让消息、工具调用和异常路径清晰可见 | 工具循环、结果校验和状态机需要项目自己维护 | 流程变复杂、需要持久化执行、观测或并发控制时，再比较框架能力与引入成本 |
| 工具只读 | Agent 只能找资料，不能审批、改文档或触发业务副作用 | 不支持写回、流程办理 | 若新增写操作，需单独加入权限、二次确认、审计和幂等设计 |
| 代码校验引用 + 有限冲突守卫 | 避免无来源 doc_id/引文，拦截验收例中的数字冲突 | 子串匹配不等于语义蕴含；规则对表述变化敏感 | 扩展为实体/属性抽取、冲突评测集和人工审核闭环 |
| 只保存本次进程中的对话 | 实现简单，离开进程不留员工对话内容 | 无长期记忆、恢复能力和多用户区分 | 需持久化时先明确隐私、保留时间、访问权和删除机制 |
| 用脚本模型做离线编排测试 | 无需 Key、稳定复现工具循环、失败及冲突守卫 | 不测真实模型决策、检索召回或在线稳定性 | 持续补真实 API Trace、端到端资料替换和固定评测集，不把两类证据混为一谈 |

## 证据校验的实际范围

- system prompt 指导模型；引用白名单、JSON 状态检查、有限数字冲突守卫和异常分支由程序执行。
- `read_document` 返回的是 SQLite 中已导入的切片，不是实时磁盘文件。
- 注入工具响应的测试覆盖 Agent 控制流；真实召回链路的运行记录单独列于[评估文档](03-evaluation.md)。
- Search/read 工具成功返回表示调用完成；资料是否适用仍须结合原文与问题判断。
- `answered` 表示至少有一条引用通过来源检查，答案的语义支持程度仍需单独评估。

## 修改时从哪儿开始

- 改 REPL 命令和历史：`backend/app/cli.py`、`next_history()`。
- 增加工具：先扩展 `backend/app/knowledge_tools.py` 的 schema 和执行函数，再在 `qa_agent.py` 处理证据形态，并增加替身测试。
- 调整切片：改 `backend/app/ingest.py` 的 `MAX_CHUNK_CHARS` 或分段逻辑；重新导入 DB，并清理向量缓存。
- 调整召回：修改 `backend/app/retrieval.py`；用改写问题测试召回并记录候选，不要只凭单次模型回答判断质量。
- 调整冲突规则：修改 `_numeric_conflicts()` 和 `_parse_final()`，加入同类句式、无关数字、相关冲突和范围明确等正反案例。
- 改输出字段：同步更新 `AgentResult`、`format_result()`、Trace JSON 和评估表，避免文档与 CLI 不一致。
