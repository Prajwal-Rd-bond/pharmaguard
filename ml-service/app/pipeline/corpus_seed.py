"""
Seed data + live feed integration for Phase 2 RAG collections (PubMed, FDA, WHO).
Collections are checked FIRST before triggering any network fetches.
Provides targeted, drug-specific live PubMed and OpenFDA query capabilities.
"""

import logging
import urllib.parse
from typing import List, Dict, Any, Optional

import requests
from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

SEEDED_COLLECTIONS = (
    "drug_labels",
    "historical_cases",
    "clinical_guidelines",
    "research_papers",
    "fda_alerts",
    "who_alerts",
)

# Reference baseline corpus for offline/fallback seeding
SEED_DOCS = [
    {
        "source_collection": "drug_labels",
        "source_id": "label-amoxicillin-001",
        "title": "Amoxicillin — FDA Package Insert, Adverse Reactions",
        "snippet": "Hypersensitivity reactions including serious cutaneous adverse reactions, rash, urticaria, serum sickness, and rarely fatal anaphylaxis have been reported following penicillin administration.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-ibuprofen-001",
        "title": "Ibuprofen — FDA Drug Safety Label",
        "snippet": "NSAIDs cause an increased risk of serious gastrointestinal adverse events including bleeding, ulceration, and perforation of the stomach or intestines. Severe hypersensitivity and bronchospasm may occur.",
    },
    {
        "source_collection": "drug_labels",
        "source_id": "label-warfarin-001",
        "title": "Warfarin Sodium — FDA Boxed Warning",
        "snippet": "Warfarin can cause major or fatal bleeding. Perform regular monitoring of INR in all treated patients. Necrosis or gangrene of skin and other tissues is a rare but severe risk.",
    },
    {
        "source_collection": "historical_cases",
        "source_id": "case-0142",
        "title": "Historical Pharmacovigilance Case #0142 (Amoxicillin Rash)",
        "snippet": "Patient developed generalized maculopapular hives and facial edema within 90 minutes of oral amoxicillin intake. Discontinuation and intramuscular antihistamine led to resolution.",
    },
    {
        "source_collection": "historical_cases",
        "source_id": "case-0891",
        "title": "Historical Pharmacovigilance Case #0891 (NSAID GI Bleed)",
        "snippet": "Elderly patient presenting with acute epigastric pain and melena following two weeks of daily ibuprofen 800mg therapy without gastroprotection. Confirmed gastric ulcer on endoscopy.",
    },
    {
        "source_collection": "clinical_guidelines",
        "source_id": "guideline-anaphylaxis-mgmt",
        "title": "WHO / WAO Guideline — Emergency Management of Acute Anaphylaxis",
        "snippet": "Intramuscular epinephrine (adrenaline) into the mid-anterolateral thigh is the first-line medication of choice for anaphylaxis. Supplemental oxygen, airway positioning, and IV fluid resuscitation are essential.",
    },
    {
        "source_collection": "clinical_guidelines",
        "source_id": "guideline-scar-management",
        "title": "Clinical Practice Guideline: Severe Cutaneous Adverse Reactions (SCAR)",
        "snippet": "Early recognition and prompt withdrawal of the offending causative medication is the most critical prognostic factor in Stevens-Johnson syndrome (SJS) and Toxic Epidermal Necrolysis (TEN).",
    },
    {
        "source_collection": "fda_alerts",
        "source_id": "fda-alert-amoxicillin-clav",
        "title": "FDA Safety Alert: Hepatotoxicity and Cholestatic Jaundice",
        "snippet": "Hepatic dysfunction, including jaundice and cholestasis, has been associated with the use of amoxicillin and clavulanate potassium, particularly in male and elderly patients.",
    },
    {
        "source_collection": "fda_alerts",
        "source_id": "fda-alert-nsaid-cardio",
        "title": "FDA Drug Safety Communication: Cardiovascular Risk of Prescription NSAIDs",
        "snippet": "The FDA requires updated warnings on prescription NSAIDs stating that they increase the risk of heart attack or stroke, which can lead to death. The risk may occur early in treatment.",
    },
    {
        "source_collection": "research_papers",
        "source_id": "pmid-31894567",
        "title": "Lancet: Epidemiology and Mechanisms of Immediate Drug Hypersensitivity",
        "snippet": "IgE-mediated beta-lactam allergy manifestations range from mild urticaria to severe respiratory compromise and cardiovascular collapse within 1 to 2 hours of administration.",
    },
    {
        "source_collection": "who_alerts",
        "source_id": "who-alert-2023-diethylene",
        "title": "WHO Medical Product Alert: Diethylene Glycol Contamination",
        "snippet": "Alert regarding sub-standard and contaminated pediatric oral liquid formulations containing toxic amounts of diethylene glycol and ethylene glycol resulting in acute kidney injury.",
    },
]


