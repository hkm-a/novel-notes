"""读取小说 TXT 文件，处理常见编码。"""

from __future__ import annotations

import codecs
from pathlib import Path
from typing import Optional

# 按常见概率排序，用于无法用检测库时的兜底尝试。
_COMMON_ENCODINGS = (
    "utf-8",
    "gb18030",
    "gbk",
    "big5",
    "utf-16-le",
    "utf-16-be",
    "utf-32-le",
    "utf-32-be",
    "shift_jis",
    "utf-8-sig",
)


def detect_encoding(data: bytes) -> Optional[str]:
    """返回检测到的编码名；检测不到时返回 None。"""
    # 先看 BOM，最可靠。
    if data.startswith(codecs.BOM_UTF8):
        return "utf-8-sig"
    if data.startswith(codecs.BOM_UTF16_LE):
        return "utf-16-le"
    if data.startswith(codecs.BOM_UTF16_BE):
        return "utf-16-be"
    if data.startswith(codecs.BOM_UTF32_LE):
        return "utf-32-le"
    if data.startswith(codecs.BOM_UTF32_BE):
        return "utf-32-be"

    # 先尝试常见编码的严格解码，避免 charset-normalizer 在短样本上误判。
    for enc in _COMMON_ENCODINGS:
        try:
            data.decode(enc)
            return enc
        except (LookupError, UnicodeDecodeError):
            continue

    # 常见编码都失败时，再用 charset-normalizer 兜底。
    try:
        from charset_normalizer import from_bytes

        best = from_bytes(data).best()
        if best is not None and best.encoding:
            return best.encoding.replace("_", "-")
    except Exception:
        pass

    return None


def read_text(path: Path, encoding: Optional[str] = None) -> str:
    """读取文本文件并统一换行符为 \\n。"""
    data = path.read_bytes()
    if encoding:
        try:
            text = data.decode(encoding, errors="replace")
        except LookupError as exc:
            raise ValueError(f"未知编码: {encoding}") from exc
    else:
        enc = detect_encoding(data)
        if enc is None:
            # 实在检测不到时用 UTF-8 替换错误，保证程序不崩。
            text = data.decode("utf-8", errors="replace")
        else:
            try:
                text = data.decode(enc, errors="replace")
            except Exception:
                text = data.decode("utf-8", errors="replace")

    return text.replace("\r\n", "\n").replace("\r", "\n")
