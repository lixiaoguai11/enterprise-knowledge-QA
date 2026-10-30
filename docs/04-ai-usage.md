# 04 — AI 使用与作者贡献

## 贡献归属

作者确定了项目的业务目标、考核要求、技术栈、系统结构、模块职责、模型和检索方案、业务规则、验证方法、文档组织及交付方式。AI 编程助手按照这些决定修改代码；本轮还按作者要求润色了项目文档的文字。需求、技术选择、设计判断和验证结论由作者负责。

## AI 承担的执行工作

- 根据作者给定的需求修改 Python 应用代码、测试和运行脚本。
- 根据作者给定的协议与服务参数实现模型、Embedding 和 rerank 接入。
- 根据作者确定的决策规则修改 Agent 工具循环、证据处理、错误状态和输出结构。
- 按作者要求编辑 README、设计说明和评估文档的措辞、结构与交叉引用，保留原有事实依据及作者确定的方案。

需求定义、技术选型、服务配置、验收标准和文档中的项目决策均来自作者。评估结论以仓库保存的测试输出与 Trace 为依据。

## 作者提出的业务与产品要求

1. **用户与目标**：服务企业员工，帮助查找制度或产品知识；回答要可靠、可追溯，并直接使用知识库证据。
2. **唯一运行入口**：采用交互式 CLI。删除原项目的 Web 前端、HTTP API、登录/权限和请假审批等其他产品路径，项目不提供网页或单次命令问答入口。
3. **输入**：接受自然语言问题，并可使用同一会话内之前的用户/助手对话历史。`/help`、`/new`、`/exit` 用于查看帮助、清空上下文和退出。
4. **知识资料**：以带文档 ID、标题和版本日期的 Markdown 合成 FAQ/制度作为演示语料；通过 CSV manifest 维护文档编号、文件路径、类别、来源和日期；导入后切为带标题、片段序号和原文的知识块。
5. **工具边界**：向模型开放只读的 `search_documents` 与 `read_document`。前者返回候选原文片段和文档元数据，后者按文档 ID 读取已导入的完整切片；Agent 不写资料、不审批、不触发业务副作用。
6. **输出契约**：每轮给出 `answer`、`citations`、`gaps`、`status`，终端同时展示本轮工具 Trace。引用保留文档 ID、标题、版本日期和可核对原文；状态表达已回答、需澄清、证据不足、工具失败或执行未完成。
7. **证据纪律**：没有相关资料时说明资料不足；引用必须来自工具结果；工具失败时停止基于不完整证据作答；达到执行上限时明确返回未完成状态。
8. **冲突规则**：D01 写明报销期限 30 天、D02 写明 15 天，且未给适用范围或优先级。遇到这种冲突时，列出双方原文及来源，说明缺少判定依据并请求确认适用制度，不根据日期、排序分数或模型偏好选择一方。只有一个相关来源且没有冲突时，才可据其作答。

## 作者选择的技术栈与架构

| 层次/组件 | 作者的选择 | 在项目中的职责 | 代码或配置位置 |
|---|---|---|---|
| 语言与运行环境 | Python 3.12+；使用 `uv` 创建虚拟环境并安装依赖 | 承载 CLI、Agent、工具、数据导入和测试脚本 | `backend/requirements.txt`、README |
| 用户入口 | Python 标准库交互式 REPL | 管理输入、`/help`、`/new`、`/exit` 和进程内对话历史 | `backend/app/cli.py` |
| Agent Harness（运行与控制框架） | 作者选择项目内原生 Python harness，不采用 LangGraph、ADK 等外部 Agent 框架 | 统一承接模型适配器、工具 schema 与执行器、观察结果回传、证据收集、错误状态、Trace 及轮数/工具数上限 | `backend/app/qa_agent.py`、`backend/app/knowledge_tools.py` |
| LLM 协议 | OpenAI Python SDK 3.3.0 + Anthropic Python SDK 2.3.0 | DeepSeek 走 OpenAI-compatible Chat Completions/function calling；Anthropic 走 Messages API 并将 `tool_use`/`tool_result` 映射到内部工具循环 | `backend/app/qa_agent.py`、`.env.example` |
| 本地知识存储 | SQLite + SQLAlchemy 2.0.52 | 保存 `Document` 元数据和关联的 `Chunk` 原文片段；不另建 Web 服务或数据库服务 | `backend/app/database.py`、`backend/app/models.py` |
| 文件导入 | Markdown + CSV manifest | 从合成资料构建文档记录及可检索片段；启动时仅在数据库为空时首次导入 | `data/clean/`、`data/meta/manifest.csv`、`backend/app/ingest.py` |
| 词法检索 | Jieba 0.42.1 + 项目内 BM25 实现 | 中文分词后计算 BM25 候选；不额外依赖外部 BM25 框架 | `backend/app/retrieval.py` |
| 向量检索 | OpenAI SDK 3.3.0（OpenAI-compatible Embedding）或 FastEmbed 0.8.0 | 将文档片段与查询编码为向量；配置远端 Key 时用指定服务，未配置时使用本地多语言模型 | `backend/app/retrieval.py`、`.env.example` |
| 向量计算与融合 | NumPy 2.5.2；余弦相似度；项目内 Reciprocal Rank Fusion（RRF） | 计算向量候选排序，并合并 BM25/向量的排名；不把相似度分数当作事实可信度 | `backend/app/retrieval.py` |
| 重排接口 | BGE embedding 相似度默认路径；可切换 `qwen_api` 或 `none` | BGE 复用本轮 query embedding；Qwen adapter 将 query 和候选片段发给作者配置的 rerank 服务，再融合分数 | `backend/app/reranker.py`、`backend/app/retrieval.py`、`.env.example` |
| rerank 服务 | 作者配置的 `Qwen/Qwen3-Reranker-8B` 服务，URL 为 `http://192.168.110.23:16386/rerank` | 通过项目适配器执行远端候选排序 | `.env` 本地配置、`backend/app/reranker.py` |
| 环境配置 | python-dotenv 1.2.3 与根目录 `.env` | 从本机读取模型、Embedding 和 rerank 参数；模板只提交占位字段 | `backend/app/config.py`、`.env.example` |
| 自动化测试 | pytest 9.1.1 | 以可控模型/工具替身验证循环、边界、冲突守卫和错误处理 | `tests/`、`backend/requirements.txt` |
| 在线验证材料 | 项目 smoke 脚本与 JSON Trace | 运行作者配置的真实服务并保存实际输入、动作、工具结果摘要和最终状态 | `scripts/`、`examples/` |

