# 数据来源说明

这批资料用于企业知识问答项目的学习、演示与评审。制度和产品文档为模拟材料；技术文档来自公开项目。文档中的制度条款不代表真实企业政策。

逐文档来源见 `manifest.csv`，取得、清洗和入库流程见[数据来源、加工与入库](../../docs/07-data-provenance.md)。

## 资料构成

| 类别 | 文档数 |
| --- | --- |
| 制度类 | 30 |
| 产品资料类 | 25 |
| 技术文档类 | 178 |
| 验收用合成制度与 FAQ | 4 |
| 合计 | 237 |

## 模拟文档

- 制度类：30 份，以虚构的云启科技为背景编写，便于构建可核对答案的评测集。
- 产品资料类：25 份，参考开源项目公开功能后重新编写，不直接复制原文。
- 上述 55 份模拟制度与产品文档均标注“模拟文档，仅用于学习演示”。
- 另有 D01—D04 四份验收用合成资料，用于验证报销期限冲突及常规问答。

## 公开技术文档

| 项目 | 文档数 | 许可证 | 来源 |
| --- | --- | --- | --- |
| docker | 38 | Apache-2.0 | https://github.com/docker/docs/tree/main |
| fastapi | 33 | MIT | https://github.com/fastapi/fastapi/tree/master |
| langchain | 30 | MIT | https://github.com/langchain-ai/docs/tree/main |
| postgresql | 41 | PostgreSQL License | https://www.postgresql.org/docs/current/ |
| redis | 36 | NOASSERTION | https://github.com/redis/redis-doc/tree/master |

## 来源与使用说明

- 模拟资料与公开技术文档分别标明来源，明细见 `manifest.csv`。
- 公开技术文档的许可证与原始地址列在上表；展示或再分发时按相应许可证核对使用条件。
- 公开演示时应注明资料用途，并区分模拟制度与真实政策。