def fetch_pubmed_for_query(drug_name: str, symptoms: Optional[List[str]] = None, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Dynamically queries PubMed for the specific drug and adverse reactions,
    fetching actual peer-reviewed titles and abstract summaries.
    """
    if not drug_name:
        return []

    docs = []
    try:
        symptom_term = f" AND ({' OR '.join(symptoms[:2])})" if symptoms else ""
        query = f"{drug_name}[Title/Abstract] AND (adverse reaction OR adverse effect OR drug toxicity){symptom_term}"
        encoded_query = urllib.parse.quote(query)

        search_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term={encoded_query}&retmode=json&retmax={limit}"
        search_res = requests.get(search_url, timeout=4)
        search_res.raise_for_status()

        id_list = search_res.json().get("esearchresult", {}).get("idlist", [])
        if not id_list:
            return []

        ids_param = ",".join(id_list)
        sum_url = f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={ids_param}&retmode=json"
        sum_res = requests.get(sum_url, timeout=4)
        sum_res.raise_for_status()

        results = sum_res.json().get("result", {})
        for pmid in id_list:
            item = results.get(pmid)
            if not item:
                continue
            title = item.get("title", f"PubMed Study on {drug_name}")
            source = item.get("source", "Medical Journal")
            pubdate = item.get("pubdate", "")
            snippet = f"Clinical study in {source} ({pubdate}) investigating {drug_name} safety profile: {title}"

            docs.append({
                "source_collection": "research_papers",
                "source_id": f"pmid-{pmid}",
                "title": f"PubMed [{source}]: {title}",
                "snippet": snippet,
                "retrieval_mode": "pubmed_live",
            })
    except Exception as exc:
        logger.warning("Dynamic PubMed fetch for '%s' failed: %s", drug_name, exc)

    return docs


def fetch_fda_for_query(drug_name: str, limit: int = 3) -> List[Dict[str, Any]]:
    """
    Dynamically queries OpenFDA label API for the specific drug's adverse reactions and boxed warnings.
    """
    if not drug_name:
        return []

    docs = []
    try:
        clean_drug = drug_name.replace('"', '').strip()
        url = f'https://api.fda.gov/drug/label.json?search=openfda.brand_name:"{clean_drug}"+openfda.generic_name:"{clean_drug}"&limit={limit}'
        res = requests.get(url, timeout=4)
        res.raise_for_status()

        results = res.json().get("results", [])
        for i, item in enumerate(results):
            brand = (item.get("openfda", {}).get("brand_name") or [drug_name])[0]
            warnings = item.get("warnings_and_cautions") or item.get("boxed_warning") or item.get("adverse_reactions")
            snippet_text = warnings[0][:300] if warnings else "Official FDA safety documentation available."

            docs.append({
                "source_collection": "drug_labels",
                "source_id": f"openfda-{item.get('id', i)}",
                "title": f"OpenFDA Label Warning: {brand}",
                "snippet": snippet_text,
                "retrieval_mode": "openfda_live",
            })
    except Exception as exc:
        logger.warning("Dynamic OpenFDA fetch for '%s' failed: %s", drug_name, exc)

    return docs


def ensure_seeded(client, embedder) -> None:
    """
    Idempotent Qdrant seeding: Checks if collections are ALREADY seeded FIRST.
    If all collections exist and contain points, returns immediately without making network calls.
    """
    vector_size = embedder.get_sentence_embedding_dimension()

    unseeded = []
    for collection in SEEDED_COLLECTIONS:
        if not client.collection_exists(collection):
            client.create_collection(
                collection_name=collection,
                vectors_config=qmodels.VectorParams(size=vector_size, distance=qmodels.Distance.COSINE),
            )
            logger.info("Created Qdrant collection: %s", collection)
            unseeded.append(collection)
        else:
            count = client.count(collection_name=collection, exact=True).count
            if count == 0:
                unseeded.append(collection)

    # Fast path: all collections already exist and have data
    if not unseeded:
        logger.debug("All Qdrant collections already populated (%s)", ", ".join(SEEDED_COLLECTIONS))
        return

    logger.info("Seeding empty Qdrant collections: %s", ", ".join(unseeded))

    for collection in unseeded:
        docs = [d for d in SEED_DOCS if d["source_collection"] == collection]
        if not docs:
            continue

        vectors = embedder.encode([f"{d['title']}. {d['snippet']}" for d in docs])
        client.upsert(
            collection_name=collection,
            points=[
                qmodels.PointStruct(
                    id=i + 1,
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
        logger.info("Seeded %d documents into %s", len(docs), collection)

