# 从零开始：项目导览与开发路径

这份说明面向第一次接手仓库的开发者。目标不是要求你先读懂所有 Agent 或检索术语，而是让你从一个终端问题出发，找到输入、检索、模型、引用检查和最终输出分别发生在哪里。

## 先知道项目做什么

用户在终端输入企业制度或产品问题。程序从本地文档库寻找证据，把问题、会话中可见的前文和工具说明交给当前配置的模型 provider（DeepSeek 或 Anthropic-compatible）。模型可以继续搜索、读取某份原文、追问，或结束本轮。程序再检查模型提供的引用，最后把回答、引用、资料缺口、状态和工具记录显示在终端。

```text
员工提问
  -> CLI 保存当前会话的 user/assistant 文本
  -> Agent 询问当前配置的 LLM provider，并开放两个只读工具
  -> 搜索工具调用本地混合检索，读取工具查本地 SQLite 原文
  -> Agent 校验状态、引用和一类数字冲突
  -> CLI 展示答案、引用、资料缺口和 Trace
```

这是一个本机演示项目。它没有组织账号、权限隔离、远端文档服务、审计保留或生产 SLA。示例制度是合成数据，不代表真实公司政策。

## 运行前要准备什么

- Python 3.12+
- uv
- 真实问答所需的当前 provider API Key
- 首次启用向量检索和重排时可访问模型下载源的网络

仓库根目录的 `.env.example` 是配置模板。将它复制为根目录 `.env`，并填入 `DEEPSEEK_API_KEY`。`.env` 已被 Git 忽略，不能提交密钥。

```powershell
uv venv --python 3.12
uv pip install --python .venv\Scripts\python.exe -r backend\requirements.txt
Copy-Item .env.example .env
# 编辑 .env 并填写当前 provider 的配置
cd backend
..\.venv\Scripts\python.exe -m app.cli
```

成功启动后可输入问题，或用 `/help`、`/new`、`/exit` 管理会话。真实 API 曾完成冲突澄清，也出现过模型最终 JSON 无法解析；请读 [03-evaluation.md](03-evaluation.md) 区分成功、失败和未覆盖场景。

## 新手建议按这个顺序阅读和动手

1. 读本页和仓库根目录 [README.md](../README.md)，掌握运行命令与已知限制。
2. 读 [01-requirements.md](01-requirements.md)，把“可靠回答”拆成可以检查的验收场景。
3. 打开 `backend/app/cli.py` 的 `initialize()` 和 `repl()`，顺着启动和一次提问看调用。
4. 打开 `backend/app/qa_agent.py` 的 `run_question()`，这是动态决策主循环；接着看 `knowledge_tools.py` 和 `retrieval.py`。
5. 阅读 [02-solution.md](02-solution.md) 对照工具消息、证据结构、检索和状态含义。
6. 跑离线 Trace 和 pytest，再将结果与 [03-evaluation.md](03-evaluation.md) 里的局限对照。
7. 修改一份合成资料前，记录原答案、引用和任务状态；修改后重建数据/索引，再比较四者是否随证据变化。

## 关键目录

| 路径 | 初学者应该知道什么 |
|---|---|
| `backend/app/cli.py` | 唯一用户入口；初始化本地数据库和检索索引，管理 REPL 和会话历史 |
| `backend/app/qa_agent.py` | 提示词、模型调用循环、JSON 解析、引用白名单和数字冲突保护 |
| `backend/app/knowledge_tools.py` | 两个只读工具的定义与执行：`search_documents`、`read_document` |
| `backend/app/retrieval.py` | Jieba/BM25、远端 OpenAI 兼容 Embedding 或本地 FastEmbed 向量召回、RRF 合并、BGE embedding 相似度重排及缓存 |
| `backend/app/ingest.py` | 从 manifest 加载 Markdown、清理元数据、切片并写入 SQLite |
| `data/clean/` | 可供检索的资料；`data/clean/synthetic/` 保存验收用合成制度 |
| `data/meta/manifest.csv` | 每份资料的 ID、路径、类别、来源和更新日期清单 |
| `tests/` | pytest 自动化用例；使用脚本化模型和注入工具，不调用在线模型 |
| `examples/` | 保存可读的运行输入、输出、工具 Trace 和测试运行模式说明 |
| `docs/` | 需求、流程、评估、决策与复盘文档 |

## 新手排查清单

- **提示未配置 Key**：确认文件名是仓库根目录 `.env`，不是 `backend/.env`；填写 `DEEPSEEK_API_KEY` 后重新开进程。
- **启动很久没有出现输入提示**：启动会尝试初始化向量和重排模型，首次下载受网络影响。当前实现会在加载异常后报告并回退 BM25，但下载超时本身可能让等待变长。
- **新增资料后查不到**：核对 `manifest.csv` 的相对路径和文档 ID。数据库已有文档时 CLI 不会自动重新导入；按 README 指引重建 SQLite 和向量缓存。
- **答案引用不存在或不完整**：看 Trace 是否有检索或读原文结果；`answered` 没有工具原文引用会降级。引用白名单只验证引用片段来自工具返回，不证明答案中每个推论都被引用蕴含。
- **冲突没有被抓到**：代码中的冲突守卫只检查同一问题相关、单位相同且归一化句式相同的数字值差异。隐含范围、跨段落或完全不同写法仍需模型识别与人工评测。
- **离线 Trace 通过但在线仍失败**：脚本化 Trace 不验证真实模型和真实检索；真实在线 Trace 也只代表当次模型、服务和语料快照。

## 文档地图

- [01 — 需求与成功标准](01-requirements.md)：为什么做、做什么、如何判断完成。
- [02 — 方案与调用流程](02-solution.md)：从提问到输出的实际代码路径、检索决策与取舍。
- [03 — 评估结果](03-evaluation.md)：测试证据、Trace、未覆盖范围和当前阻塞。
- [04 — AI 使用记录](04-ai-usage.md)：AI 辅助范围、开发者选择、复核和隐私边界。
- [05 — 复盘与下一步](05-retrospective.md)：开发者从 0 到 1 的决策记录、教训和优先事项。
