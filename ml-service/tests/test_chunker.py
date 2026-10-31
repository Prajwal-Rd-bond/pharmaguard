"""
Unit tests for openFDA drug safety label chunking.
"""

from app.evidence.chunker import chunk_section, chunk_all_sections


def test_chunk_short_section():
    section = {
        "source_id": "test-sec-01",
        "title": "Ibuprofen — Warnings",
        "text": "Cardiovascular Thrombotic Events: Clinical trials of several COX-2 selective and nonselective NSAIDs have shown an increased risk of serious cardiovascular events.",
    }
    chunks = chunk_section(section, target_chunk_size=500, min_chunk_size=50)
    assert len(chunks) == 1
    assert chunks[0]["chunk_index"] == 0
    assert chunks[0]["title"] == "Ibuprofen — Warnings"
    assert "Cardiovascular" in chunks[0]["text"]


def test_chunk_long_section_splits_sentences():
    sentences = [
        f"Sentence number {i} provides detailed clinical precautions regarding adverse drug event monitoring in hospital settings."
        for i in range(20)
    ]
    long_text = " ".join(sentences)

    section = {
        "source_id": "test-sec-02",
        "title": "Long Section Test",
        "text": long_text,
    }
    chunks = chunk_section(section, target_chunk_size=400, min_chunk_size=100)
    assert len(chunks) > 1
    for c in chunks:
        assert c["chunk_id"].startswith("test-sec-02-p")
        assert len(c["text"]) >= 100

