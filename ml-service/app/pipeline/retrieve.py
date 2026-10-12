"""
Module 6/7 — RAG Knowledge Base retrieval with Hybrid Dense + Sparse BM25 and Re-ranking.

Combines:
1. Sparse BM25 keyword retrieval (Okapi BM25) for precise clinical terminology matching.
2. Dense semantic embeddings via SentenceTransformers and Qdrant.
3. Reciprocal Rank Fusion (RRF) with k=60 to fuse dense and sparse ranks.
4. Domain-specific clinical re-ranker scoring candidate passages against suspect drug & symptoms.
"""

import os
import math
import re
from typing import List, Dict, Any, Optional

try:
    from sentence_transformers import SentenceTransformer
except ImportError:
    SentenceTransformer = None

try:
    from qdrant_client import QdrantClient
    from qdrant_client.models import VectorParams, Distance, PointStruct
except ImportError:
    QdrantClient = None
    VectorParams = None
    Distance = None
    PointStruct = None

# Comprehensive knowledge base corpus spanning major FDA drug labels, guidelines, and literature
KNOWLEDGE_CORPUS = [
    {
        "source_collection": "drug_labels",
        "source_id": "label-amoxicillin-001",
        "title": "Amoxicillin — FDA Prescribing Information (Adverse Reactions)",
        "keywords": ["amoxicillin", "rash", "anaphylaxis", "urticaria", "hypersensitivity", "allergy"],
        "snippet": "Serious and occasionally fatal hypersensitivity (anaphylactic) reactions have been reported in patients on penicillin therapy. Erythematous maculopapular rashes, erythema multiforme, and Stevens-Johnson syndrome may occur. Discontinue immediately if allergic reaction arises.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-ibuprofen-001",
        "title": "Ibuprofen — FDA Prescribing Information (Boxed Warnings)",
        "keywords": ["ibuprofen", "bleeding", "gastrointestinal", "ulcer", "kidney", "renal", "nsaid"],
        "snippet": "NSAIDs cause an increased risk of serious gastrointestinal adverse events including bleeding, ulceration, and perforation of the stomach or intestines. Long-term administration may result in renal papillary necrosis and acute kidney injury.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-ciprofloxacin-001",
        "title": "Ciprofloxacin — FDA Boxed Warning (Tendinitis & Neuropathy)",
        "keywords": ["ciprofloxacin", "tendon", "tendinitis", "neuropathy", "qt", "fluoroquinolone"],
        "snippet": "Fluoroquinolones, including ciprofloxacin, are associated with an increased risk of tendinitis and tendon rupture in all ages, especially the Achilles tendon. May cause irreversible peripheral neuropathy and QT prolongation.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-lisinopril-001",
        "title": "Lisinopril — FDA Prescribing Information (Head and Neck Angioedema)",
        "keywords": ["lisinopril", "angioedema", "cough", "hyperkalemia", "swelling", "ace"],
        "snippet": "Angioedema of the face, extremities, lips, tongue, glottis, and larynx has been reported in patients treated with ACE inhibitors. If laryngeal stridor or angioedema occurs, discontinue lisinopril immediately and administer subcutaneous epinephrine.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-metformin-001",
        "title": "Metformin — FDA Prescribing Information (Lactic Acidosis)",
        "keywords": ["metformin", "lactic", "acidosis", "hypoglycemia", "renal", "kidney"],
        "snippet": "Lactic acidosis is a rare but fatal metabolic complication that can occur due to metformin accumulation during treatment. Risk increases with conditions such as renal impairment, hypoperfusion, and hypoxemia.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-atorvastatin-001",
        "title": "Atorvastatin — FDA Label (Skeletal Muscle & Rhabdomyolysis)",
        "keywords": ["atorvastatin", "rhabdomyolysis", "myalgia", "muscle", "statin", "ck"],
        "snippet": "Cases of myopathy and rhabdomyolysis with acute renal failure secondary to myoglobinuria have been reported with atorvastatin. Promptly discontinue if markedly elevated creatine kinase levels occur or myopathy is diagnosed.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-warfarin-001",
        "title": "Warfarin — FDA Prescribing Information (Major Hemorrhage)",
        "keywords": ["warfarin", "hemorrhage", "bleeding", "inr", "hematuria", "anticoagulant"],
        "snippet": "Warfarin can cause major or fatal bleeding. Bleeding is more likely to occur during the starting period and with higher doses. Perform regular monitoring of INR in all treated patients.",
    },
    {
        "source_collection": "clinical_guidelines",
        "source_id": "guideline-anaphylaxis-mgmt",
        "title": "WHO & WAO International Guidelines — Recognition and Management of Anaphylaxis",
        "keywords": ["anaphylaxis", "epinephrine", "swelling", "airway", "hypotension", "allergy"],
        "snippet": "Intramuscular epinephrine in the mid-anterolateral thigh is the first-line therapy for anaphylaxis. Supplemental oxygen, airway assessment, and rapid intravenous fluid resuscitation should follow immediately.",
    },
    {
        "source_collection": "clinical_guidelines",
        "source_id": "guideline-drug-induced-aki",
        "title": "KDIGO Clinical Practice Guideline — Drug-Induced Acute Kidney Injury",
        "keywords": ["kidney", "renal", "aki", "creatinine", "nsaid", "toxicity"],
        "snippet": "Discontinue all potential nephrotoxic medications immediately upon identification of acute kidney injury. Ensure volume euvolemia and monitor serum creatinine and urine output closely.",
    },
    {
        "source_collection": "historical_cases",
        "source_id": "case-historical-0142",
        "title": "Historical ADR Case Archive #0142 — Drug Hypersensitivity",
        "keywords": ["amoxicillin", "rash", "hives", "urticaria", "pruritus"],
        "snippet": "A 34-year-old female developed generalized urticaria and facial flushing 90 minutes post second dose of amoxicillin. Rapidly resolved following oral cetirizine and discontinuation of the beta-lactam.",
    },
    {
        "source_collection": "historical_cases",
        "source_id": "case-historical-0289",
        "title": "Historical ADR Case Archive #0289 — Fluoroquinolone Arthropathy",
        "keywords": ["ciprofloxacin", "tendon", "pain", "swelling", "rupture"],
        "snippet": "A 58-year-old male presenting with acute left heel pain and tenderness after 5 days of ciprofloxacin therapy. MRI confirmed Achilles tendon rupture. Underwent surgical repair and therapy was switched to ceftriaxone.",
    },
]

