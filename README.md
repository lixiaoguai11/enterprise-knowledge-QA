# 企业知识增强 Agent

面向员工的知识库问答终端工具。Agent 通过混合检索找到制度或产品资料，再自行决定是否补充检索、读取文档原文、追问或结束。回答附带文档 ID、版本日期和可核对的原文引用；冲突资料不会被擅自归并成单一答案。

## 提交信息

- 题目：企业知识增强 Agent
- 题号：当前提供的考核材料未包含编号，提交考核平台时需补填
- GitHub：[lixiaoguai11/enterprise-knowledge-QA](https://github.com/lixiaoguai11/enterprise-knowledge-QA)
- 最终 commit SHA：以本次交付提交后的 `main` 最新提交为准（交付说明中附上）

## 环境

- Python 3.12 或更新版本
- 当前所选 provider 的 API Key（DeepSeek 或 Anthropic；真实模型问答需要）
- CLI 启动时若配置了 Embedding API Key，会用远端服务建立向量索引；否则加载本地 FastEmbed。默认用 BGE embedding 余弦相似度重排，不下载 CrossEncoder；向量初始化失败时会退回 BM25
- 不需要 Node.js、Docker、GPU 或 Web 服务

## 快速使用（Windows PowerShell）

先在仓库根目录创建环境、安装依赖并准备配置文件。若 `.env` 已存在，下面的命令不会覆盖它：

```powershell
uv venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

`.env` 位于仓库根目录。通过 `LLM_PROVIDER` 选择模型接口：`deepseek` 使用 OpenAI 兼容 Chat Completions，`anthropic` 使用 Anthropic Messages API。DeepSeek 配置 `DEEPSEEK_API_KEY`，可选 `DEEPSEEK_BASE_URL` 与 `MODEL_NAME`；Anthropic 配置 `ANTHROPIC_API_KEY`、`ANTHROPIC_BASE_URL` 和 `ANTHROPIC_MODEL`。使用 Anthropic 协议兼容网关时，把服务商提供的 URL 填入 `ANTHROPIC_BASE_URL`，并选 `LLM_PROVIDER=anthropic`。

向量检索可选使用 OpenAI 兼容 Embedding 服务，配置 `EMBEDDING_API_KEY`、`EMBEDDING_MODEL_NAME` 和 `EMBEDDING_BASE_URL`。配置非空 Key 后，程序用远端接口生成文档片段与问题向量；Key 为空时回退至本地 FastEmbed 模型。`.env.example` 只提供占位配置，真实地址和凭据应放在本机 `.env`，不要提交。

例如切换到 Anthropic 格式（把 URL、Key 和模型替换为服务商给你的值）：

```dotenv
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=your-key
ANTHROPIC_BASE_URL=https://api.anthropic.com
ANTHROPIC_MODEL=claude-sonnet-4-5
```

修改 `.env` 后重新启动 CLI。Anthropic 专用变量优先；未填写时，程序会回退使用已有的 `DEEPSEEK_API_KEY`、`DEEPSEEK_BASE_URL` 和 `MODEL_NAME`，便于对同一网关切换协议，不必重复复制密钥。`ANTHROPIC_BASE_URL` 可以是服务根地址，也可以带结尾 `/v1`；适配器会去掉结尾 `/v1`，SDK 随后请求 `/v1/messages`。

启动交互式 CLI：

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli
```

数据库为空时，启动会将 `data/clean` 中的 Markdown 文档导入本地 SQLite，并建立 BM25 索引；可用时还会启用向量检索和 BGE embedding 相似度重排。若数据库已有文档，启动不会自动重新导入资料。提问后可继续追问以使用当前进程内的对话上下文。

`RERANKER_PROVIDER=bge_similarity` 会复用 BGE embedding 给候选片段打余弦相似度分；`RERANKER_PROVIDER=qwen_api` 会调用 `RERANK_BASE_URL`，并使用 `RERANK_API_KEY`、`RERANK_MODEL_NAME`；`none` 可关闭第二阶段重排。`.env.example` 默认使用无需额外 API 的 BGE 相似度模式。远端 API adapter 实现了 `backend/app/reranker.py` 的统一接口，API 失败会作为检索工具失败返回，不会静默假装重排成功。

若启用你提供的 Qwen rerank 服务，在本机 `.env` 中设置 `RERANKER_PROVIDER=qwen_api` 以及 `RERANK_API_KEY`、`RERANK_MODEL_NAME`、`RERANK_BASE_URL`。程序会向该完整 URL POST JSON，body 包含 `model`、`query`、`documents`、`top_n`，并读取 `results` 中的 `index` 与 `relevance_score` 排序。不同网关的请求结构可能有差异，首次配置需用在线 smoke 验证。

- `/help`：查看可用命令
- `/new`：清空当前对话上下文
- `/exit`：退出

输入自然语言问题即可开始问答。每轮输出回答、引用原文及文档版本、资料缺口、任务状态和本轮工具 Trace。

从首次接手仓库的角度阅读：[docs/00-start-here.md](docs/00-start-here.md)。它给出目录地图、代码走读顺序和常见排查方法。

每轮显示答案、状态、引用（文档 ID、版本日期、原句）、资料缺口和工具 Trace。状态包括 `answered`、`needs_clarification`、`insufficient_evidence`、`tool_error` 和达到调用上限时的 `incomplete`。

## 评审入口

- 需求与成功标准：[docs/01-requirements.md](docs/01-requirements.md)
- 新手导览与排查：[docs/00-start-here.md](docs/00-start-here.md)
- Agent 流程与设计取舍：[docs/02-solution.md](docs/02-solution.md)
- 评估结果、场景和限制：[docs/03-evaluation.md](docs/03-evaluation.md)
- AI 辅助开发与个人复核：[docs/04-ai-usage.md](docs/04-ai-usage.md)
- 复盘与后续工作：[docs/05-retrospective.md](docs/05-retrospective.md)
- 脚本化与真实模型的输入、输出和 Trace：[examples/](examples/)
- 真实模型请求超时记录：[examples/04-live-deepseek-timeout.json](examples/04-live-deepseek-timeout.json)
- 合成冲突资料：[data/clean/synthetic/](data/clean/synthetic/)

运行测试：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

测试采用脚本化模型与隔离 SQLite，不会请求模型服务。真实模型运行需配置当前 provider 的 API Key，并在 Trace 中标注 provider、模型名和运行日期。

无需模型 API Key 或下载检索模型，即可单独复跑 Agent 的离线编排 Trace（使用脚本化模型和工具替身，不验证真实检索）：

```powershell
.venv\Scripts\python.exe scripts/run_agent_smoke.py
```

如需验证真实服务，可在仓库根目录执行下面命令。它会初始化本地知识库，调用当前 Embedding、reranker 和 LLM provider，运行冲突问题与产品知识问题两条路径；分别写入 `examples/08-live-qwen-reranker.json` 与 `examples/09-live-product-question.json`。真实调用会发送问题和候选片段到配置的服务，并可能产生费用，需显式提供 `--run-live`：

```powershell
.venv\Scripts\python.exe scripts/run_live_api_smoke.py --run-live
```

在线验证与 pytest 替身测试分开运行。若 API 不可达、模型输出无法解析或没有达到各路径断言，脚本会以非零状态退出并保留 Trace，便于排错。`decision_basis` 是根据可观察的工具结果与模型所选动作生成的简短摘要，不包含模型内部思维过程；真实 API 结果会波动，应同时阅读失败记录。

## 资料格式和重建索引

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
