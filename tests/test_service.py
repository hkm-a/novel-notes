from novel_notes.service import split_text_into_chunks


def test_short_text_returns_one():
    text = "短文本"
    assert split_text_into_chunks(text, max_chars=10) == [text]


def test_long_text_chunk_size_and_overlap():
    text = "字" * 2500
    chunks = split_text_into_chunks(text, max_chars=1000, overlap_chars=100)
    assert len(chunks) >= 2
    assert all(len(c) <= 1000 for c in chunks)
    assert chunks[1].startswith(chunks[0][-100:])


def test_chunks_preserve_content():
    text = "abcdefghij" * 100
    joined = "".join(split_text_into_chunks(text, max_chars=100, overlap_chars=10))
    assert "abcdefghij" in joined
