from pathlib import Path

from novel_notes.encoding import detect_encoding, read_text


def test_detect_utf8():
    data = "第一章 风起\n".encode("utf-8")
    assert detect_encoding(data) == "utf-8"


def test_detect_gb18030():
    data = "第一章 风起\n".encode("gb18030")
    assert detect_encoding(data) == "gb18030"


def test_read_text_normalizes_newlines(tmp_path: Path):
    p = tmp_path / "a.txt"
    p.write_bytes("a\r\nb\rc\n".encode("utf-8"))
    assert read_text(p) == "a\nb\nc\n"


def test_read_text_with_encoding(tmp_path: Path):
    p = tmp_path / "gb.txt"
    p.write_bytes("你好".encode("gb18030"))
    assert read_text(p, encoding="gb18030") == "你好"
