"""
Module 6/7 — RAG Knowledge Base retrieval.

Baseline implementation: a small in-memory mock corpus with keyword matching, so the pipeline
runs without a seeded Qdrant instance. Phase 1 hardening should embed a real corpus (FDA labels,
WHO PV docs, PubMed abstracts, historical cases) with Sentence Transformers and query Qdrant
(see QDRANT_URL in docker-compose.yml / qdrant-client in requirements.txt).
"""

MOCK_CORPUS = [
    {
        "source_collection": "drug_labels",
        "source_id": "label-ibuprofen-001",
        "title": "Ibuprofen — FDA Label, Warnings section",
        "keywords": ["ibuprofen"],
        "snippet": "May cause gastrointestinal bleeding, ulceration; rare risk of anaphylactoid reactions.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-amoxicillin-001",
        "title": "Amoxicillin — FDA Label, Adverse Reactions",
        "keywords": ["amoxicillin"],
        "snippet": "Hypersensitivity reactions including rash, urticaria, and rarely anaphylaxis have been reported.",
    },
    {
        "source_collection": "historical_cases",
        "source_id": "case-0142",
        "title": "Similar historical ADR case #0142",
        "keywords": ["rash", "hives", "amoxicillin"],
        "snippet": "Patient developed hives within 2 hours of amoxicillin administration; resolved with antihistamines.",
    },
    {
        "source_collection": "clinical_guidelines",
        "source_id": "guideline-anaphylaxis-mgmt",
        "title": "WHO Guideline — Recognition and Management of Anaphylaxis",
        "keywords": ["anaphylaxis", "shortness of breath", "swelling"],
        "snippet": "Immediate epinephrine administration is recommended for suspected anaphylaxis; monitor airway.",
    },
]


def retrieve(extraction: dict, top_k: int = 5):
    query_terms = set()
    if extraction.get("drugName"):
        query_terms.add(extraction["drugName"].lower())
    query_terms |= {s.lower() for s in (extraction.get("symptoms") or [])}

    scored = []
    for doc in MOCK_CORPUS:
        overlap = len(query_terms & set(doc["keywords"]))
        if overlap > 0:
            score = min(0.99, 0.5 + 0.15 * overlap)
            scored.append({
                "source_collection": doc["source_collection"],
                "source_id": doc["source_id"],
                "title": doc["title"],
                "snippet": doc["snippet"],
                "similarity_score": round(score, 2),
            })

    scored.sort(key=lambda d: d["similarity_score"], reverse=True)
    return scored[:top_k]
    # TODO(Phase 1 hardening): replace with real Qdrant search, e.g.:
    #   query_vector = embedding_model.encode(query_text)
    #   hits = qdrant_client.search(collection_name="drug_labels", query_vector=query_vector, limit=top_k)
