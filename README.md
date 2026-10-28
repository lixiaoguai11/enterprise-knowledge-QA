# 企业知识增强 Agent

面向员工的知识库问答终端工具。Agent 通过混合检索找到制度或产品资料，再自行决定是否补充检索、读取文档原文、追问或结束。回答附带文档 ID、版本日期和可核对的原文引用；冲突资料不会被擅自归并成单一答案。

## 环境

- Python 3.12 或更新版本
- DeepSeek API Key（真实模型问答需要）
- 首次启用向量检索/重排时需要联网下载模型；无法加载时检索会降级到 BM25
- 不需要 Node.js、Docker、GPU 或 Web 服务

## 安装和配置

项目使用 [uv](https://docs.astral.sh/uv/) 创建虚拟环境并安装 `requirements.txt` 中固定版本的直接依赖。先安装 uv，然后在仓库根目录运行：

```powershell
uv venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
Copy-Item .env.example .env
```

在 `.env` 中填写 `DEEPSEEK_API_KEY`。可选配置 `DEEPSEEK_BASE_URL` 和 `MODEL_NAME`。密钥只在本机 `.env` 中配置，不要提交。

## 运行 REPL

```powershell
cd backend
..\.venv\Scripts\python.exe -m app.cli
```

第一次启动会将 `data/clean` 中的 Markdown 文档导入本地 SQLite，并建立 BM25 索引；可用时还会启用向量检索和 BGE 重排。提问后可继续追问以使用上下文。

- `/help`：查看可用命令
- `/new`：清空当前对话上下文
- `/exit`：退出

每轮显示答案、状态、引用（文档 ID、版本日期、原句）、资料缺口和工具 Trace。状态包括 `answered`、`needs_clarification`、`insufficient_evidence`、`tool_error` 和达到调用上限时的 `incomplete`。

## 评审入口

- 需求与成功标准：[docs/01-requirements.md](docs/01-requirements.md)
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

向 `data/clean/` 放入 Markdown 文件，并在 `data/meta/manifest.csv` 增加文档编号、相对路径、类别、来源和更新日期。文档正文、标题及元数据评论会被导入；检索片段保留文档 ID 和版本日期。需要重建时，删除 `backend/knowledge.db` 后重新启动即可。

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
