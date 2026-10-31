# 企业知识增强 Agent

员工可在终端查询制度和产品资料。Agent 根据检索结果决定继续搜索、读取原文、请求澄清或结束，并在回答中列出文档 ID、版本日期和原文引用。资料相互冲突时，系统展示各方依据及待确认的适用规则。

## 功能

- 交互式 CLI 问答，支持本进程内的上下文追问。
- BM25 与可选向量检索、RRF 融合及候选重排。
- 模型根据工具结果选择继续搜索、读取原文或结束；回答附带可核对的引用和任务状态。
- 支持 OpenAI 兼容 Chat Completions 与 Anthropic Messages API。

## 环境

- Python 3.12+ 和 uv
- 所选模型服务的 API Key（真实模型问答需要）
- Embedding 服务或本地 FastEmbed 模型可选；向量初始化失败时检索回退至 BM25
- 无需 Node.js、Docker、GPU 或 Web 服务

## 快速使用（Windows PowerShell）

在仓库根目录执行以下命令。已有的 `.env` 不会被覆盖：

```powershell
uv venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

在 `.env` 填入所选模型服务的 API Key 后，启动交互式 CLI：

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli
```

输入问题即可问答；`/help` 查看命令，`/new` 清空当前会话，`/exit` 退出。每轮展示答案、引用原文、资料缺口、状态和工具 Trace。首次接手项目可先读[开发者导览](docs/00-start-here.md)。

## 配置

`.env` 位于仓库根目录。通过 `LLM_PROVIDER` 选择模型接口：`deepseek` 使用 OpenAI 兼容 Chat Completions，`anthropic` 使用 Anthropic Messages API。DeepSeek 配置 `DEEPSEEK_API_KEY`，可选 `DEEPSEEK_BASE_URL` 与 `MODEL_NAME`；Anthropic 配置 `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL` 和 `ANTHROPIC_MODEL`。使用 Anthropic 协议兼容网关时，把服务商提供的 URL 填入 `ANTHROPIC_BASE_URL`，并选 `LLM_PROVIDER=anthropic`。

向量检索可通过 `EMBEDDING_API_KEY`、`EMBEDDING_MODEL_NAME` 和 `EMBEDDING_BASE_URL` 接入 OpenAI 兼容服务。配置 Key 后，文档片段和问题会发送至该服务生成向量；未配置时使用本地 FastEmbed。真实地址和凭据只写入本机 `.env`。

