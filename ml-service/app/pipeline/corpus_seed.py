"""
Seed data + idempotent seeding for the Phase 1 "reduced corpus" RAG collections.

Ported from the values that used to live in retrieve.py's MOCK_CORPUS. Real embeddings replace
the old keyword-list matching, so each doc now only needs the text that gets embedded (title +
snippet) plus its identity/collection fields.
"""

import logging

from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

SEED_DOCS = [
    {
        "source_collection": "drug_labels",
        "source_id": "label-ibuprofen-001",
        "title": "Ibuprofen — FDA Label, Warnings section",
        "snippet": "May cause gastrointestinal bleeding, ulceration; rare risk of anaphylactoid reactions.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-amoxicillin-001",
        "title": "Amoxicillin — FDA Label, Adverse Reactions",
        "snippet": "Hypersensitivity reactions including rash, urticaria, and rarely anaphylaxis have been reported.",
    },
    {
        "source_collection": "historical_cases",
        "source_id": "case-0142",
        "title": "Similar historical ADR case #0142",
        "snippet": "Patient developed hives within 2 hours of amoxicillin administration; resolved with antihistamines.",
    },
    {
        "source_collection": "clinical_guidelines",
        "source_id": "guideline-anaphylaxis-mgmt",
        "title": "WHO Guideline — Recognition and Management of Anaphylaxis",
        "snippet": "Immediate epinephrine administration is recommended for suspected anaphylaxis; monitor airway.",
    },
]

SEEDED_COLLECTIONS = ("drug_labels", "historical_cases", "clinical_guidelines")


def ensure_seeded(client, embedder) -> None:
    """Create each Phase 1 collection if missing and upsert seed docs if it's currently empty."""
    vector_size = embedder.get_sentence_embedding_dimension()

    for collection in SEEDED_COLLECTIONS:
        if not client.collection_exists(collection):
            client.create_collection(
                collection_name=collection,
                vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
            )
            logger.info("Created Qdrant collection %s", collection)

        count = client.count(collection_name=collection, exact=True).count
        if count > 0:
            continue

        docs = [d for d in SEED_DOCS if d["source_collection"] == collection]
        if not docs:
            continue

        vectors = embedder.encode([f"{d['title']}. {d['snippet']}" for d in docs])
        client.upsert(
            collection_name=collection,
            points=[
                qmodels.PointStruct(
                    id=i,
                    vector=vectors[i].tolist(),
                    payload={
                        "source_id": d["source_id"],
                        "title": d["title"],
                        "snippet": d["snippet"],
                    },
                )
                for i, d in enumerate(docs)
            ],
        )
        logger.info("Seeded %d docs into %s", len(docs), collection)
