# 企业知识增强 Agent

面向员工的知识库问答终端工具。Agent 通过混合检索找到制度或产品资料，再自行决定是否补充检索、读取文档原文、追问或结束。回答附带文档 ID、版本日期和可核对的原文引用；冲突资料不会被擅自归并成单一答案。

## 环境

- Python 3.12 或更新版本
- DeepSeek API Key（真实模型问答需要）
- CLI 启动会尝试加载向量检索和重排模型；首次下载需要联网，加载异常时尝试降级到 BM25，但下载等待可能拖慢首次启动
- 不需要 Node.js、Docker、GPU 或 Web 服务

## 快速使用（Windows PowerShell）

先在仓库根目录创建环境、安装依赖并准备配置文件。若 `.env` 已存在，下面的命令不会覆盖它：

```powershell
uv venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
if (-not (Test-Path .env)) { Copy-Item .env.example .env }
notepad .env
```

`.env` 位于仓库根目录。在记事本中填写 `DEEPSEEK_API_KEY`；可选配置 `DEEPSEEK_BASE_URL` 和 `MODEL_NAME`。密钥只保存在本机 `.env` 中，不要提交，也不要发到聊天里。

启动交互式 CLI：

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli
```

数据库为空时，启动会将 `data/clean` 中的 Markdown 文档导入本地 SQLite，并建立 BM25 索引；可用时还会启用向量检索和 BGE 重排。若数据库已有文档，启动不会自动重新导入资料。提问后可继续追问以使用当前进程内的对话上下文。

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
- 复盘与后续工作：[docs/05-retrospective.md](docs/05-retrospective.md)
- 三组验收输入、输出和 Trace：[examples/](examples/)
- 合成冲突资料：[data/clean/synthetic/](data/clean/synthetic/)

运行测试：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

测试采用脚本化模型与隔离 SQLite，不会请求 DeepSeek。真实模型运行需配置 API Key，并在 Trace 中标注模型名和运行日期。

无需 DeepSeek API Key 或下载检索模型，即可单独复跑 Agent 的离线编排 Trace（使用脚本化模型和工具替身，不验证真实检索）：

```powershell
.venv\Scripts\python.exe scripts/run_agent_smoke.py
```

## 资料格式和重建索引

向 `data/clean/` 放入 Markdown 文件，并在 `data/meta/manifest.csv` 增加文档编号、相对路径、类别、来源和更新日期。文档正文、标题及元数据评论会被导入；检索片段保留文档 ID 和版本日期。当前没有增量导入命令。新增或修改资料后，要先退出程序，再删除 `backend/knowledge.db` 和 `backend/data/embeddings/`，然后重启以重建数据库与向量缓存：

```powershell
Remove-Item backend\knowledge.db -ErrorAction SilentlyContinue
Remove-Item backend\data\embeddings -Recurse -Force -ErrorAction SilentlyContinue
```

只改磁盘 Markdown 而不重建 SQLite 时，`read_document` 读取的仍是数据库里原先导入的切片。只按 chunk ID 判断向量缓存是否匹配，因此原文变化时也应清理向量缓存。

内置 D01 与 D02 是用于验收的合成资料：两者分别写明报销期限为 30 天和 15 天，且均未提供适用范围或优先级。它们不是现实制度建议。

## 技术组件

| 组件 | 固定版本/来源 | 用途 |
|---|---|---|
| Python | 3.12+ | CLI 和 Agent 运行时 |
| SQLAlchemy | `backend/requirements.txt` | SQLite 文档/片段存储 |
| Jieba | `backend/requirements.txt` | 中文 BM25 分词 |
| fastembed + NumPy | `backend/requirements.txt` | 多语言向量召回 |
| Hugging Face Hub + ONNX Runtime + Tokenizers | `backend/requirements.txt` | 下载并运行 Xenova BGE Reranker ONNX，对候选片段重排 |
| OpenAI Python SDK | `backend/requirements.txt` | 通过兼容 API 调用 DeepSeek 与 function calling |
| pytest | `backend/requirements.txt` | 自动化测试 |

向量索引和重排模型仅作为 BM25 之上的召回/排序改进。模型不可用时系统报告并回退到 BM25；模型 API 调用失败则返回 `tool_error`，不会把模型常识当作知识库答案。
