"""TXT 章节识别与切分。

设计目标：
- 兼容常见网文/出版小说章节标题
- 尽量跳过“目录”造成的误切分
- 没有章节标题时提供按行数兜底切分
- 保留章节原文，供 LLM 使用
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Iterable, List, Optional, Pattern, Tuple

# 默认章节标题正则。
# 使用 VERBOSE 便于阅读；匹配的是“整行”，避免把正文中出现的“第一章”误判。
DEFAULT_CHAPTER_PATTERN = r"""
    ^\s*
    (?:
        第\s*[0-9０-９一二三四五六七八九十百千万零〇]+\s*[章回节]
            (?:\s*[:：、.\-—]?\s*.*)?
      | (?:chapter|第)\s+(?:[0-9]+|[ivxlcdm]+|one|two|three|four|five|six|seven|eight|nine|ten)
            (?:\s*[:：.\-—]?\s*.*)?
      | 序章 | 序言 | 楔子 | 引子 | 前言 | 尾声 | 后记 | 终章 | 最终章 | 间章
      | 番外(?:\s*[0-9一二三四五六七八九十百千]+)?(?:\s*[:：.\-—]?\s*.*)?
      | 外传(?:\s*[0-9一二三四五六七八九十百千]+)?(?:\s*[:：.\-—]?\s*.*)?
    )
    \s*$
