"""命令行入口。"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from . import __version__
from .chapter import Chapter, split_chapters, summarize_chapters
from .encoding import read_text
from .llm import LLMClient, LLMConfig
from .output import (
    chapter_filename,
    write_chapter_error,
    write_chapter_note,
    write_index,
    write_single_file,
    write_split_txt,
)
from .progress import is_done, load_progress, mark_done, mark_error, save_progress
from .service import generate_chapter_note

logger = logging.getLogger(__name__)


def _add_text_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--encoding", help="指定输入文件编码，例如 utf-8、gb18030、big5")
    parser.add_argument(
        "--chapter-pattern",
        default="default",
        help="自定义章节标题正则（默认内置中英文网文规则）",
    )
    parser.add_argument(
        "--max-heading-len",
        type=int,
        default=80,
        help="标题行最大长度，超过则视为正文（默认 80）",
    )
    parser.add_argument(
        "--no-skip-toc",
        action="store_false",
        dest="skip_toc",
        help="不自动跳过疑似目录页的章节标题",
    )
    parser.add_argument(
        "--fallback-chunk-lines",
        type=int,
        default=800,
        help="未识别到章节时按多少行切一部分（默认 800；设 0 禁用）",
    )
    parser.add_argument(
        "--no-preamble",
        action="store_false",
        dest="include_preamble",
        help="不把开篇内容（书名/简介/序等）作为第 0 章",
    )
    parser.add_argument(
        "--preamble-min-chars",
        type=int,
        default=300,
        help="开篇内容至少多少字才保留为第 0 章（默认 300）",
    )


def _add_llm_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--base-url",
        default=os.getenv("OPENAI_BASE_URL", "https://api.openai.com/v1"),
        help="OpenAI 兼容接口地址，Ollama 示例：http://localhost:11434/v1",
    )
    parser.add_argument(
        "--api-key",
        default=os.getenv("OPENAI_API_KEY", ""),
        help="API Key；本地 Ollama 可留空或填 ollama",
    )
    parser.add_argument(
        "--model",
        default=os.getenv("LLM_MODEL", "gpt-4o-mini"),
        help="模型名，例如 gpt-4o-mini、deepseek-chat、qwen2.5:7b",
    )
    parser.add_argument("--temperature", type=float, default=0.3)
    parser.add_argument("--max-tokens", type=int, default=2000)
    parser.add_argument("--timeout", type=float, default=120.0, help="单次请求超时秒数")
    parser.add_argument("--max-retries", type=int, default=5)
    parser.add_argument(
        "--max-chunk-chars",
        type=int,
        default=6000,
        help="超过该字符数的章节启用分片摘要（默认 6000）",
    )
    parser.add_argument(
        "--chunk-overlap",
        type=int,
        default=200,
        help="长章节分片时相邻片段保留的重叠字符数（默认 200）",
    )


def _add_output_options(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("-o", "--output-dir", type=Path, default=Path("notes"))
    parser.add_argument("--title", help="书名/笔记标题，默认取输入文件名")
    parser.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="novel-notes",
        description="TXT 小说按章节生成结构化读书笔记",
    )
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    gen = sub.add_parser("generate", help="生成章节读书笔记")
    gen.add_argument("input", type=Path, help="输入的 TXT 小说文件")
    _add_output_options(gen)
    _add_text_options(gen)
    _add_llm_options(gen)
    gen.add_argument("--workers", type=int, default=1, help="并发工作数（默认 1，避免限流）")
    gen.add_argument("--force", action="store_true", help="强制重新生成已完成章节")
    gen.add_argument(
        "--no-continue-on-error",
        action="store_false",
        dest="continue_on_error",
        help="某个章节失败时立即停止，而不是写错误文件继续",
    )
    gen.add_argument("--single-file", action="store_true", help="额外生成一个合并版 Markdown")
    gen.add_argument("--dry-run", action="store_true", help="只切分章节并预览，不调用 LLM")

    split = sub.add_parser("split", help="只把 TXT 按章节切分为文本文件，不调用 LLM")
    split.add_argument("input", type=Path, help="输入的 TXT 小说文件")
    split.add_argument("-o", "--output-dir", type=Path, default=Path("chapters"))
    _add_text_options(split)
    split.add_argument("-v", "--verbose", action="store_true", help="输出调试日志")

    return parser


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )


def _load_chapters(args: argparse.Namespace) -> List[Chapter]:
    text = read_text(args.input, getattr(args, "encoding", None))
    chapters = split_chapters(
        text,
        chapter_pattern=args.chapter_pattern,
        max_heading_len=args.max_heading_len,
        skip_toc=args.skip_toc,
        fallback_chunk_lines=args.fallback_chunk_lines,
        include_preamble=getattr(args, "include_preamble", True),
        preamble_min_chars=args.preamble_min_chars,
    )
    if not chapters:
        logger.error("未能识别到任何章节，请检查 --chapter-pattern 或 --fallback-chunk-lines")
        return []
    return chapters


def cmd_split(args: argparse.Namespace) -> int:
    if not args.input.exists():
        logger.error("输入文件不存在: %s", args.input)
        return 1

    chapters = _load_chapters(args)
    if not chapters:
        return 1

    args.output_dir.mkdir(parents=True, exist_ok=True)
    records = []
    for chapter in chapters:
        path = write_split_txt(args.output_dir, chapter)
        records.append(
            {
                "index": chapter.index,
                "title": chapter.title,
                "file": path.name,
                "line_start": chapter.line_start + 1,
                "line_end": chapter.line_end + 1,
                "chars": len(chapter.text),
            }
        )
        logger.info("已写出: %s", path.name)

    manifest = args.output_dir / "chapters.json"
    manifest.write_text(
        json.dumps(
            {
                "input": str(args.input),
                "chapters": records,
                "total_chapters": len(records),
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"\n完成：共切分 {len(chapters)} 个章节，输出目录：{args.output_dir}")
    print(summarize_chapters(chapters))
    return 0


def _book_title(args: argparse.Namespace) -> str:
    if args.title:
        return args.title
    return args.input.stem


def _record_dict(chapter: Chapter, filename: str, status: str, error: Optional[str] = None) -> Dict[str, str]:
    return {
        "index": str(chapter.index),
        "title": chapter.title,
        "file": filename,
        "status": status,
        "error": error or "",
    }


def cmd_generate(args: argparse.Namespace) -> int:
    if not args.input.exists():
        logger.error("输入文件不存在: %s", args.input)
        return 1

    chapters = _load_chapters(args)
    if not chapters:
        return 1

    title = _book_title(args)
    if args.dry_run:
        print(f"书名：{title}")
        print(f"识别到 {len(chapters)} 个章节：")
        print(summarize_chapters(chapters))
        return 0

    args.output_dir.mkdir(parents=True, exist_ok=True)
    progress = load_progress(args.output_dir)

    llm_config = LLMConfig(
        base_url=args.base_url,
        api_key=args.api_key,
        model=args.model,
        temperature=args.temperature,
        max_tokens=args.max_tokens,
        timeout=args.timeout,
        max_retries=args.max_retries,
    )

    lock = threading.Lock()
    client_local = threading.local()

    def get_client() -> LLMClient:
        if not hasattr(client_local, "client"):
            client_local.client = LLMClient(llm_config)
        return client_local.client

    def process_chapter(chapter: Chapter) -> Dict[str, str]:
        filename = chapter_filename(chapter.index, chapter.title)
        if not args.force:
            record = progress.get("chapters", {}).get(str(chapter.index))
            if record and record.get("status") == "done":
                note_path = args.output_dir / (record.get("file") or filename)
                if note_path.exists():
                    logger.info("跳过已完成章节: %s", chapter.title)
                    return _record_dict(chapter, filename, "skipped")
                logger.warning(
                    "进度显示已完成但文件缺失，重新生成: %s", chapter.title
                )

        try:
            logger.info("正在生成: %s（%d 字符）", chapter.title, len(chapter.text))
            client = get_client()
            note = generate_chapter_note(
                client,
                chapter,
                max_chunk_chars=args.max_chunk_chars,
                chunk_overlap=args.chunk_overlap,
            )
            path = write_chapter_note(args.output_dir, chapter, note)
            with lock:
                mark_done(progress, chapter.index, path.name, chapter.title)
                save_progress(args.output_dir, progress)
            logger.info("完成: %s -> %s", chapter.title, path.name)
            return _record_dict(chapter, path.name, "done")
        except Exception as exc:
            logger.exception("章节生成失败: %s", chapter.title)
            if not args.continue_on_error:
                raise
            path = write_chapter_error(args.output_dir, chapter, str(exc))
            with lock:
                mark_error(progress, chapter.index, path.name, chapter.title, str(exc))
                save_progress(args.output_dir, progress)
            return _record_dict(chapter, path.name, "error", str(exc))

    records: List[Dict[str, str]] = []
    if args.workers <= 1:
        for chapter in chapters:
            records.append(process_chapter(chapter))
    else:
        with ThreadPoolExecutor(max_workers=args.workers) as executor:
            future_map = {
                executor.submit(process_chapter, chapter): chapter for chapter in chapters
            }
            for future in as_completed(future_map):
                records.append(future.result())

    # 保持输出顺序与章节顺序一致。
    order = {chapter.index: i for i, chapter in enumerate(chapters)}
    records.sort(key=lambda item: order.get(int(item.get("index", -1)), -1))

    write_index(
        args.output_dir,
        title,
        args.model,
        [
            {
                **rec,
                "title": rec["title"],
                "file": rec.get("file") or "",
            }
            for rec in records
        ],
    )
    if args.single_file:
        write_single_file(args.output_dir, title, args.model, records)

    done = sum(1 for r in records if r["status"] == "done")
    skipped = sum(1 for r in records if r["status"] == "skipped")
    errors = sum(1 for r in records if r["status"] == "error")
    print(f"\n完成：共 {len(chapters)} 章，成功 {done}，跳过 {skipped}，失败 {errors}")
    print(f"输出目录：{args.output_dir}")

    if errors and done == 0 and skipped == 0:
        return 1
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    try:
        if args.command == "generate":
            return cmd_generate(args)
        if args.command == "split":
            return cmd_split(args)
        parser.error("未知命令")
    except KeyboardInterrupt:
        logger.warning("用户中断")
        return 130
    except Exception as exc:
        logger.error("运行失败: %s", exc)
        if args.verbose:
            logger.exception("详细堆栈")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
