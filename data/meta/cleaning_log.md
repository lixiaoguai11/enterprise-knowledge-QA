# 数据清洗日志

资料入库前统一换行与空行，合并表格中的多余空行，将 MDX 转为 Markdown，并移除 PostgreSQL 页面目录。

## 处理统计

- 处理文档数：233（不含另行编写的 D01—D04 验收资料）

| 处理项 | 文档数 |
| --- | --- |
| MDX 转 Markdown：移除 frontmatter 与 JSX 组件标签 | 30 |
| PostgreSQL 页面：移除 Table of Contents | 14 |

## 主要格式问题与处理

1. 来源文件混用 Markdown、MDX 和 HTML：统一转为 Markdown，移除 MDX 的 JSX 标签与 frontmatter。
2. PostgreSQL 文档为 HTML 页面：提取正文后转换为 Markdown，移除目录和导航链接。
3. 部分生成表格的行间有空行：清洗时合并，保持 Markdown 表格结构。
4. 获取公开文件时无法访问 `raw.githubusercontent.com`：改从 jsDelivr CDN 下载同一文件，元数据仍保留原始仓库地址。