以上组件和模块边界均按作者的方案实现。依赖版本固定在 `backend/requirements.txt`；模型、Embedding 和 rerank 服务由环境变量配置，密钥保存在本机 `.env`。

## Agent Harness 的设计

**Agent Harness** 是项目内围绕模型决策循环实现的运行控制层，入口为 `qa_agent.run_question()`。作者选择用原生 Python 管理工具执行、观察回传、证据核验和终止条件。

Harness 的边界和职责如下：

1. **统一模型接口**：调用 `call_model(messages, tools)`；provider 适配器负责把内部消息和工具定义转换为 DeepSeek 的 OpenAI-compatible function calling 或 Anthropic Messages 的 `tool_use` 结构，并把响应转换回统一表示。
2. **维护任务上下文**：将系统要求、之前的 user/assistant 对话和当前问题组为消息；工具结果只在本轮决策循环中回传，CLI 历史保留面向用户的问答内容。
3. **交还动作选择权给模型**：每轮模型可选择 `search_documents`、`read_document` 或返回最终结果；harness 不预置“先搜再读”的固定业务流程，而负责解释并执行模型返回的工具调用。
4. **统一工具执行边界**：将工具名和 JSON 参数交给 `execute_tool`，由 `knowledge_tools.py` 分发到检索或 SQLite 原文读取；工具结果以 tool message 追加到下一轮模型上下文。
5. **记录观察并收集证据**：保存所选工具、参数、结果数量/摘要和后续动作；检索片段及原文切片进入本轮 evidence 集合，供最终引用校验使用。
6. **强制执行运行上限**：默认最多 6 次模型请求、8 次工具调用；这是 harness 的程序边界，不依赖 prompt 自觉遵守。达到上限返回 `incomplete`。
7. **统一终止和故障处理**：解析最终 JSON、限制 citation 来自本轮工具证据、执行有限数字冲突保护；模型/工具调用失败、JSON 无效或引用为空时走明确状态及 fallback，不将异常伪装成知识答案。
8. **返回稳定结果对象**：用 `AgentResult` 提供 answer、citations、gaps、status、trace 和已用工具等运行数据，再由 CLI renderer 展示。

### Harness 的可替换依赖与测试方式

作者要求把 Agent 决策循环与服务传输、知识库工具实现隔开，因此 `run_question()` 接受可替换的 `model`、`tool_executor`、`max_rounds` 和 `max_tool_calls` 参数。线上默认接入真实 provider 与知识库工具；离线验证则注入 `ScriptedModel` 和工具函数替身，以固定响应复现工具选择、Observation 回传、冲突防护、故障路径和上限行为。

| Harness 验证层 | 使用方式 | 证明范围 |
|---|---|---|
| 单元测试 | `tests/test_qa_agent.py` 注入脚本模型和工具替身 | 状态、引用白名单、冲突守卫、Trace、上下文历史、工具异常和调用上限是否按控制逻辑运行 |
| 离线运行 Harness | `scripts/run_agent_smoke.py` 提供预先编排的模型响应和工具响应，序列化为 JSON 输出 | 可重复检查完整 CLI 输出、资料改写传播和多场景的 Agent 循环；它不证明真实模型会选择同样动作 |
| 在线集成 Harness | `scripts/run_live_api_smoke.py` 连接作者配置的 LLM、Embedding 与 rerank 服务，保存 `examples/` Trace | 观察实际 provider/服务返回、模型工具动作及线上错误；结果只代表该次运行和配置 |

