"""
Seed data + live feed integration for Phase 2 RAG collections (PubMed, FDA, WHO).
If live APIs fail, it falls back to a robust set of mock documents.
"""

import logging
import requests

from qdrant_client.http import models as qmodels

logger = logging.getLogger(__name__)

SEEDED_COLLECTIONS = ("drug_labels", "historical_cases", "clinical_guidelines", "research_papers", "fda_alerts", "who_alerts")

# Extended mock corpus for Phase 2 fallbacks
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
    {
        "source_collection": "fda_alerts",
        "source_id": "fda-alert-2023-01",
        "title": "FDA Drug Safety Communication: Risk of severe adverse events",
        "snippet": "The FDA is warning that certain medications can cause rare but severe allergic reactions including Stevens-Johnson syndrome.",
    },
    {
        "source_collection": "research_papers",
        "source_id": "pmid-12345678",
        "title": "Adverse Drug Reactions: A systematic review",
        "snippet": "This paper analyzes common ADRs across multiple drug classes, highlighting the prevalence of hepatotoxicity and nephrotoxicity.",
    },
    {
        "source_collection": "who_alerts",
        "source_id": "who-alert-2023",
        "title": "WHO Medical Product Alert",
        "snippet": "Alert concerning contaminated batches of cough syrups causing acute kidney injury in pediatric patients.",
    },
]

def fetch_live_pubmed_feeds() -> list:
    """Fetch recent papers on ADRs from PubMed."""
    docs = []
    try:
        search_res = requests.get(
            "https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esearch.fcgi?db=pubmed&term=adverse+drug+reaction&retmode=json&retmax=5",
            timeout=5
        )
        search_res.raise_for_status()
        pmids = search_res.json().get("esearchresult", {}).get("idlist", [])
        
        if pmids:
            fetch_res = requests.get(
                f"https://eutils.ncbi.nlm.nih.gov/entrez/eutils/esummary.fcgi?db=pubmed&id={','.join(pmids)}&retmode=json",
                timeout=5
            )
            fetch_res.raise_for_status()
            data = fetch_res.json().get("result", {})
            for pmid in pmids:
                if pmid in data:
                    title = data[pmid].get("title", "")
                    docs.append({
                        "source_collection": "research_papers",
                        "source_id": f"pmid-{pmid}",
                        "title": f"PubMed: {title}",
                        "snippet": f"Recent research article regarding adverse drug reactions.",
                    })
    except Exception as exc:
        logger.warning("Failed to fetch live PubMed feeds: %s", exc)
    return docs

def fetch_live_fda_feeds() -> list:
    """Fetch recent FDA label data using OpenFDA."""
    docs = []
    try:
        res = requests.get(
            "https://api.fda.gov/drug/label.json?search=adverse_reactions:*&limit=5",
            timeout=5
        )
        res.raise_for_status()
        for i, item in enumerate(res.json().get("results", [])):
            brand_name = item.get("openfda", {}).get("brand_name", ["Unknown Drug"])[0]
            warnings = item.get("warnings_and_cautions", ["No warnings available."])[0][:200]
            docs.append({
                "source_collection": "fda_alerts",
                "source_id": f"fda-label-{item.get('id', i)}",
                "title": f"OpenFDA Label: {brand_name}",
                "snippet": f"{warnings}...",
            })
    except Exception as exc:
        logger.warning("Failed to fetch live FDA feeds: %s", exc)
    return docs

def ensure_seeded(client, embedder) -> None:
    """Create collections and seed them with live feeds or fallbacks."""
    vector_size = embedder.get_sentence_embedding_dimension()

    # Combine mock docs with live feeds
    live_docs = fetch_live_pubmed_feeds() + fetch_live_fda_feeds()
    all_docs = SEED_DOCS + live_docs

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

        docs = [d for d in all_docs if d["source_collection"] == collection]
        if not docs:
            continue

        vectors = embedder.encode([f"{d['title']}. {d['snippet']}" for d in docs])
        client.upsert(
            collection_name=collection,
            points=[
                qmodels.PointStruct(
                    id=i, # Use simple integer IDs
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
