"""
Vector Knowledge Base Store backed by Qdrant and fastembed.

Manages:
- Collection creation with 384-dimensional dense embeddings (BAAI/bge-small-en-v1.5).
- Deterministic UUIDv5 point IDs for idempotent upserts.
- Lazy ingestion: automatically indexes openFDA label chunks on first encounter.
- Vector search with ingredient-scoped filtering.
- Graceful in-memory fallback if Qdrant service is temporarily unavailable.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any, Dict, List, Optional
import numpy as np
from pydantic import BaseModel, Field

try:
    from fastembed import TextEmbedding
except ImportError:
    TextEmbedding = None
from qdrant_client import QdrantClient
from qdrant_client.http import models as qmodels

from ..config import get_settings
from .chunker import chunk_all_sections
from .openfda import fetch_openfda_labels

logger = logging.getLogger(__name__)

# Module-level embedding model cache
_EMBED_MODEL: Optional[Any] = None
# In-memory fallback index for environments without a live Qdrant container
_IN_MEMORY_FALLBACK_STORE: Dict[str, List[Dict[str, Any]]] = {}


class StoreSearchResult(BaseModel):
    status: str  # ok | none_found | provider_error | not_configured
    items: List[Dict[str, Any]] = Field(default_factory=list)


class StoreSearchResultList(list):
    """List preserving backward compatibility while providing typed status."""
    def __init__(self, items: List[Dict[str, Any]], status: str = "ok"):
        super().__init__(items)
        self.status = status

    def to_result(self) -> StoreSearchResult:
        return StoreSearchResult(status=self.status, items=list(self))


def get_embed_model(model_name: str = "BAAI/bge-small-en-v1.5", cache_dir: str = "") -> Any:
    global _EMBED_MODEL
    if _EMBED_MODEL is None:
        if TextEmbedding is None:
            class InMemEmbedder:
                def embed(self, texts):
                    for _ in texts:
                        yield np.zeros(384, dtype=np.float32)
            return InMemEmbedder()
        kwargs = {"model_name": model_name}
        if cache_dir:
            kwargs["cache_dir"] = cache_dir
        _EMBED_MODEL = TextEmbedding(**kwargs)
    return _EMBED_MODEL

class EvidenceStore:
    def __init__(
        self,
        qdrant_url: str = "http://localhost:6333",
        collection_name: str = "drug_label_chunks",
        embed_model_name: str = "BAAI/bge-small-en-v1.5",
    ):
        self.qdrant_url = qdrant_url
        self.collection_name = collection_name
        self.embed_model_name = embed_model_name
        self._client: Optional[QdrantClient] = None
        self._is_connected: Optional[bool] = None

    def get_client(self) -> Optional[QdrantClient]:
        if self._client is None:
            try:
                self._client = QdrantClient(url=self.qdrant_url, timeout=5.0)
                # Quick health ping
                self._client.get_collections()
                self._is_connected = True
                self._ensure_collection()
            except Exception as exc:
                logger.warning("Could not connect to Qdrant at %s: %s. Using in-memory fallback.", self.qdrant_url, exc)
                self._client = None
                self._is_connected = False
        return self._client

    def _ensure_collection(self) -> None:
        if not self._client:
            return
        try:
            collections = self._client.get_collections().collections
            exists = any(c.name == self.collection_name for c in collections)
            if not exists:
                logger.info("Creating Qdrant collection: %s", self.collection_name)
                self._client.create_collection(
                    collection_name=self.collection_name,
                    vectors_config=qmodels.VectorParams(
                        size=384,
                        distance=qmodels.Distance.COSINE,
                    ),
                )
        except Exception as exc:
            logger.warning("Failed to verify/create Qdrant collection: %s", exc)

    def is_ingredient_indexed(self, ingredient_name: str, rxcui: Optional[str] = None) -> bool:
        clean_name = ingredient_name.strip().lower()
        client = self.get_client()
        if not client:
            return clean_name in _IN_MEMORY_FALLBACK_STORE

        try:
            # Check using count query
            filter_conditions = [
                qmodels.FieldCondition(
                    key="ingredient_name",
                    match=qmodels.MatchValue(value=clean_name),
                )
            ]
            count_res = client.count(
                collection_name=self.collection_name,
                count_filter=qmodels.Filter(must=filter_conditions),
            )
            return count_res.count > 0
        except Exception as exc:
            logger.warning("Qdrant count query failed: %s", exc)
            return clean_name in _IN_MEMORY_FALLBACK_STORE

    def upsert_chunks(self, chunks: List[Dict[str, Any]], ingredient_rxcui: Optional[str] = None) -> int:
        if not chunks:
            return 0

        embedder = get_embed_model(self.embed_model_name)
        texts = [c["text"] for c in chunks]
        embeddings = list(embedder.embed(texts))

        client = self.get_client()

        # Always update in-memory cache as well (grouped by ingredient)
        for c, e in zip(chunks, embeddings):
            c_ingr = c.get("ingredient_name", "").lower()
            if c_ingr not in _IN_MEMORY_FALLBACK_STORE:
                _IN_MEMORY_FALLBACK_STORE[c_ingr] = []
            _IN_MEMORY_FALLBACK_STORE[c_ingr].append({**c, "embedding": np.array(e)})

        clean_ingr = chunks[0].get("ingredient_name", "").lower() if chunks else ""

        if not client:
            logger.info("Upserted %d chunks to in-memory fallback store", len(chunks))
            return len(chunks)

        points = []
        for c, emb in zip(chunks, embeddings):
            chunk_id = c.get("chunk_id", str(uuid.uuid4()))
            point_uuid = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"{ingredient_rxcui or clean_ingr}:{chunk_id}"))

            payload = {
                "chunk_id": chunk_id,
                "ingredient_name": clean_ingr,
                "ingredient_rxcui": ingredient_rxcui or "",
                "section": c.get("section", ""),
                "title": c.get("title", ""),
                "source_id": c.get("source_id", ""),
                "set_id": c.get("set_id", ""),
                "url": c.get("url", ""),
                "text": c.get("text", ""),
            }

            points.append(
                qmodels.PointStruct(
                    id=point_uuid,
                    vector=emb.tolist(),
                    payload=payload,
                )
            )

        try:
            client.upsert(collection_name=self.collection_name, points=points)
            logger.info("Successfully indexed %d chunks in Qdrant for %s", len(points), clean_ingr)
            return len(points)
        except Exception as exc:
            logger.warning("Qdrant upsert failed: %s", exc)
            return len(chunks)

    async def lazy_index_ingredient(
        self,
        ingredient_name: str,
        rxcui: Optional[str] = None,
        api_key: str = "",
    ) -> bool:
        """
        If ingredient is not yet in vector store, fetches openFDA labels, chunks, and indexes.
        """
        clean_name = ingredient_name.strip().lower()
        if not clean_name:
            return False

        if self.is_ingredient_indexed(clean_name, rxcui):
            return True

        logger.info("Lazy-indexing openFDA safety label for: %s", clean_name)
        sections = await fetch_openfda_labels(clean_name, api_key=api_key)
        if not sections:
            logger.info("No openFDA sections retrieved for %s", clean_name)
            return False

        chunks = chunk_all_sections(sections)
        if not chunks:
            return False

        self.upsert_chunks(chunks, ingredient_rxcui=rxcui)
        return True

    def search(
        self,
        query: str,
        ingredient_name: Optional[str] = None,
        top_k: int = 5,
    ) -> StoreSearchResultList:
        """
        Vector search for safety chunks relevant to the clinical query.
        """
        if not query.strip():
            return StoreSearchResultList([], status="none_found")

        embedder = get_embed_model(self.embed_model_name)
        query_vector = list(embedder.embed([query]))[0]

        client = self.get_client()
        clean_ingr = (ingredient_name or "").strip().lower()

        # If Qdrant is connected, search via vector index
        if client:
            try:
                filter_obj = None
                if clean_ingr:
                    filter_obj = qmodels.Filter(
                        must=[
                            qmodels.FieldCondition(
                                key="ingredient_name",
                                match=qmodels.MatchValue(value=clean_ingr),
                            )
                        ]
                    )

                results = client.search(
                    collection_name=self.collection_name,
                    query_vector=query_vector.tolist(),
                    query_filter=filter_obj,
                    limit=top_k,
                )

                items = []
                for hit in results:
                    payload = hit.payload or {}
                    items.append({
                        "source_collection": self.collection_name,
                        "source_id": payload.get("source_id", "label"),
                        "title": payload.get("title", ""),
                        "snippet": payload.get("text", ""),
                        "section": payload.get("section", ""),
                        "similarity_score": round(float(hit.score), 3),
                        "url": payload.get("url", ""),
                        "set_id": payload.get("set_id", ""),
                    })
                return StoreSearchResultList(items, status="ok" if items else "none_found")
            except Exception as exc:
                logger.warning("Qdrant vector search failed: %s. Falling back to memory.", exc)

        # In-memory cosine similarity fallback
        q_vec = np.array(query_vector)
        norm_q = np.linalg.norm(q_vec) or 1.0

        candidates = []
        if clean_ingr and clean_ingr in _IN_MEMORY_FALLBACK_STORE:
            candidates = _IN_MEMORY_FALLBACK_STORE[clean_ingr]
        else:
            for chunk_list in _IN_MEMORY_FALLBACK_STORE.values():
                candidates.extend(chunk_list)

        scored = []
        for item in candidates:
            emb = item.get("embedding")
            if emb is not None:
                norm_e = np.linalg.norm(emb) or 1.0
                score = float(np.dot(q_vec, emb) / (norm_q * norm_e))
            else:
                score = 0.5

            scored.append({
                "source_collection": "drug_labels",
                "source_id": item.get("source_id", "label"),
                "title": item.get("title", ""),
                "snippet": item.get("text", ""),
                "section": item.get("section", ""),
                "similarity_score": round(score, 3),
                "url": item.get("url", ""),
                "set_id": item.get("set_id", ""),
            })

        scored.sort(key=lambda x: x["similarity_score"], reverse=True)
        final_items = scored[:top_k]
        return StoreSearchResultList(final_items, status="ok" if final_items else "none_found")

