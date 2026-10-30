# 03 — 评估方案、执行结果与已知限制

本文件把“代码路径测试”“离线编排示例”和“真实模型运行”分开。三者回答不同问题，不能互相替代。

## 当前运行结论

Anthropic 协议和远端 Embedding 均已有成功的真实调用记录。向量验证首次发现接口的 512 token 上限，代码改为窗口化后，整库向量建索引和 BM25/向量融合检索成功。在线结果只代表当前网关、模型与资料版本，不能替代稳定性和召回质量基准。

| 验证层 | 当前结果 | 可以说明什么 | 不能说明什么 |
|---|---|---|---|
| uv 依赖安装 | `uv 0.12.15` 创建 Python 3.12 环境并安装 `backend/requirements.txt` | 本机当前 Windows 环境能解析并安装依赖 | 不能保证所有操作系统、包源和机器都相同 |
| pytest | **16 passed**；Windows 退出时 `pyreadline3` 会有一个清理异常日志，但 pytest 进程退出码为 0 | Agent 逻辑、引用边界、Trace 摘要、调用上限及 reranker HTTP 映射通过隔离测试 | 这些自动化用例不替代真实网络验证；真实服务结果见下面在线行 |
| 离线 Trace | **6 个问答场景通过**，另有资料数值变更检查 | 编排在正常、冲突、缺口、工具失败、改写和上下文场景下按脚本预期输出 | 不调用真实 DeepSeek；不经过真实数据库导入、BM25/向量/RRF/Rerank |
| CLI 交互启动（历史记录） | 2026-10-29 在关闭可选模型下载的情况下到达 `你：` 提示；当时未下载的向量/重排模型回退 | REPL 可启动；普通首次启动尝试曾超过 30 秒 | 该记录早于当前相似度重排改造；新的重排不再额外加载 CrossEncoder |
| DeepSeek 直连接口历史尝试 | 2026-10-29 向 DeepSeek 发起“报销期限多久？”请求，返回 `Request timed out.`，状态为 `tool_error` | CLI 进入模型调用分支，没有报告缺少 Key；请求未得到模型响应 | 不能据此验证 Key 有效性、冲突决策、检索或引用；DeepSeek 直连还没有成功运行记录 |
| Anthropic Messages 在线验证 | 旧网关配置曾超时；用户更换网关配置后，2026-10-29 再次以 `LLM_PROVIDER=anthropic` 实际调用成功，返回 `needs_clarification` | Anthropic 请求、工具调用、原文读取、引用回传与冲突守卫均在本次真实 CLI 运行中完成，见 [05-live-anthropic-success.json](../examples/05-live-anthropic-success.json) | 仅验证当前网关、当前模型和 D01/D02 冲突问题；没有验证其他模型、所有问题类型或模型服务长期稳定性 |
| 远端 Embedding 在线验证（改造前记录） | 2026-10-30 短文本请求返回 2 个 1024 维向量；首次整库请求因服务端 512 token 限制收到 400，改为窗口化后重试成功 | 本机项目 `VectorIndex` 成功嵌入 5381 个片段，矩阵为 5381×1024；当时 BM25 + RRF 前两项命中 D02、D01，见 [06-live-embedding-index.json](../examples/06-live-embedding-index.json) | 这是关闭新相似度重排前的历史 Trace；它不证明当前 reranker 版本的最终顺序或质量 |
| 当前真实 Embedding + BGE 相似度检索 | 2026-10-30 运行 `scripts/run_live_api_smoke.py --run-live`；API 返回 1024 维 query embedding，真实向量检索和当前 BGE 相似度重排成功，前两项为 D02、D01 | 证实当前 Embedding endpoint 可用，候选评分实际执行，见 [07-live-current-reranker.json](../examples/07-live-current-reranker.json) | 单条冲突问题不足以代表全库排序质量；没有离线排序指标 |
| 当前 Qwen rerank API | 2026-10-30 使用 `http://192.168.110.23:16386/rerank` 完成真实 rerank 请求；Embedding 返回 1024 维，D01/D02 进入候选，完整记录见 [08-live-qwen-reranker.json](../examples/08-live-qwen-reranker.json) | 证明本次网络环境可访问远端 16386 服务，HTTP 适配能解析响应，Qwen 重排参与真实检索 | 单条问题不证明排序质量全面达标；仍需固定评测集比较排序指标、延迟和成本 |
| 真实冲突 Agent 路径 | 2026-10-30 Anthropic-compatible `deepseek-flash` 在真实 Embedding + Qwen rerank 检索后，选择补充搜索并读取 D01/D02 等原文；Conflict Guard 识别 30/15 天冲突，结果为 `needs_clarification`，两份引用齐全，见 [08-live-qwen-reranker.json](../examples/08-live-qwen-reranker.json) | 这条在线路径通过冲突和引用断言，Trace 包含实际工具参数、结果摘要、后续模型动作与简短可观察依据 | 只证明一次运行；不代表真实模型长期稳定或能处理所有冲突类型 |
| 真实模型补查/读取路径 | 2026-10-30 另一次真实模型运行对产品问题先搜索、再改写 query 搜索并读取多份原文，最终模型输出无法解析为 JSON；Agent 明确返回 `tool_error`，记录见 [09-live-product-question.json](../examples/09-live-product-question.json) | 证明真实模型会根据前次检索结果继续改变工具动作；格式错误被安全处理并保留决策 Trace | 此路径没有得到有效答案，不能记作明确问题验收通过；模型的结构化输出稳定性是当前限制 |
| 代码风格统一检查 | 当前仅运行 `git diff --check` 检查空白错误；没有配置 Ruff、Black、isort 或 flake8 | `py_compile` 成功；`git diff --check` 未报格式错误 | 语法/空白检查不等于统一的 Python 风格 lint 或自动格式化 |
| GitHub 发布状态 | 记录到的推送尝试返回 HTTP 403；2026-10-30 本机再次检查时 DNS 无法解析 `github.com` | 当前本地 `main` 为 `d4c8aba562d26e27ebfa46cec300bc7aeb9c9869`；工作区有未提交变更 | 网络恢复后需用 `git ls-remote` 比对远端，再推送；本地提交和未提交改动均不能据此称为已发布 |

