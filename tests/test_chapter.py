from novel_notes.chapter import split_chapters

TOC_SAMPLE = """书名：测试小说
作者：某人

目录
第一章 风起
第二章 云涌
第三章 惊变

正文

第一章 风起

风起了。

少年站在山巅，望着远方。

第二章 云涌

云层翻涌。

少年握紧了剑。

第三章 惊变

敌人出现了。
"""

NO_TOC_SAMPLE = """第一章 风起

风起了。

第二章 云涌

云层翻涌。
"""


def test_skip_toc_and_keep_body():
    chapters = split_chapters(TOC_SAMPLE)
    assert [c.title for c in chapters] == [
        "第一章 风起",
        "第二章 云涌",
        "第三章 惊变",
    ]
    assert all("风" in c.text or "云" in c.text or "敌人" in c.text for c in chapters)


def test_no_toc_simple():
    chapters = split_chapters(NO_TOC_SAMPLE)
    assert len(chapters) == 2
    assert chapters[0].title == "第一章 风起"
    assert chapters[1].title == "第二章 云涌"


def test_fallback_chunk_lines():
    text = "\n".join(f"line {i}" for i in range(100))
    chapters = split_chapters(text, fallback_chunk_lines=30)
    assert len(chapters) == 4
    assert chapters[0].title == "第1部分"
    assert all(ch.text for ch in chapters)


def test_custom_pattern():
    text = "Part 1\n内容一\nPart 2\n内容二\n"
    chapters = split_chapters(text, chapter_pattern=r"^Part\s+\d+$")
    assert len(chapters) == 2
    assert chapters[0].title == "Part 1"


def test_no_chapters_without_fallback():
    text = "没有章节标题的普通文本"
    assert split_chapters(text) == []