Harness 让模型选择动作，由程序控制执行边界和输出契约。离线控制流与在线模型行为分别留证；Trace 记录动作、参数、工具结果摘要和后续变化。

## 作者制定的验证要求

验证分为**离线可重复验证**与**真实服务验证**：前者检查程序控制流，后者观察模型、Embedding 和重排服务在当前资料下的实际行为。两类证据分别记录，避免把替身测试当作真实模型决策结果。

### 必须覆盖的问答行为

1. **单一证据的明确答案**：检索只找到一份相关资料时，答案应准确复述该资料，引用原文与回答相符。
2. **资料冲突**：同时检索到 D01 的 30 天与 D02 的 15 天时，回答须列出双方引用并追问适用制度，不得擅自择一。
3. **资料外问题**：没有相关证据时返回证据不足和资料缺口，不用模型常识补充制度事实。
4. **改写后的相似问题**：用与资料不同的口语表达提问，观察模型是否选择更合适的检索 query 并找到正确资料。
5. **上下文追问**：后续问题省略前文主体时，验证 Agent 是否将本会话历史带入下一轮并沿用正确语境。
6. **工具失败**：模拟检索或原文读取失败，要求状态、Trace 和用户答案清楚表明失败，不能将异常描述为有效检索结果。
7. **替换资料**：修改合成资料中的事实值或冲突关系后，重新导入并建索引，再问同一问题；答案、引用、资料缺口或追问动作应随新证据变化。

### 必须验证的动态决策和 Trace

- 至少保留两条真实模型工具路径，呈现模型如何从不同工具观察结果调整下一步：例如第一次搜索后补充改写搜索、读取原文，或依据证据结束。
- 每条 Trace 记录模型所选动作、工具名、参数、结果摘要、下一动作和可观察到的决策依据；不记录或伪称模型内部思维过程。
- 使用可控替身复现工具循环、工具异常、冲突守卫和执行上限；替身结果标为离线模拟，不能表述为真实模型决策证据。
- 确认工具调用次数或执行步数有上限；达到上限时返回 `incomplete`，且不会静默给出未完成答案。
- 模型返回 JSON 无效、引用超出工具证据或服务请求失败时，检查程序是否进入明确错误状态并保留可读 Trace。

### 必须执行和记录的真实服务验证

- 使用作者提供的模型配置至少运行真实 Agent 路径，保存真实模型工具选择与最终响应；区分实际成功、失败和未覆盖场景。
- 若启用远端 Embedding，验证文档向量构建、查询向量请求及混合检索输出；记录服务错误和 BM25 回退行为。
- 若启用远端 Qwen rerank，检查真实请求是否使用指定 query、候选文本、模型和 endpoint，返回排序能否进入检索结果；记录接口失败时的处理。
- 将输入、实际输出、provider/model、工具 Trace 和运行状态保存在 `examples/`，由 `docs/03-evaluation.md` 链接；不把 API 密钥或私密资料写入仓库。
- 每个结论都对照文档 ID、版本日期和原文核对。真实模型偶发成功不能证明所有问题可靠，失败运行也作为实际结果保留。

## 作者制定的交付与资料治理要求

- 仓库包含 README、`src/` 或对应代码目录、`tests/`、`examples/`、`data/`、`docs/`、依赖文件及 `.env.example`；资料、测试结果与 Trace 归入同一仓库。
- README 说明环境、安装、CLI 命令、配置和评审入口；需求、方案、评估、AI 使用和复盘分别有独立文档。
- 文档说明设计理由、运行结果、已验证行为和已知限制。示例使用合成制度，并清晰表明不是现实企业政策。
- `.env` 保存本机凭据并被 Git 忽略；Trace 不携带真实 Key。接入真实企业资料前，由作者确认数据来源、服务调用边界和隐私处理要求。
- CLI 是项目唯一面向用户的使用方式；代码库中的脚本用于测试、导入和验证，不构成额外产品入口。

## 项目材料与事实索引

- 项目目标和验收矩阵：[01-requirements.md](01-requirements.md)
- 技术流程与设计取舍：[02-solution.md](02-solution.md)
- 实际测试、在线运行与已知限制：[03-evaluation.md](03-evaluation.md)
- 从 0 到 1 的决策与复盘：[05-retrospective.md](05-retrospective.md)
- CodeGraph 辅助生成的架构图：[06-architecture.md](06-architecture.md)
- 可复核输入、输出和 Trace：[examples/](../examples/)

截至 2026-10-30，本轮考核要求核对、决策 Trace 与文档补齐用时记录为 3 小时；该记录不代表项目累计开发时长。项目累计时长没有从第一天开始连续记录，不能由本轮工时或 Git 提交间隔推算。
