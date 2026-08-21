"""章节笔记生成编排：直接总结 + 长章节 Map-Reduce。"""

from __future__ import annotations

from typing import List

from .chapter import Chapter
from .llm import LLMClient
from .prompts import (
    SYSTEM_PROMPT,
    chunk_summary_user_prompt,
    full_chapter_user_prompt,
    merge_chapter_user_prompt,
)


def split_text_into_chunks(
    text: str,
    max_chars: int = 6000,
    overlap_chars: int = 200,
) -> List[str]:
    """按字符窗口切分长文本，尽量在换行处断开，并保留重叠。

    重叠用于降低长章节切在关键信息中间导致的信息丢失。
    """
    if max_chars <= 0:
        raise ValueError("max_chars 必须大于 0")
    if len(text) <= max_chars:
        return [text]

    chunks: List[str] = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = min(start + max_chars, text_len)

        # 如果窗口内后半段有换行，优先在换行处切断，避免把一个段落硬切两半。
        window = text[start:end]
        newline_rel = window.rfind("\n")
        if newline_rel > max_chars // 2:
            end = start + newline_rel + 1

        chunk = text[start:end]
        if chunk.strip():
            chunks.append(chunk.strip())

        if end >= text_len:
            break

        # 下一片从“本片结尾 - overlap”开始，形成重叠。
        next_start = max(end - overlap_chars, start + 1)
        start = next_start

    return [c for c in chunks if c.strip()]


def generate_chapter_note(
    client: LLMClient,
    chapter: Chapter,
    max_chunk_chars: int = 6000,
    chunk_overlap: int = 200,
) -> str:
    """为单个章节生成结构化 Markdown 笔记。

    短章节直接总结；长章节先分片摘要，再合并为最终笔记。
    """
    if len(chapter.text) <= max_chunk_chars:
        return client.complete(
            SYSTEM_PROMPT,
            full_chapter_user_prompt(chapter.title, chapter.text),
        )

    chunks = split_text_into_chunks(chapter.text, max_chunk_chars, chunk_overlap)
    summaries: List[str] = []
    for i, chunk in enumerate(chunks, start=1):
        summaries.append(
            client.complete(
                SYSTEM_PROMPT,
                chunk_summary_user_prompt(chapter.title, i, len(chunks), chunk),
            )
        )

    return client.complete(
        SYSTEM_PROMPT,
        merge_chapter_user_prompt(chapter.title, summaries),
    )