# Initialize embedding model (SentenceTransformer)
embedding_model = None
if SentenceTransformer is not None:
    try:
        embedding_model = SentenceTransformer('all-MiniLM-L6-v2')
    except Exception as e:
        print(f"Warning: Failed to load embedding model: {e}")
        embedding_model = None

# Initialize Qdrant Client
QDRANT_URL = os.environ.get("QDRANT_URL", "http://localhost:6333")
COLLECTION_NAME = "knowledge_base"

qdrant_client = None
_is_seeded = False


def get_qdrant_client():
    global qdrant_client
    if QdrantClient is not None and qdrant_client is None:
        try:
            qdrant_client = QdrantClient(url=QDRANT_URL, timeout=5)
        except Exception as e:
            print(f"Warning: Failed to connect to Qdrant at {QDRANT_URL}: {e}")
            qdrant_client = None
    return qdrant_client


def ensure_seeded():
    """
    Idempotent initialization: Checks if Qdrant collection exists and has documents
    BEFORE fetching any feeds or embedding documents. Never re-seeds if data is present.
    """
    global _is_seeded
    if _is_seeded:
        return

    client = get_qdrant_client()
    if not client:
        return

    try:
        if not client.collection_exists(collection_name=COLLECTION_NAME):
            client.create_collection(
                collection_name=COLLECTION_NAME,
                vectors_config=VectorParams(size=384, distance=Distance.COSINE),
            )

        # Check existing point count before doing any seeding
        count_res = client.count(collection_name=COLLECTION_NAME)
        if count_res.count > 0:
            _is_seeded = True
            return

        # Seed baseline knowledge base
        if embedding_model:
            points = []
            for i, doc in enumerate(KNOWLEDGE_CORPUS):
                text_to_embed = f"{doc['title']}. {doc['snippet']}"
                vector = embedding_model.encode(text_to_embed).tolist()
                points.append(
                    PointStruct(
                        id=i,
                        vector=vector,
                        payload={
                            "source_collection": doc["source_collection"],
                            "source_id": doc["source_id"],
                            "title": doc["title"],
                            "snippet": doc["snippet"],
                        }
                    )
                )
            if points:
                client.upsert(collection_name=COLLECTION_NAME, points=points)
                print(f"[RAG] Successfully seeded {COLLECTION_NAME} with {len(points)} documents.")

        _is_seeded = True
    except Exception as e:
        print(f"Warning: Failed to seed Qdrant collection: {e}")


# Run initial seed on module load
try:
    ensure_seeded()
except Exception as e:
    print(f"Warning: Startup seeding failed: {e}")


