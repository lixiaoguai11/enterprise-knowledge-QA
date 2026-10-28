# 03 — 评估结果

## 自动化验证

测试入口：`.venv\\Scripts\\python.exe -m pytest -q`。测试通过脚本化模型和注入工具响应，验证编排、引用过滤、冲突状态、上下文和故障处理；这些结果不是 DeepSeek 实际推理能力的评测。离线 Trace 由 `.venv\\Scripts\\python.exe scripts/run_agent_smoke.py` 生成，可在没有 API Key 的环境复跑。

| 场景 | 预期 | 实际结果 | 运行记录 |
|---|---|---|---|
| 单一证据答案、改写问题、上下文追问 | 引用来自工具原文，完成状态为 `answered` | 离线脚本通过，含 3 个场景 | [01-normal-context.json](../examples/01-normal-context.json) |
| D01/D02 冲突 | 两边引用齐全，状态 `needs_clarification`，询问范围/优先级 | 离线脚本通过；覆盖模型错误地只选 15 天的反例 | [02-conflict.json](../examples/02-conflict.json) |
| 资料外问题、工具失败、资料替换 | 明确资料不足或 `tool_error`；答案随替换证据变化 | 离线脚本通过；读取 D01 合成文件并把 30 天改为 20 天后，答案和引用同步变化 | [03-gaps-and-failure.json](../examples/03-gaps-and-failure.json) |

本机执行结果：uv 0.12.15 创建 Python 3.12 虚拟环境并从 PyPI 安装依赖；`pytest -q` 为 11 passed，离线 Trace 脚本通过 6 个问答场景和 D01 资料替换检查；`compileall` 对 `backend/`、`tests/` 和 `scripts/` 通过。pytest 在 Windows 退出时出现一条 `pyreadline3` 清理异常日志，但退出码为 0。没有配置 `DEEPSEEK_API_KEY`，也未执行真实模型请求。

## 失败与限制

- 当前环境无 `DEEPSEEK_API_KEY`，因此没有真实模型运行结果；脚本化测试不能证明线上模型每次都正确识别矛盾。补充真实模型 Trace 前不得将其宣称为已验收。
- 数字冲突守卫可拦截不同文档中句式相同、单位相同但数值不同的陈述。不同表述、隐含前提或跨段落的复杂矛盾仍主要依赖模型识别，可能漏检。
- 向量/重排模型需要下载且受本机网络影响，失败时回退到 BM25。降级可能降低改写问题的召回率。
- 当前 REPL 不做多用户隔离、权限管理或历史持久化；用于单机演示，不可直接视为企业生产权限系统。
