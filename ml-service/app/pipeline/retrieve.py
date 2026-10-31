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
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

class TrustedEvidenceRecord(dict):
    """
    Internal provenance marker (dict subclass) designating evidence records retrieved
    from internal retrieval / regulatory label sources.
    JSON deserialization of client HTTP requests or LLM response parsing produces
    standard dict instances rather than TrustedEvidenceRecord.
    Inherits from dict, enabling native JSON serialization without custom encoders.
    """
    pass


_QUERY_ALLOWED_RE = re.compile(r"^[A-Za-z0-9 '\-]+$")


class RetrievalList(list):
    """Subclass of list preserving list semantics while exposing typed evidence_status and rejected_records."""
    def __init__(
        self,
        items: List[Dict[str, Any]],
        evidence_status: str = "ok",
        rejected_records: Optional[List[Dict[str, str]]] = None,
    ):
        super().__init__(items)
        self.evidence_status = evidence_status
        self.rejected_records: List[Dict[str, str]] = list(rejected_records) if rejected_records else []


def sanitize_and_mark_trusted_evidence(
    records: List[Dict[str, Any]],
    *,
    base_status: str = "ok",
    static_ids: Optional[set] = None,
) -> RetrievalList:
    """
    Applies the trusted-evidence identifier check (phone, email, SSN, MRN, date, address)
    without the title-name heuristic (NAME_TITLE_RE).
    Contaminated-record policy:
    - When a trusted record fails the identifier check, drop ONLY that record.
    - Add {"source_id": ..., "reason": "pii_rejected"} to rejected_records.
    - Set evidence_status to "partial_pii_rejected" when other records remain,
      or "pii_rejected" when none remain.
    - Never log or return the rejected text.
    """
    from ..privacy import _has_trusted_evidence_identifier_phi

    if static_ids is None:
        static_ids = {d["source_id"] for d in KNOWLEDGE_CORPUS}

    clean_records: List[Dict[str, Any]] = []
    rejected_records: List[Dict[str, str]] = []

    for doc in records:
        if not isinstance(doc, dict):
            continue
        sid = str(doc.get("source_id") or doc.get("evidence_id") or "unknown")
        title_text = str(doc.get("title") or "")
        snippet_text = str(doc.get("snippet") or "")
        if _has_trusted_evidence_identifier_phi(title_text) or _has_trusted_evidence_identifier_phi(snippet_text):
            rejected_records.append({"source_id": sid, "reason": "pii_rejected"})
            logger.warning("Trusted evidence record rejected due to identifier check (source_id=%s).", sid)
            continue
        clean_records.append(doc)

    trusted_out: List[Dict[str, Any]] = []
    for idx, doc in enumerate(clean_records, start=1):
        doc_copy = dict(doc)
        if not doc_copy.get("evidence_id"):
            doc_copy["evidence_id"] = f"E{idx}"
        origin = doc_copy.get("corpus_origin") or (
            "builtin_demo_corpus" if doc_copy.get("source_id") in static_ids else "external_or_vector"
        )
        doc_copy["corpus_origin"] = origin
        rec = TrustedEvidenceRecord(doc_copy)
        rec.corpus_origin = origin
        trusted_out.append(rec)

    if rejected_records:
        final_status = "partial_pii_rejected" if trusted_out else "pii_rejected"
    else:
        final_status = base_status

    return RetrievalList(trusted_out, evidence_status=final_status, rejected_records=rejected_records)


_DOSAGE_TOKEN_RE = re.compile(r"^\d+(?:\.\d+)?(?:-?(?:mg|mcg|ug|g|ml|iu|units?))?$", re.IGNORECASE)
_CLINICAL_DESCRIPTOR_TOKENS = {
    "oral", "tablet", "tablets", "capsule", "capsules", "sodium", "potassium",
    "hydrochloride", "hcl", "sulfate", "acetate", "tartrate", "succinate",
    "extended-release", "er", "xr", "sr", "iv", "injection", "solution",
    "disease", "syndrome",
}


