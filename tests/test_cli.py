import json
from pathlib import Path

from novel_notes.cli import main


def test_split_command(tmp_path: Path):
    src = tmp_path / "book.txt"
    src.write_text(
        "第一章 风起\n内容\n第二章 云涌\n内容\n",
        encoding="utf-8",
    )
    out = tmp_path / "out"
    code = main(["split", str(src), "-o", str(out)])
    assert code == 0
    assert len(list(out.glob("*.txt"))) == 2
    manifest = json.loads((out / "chapters.json").read_text(encoding="utf-8"))
    assert manifest["total_chapters"] == 2


def test_generate_dry_run(tmp_path: Path):
    src = tmp_path / "book.txt"
    src.write_text("第一章 风起\n内容\n第二章 云涌\n内容\n", encoding="utf-8")
    code = main(["generate", str(src), "--dry-run"])
    assert code == 0


def test_generate_writes_notes_and_progress(tmp_path: Path, monkeypatch):
    from novel_notes import cli

    src = tmp_path / "book.txt"
    src.write_text("第一章 风起\n内容\n第二章 云涌\n内容\n", encoding="utf-8")
    out = tmp_path / "notes"

    def fake_generate(client, chapter, max_chunk_chars=6000, chunk_overlap=200):
        return "## 一句话概括\n测试摘要\n"

    monkeypatch.setattr(cli, "generate_chapter_note", fake_generate)
    code = cli.main([
        "generate", str(src), "-o", str(out),
        "--base-url", "http://example.com/v1", "--model", "test",
    ])
    assert code == 0
    assert (out / "index.md").exists()
    assert len(list(out.glob("*.md"))) >= 3  # 2 章 + index
    assert (out / ".progress.json").exists()
