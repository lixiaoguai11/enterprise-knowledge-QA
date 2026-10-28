from __future__ import annotations

import json
from typing import Any


def format_result(result: Any) -> str:
    lines = [f"\n答案：{result.answer}", f"状态：{result.status}", "引用："]
    if result.citations:
        for citation in result.citations:
            lines.extend(
                [
                    f"  - {citation['doc_id']} | {citation['title']} "
                    f"| 版本 {citation['version_date'] or '未注明'}",
                    f"    原文：{citation['quote']}",
                ]
            )
    else:
        lines.append("  - 无")
    lines.append("资料缺口：")
    for gap in result.gaps or ["无"]:
        lines.append(f"  - {gap}")
    lines.append("工具 Trace：")
    for item in result.trace or [{"action": "none"}]:
        lines.append(f"  - {json.dumps(item, ensure_ascii=False)}")
    return "\n".join(lines) + "\n"
