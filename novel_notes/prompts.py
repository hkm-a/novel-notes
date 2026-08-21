"""提示词模板。"""

from __future__ import annotations

SYSTEM_PROMPT = """你是一个专业的小说读书笔记助手。你的任务是根据用户提供的小说章节原文，生成结构清晰、忠实原文的 Markdown 读书笔记。

要求：
1. 使用简体中文。
2. 只输出笔记本身，不要输出“好的”“以下是”等寒暄，不要复述原文。
3. 严格基于原文，不要编造原文中没有出现的人物、情节或台词。
4. 如果某项确实没有内容，写“无”或“暂无”。
5. 保持输出格式稳定，方便后续整理。
6. 固定输出以下结构：
## 一句话概括
## 本章摘要
## 主要人物
## 剧情推进 / 关键事件
## 伏笔 / 线索
## 关键台词
## 本章疑问
## 写作技巧 / 原文体现

其中“写作技巧 / 原文体现”必须用 Markdown 表格输出，列为：
| 技巧 | 原文体现 |
|------|----------|

每一行写一种写作技巧，并在“原文体现”中引用或概括原文里的具体表现。
"""

FULL_USER_TEMPLATE = """请阅读以下小说章节原文，并生成结构化读书笔记。

【章节标题】
{title}

【原文】
{text}
"""

CHUNK_SUMMARY_USER_TEMPLATE = """下面是小说的一个章节片段。请生成该片段的简明摘要。

【章节标题】
{title}

【片段位置】
第 {chunk_index} / {chunk_count} 个片段

【片段原文】
{text}

请输出以下内容（Markdown 格式）：
- 本片段涉及的主要人物
- 本片段发生的关键事件
- 出现的伏笔、线索或悬念
- 值得记住的台词（如有）
- 一句话概括本片段

不要输出完整章节笔记，只输出这个片段的摘要。
"""

MERGE_USER_TEMPLATE = """下面是某小说章节的分片摘要。请把这些摘要综合成一份完整的章节读书笔记。

【章节标题】
{title}

【分片摘要】
{summaries}

请按以下固定结构输出 Markdown：

## 一句话概括

## 本章摘要

## 主要人物

## 剧情推进 / 关键事件

## 伏笔 / 线索

## 关键台词

## 本章疑问

## 写作技巧 / 原文体现

“写作技巧 / 原文体现”必须用 Markdown 表格输出：
| 技巧 | 原文体现 |
|------|----------|

要求：
- 把各分片的信息合并、去重、按时间顺序整理。
- 不要编造分片摘要中没有的内容。
- 某项没有内容时写“无”或“暂无”。
"""


def full_chapter_user_prompt(title: str, text: str) -> str:
    return FULL_USER_TEMPLATE.format(title=title, text=text)


def chunk_summary_user_prompt(title: str, chunk_index: int, chunk_count: int, text: str) -> str:
    return CHUNK_SUMMARY_USER_TEMPLATE.format(
        title=title,
        chunk_index=chunk_index,
        chunk_count=chunk_count,
        text=text,
    )


def merge_chapter_user_prompt(title: str, summaries: list[str]) -> str:
    joined = "\n\n---\n\n".join(
        f"### 片段 {i + 1}\n\n{summary.strip()}"
        for i, summary in enumerate(summaries)
    )
    return MERGE_USER_TEMPLATE.format(title=title, summaries=joined)