# In-memory cache for live evidence by drug name
_LIVE_EVIDENCE_CACHE = {}


def retrieve_live_evidence_for_drug(drug_name: str) -> List[Dict[str, Any]]:
    """
    Fetches live OpenFDA drug label warnings tied to the extracted drug with caching.
    """
    if not drug_name:
        return []

    clean_drug = drug_name.strip().lower()
    if clean_drug in _LIVE_EVIDENCE_CACHE:
        return _LIVE_EVIDENCE_CACHE[clean_drug]

    evidence = []
    try:
        import urllib.request
        import json
        url = f"https://api.fda.gov/drug/label.json?search=openfda.generic_name:{clean_drug}+OR+openfda.brand_name:{clean_drug}&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "PharmaGuard-PV/1.0"})
        with urllib.request.urlopen(req, timeout=3) as resp:
            data = json.loads(resp.read().decode())
            results = data.get("results", [])
            if results:
                res = results[0]
                warnings = res.get("warnings") or res.get("adverse_reactions") or []
                snippet = warnings[0][:320] if warnings else "FDA prescribing information on record."
                evidence.append({
                    "source_collection": "openfda_labels",
                    "source_id": f"fda-{clean_drug}",
                    "title": f"{drug_name.capitalize()} — FDA Prescribing Information",
                    "snippet": snippet,
                    "similarity_score": 0.88,
                })
    except Exception:
        pass

    _LIVE_EVIDENCE_CACHE[clean_drug] = evidence
    return evidence


# -------------------------------------------------------------
# Hybrid Retrieval: BM25 (Sparse) + Dense + RRF + Re-ranking
# -------------------------------------------------------------

def _tokenize(text: str) -> List[str]:
    return [w.lower() for w in re.findall(r"\b[A-Za-z0-9\-\%]+\b", text)]


def compute_bm25_scores(query: str, corpus: List[Dict[str, Any]], k1: float = 1.5, b: float = 0.75) -> List[float]:
    """
    Computes Okapi BM25 relevance scores across corpus documents.
    """
    query_tokens = _tokenize(query)
    if not query_tokens:
        return [0.0] * len(corpus)

    doc_tokens_list = [_tokenize(f"{d['title']} {d['snippet']} {' '.join(d.get('keywords', []))}") for d in corpus]
    doc_lens = [len(dt) for dt in doc_tokens_list]
    avg_dl = sum(doc_lens) / len(doc_lens) if doc_lens else 1.0
    N = len(corpus)

    # Document frequency for query terms
    df = {}
    for qt in query_tokens:
        df[qt] = sum(1 for dt in doc_tokens_list if qt in dt)

    scores = []
    for dt, dl in zip(doc_tokens_list, doc_lens):
        score = 0.0
        doc_token_counts = {}
        for token in dt:
            doc_token_counts[token] = doc_token_counts.get(token, 0) + 1

        for qt in query_tokens:
            if qt not in df or df[qt] == 0:
                continue
            # IDF = ln( (N - n(qi) + 0.5) / (n(qi) + 0.5) + 1 )
            n_qi = df[qt]
            idf = math.log(((N - n_qi + 0.5) / (n_qi + 0.5)) + 1.0)
            f = doc_token_counts.get(qt, 0)
            if f > 0:
                num = f * (k1 + 1.0)
                den = f + k1 * (1.0 - b + b * (dl / avg_dl))
                score += idf * (num / den)

        scores.append(score)

    return scores


def reciprocal_rank_fusion(dense_ranked_ids: List[str], sparse_ranked_ids: List[str], k: int = 60) -> Dict[str, float]:
    """
    Computes Reciprocal Rank Fusion (RRF) scores:
    RRF(d) = sum(1 / (k + rank_i(d)))
    """
    rrf_scores: Dict[str, float] = {}

    for rank, doc_id in enumerate(dense_ranked_ids):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))

    for rank, doc_id in enumerate(sparse_ranked_ids):
        rrf_scores[doc_id] = rrf_scores.get(doc_id, 0.0) + (1.0 / (k + rank + 1))

    return rrf_scores