例如切换到 Anthropic 格式（把 URL、Key 和模型替换为服务商给你的值）：

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=claude-sonnet-4-5
```

修改 `.env` 后重启 CLI。Anthropic 专用变量优先；未填写时使用对应的 DeepSeek 变量，便于同一网关切换协议。`ANTHROPIC_BASE_URL` 可填写服务根地址或以 `/v1` 结尾的地址；适配器会规范化地址，由 SDK 请求 `/v1/messages`。

数据库为空时，启动会导入 `data/clean` 中的 Markdown 文档，建立 BM25 索引，并在向量后端可用时启用向量检索和 BGE embedding 相似度重排。已有数据库不会自动重新导入资料。当前进程保留对话上下文，可直接追问。

`RERANKER_PROVIDER=bge_similarity` 会复用 BGE embedding 给候选片段打余弦相似度分；`RERANKER_PROVIDER=qwen_api` 会调用 `RERANK_BASE_URL`，并使用 `RERANK_API_KEY`、`RERANK_MODEL_NAME`；`none` 可关闭第二阶段重排。`.env.example` 默认使用无需额外 API 的 BGE 相似度模式。远端 API adapter 实现了 `backend/app/reranker.py` 的统一接口，API 失败会作为检索工具失败返回，不会静默假装重排成功。

启用 Qwen rerank 服务时，在本机 `.env` 中设置 `RERANKER_PROVIDER=qwen_api`、`RERANK_API_KEY`、`RERANK_MODEL_NAME` 和 `RERANK_BASE_URL`。程序向完整 URL 发送包含 `model`、`query`、`documents`、`top_n` 的 JSON，并按返回的 `index` 与 `relevance_score` 排序。接入新网关后，用在线 smoke 检查其请求和响应结构。

状态包括 `answered`、`needs_clarification`、`insufficient_evidence`、`tool_error` 和达到调用上限时的 `incomplete`。

## 文档

- 需求与成功标准：[docs/01-requirements.md](docs/01-requirements.md)
- 新手导览与排查：[docs/00-start-here.md](docs/00-start-here.md)
- 项目架构图与模块边界：[docs/06-architecture.md](docs/06-architecture.md)
- 数据来源、清洗和入库：[docs/07-data-provenance.md](docs/07-data-provenance.md)
- Agent 流程与设计取舍：[docs/02-solution.md](docs/02-solution.md)
- 评估结果、场景和限制：[docs/03-evaluation.md](docs/03-evaluation.md)
- AI 使用范围与作者贡献：[docs/04-ai-usage.md](docs/04-ai-usage.md)
- 复盘与后续工作：[docs/05-retrospective.md](docs/05-retrospective.md)
- 脚本化与真实模型的输入、输出和 Trace：[examples/](examples/)
- 合成冲突资料：[data/clean/synthetic/](data/clean/synthetic/)

## 测试与验证

以下命令在仓库根目录执行；若仍位于 `backend/`，先运行 `cd ..`。运行自动化测试：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

自动化测试使用脚本化模型与隔离 SQLite，不请求模型服务。真实模型运行需要配置所选 provider 的 API Key；Trace 记录 provider、模型名和运行日期。

无需模型 API Key 或下载检索模型，即可单独复跑 Agent 的离线编排 Trace（使用脚本化模型和工具替身，不验证真实检索）：

```powershell
.venv\Scripts\python.exe scripts/run_agent_smoke.py
```

如需验证真实服务，可在仓库根目录执行下面命令。它会初始化本地知识库，调用当前 Embedding、reranker 和 LLM provider，运行冲突问题与产品知识问题两条路径；分别写入 `examples/08-live-qwen-reranker.json` 与 `examples/09-live-product-question.json`。真实调用会发送问题和候选片段到配置的服务，并可能产生费用，需显式提供 `--run-live`：

```powershell
.venv\Scripts\python.exe scripts/run_live_api_smoke.py --run-live
```

在线验证与 pytest 分开运行。API 不可达、模型输出无法解析或路径断言失败时，脚本以非零状态退出并保留 Trace。`decision_basis` 根据工具结果和模型所选动作生成，只描述可观察的依据。成功与失败记录均见[评估文档](docs/03-evaluation.md)。

## 资料格式和重建索引

资料从哪里来、公开文档的版本记录及本地数据库如何生成，见[数据来源、加工与入库](docs/07-data-provenance.md)。

向 `data/clean/` 放入 Markdown 文件，并在 `data/meta/manifest.csv` 增加文档编号、相对路径、类别、来源和更新日期。文档正文、标题及元数据评论会被导入；检索片段保留文档 ID 和版本日期。当前没有增量导入命令。新增或修改资料后，要先退出程序，再删除 `backend/knowledge.db` 和 `backend/data/embeddings/`，然后重启以重建数据库与向量缓存：

```powershell
Remove-Item backend\knowledge.db -ErrorAction SilentlyContinue
Remove-Item backend\data\embeddings -Recurse -Force -ErrorAction SilentlyContinue
```

只改磁盘 Markdown 而不重建 SQLite 时，`read_document` 读取的仍是数据库里原先导入的切片。向量缓存按 chunk ID、模型名和后端 URL 指纹检查，但不按正文哈希检查，因此原文变化时也应重建 SQLite 和向量缓存。

内置 D01 与 D02 是用于验收的合成资料：两者分别写明报销期限为 30 天和 15 天，且均未提供适用范围或优先级。它们不是现实制度建议。

## 技术组件

| 组件 | 固定版本/来源 | 用途 |
|---|---|---|
| Python | 3.12+ | CLI 和 Agent 运行时 |
| SQLAlchemy | `backend/requirements.txt` | SQLite 文档/片段存储 |
| Jieba | `backend/requirements.txt` | 中文 BM25 分词 |
| OpenAI Python SDK + NumPy | `backend/requirements.txt` | 配置 `EMBEDDING_API_KEY` 时调用 OpenAI 兼容 Embedding API，并计算余弦相似度 |
| FastEmbed | `backend/requirements.txt` | 未配置远端 Embedding Key 时在本地生成多语言向量 |
| OpenAI Python SDK | `backend/requirements.txt` | 通过 OpenAI 兼容 Chat Completions 调用 DeepSeek 与 function calling |
| Anthropic Python SDK | `backend/requirements.txt` | 通过原生 Messages API 调用 Anthropic 格式服务，并处理 `tool_use`/`tool_result` |
| pytest | `backend/requirements.txt` | 自动化测试 |

向量索引和重排仅作为 BM25 之上的召回/排序改进。Embedding API 用于文档切片和查询向量，服务不可用时索引初始化会报告并回退到 BM25；索引初始化成功后若单次查询向量 API 失败，会返回 `tool_error`。本地 FastEmbed 未配置远端 Key 时仍可作为向量模型。BGE 相似度重排复用向量索引；设置 `RERANKER_PROVIDER=none` 时只使用 BM25 与向量 RRF 融合。模型 API 调用失败不会被伪装成有依据的知识库答案。