在线验证分开保存了冲突成功路径和模型输出格式失败路径。成功的冲突路径在 Qwen rerank 后召回 D01/D02，读取原文并返回 `needs_clarification`，见 [08-live-qwen-reranker.json](../examples/08-live-qwen-reranker.json)；另一次产品查询展示模型选择补充检索及读原文，但最终结构化输出无效，Agent 返回 `tool_error`，见 [09-live-product-question.json](../examples/09-live-product-question.json)。较早的 Anthropic 成功 Trace 见 [05-live-anthropic-success.json](../examples/05-live-anthropic-success.json)。这些 Trace 记录真实模型的可观察动作，不代表内部思维过程。

## 自动化测试覆盖

运行方式：

```powershell
.venv\Scripts\python.exe -m pytest -q
```

`tests/test_qa_agent.py` 使用 `ScriptedModel` 和函数替身注入工具结果；没有实际连接 DeepSeek，也没有调用 SQLite 真检索。它覆盖：

1. 有证据的明确答案能保留精确引用。
2. D01/D02 的 30 天与 15 天冲突会覆盖模型只选一边的输出。
3. 资料外问题返回资料不足。
4. 改写问题会把模型选择的改写 query 传给检索工具。
5. 上下文历史会随问题一并交给模型。
6. 工具异常返回 `tool_error` 并留 Trace。
7. 超过 6 次模型请求或 8 次工具调用返回 `incomplete`。
8. 替换工具证据里的事实会改变被支持答案。
9. 不在工具证据里的伪造引用会被过滤并让状态降级。
10. 与当前问题无关的数字差异不会触发冲突保护。
11. CLI 格式化会显示状态、引用、缺口和工具 Trace。

注：测试数量以本次执行的 16 项为准；函数级用例不等于同样数量的线上场景或模型运行。

## 示例 Trace 怎么看

可重新生成脚本化 Trace：

```powershell
.venv\Scripts\python.exe scripts/run_agent_smoke.py
```

- [01-normal-context.json](../examples/01-normal-context.json)：明确答案、改写问题和上下文追问。
- [02-conflict.json](../examples/02-conflict.json)：模型故意给出“15 天”的单边答案，应用层守卫将其改为冲突澄清。
- [03-gaps-and-failure.json](../examples/03-gaps-and-failure.json)：资料外问题、工具异常和 D01 数字修改后的证据传播。
- [08-live-qwen-reranker.json](../examples/08-live-qwen-reranker.json)：真实模型的冲突路径，包含 Qwen 检索、观察摘要、后续模型动作和澄清输出。
- [09-live-product-question.json](../examples/09-live-product-question.json)：真实模型的补查/读原文路径；本次最终 JSON 无效，Agent 返回 `tool_error`，是失败记录而非成功答案。

每份 Trace 的 `run_mode` 都标记脚本化模型/工具替身。Trace 中的 `cli_output` 是真实 formatter 输出，但不是一次线上模型或真实检索的结果。`mutation_check` 从 Markdown 文本取出 30/20 天并把它作为替身工具的证据；它证明 Agent 将变化后的证据传导到回答和引用，不证明 SQLite 重新导入、BM25 命中或向量缓存已刷新。

## 对必须验收场景的结论

