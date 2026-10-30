# 项目架构图

架构图展示三个视角：运行时组件、启动建库与索引、单轮 Agent 决策循环。模块关系根据 CodeGraph MCP 的 `codegraph_explore` 调用路径整理，并与源码入口对应。

在仓库根目录可以复查图谱并重新查询：

```powershell
codegraph status
codegraph explore "Trace the CLI question flow through Agent tools, retrieval, reranker, database, and output"
```

图中的外部模型与服务以调用边界表示；其内部实现不属于本仓库。下方[代码对应关系](#代码对应关系)可用于逐项核对。

## 运行时组件

```mermaid
flowchart LR
    U[员工] -->|问题与命令| CLI[交互式 CLI<br/>app.cli]
    CLI -->|question + history| AGENT[Agent 编排<br/>app.qa_agent]
    AGENT -->|配置选择| PROVIDER{LLM_PROVIDER}
    PROVIDER -->|deepseek| DS[OpenAI SDK<br/>Chat Completions]
    PROVIDER -->|anthropic| AN[Anthropic SDK<br/>Messages API]
    DS <--> AGENT
    AN <--> AGENT

    AGENT -->|模型选择工具及参数| TOOLS[工具分发<br/>app.knowledge_tools]
    TOOLS -->|search_documents| SEARCH[混合检索<br/>app.retrieval]
    TOOLS -->|read_document| DB[(SQLite<br/>documents + chunks)]
    SEARCH --> BM25[BM25 / Jieba]
    SEARCH --> VECTOR[向量召回<br/>本地 FastEmbed 或远端 Embedding API]
    BM25 --> FUSION{向量索引可用?}
    VECTOR -->|向量候选| RRF[RRF 融合 BM25 与向量候选]
    FUSION -->|是| RRF
    FUSION -->|否| BM25TOP[返回 BM25 Top-k]
    RRF --> RERANK{是否配置重排器?}
    RERANK -->|bge_similarity| BGE[BGE embedding 相似度]
    RERANK -->|qwen_api| QWEN[远端 Qwen Rerank API]
    RERANK -->|未配置| TOPK[返回融合 Top-k]
    BGE --> TOPK2[分数融合后返回 Top-k]
    QWEN --> TOPK2
    TOPK --> TOOLS
    TOPK2 --> TOOLS
    BM25TOP --> TOOLS
    DB --> TOOLS
    TOOLS -->|观察结果| AGENT

    AGENT --> VALIDATE[最终响应解析<br/>引用白名单与冲突检查]
    VALIDATE --> RESULT[AgentResult<br/>answer / citations / gaps / status / trace]
    RESULT --> OUTPUT[终端渲染<br/>app.cli_output]
    OUTPUT --> U

    FILES[(data/clean Markdown<br/>data/meta/manifest.csv)] --> INGEST[导入与切片<br/>app.ingest]
    INGEST --> DB
    CLI -->|启动时初始化| INDEX[构建进程内索引]
    DB --> INDEX
    INDEX -. BM25 + 可选向量 .-> SEARCH
```

CLI、SQLite、BM25 和工具调度在本地运行。启用远端 Embedding 时，服务生成文档及查询向量；设置 `RERANKER_PROVIDER=qwen_api` 时，候选片段再交给 Qwen Rerank 服务排序。Agent 的最终引用来自本轮工具证据。

## 启动与建库流程

```mermaid
flowchart TD
    START[python -m app.cli] --> INIT[cli.initialize]
    INIT --> SCHEMA[database.init_db<br/>创建 SQLAlchemy 表]
    SCHEMA --> CHECK{documents 表为空?}
    CHECK -->|是| MANIFEST[读取 data/meta/manifest.csv]
    MANIFEST --> MARKDOWN[读取 data/clean Markdown]
    MARKDOWN --> CHUNK[解析元数据并按标题/段落切片]
    CHUNK --> STORE[(SQLite documents / chunks)]
    CHECK -->|否| SKIP[沿用现存数据库内容]
    STORE --> BUILD[retrieval.build_index]
    SKIP --> BUILD
    BUILD --> BM25IDX[建立 BM25 索引]
    BUILD --> VECTORIDX{向量后端可用?}
    VECTORIDX -->|是| EMBED[生成或读取向量缓存]
    VECTORIDX -->|否| BM25ONLY[BM25-only 检索]
    EMBED --> READY[进入 CLI REPL]
    BM25ONLY --> READY
```

当前启动逻辑只在数据库没有任何文档时导入资料。更新 Markdown 后，需要按 README 删除 SQLite 数据库及向量缓存再启动；只修改源文件不会自动刷新已入库内容。

## 单轮 ReAct 决策循环

```mermaid
sequenceDiagram
    actor Employee as 员工
    participant CLI as CLI / 会话历史
    participant Agent as qa_agent
    participant LLM as 当前 LLM Provider
    participant Tool as knowledge_tools
    participant Retrieval as retrieval / reranker
    participant Store as SQLite

    Employee->>CLI: 输入当前问题
    CLI->>Agent: run_question(question, history)
    Agent->>LLM: 问题 + 历史 + 工具定义
    loop 最多 6 次模型请求，最多 8 次工具调用
        LLM-->>Agent: 选择 search_documents / read_document / 最终响应
        alt 搜索资料
            Agent->>Tool: search_documents(query, top_k)
            Tool->>Retrieval: 混合检索与排序
            Retrieval->>Store: 读取索引文档切片
            Store-->>Retrieval: 候选片段与元数据
            Retrieval-->>Tool: 排序后的候选片段
        else 读取文档原文
            Agent->>Tool: read_document(doc_id)
            Tool->>Store: 查询文档及全部切片
            Store-->>Tool: 原文切片与版本日期
        end
        Tool-->>Agent: 工具观察结果或错误
        Agent->>LLM: 追加工具结果，请模型决定下一步
    end
    LLM-->>Agent: 最终 JSON 或达到循环上限
    Agent->>Agent: 解析状态、过滤引用、检查数字冲突
    Agent-->>CLI: AgentResult 与可观察 Trace
    CLI-->>Employee: answer / citations / gaps / status / trace
```

模型选择工具和后续动作；Python harness 执行工具、限制次数、适配协议、校验引用并整理状态。达到上限返回 `incomplete`，调用异常返回 `tool_error`。Trace 记录动作、参数、工具结果摘要和后续动作。

## 代码对应关系

| 架构职责 | 源码位置 | 主要边界 |
|---|---|---|
| 唯一用户入口、启动和 REPL | [`backend/app/cli.py`](../backend/app/cli.py) | 管理输入命令、历史和初始化，不实现检索算法 |
| 终端展示 | [`backend/app/cli_output.py`](../backend/app/cli_output.py) | 把 AgentResult 转为人可读输出 |
| Agent 循环、协议映射、证据整理 | [`backend/app/qa_agent.py`](../backend/app/qa_agent.py) | provider 调用、工具循环、最终响应和状态控制 |
| 工具 schema 与分发 | [`backend/app/knowledge_tools.py`](../backend/app/knowledge_tools.py) | 把模型请求映射到检索或 SQLite 读取函数 |
| 文档导入和切片 | [`backend/app/ingest.py`](../backend/app/ingest.py) | manifest/Markdown 到数据库记录的转换 |
| 混合召回、RRF、向量缓存 | [`backend/app/retrieval.py`](../backend/app/retrieval.py) | BM25 与向量召回、融合及第二阶段排序协调 |
| 重排器适配接口 | [`backend/app/reranker.py`](../backend/app/reranker.py) | BGE 相似度与远端 Qwen API 实现统一契约 |
| 数据库连接和表模型 | [`backend/app/database.py`](../backend/app/database.py)、[`backend/app/models.py`](../backend/app/models.py) | SQLite/SQLAlchemy 中的 Document 与 Chunk |
| 用户可替换知识资料 | [`data/clean/`](../data/clean/)、[`data/meta/manifest.csv`](../data/meta/manifest.csv) | 源 Markdown、文档 ID 和版本元数据 |

## 运行边界

- 产品入口为交互式 CLI。
- SQLite 保存本地资料；对话历史保存在当前进程内存中。
- 向量检索可使用本地 FastEmbed 或 OpenAI-compatible Embedding 服务；是否启用取决于环境配置与初始化结果。
- BGE 相似度排序复用已有向量；远端 Qwen 排序是可选适配器。排序分数只用于候选顺序，不能替代对原文的核对。
- 引用白名单检查片段来源；答案的语义支持程度与复杂冲突还需结合原文单独评估。