"""


@dataclass
class Chapter:
    index: int
    title: str
    line_start: int  # 0-based，章节标题所在行
    line_end: int    # 0-based，闭区间
    start_char: int  # 原文中的字符偏移
    end_char: int
    text: str


def _compile_pattern(pattern: str) -> Pattern[str]:
    if pattern == "default" or pattern == "":
        return re.compile(DEFAULT_CHAPTER_PATTERN, re.VERBOSE | re.IGNORECASE)
    # 用户自定义正则：按普通正则编译，不强制 VERBOSE，避免空格语义变化。
    return re.compile(pattern, re.IGNORECASE)


def _heading_candidates(
    lines: List[str],
    pattern: Pattern[str],
    max_heading_len: int,
) -> List[Tuple[int, str]]:
    candidates: List[Tuple[int, str]] = []
    for idx, line in enumerate(lines):
        stripped = line.strip()
        if not stripped or len(stripped) > max_heading_len:
            continue
        # 标题行通常不是以句末标点结尾的完整句子。
        if stripped[-1] in "。！？；，：、":
            continue
        if pattern.fullmatch(stripped):
            candidates.append((idx, stripped))
    return candidates


def _collect_toc_runs(
    candidates: List[Tuple[int, str]],
    lines: List[str],
) -> List[List[Tuple[int, str]]]:
    """把连续且中间没有正文/分隔内容的标题聚成 run。"""
    runs: List[List[Tuple[int, str]]] = []
    if not candidates:
        return runs
    candidate_lines = {line_no for line_no, _ in candidates}
    current = [candidates[0]]
    for prev, cur in zip(candidates, candidates[1:]):
        gap = cur[0] - prev[0] - 1
        between = lines[prev[0] + 1 : cur[0]]
        # 中间出现非空且不是标题的行，视为目录和正文的分界（例如“正文”）。
        has_separator = any(
            line.strip() and idx not in candidate_lines
            for idx, line in enumerate(between, start=prev[0] + 1)
        )
        if gap <= 10 and not has_separator:
            current.append(cur)
        else:
            runs.append(current)
            current = [cur]
    runs.append(current)
    return runs


def _drop_toc_candidates(
    candidates: List[Tuple[int, str]],
    lines: List[str],
) -> List[Tuple[int, str]]:
    """过滤常见的“目录页”标题。

    策略：
    1. 如果同一标题在文件中出现多次，优先保留后面的正文章节，丢掉前面的目录。
    2. 否则，丢弃出现在第一段长正文之前的连续标题块；如果全部被丢，则保留最后一个块。
    """
    if len(candidates) < 3:
        return candidates

    runs = _collect_toc_runs(candidates, lines)
    if not runs:
        return candidates

    # 策略 1：标题重复时，去掉“后面还会再出现”的目录块。
    from collections import Counter

    title_counts = Counter(title for _, title in candidates)
    if any(count > 1 for count in title_counts.values()):
        kept: List[Tuple[int, str]] = []
        for run_idx, run in enumerate(runs):
            later_titles = {
                title
                for later in runs[run_idx + 1 :]
                for _, title in later
            }
            if len(run) >= 2 and all(
                title_counts[title] > 1 and title in later_titles
                for _, title in run
            ):
                continue
            kept.extend(run)
        return kept or candidates

    # 策略 2：无重复标题时，按“长正文之前”的启发式丢弃。
    first_body = next(
        (i for i, line in enumerate(lines) if len(line.strip()) > 50),
        None,
    )
    kept = []
    for run in runs:
        run_end_line = run[-1][0]
        if len(run) >= 3 and (first_body is None or run_end_line < first_body):
            continue
        kept.extend(run)

    if not kept and runs:
        kept = runs[-1]
    return kept

def _fallback_chapters(lines: List[str], chunk_lines: int) -> List[Chapter]:
    """没有识别到章节标题时，按固定行数切分。"""
    chapters: List[Chapter] = []
    line_offsets: List[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1

    for start in range(0, len(lines), chunk_lines):
        end = min(start + chunk_lines, len(lines)) - 1
        text = "\n".join(lines[start : end + 1]).strip()
        if not text:
            continue
        chapters.append(
            Chapter(
                index=len(chapters) + 1,
                title=f"第{len(chapters) + 1}部分",
                line_start=start,
                line_end=end,
                start_char=line_offsets[start],
                end_char=line_offsets[end] + len(lines[end]),
                text=text,
            )
        )
    return chapters


def split_chapters(
    text: str,
    chapter_pattern: str = "default",
    max_heading_len: int = 80,
    skip_toc: bool = True,
    fallback_chunk_lines: int = 0,
    include_preamble: bool = True,
    preamble_min_chars: int = 300,
) -> List[Chapter]:
    """把整本小说文本切成章节列表。"""
    lines = text.split("\n")
    line_offsets: List[int] = []
    offset = 0
    for line in lines:
        line_offsets.append(offset)
        offset += len(line) + 1

    pattern = _compile_pattern(chapter_pattern)
    candidates = _heading_candidates(lines, pattern, max_heading_len)
    if skip_toc:
        candidates = _drop_toc_candidates(candidates, lines)

    if not candidates:
        if fallback_chunk_lines > 0:
            return _fallback_chapters(lines, fallback_chunk_lines)
        return []

    starts = [line_no for line_no, _title in candidates]
    chapters: List[Chapter] = []
    next_index = 1

    # 开篇内容（书名、简介、序等）如果足够长，保留为第 0 章，避免丢内容。
    first_start = starts[0]
    if include_preamble and first_start > 0:
        preamble_text = "\n".join(lines[:first_start]).strip()
        if len(preamble_text) >= preamble_min_chars:
            chapters.append(
                Chapter(
                    index=0,
                    title="开头 / 前言",
                    line_start=0,
                    line_end=first_start - 1,
                    start_char=line_offsets[0],
                    end_char=line_offsets[first_start - 1] + len(lines[first_start - 1])
                    if first_start - 1 < len(lines)
                    else offset,
                    text=preamble_text,
                )
            )
            next_index = 1

    for pos, start in enumerate(starts):
        end = (starts[pos + 1] - 1) if pos + 1 < len(starts) else len(lines) - 1
        title = candidates[pos][1]
        text = "\n".join(lines[start : end + 1]).strip()
        if not text:
            continue
        chapters.append(
            Chapter(
                index=next_index,
                title=title,
                line_start=start,
                line_end=end,
                start_char=line_offsets[start],
                end_char=line_offsets[end] + len(lines[end]),
                text=text,
            )
        )
        next_index += 1

    # 如果正文本身为空则回退到原文整体。
    if not chapters:
        return [
            Chapter(
                index=0,
                title="全文",
                line_start=0,
                line_end=len(lines) - 1,
                start_char=line_offsets[0],
                end_char=offset,
                text=text.strip(),
            )
        ]

    return chapters


def summarize_chapters(chapters: Iterable[Chapter]) -> str:
    """返回章节列表的人类可读摘要，用于 dry-run / 日志。"""
    lines = []
    for ch in chapters:
        lines.append(
            f"{ch.index:>4}  {ch.title}  "
            f"[行 {ch.line_start + 1}-{ch.line_end + 1}, {len(ch.text)} 字符]"
        )
    return "\n".join(lines)