def rerank_candidates(candidates: List[Dict[str, Any]], drug_name: str, symptoms: List[str]) -> List[Dict[str, Any]]:
    """
    Clinical domain re-ranker:
    Boosts candidate passages containing exact suspect drug names and specific clinical adverse reactions.
    """
    clean_drug = (drug_name or "").lower().strip()
    clean_symptoms = [s.lower().strip() for s in symptoms if s]

    reranked = []
    for doc in candidates:
        text = f"{doc.get('title', '')} {doc.get('snippet', '')}".lower()
        score = doc.get("similarity_score", 0.5)

        # Exact drug match boost
        if clean_drug and clean_drug in text:
            score += 0.25

        # Symptom overlap boost
        matched_symptoms = sum(1 for sx in clean_symptoms if sx in text)
        if matched_symptoms > 0:
            score += 0.15 * matched_symptoms

        # Source reliability weight: FDA label and guidelines weighted higher than historical cases
        col = doc.get("source_collection", "")
        if "label" in col or "guideline" in col:
            score += 0.05

        doc_copy = dict(doc)
        doc_copy["similarity_score"] = round(min(0.99, max(0.1, score)), 2)
        reranked.append(doc_copy)

    reranked.sort(key=lambda d: d["similarity_score"], reverse=True)
    return reranked


def retrieve(extraction: dict, top_k: int = 5) -> List[Dict[str, Any]]:
    """
    Retrieves supporting clinical literature, FDA labels, and guidelines using
    hybrid dense + sparse BM25 retrieval, RRF rank fusion, and clinical re-ranking.
    """
    ensure_seeded()

    drug_name = extraction.get("drugName") or ""
    symptoms = extraction.get("symptoms") or []

    query_parts = []
    if drug_name:
        query_parts.append(drug_name)
    if symptoms:
        query_parts.extend(symptoms)

    query_text = " ".join(query_parts)
    if not query_text:
        return []

    # 1. Sparse BM25 retrieval over corpus
    bm25_scores = compute_bm25_scores(query_text, KNOWLEDGE_CORPUS)
    sparse_sorted_indices = sorted(range(len(KNOWLEDGE_CORPUS)), key=lambda i: bm25_scores[i], reverse=True)
    sparse_ranked_ids = [KNOWLEDGE_CORPUS[i]["source_id"] for i in sparse_sorted_indices if bm25_scores[i] > 0]

    # 2. Dense semantic retrieval via Qdrant or keyword vector proxy
    dense_ranked_ids = []
    dense_hits_map = {}
    client = get_qdrant_client()

    if client and embedding_model:
        try:
            query_vector = embedding_model.encode(query_text).tolist()
            hits = client.search(collection_name=COLLECTION_NAME, query_vector=query_vector, limit=top_k * 2)
            for hit in hits:
                sid = hit.payload.get("source_id", "")
                dense_ranked_ids.append(sid)
                dense_hits_map[sid] = {
                    "source_collection": hit.payload.get("source_collection", "unknown"),
                    "source_id": sid,
                    "title": hit.payload.get("title", ""),
                    "snippet": hit.payload.get("snippet", ""),
                    "similarity_score": round(hit.score, 2),
                }
        except Exception as e:
            print(f"Dense vector search failed: {e}. Falling back to sparse ranker.")

    # If dense search was unavailable, create dense proxy rank from keyword containment
    if not dense_ranked_ids:
        dense_ranked_ids = [
            doc["source_id"] for doc in KNOWLEDGE_CORPUS
            if any(term.lower() in doc["snippet"].lower() or term.lower() in doc["title"].lower() for term in query_parts)
        ]

    # 3. Reciprocal Rank Fusion
    rrf_scores = reciprocal_rank_fusion(dense_ranked_ids, sparse_ranked_ids, k=60)

    # Build merged candidates pool
    candidates = []
    seen_ids = set()

    for doc in KNOWLEDGE_CORPUS:
        sid = doc["source_id"]
        if sid in rrf_scores and sid not in seen_ids:
            seen_ids.add(sid)
            # Normalize RRF score to 0.40 - 0.90 baseline
            norm_score = min(0.95, 0.45 + rrf_scores[sid] * 15.0)
            candidates.append({
                "source_collection": doc["source_collection"],
                "source_id": sid,
                "title": doc["title"],
                "snippet": doc["snippet"],
                "similarity_score": round(norm_score, 2),
            })

    # Add dense hits not in static corpus if any
    for sid, hit_doc in dense_hits_map.items():
        if sid not in seen_ids:
            seen_ids.add(sid)
            candidates.append(hit_doc)

    # 4. Supplemental live OpenFDA evidence
    live = retrieve_live_evidence_for_drug(drug_name)
    for item in live:
        if item["source_id"] not in seen_ids:
            seen_ids.add(item["source_id"])
            candidates.append(item)

    # 5. Clinical Re-ranking
    final_ranked = rerank_candidates(candidates, drug_name, symptoms)
    return final_ranked[:top_k]
