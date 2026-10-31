"""
Semantic Chunker for Clinical Drug Labels.

Splits long regulatory label sections into coherent ~600-900 character chunks
respecting paragraph and sentence boundaries, with metadata attached.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?])\s+(?=[A-Z0-9])")


def chunk_section(
    section_data: Dict[str, Any],
    target_chunk_size: int = 750,
    min_chunk_size: int = 150,
) -> List[Dict[str, Any]]:
    """
    Chunks a section into ~750 char chunks preserving sentence boundaries.
    """
    raw_text = section_data.get("text", "").strip()
    if not raw_text:
        return []

    # Clean multiple consecutive blank lines or tabs
    cleaned = re.sub(r"\n{3,}", "\n\n", raw_text)
    paragraphs = cleaned.split("\n\n")

    chunks: List[Dict[str, Any]] = []
    current_sentences: List[str] = []
    current_len = 0
    chunk_idx = 0

    def _flush_chunk():
        nonlocal current_sentences, current_len, chunk_idx
        if not current_sentences:
            return
        chunk_text = " ".join(current_sentences).strip()
        if len(chunk_text) >= min_chunk_size:
            chunk_copy = dict(section_data)
            chunk_copy["chunk_index"] = chunk_idx
            chunk_copy["chunk_id"] = f"{section_data.get('source_id', 'chunk')}-p{chunk_idx}"
            chunk_copy["text"] = chunk_text
            chunks.append(chunk_copy)
            chunk_idx += 1
        current_sentences = []
        current_len = 0

    for para in paragraphs:
        para_clean = para.strip()
        if not para_clean:
            continue

        sentences = SENTENCE_SPLIT_RE.split(para_clean)
        for s in sentences:
            s_clean = s.strip()
            if not s_clean:
                continue

            s_len = len(s_clean)
            if current_len + s_len > target_chunk_size and current_sentences:
                _flush_chunk()

            current_sentences.append(s_clean)
            current_len += s_len + 1

    _flush_chunk()
    return chunks


def chunk_all_sections(sections: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    all_chunks = []
    for s in sections:
        all_chunks.extend(chunk_section(s))
    return all_chunks

