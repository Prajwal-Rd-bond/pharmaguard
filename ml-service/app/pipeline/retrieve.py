"""
Module 6/7 — RAG Knowledge Base retrieval.

Embeds the extraction (drug + symptoms) with Sentence Transformers and searches the seeded Qdrant
collections (see corpus_seed.py) for supporting evidence. Per Module 6's AC, empty/low-confidence
retrieval must be shown as such, not hidden — and per the platform's NFRs, every AI-facing endpoint
must persist which model/mode produced its output. If Qdrant or the embedding model is unavailable,
we fall back to the keyword-overlap baseline and tag results `retrieval_mode: "fallback_baseline"`
rather than failing the whole pipeline run — same resilience pattern as extract.py/deidentify.py.
"""

import logging
import os
from functools import lru_cache

from qdrant_client import QdrantClient

from .corpus_seed import SEED_DOCS, SEEDED_COLLECTIONS, ensure_seeded

logger = logging.getLogger(__name__)

QDRANT_URL = os.getenv("QDRANT_URL", "http://localhost:6333")
EMBEDDING_MODEL_NAME = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")


@lru_cache(maxsize=1)
def _get_qdrant_client() -> QdrantClient:
    return QdrantClient(url=QDRANT_URL)


@lru_cache(maxsize=1)
def _get_embedder():
    from sentence_transformers import SentenceTransformer

    return SentenceTransformer(EMBEDDING_MODEL_NAME)


def _query_text(extraction: dict) -> str:
    parts = []
    if extraction.get("drugName"):
        parts.append(extraction["drugName"])
    parts += extraction.get("symptoms") or []
    return ", ".join(parts)


def _retrieve_baseline(extraction: dict, top_k: int) -> list:
    query_terms = set()
    if extraction.get("drugName"):
        query_terms.add(extraction["drugName"].lower())
    query_terms |= {s.lower() for s in (extraction.get("symptoms") or [])}

    scored = []
    for doc in SEED_DOCS:
        overlap = len({t for t in query_terms if t in f"{doc['title']} {doc['snippet']}".lower()})
        if overlap > 0:
            score = min(0.99, 0.5 + 0.15 * overlap)
            scored.append({
                "source_collection": doc["source_collection"],
                "source_id": doc["source_id"],
                "title": doc["title"],
                "snippet": doc["snippet"],
                "similarity_score": round(score, 2),
                "retrieval_mode": "fallback_baseline",
            })

    scored.sort(key=lambda d: d["similarity_score"], reverse=True)
    return scored[:top_k]


def _retrieve_qdrant(extraction: dict, top_k: int) -> list:
    client = _get_qdrant_client()
    embedder = _get_embedder()
    ensure_seeded(client, embedder)

    query_vector = embedder.encode(_query_text(extraction)).tolist()

    hits = []
    for collection in SEEDED_COLLECTIONS:
        for hit in client.search(collection_name=collection, query_vector=query_vector, limit=top_k):
            hits.append({
                "source_collection": collection,
                "source_id": hit.payload["source_id"],
                "title": hit.payload["title"],
                "snippet": hit.payload["snippet"],
                "similarity_score": round(hit.score, 2),
                "retrieval_mode": "qdrant",
            })

    hits.sort(key=lambda d: d["similarity_score"], reverse=True)
    return hits[:top_k]


def retrieve(extraction: dict, top_k: int = 5) -> list:
    if not extraction.get("drugName") and not extraction.get("symptoms"):
        return []

    try:
        return _retrieve_qdrant(extraction, top_k)
    except Exception as exc:
        logger.warning("Qdrant retrieval failed (%s), falling back to baseline retriever", exc)
        return _retrieve_baseline(extraction, top_k)