| 场景 | 当前验证程度 | 评审意见 |
|---|---|---|
| 单一证据回答 | 替身工具 + Agent 解析通过 | 新增真实产品问题路径本次未形成有效答案；仍缺一条成功的真实单证据回答 |
| 文档冲突 | 替身用例和真实 API 成功路径均返回 D01/D02 双引用及澄清状态 | 其他语义冲突依赖模型，仍需真人审查 Trace |
| 资料外问题 | 替身返回空数组后，脚本模型输出 insufficient 通过 | 未验证真实检索空结果下 DeepSeek 是否会乱答 |
| 改写相似问题 | 测试确认改写 query 被传给工具 | 未证明真实 BM25/向量/Reranker 能召回目标段落 |
| 上下文追问 | 测试确认 user/assistant 历史进入模型消息 | 未验证真实模型的指代消解表现 |
| 工具失败 | 注入异常，返回 `tool_error` 通过 | 未模拟所有 SQLite、模型下载和 API 错误类型 |
| 资料替换 | Agent 层证据替换通过 | 端到端检查还需重建 DB/缓存并再次实际检索 |

## 真正的端到端验收步骤

以下步骤仍需继续完成，执行后把真实输出与模型版本、日期、资料版本、缓存状态追加到示例或独立 Trace：

1. 在仓库根目录创建 `.env`，填写当前真实模型配置；不要把密钥放进 Trace 或 Git。
2. 运行 REPL，确认出现提问提示，然后用 `/exit` 正常退出。
3. 询问“报销期限多久”，核对两条引用都来自 D01/D02、状态为 `needs_clarification`、没有择一回答。
4. 询问 D03 中有明确单一证据的问题，再检查 citation quote 是否逐字来自实际文档。
5. 以口语改写问题和上下文追问重复运行，检查 Trace 中的实际搜索 query 和最终命中文档。
6. 提出资料外问题，核对答案没有用模型常识填空。
7. 在本地副本中把 D01 的 30 天改成 20 天，并把 D02 改为相同值测试冲突解除；重建数据库和 `backend/data/embeddings/` 缓存，再确认答案、quote 或澄清动作改变。
8. 暂时让检索工具失败或使用受控替身，确认结果为 `tool_error`，没有伪造答案。

不要把 API Key、企业敏感内容、含敏感数据的原文放到示例 Trace。

## 已知失败、限制和风险

- **真实模型结构化输出有波动**：Anthropic-compatible `deepseek-flash` 的历史冲突运行和本次冲突运行成功；本次另一条产品查询在执行多步搜索/读原文后返回了无法解析的 JSON，安全降级为 `tool_error`。DeepSeek 直连历史调用超时。不能把模型偶发成功外推为稳定性保证；下一步应评估 JSON schema/结构化输出能力并收集更多真实路径。
- **首次初始化可能较慢**：远端 Embedding 会为导入片段批量请求向量；本地 FastEmbed 首次使用也可能下载模型。当前 BGE 相似度 reranker 不需要额外模型下载。下载源、代理或服务可达性会影响 CLI 启动。Embedding 初始化异常会尝试回退 BM25，但当前没配置“离线直接跳过可选模型”的显式开关。
- **向量缓存可能过期**：缓存按 chunk ID、后端、模型名、URL 指纹和窗口策略比较，但不按原文哈希。若保持切片数量/ID 不变而修改文字，缓存可能误用旧向量；重建数据时同时清理 `backend/data/embeddings/`。
- **冲突检测范围有限**：代码只把相关句中匹配的数字和单位替换成占位符，再比较归一化句子。别名单位、条件范围、表格、否定、跨句逻辑等不在保证范围内。
- **引用并非蕴含证明**：quote 子串与 doc_id 白名单能拦截伪造来源，但不能保证整段自然语言答案被引用完全支持。
- **读取的是已导入切片**：更新磁盘 Markdown 后，数据库和 BM25/向量索引都需要重建，否则读原文可能还是旧内容。
- **权限边界缺失**：当前所有数据对本地运行者可查；真实企业接入前必须补文档 ACL、用户身份、密钥治理、审计和留存策略。
- **对话历史仅内存**：进程重启即丢失；当前不支持用户隔离、恢复和历史删除流程。
- **数据覆盖并非统一政策**：真实企业文件和合成演示资料同时在 `data/clean/` 中；这方便复用数据管道，但正式部署前必须确认每份文件来源、授权和适用对象。

## 最终验收状态

本次执行 `pytest` 为 16 项通过；离线编排脚本有 6 个场景。真实 Qwen rerank 与冲突问答成功，模型输出格式失败的真实路径也已保留。当前无 Ruff/Black 等统一代码风格检查；资料替换端到端验收、成功的真实单证据回答和固定集排序指标仍未完成。Git 工作区已清洁，本地 `main` 新增两个提交；本机 `git ls-remote origin refs/heads/main` 因无法解析 `github.com` 失败，所以远端最新 SHA 未确认，也未推送。历史推送曾返回 HTTP 403。项目累计开发工时没有连续计时记录，不能准确还原；本轮考核规则核对与补齐用时约 6 分钟（2026-10-30 14:47 至 14:53 中国标准时间，分钟级估计）。评审时应按各自 Trace 区分已验证、失败和未覆盖范围。