def validate_openfda_query_term(term: Any) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Validates drug query term for OpenFDA retrieval.
    Note: Live OpenFDA lookup (`ENABLE_LIVE_OPENFDA=true`) is strictly for drug names only.
    Policy:
    - Allowed characters: letters, digits, spaces, hyphen, apostrophe.
    - Maximum length: 64 characters after trimming.
    - Reject empty or whitespace-only terms.
    - Reject terms containing any other characters, including &, +, =, /, quotation marks, newlines, parentheses.
    - Reject terms that trigger the residual-PII tripwire.
    - Reject anything that looks like a person name (e.g., 'John Smith', 'Dr. Jane Doe', spaCy PERSON entities)
      or raw clinical narrative sentences (> 4 words).
    - Reject invalid terms; do not silently rewrite them.
    Returns: (is_valid, clean_trimmed_term, error_status)
    """
    if not isinstance(term, str):
        return False, None, "invalid_term"
    trimmed = term.strip()
    if not trimmed:
        return False, None, "invalid_term"
    if len(trimmed) > 64:
        return False, None, "term_too_long"
    if not _QUERY_ALLOWED_RE.match(trimmed):
        return False, None, "invalid_characters"
    disallowed = {'"', '&', '+', '=', '/', '\n', '\r', '(', ')'}
    if any(ch in trimmed for ch in disallowed):
        return False, None, 'invalid_characters'
    try:
        from ..privacy import _assert_no_residual_regex_phi
        _assert_no_residual_regex_phi(trimmed)
    except Exception:
        return False, None, "pii_rejected"

    words = trimmed.split()
    if len(words) > 4:
        return False, None, "invalid_term"

    # Reject person names / non-drug multi-word phrases
    from .deidentify import is_protected_clinical_term, get_spacy_model, _CLINICAL_PHRASE_AT_SPAN_RE
    from .extract import KNOWN_DRUGS

    lower_trimmed = trimmed.lower()
    known_drug_set = set(KNOWN_DRUGS)
    is_known_or_protected = (
        lower_trimmed in known_drug_set
        or is_protected_clinical_term(lower_trimmed)
        or bool(_CLINICAL_PHRASE_AT_SPAN_RE.match(trimmed))
        or all(
            w.lower() in known_drug_set
            or is_protected_clinical_term(w.lower())
            or w.lower() in _CLINICAL_DESCRIPTOR_TOKENS
            or bool(_DOSAGE_TOKEN_RE.match(w))
            for w in words
        )
    )

    if not is_known_or_protected:
        # Multi-word phrase with capitalized words (e.g. 'John Smith', 'Alice Wonderland') or
        # untitled two-word lowercase name ('john smith') that is not a drug term -> reject as pii_rejected
        if len(words) >= 2:
            return False, None, "pii_rejected"
        # Single-word capitalized proper noun that is not a known/protected drug (e.g. 'John', 'Smith')
        if len(words) == 1 and words[0][0].isupper() and not words[0].isupper():
            nlp = get_spacy_model()
            if nlp is not None:
                doc = nlp(trimmed)
                if any(ent.label_ == "PERSON" for ent in doc.ents):
                    return False, None, "pii_rejected"

    return True, trimmed, None

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

# Built-in static demo/reference corpus (used for offline demo/regression when ALLOW_BUILTIN_REFERENCE_CORPUS=true;
# NOT a live FDA regulatory label feed. Set ALLOW_BUILTIN_REFERENCE_CORPUS=false in strict regulatory production
# to require verified Qdrant / live OpenFDA evidence only).
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

try:
    from .corpus_seed import SEED_DOCS
except Exception as e:
    SEED_DOCS = []

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

        try:
            from ..config import get_settings
            allow_seed = getattr(get_settings(), "allow_builtin_reference_corpus", False)
        except Exception:
            allow_seed = os.environ.get("ALLOW_BUILTIN_REFERENCE_CORPUS", "").strip().lower() in ("1", "true", "yes", "on")

        if not allow_seed:
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


def retrieve_live_evidence_for_drug(drug_name: str, settings: Optional[Any] = None) -> RetrievalList:
    """
    Fetches live OpenFDA drug label warnings tied to the extracted drug with caching.
    Governed by ENABLE_LIVE_OPENFDA (default: false).
    """
    if settings is None:
        try:
            from ..config import get_settings
            settings = get_settings()
        except Exception:
            settings = None

    if settings is None or not getattr(settings, "enable_live_openfda", False):
        return RetrievalList([], evidence_status="live_disabled")

    is_valid, clean_drug, err_status = validate_openfda_query_term(drug_name)
    if not is_valid:
        return RetrievalList([], evidence_status=err_status or "invalid_term")

    cache_key = clean_drug.lower()
    if cache_key in _LIVE_EVIDENCE_CACHE:
        cached = _LIVE_EVIDENCE_CACHE[cache_key]
        return RetrievalList(cached, evidence_status="ok" if cached else "none_found")

    evidence = []
    status = "ok"
    try:
        import urllib.request
        import urllib.parse
        import json
        quoted = urllib.parse.quote(clean_drug)
        base_url = getattr(settings, "openfda_base_url", "https://api.fda.gov")
        url = f"{base_url}/drug/label.json?search=openfda.generic_name:{quoted}+OR+openfda.brand_name:{quoted}&limit=1"
        req = urllib.request.Request(url, headers={"User-Agent": "PharmaGuard-PV/1.0"})
        timeout_s = min(float(getattr(settings, "http_timeout_s", 20.0)), 5.0)
        with urllib.request.urlopen(req, timeout=timeout_s) as resp:
            try:
                raw_bytes = resp.read()
                data = json.loads(raw_bytes.decode())
            except Exception as parse_exc:
                logger.warning("Live OpenFDA response malformed (error_type=%s).", type(parse_exc).__name__)
                status = "malformed_response"
                data = None
            if data is not None:
                if not isinstance(data, dict) or "results" not in data:
                    status = "malformed_response"
                else:
                    results = data.get("results", [])
                    if results and isinstance(results, list):
                        res = results[0]
                        warnings = res.get("warnings") or res.get("adverse_reactions") or []
                        snippet = warnings[0][:320] if warnings else "FDA prescribing information on record."
                        evidence.append({
                            "source_collection": "openfda_labels",
                            "source_id": f"fda-{cache_key}",
                            "title": f"{clean_drug.capitalize()} — FDA Prescribing Information",
                            "snippet": snippet,
                            "similarity_score": 0.88,
                        })
                        status = "ok"
                    else:
                        status = "none_found"
    except Exception as exc:
        if "NETWORK ISOLATION VIOLATION" in str(exc):
            raise
        err_str = str(exc).lower()
        if isinstance(exc, (TimeoutError, urllib.error.URLError)) and ("timed out" in err_str or "timeout" in err_str):
            logger.warning("Live OpenFDA retrieval timed out (error_type=%s).", type(exc).__name__)
            status = "live_timeout"
        else:
            logger.warning("Live OpenFDA retrieval failed (error_type=%s).", type(exc).__name__)
            status = "provider_error"

    if status in ("ok", "none_found"):
        _LIVE_EVIDENCE_CACHE[cache_key] = evidence
    return RetrievalList(evidence, evidence_status=status)


_ORIGINAL_RETRIEVE_LIVE_EVIDENCE_FOR_DRUG = retrieve_live_evidence_for_drug


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


def retrieve(extraction: dict, top_k: int = 5, settings: Optional[Any] = None) -> RetrievalList:
    """
    Retrieves supporting clinical literature, FDA labels, and guidelines using
    hybrid dense + sparse BM25 retrieval, RRF rank fusion, and clinical re-ranking.
    Assigns evidence_id exactly once (E1..En) and marks records with trusted provenance.
    """
    if settings is None:
        try:
            from ..config import get_settings
            settings = get_settings()
        except Exception:
            settings = None

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
        return RetrievalList(
            [],
            evidence_status="live_disabled" if (settings is None or not getattr(settings, "enable_live_openfda", False)) else "none_found"
        )

    allow_builtin_corpus = (
        getattr(settings, "allow_builtin_reference_corpus", False)
        if settings is not None
        else (
            os.environ.get("ALLOW_BUILTIN_REFERENCE_CORPUS", "").strip().lower() in ("1", "true", "yes", "on")
        )
    )
    active_static_corpus = KNOWLEDGE_CORPUS if allow_builtin_corpus else []

    # 1. Sparse BM25 retrieval over corpus
    bm25_scores = compute_bm25_scores(query_text, active_static_corpus) if active_static_corpus else []
    sparse_sorted_indices = sorted(range(len(active_static_corpus)), key=lambda i: bm25_scores[i], reverse=True)
    sparse_ranked_ids = [active_static_corpus[i]["source_id"] for i in sparse_sorted_indices if bm25_scores[i] > 0]

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
            logger.warning("Dense vector search failed: %s. Falling back to sparse ranker.", type(e).__name__)

    # If dense search was unavailable, create dense proxy rank from keyword containment
    if not dense_ranked_ids and active_static_corpus:
        dense_ranked_ids = [
            doc["source_id"] for doc in active_static_corpus
            if any(term.lower() in doc["snippet"].lower() or term.lower() in doc["title"].lower() for term in query_parts)
        ]

    # 3. Reciprocal Rank Fusion
    rrf_scores = reciprocal_rank_fusion(dense_ranked_ids, sparse_ranked_ids, k=60)

    # Build merged candidates pool
    candidates = []
    seen_ids = set()

    for doc in active_static_corpus:
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

    # 4. Supplemental live OpenFDA evidence (governed by ENABLE_LIVE_OPENFDA)
    live_status = "live_disabled"
    if settings is not None and getattr(settings, "enable_live_openfda", False):
        live_res = retrieve_live_evidence_for_drug(drug_name, settings=settings)
        live_status = getattr(live_res, "evidence_status", "ok")
        for item in live_res:
            if item["source_id"] not in seen_ids:
                seen_ids.add(item["source_id"])
                candidates.append(item)

    # 5. Clinical Re-ranking
    final_ranked = rerank_candidates(candidates, drug_name, symptoms)
    top_candidates = final_ranked[:top_k]

    # Status determination (before contaminated-record filtering):
    if settings is None or not getattr(settings, "enable_live_openfda", False):
        base_status = "live_disabled"
    elif live_status in ("provider_error", "live_timeout", "malformed_response"):
        base_status = live_status
    elif live_status in ("invalid_term", "invalid_characters", "term_too_long", "pii_rejected", "partial_pii_rejected"):
        base_status = live_status
    elif live_status not in ("ok", "none_found", "live_disabled"):
        # Unknown status values must never fall through to none_found
        base_status = live_status
    elif top_candidates:
        base_status = "ok"
    else:
        base_status = "none_found"

    static_ids = {d["source_id"] for d in KNOWLEDGE_CORPUS}
    return sanitize_and_mark_trusted_evidence(
        top_candidates,
        base_status=base_status,
        static_ids=static_ids,
    )
