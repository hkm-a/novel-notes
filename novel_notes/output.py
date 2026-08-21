"""输出 Markdown 笔记、索引和切分文件。"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from urllib.parse import quote
from pathlib import Path
from typing import Dict, List, Optional

from .chapter import Chapter


def _safe_part(title: str, fallback: str, max_len: int = 80) -> str:
    # 去掉 Windows 保留字符和不可见控制字符。
    cleaned = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "", title)
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" .")
    if not cleaned:
        cleaned = fallback
    return cleaned[:max_len] or fallback


def chapter_filename(index: int, title: str, ext: str = ".md") -> str:
    safe = _safe_part(title, f"chapter_{index}")
    return f"{index:04d}_{safe}{ext}"


def chapter_filepath(output_dir: Path, index: int, title: str, ext: str = ".md") -> Path:
    return output_dir / chapter_filename(index, title, ext)


def write_chapter_note(output_dir: Path, chapter: Chapter, note: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = chapter_filepath(output_dir, chapter.index, chapter.title)
    content = (
        f"# {chapter.title}\n\n"
        f"> 原文位置：第 {chapter.line_start + 1}-{chapter.line_end + 1} 行\n\n"
        f"{note.strip()}\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def write_chapter_error(output_dir: Path, chapter: Chapter, error: str) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = chapter_filepath(output_dir, chapter.index, chapter.title)
    content = (
        f"# {chapter.title}\n\n"
        f"> ⚠️ 本章笔记生成失败\n\n"
        f"**错误信息**：\n\n```\n{error}\n```\n\n"
        f"可稍后使用 `--force` 重新生成本章。\n"
    )
    path.write_text(content, encoding="utf-8")
    return path


def write_split_txt(output_dir: Path, chapter: Chapter) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = chapter_filepath(output_dir, chapter.index, chapter.title, ext=".txt")
    path.write_text(chapter.text + "\n", encoding="utf-8")
    return path


def write_index(
    output_dir: Path,
    book_title: str,
    model: str,
    items: List[Dict[str, str]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {book_title} 读书笔记",
        "",
        f"> 生成模型：`{model}`",
        f"> 生成时间：{_now_iso()}",
        "",
        "## 目录",
        "",
        "| 章节 | 状态 | 文件 |",
        "| --- | --- | --- |",
    ]
    for item in items:
        index = item.get("index", "")
        title = item.get("title", "")
        status = item.get("status", "pending")
        file = item.get("file", "")
        status_text = {
            "done": "✅ 完成",
            "error": "❌ 失败",
            "skipped": "⏭️ 跳过",
            "pending": "⏳ 待生成",
        }.get(status, status)
        link = f"[{title}]({quote(file)})" if file else title
        lines.append(f"| {index} | {status_text} | {link} |")

    path = output_dir / "index.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def write_single_file(
    output_dir: Path,
    book_title: str,
    model: str,
    items: List[Dict[str, str]],
) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        f"# {book_title} 读书笔记（合并版）",
        "",
        f"> 生成模型：`{model}`",
        f"> 生成时间：{_now_iso()}",
        "",
    ]
    for item in items:
        title = item.get("title", "")
        note_file = item.get("file", "")
        status = item.get("status", "pending")
        lines.append("")
        lines.append("---")
        lines.append("")
        lines.append(f"## {title}")
        lines.append("")
        if status == "done" and note_file:
            note_path = output_dir / note_file
            if note_path.exists():
                content = note_path.read_text(encoding="utf-8")
                # 去掉单个文件里已有的 H1 标题，避免合并后层级混乱。
                body_lines = content.splitlines()
                while body_lines and body_lines[0].startswith("# "):
                    body_lines.pop(0)
                while body_lines and not body_lines[0].strip():
                    body_lines.pop(0)
                lines.extend(body_lines)
            else:
                lines.append("> 笔记文件缺失")
        elif status == "error":
            lines.append("> ⚠️ 本章生成失败")
        else:
            lines.append("> 未生成")

    path = output_dir / "读书笔记_合并.md"
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
