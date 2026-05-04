from src.ingestion.pipeline import chunk_text, CHUNK_SIZE, CHUNK_OVERLAP


def test_single_chunk_for_short_text() -> None:
    text = "hello world " * 10
    chunks = chunk_text("doc1", text)
    assert len(chunks) == 1
    assert chunks[0].doc_id == "doc1"
    assert chunks[0].chunk_index == 0


def test_multiple_chunks_for_long_text() -> None:
    text = " ".join(str(i) for i in range(CHUNK_SIZE * 3))
    chunks = chunk_text("doc2", text)
    assert len(chunks) > 1
    for i, chunk in enumerate(chunks):
        assert chunk.chunk_index == i


def test_overlap_produces_repeated_words() -> None:
    words = [str(i) for i in range(CHUNK_SIZE + CHUNK_OVERLAP + 10)]
    text = " ".join(words)
    chunks = chunk_text("doc3", text)
    last_words_of_first = chunks[0].text.split()[-CHUNK_OVERLAP:]
    first_words_of_second = chunks[1].text.split()[:CHUNK_OVERLAP]
    assert last_words_of_first == first_words_of_second
