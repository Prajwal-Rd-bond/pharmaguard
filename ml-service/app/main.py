import os
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from .schemas import PipelineRequest, PipelineResponse
from .pipeline.deidentify import deidentify
from .pipeline.extract import extract
from .pipeline.classify import classify
from .pipeline.retrieve import retrieve
from .pipeline.summarize import summarize
from .pipeline.citation_checker import verify_summary_citations
from .pipeline.causality import evaluate_naranjo_causality
from .analytics.signals import detect_signal_for_pair, get_faers_dashboard_overview
from .analytics.knowledge_graph import explore_drug_graph, get_full_graph

app = FastAPI(title="PharmaGuard ML & Pharmacovigilance Intelligence Service", version="0.2.0")

allowed_origins = [
    origin.strip()
    for origin in os.environ.get(
        "CORS_ORIGINS",
        "http://localhost:5000,http://server:5000,http://localhost:5001,http://localhost:5173",
    ).split(",")
]

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"ok": True, "service": "pharmaguard-ml-service", "version": "0.2.0"}


@app.post("/pipeline/run", response_model=PipelineResponse)
def run_pipeline(req: PipelineRequest):
    """
    Module 7 — End-to-end multi-stage clinical intelligence chain:
    De-identification -> Extraction (with MedDRA/RxNorm) -> ICH E2A Classification ->
    Hybrid RAG Retrieval -> Constrained Summary -> Citation Verification -> Causality Assessment.
    """
    deidentified_text, deid_log = deidentify(req.raw_text)
    extraction = extract(deidentified_text)
    classification = classify(extraction)
    retrievals = retrieve(extraction)
    summary = summarize(extraction, classification, retrievals)
    citation_verification = verify_summary_citations(summary, retrievals)
    causality = evaluate_naranjo_causality(extraction, deidentified_text)

    return PipelineResponse(
        pipeline_run_id=req.pipeline_run_id,
        deidentified_text=deidentified_text,
        deidentification_log=deid_log,
        extraction=extraction,
        classification=classification,
        retrievals=retrievals,
        summary=summary,
        citation_verification=citation_verification,
        causality=causality,
    )


# Stage-specific endpoints
@app.post("/pipeline/deidentify")
def deidentify_endpoint(req: PipelineRequest):
    text, log = deidentify(req.raw_text)
    return {"deidentified_text": text, "deidentification_log": log}


@app.post("/pipeline/extract")
def extract_endpoint(req: PipelineRequest):
    return extract(req.raw_text)


@app.post("/pipeline/classify")
def classify_endpoint(req: PipelineRequest):
    ext = extract(req.raw_text)
    return classify(ext)


@app.post("/pipeline/causality")
def causality_endpoint(req: PipelineRequest):
    ext = extract(req.raw_text)
    return evaluate_naranjo_causality(ext, req.raw_text)


# Phase 2C: Disproportionality Signal Detection Endpoints
@app.get("/analytics/signals/overview")
def signals_overview_endpoint():
    """Returns aggregated FAERS disproportionality metrics and dashboard trends."""
    return get_faers_dashboard_overview()


@app.get("/analytics/signals/detect")
def signals_detect_endpoint(
    drug: str = Query(..., description="Target suspect drug generic name"),
    reaction: str = Query(..., description="Target adverse reaction term"),
):
    """Computes PRR, ROR, and Evans criteria for a drug-reaction pair."""
    return detect_signal_for_pair(drug, reaction)


# Phase 2C: Clinical Knowledge Graph Endpoints
@app.get("/analytics/graph/explore")
def graph_explore_endpoint(
    drug: Optional[str] = Query(None, description="Suspect drug to center the graph on"),
):
    """Returns connected subgraph for target drug (Class, Adverse Events, Organs, Risk Factors)."""
    return explore_drug_graph(drug or "amoxicillin")


@app.get("/analytics/graph/full")
def graph_full_endpoint():
    """Returns full topological knowledge graph dataset."""
    return get_full_graph()
