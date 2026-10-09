import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .schemas import PipelineRequest, PipelineResponse
from .pipeline.deidentify import deidentify
from .pipeline.extract import extract
from .pipeline.classify import classify
from .pipeline.retrieve import retrieve, _get_qdrant_client, _get_embedder
from .pipeline.corpus_seed import ensure_seeded
from .pipeline.summarize import summarize

logger = logging.getLogger(__name__)

app = FastAPI(title="PharmaGuard ML Service", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # tighten before production
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.on_event("startup")
def seed_rag_corpus():
    # Fail open: if Qdrant/embedder aren't ready yet, retrieve() falls back to the baseline
    # retriever per-request until they are, rather than blocking ml-service from starting.
    try:
        ensure_seeded(_get_qdrant_client(), _get_embedder())
    except Exception as exc:
        logger.warning("RAG corpus seeding skipped at startup (%s)", exc)


@app.get("/health")
def health():
    return {"ok": True, "service": "pharmaguard-ml-service"}


@app.post("/pipeline/run", response_model=PipelineResponse)
def run_pipeline(req: PipelineRequest):
    """
    Module 7 — Multi-step LLM chain, orchestrated server-side:
    clean text -> de-identify -> extract -> classify -> retrieve evidence -> summarize.
    Each stage's output is returned so the Node API can persist it independently for audit/debugging.
    """
    deidentified_text, deid_log = deidentify(req.raw_text)
    extraction = extract(deidentified_text)
    classification = classify(extraction, deidentified_text)
    retrievals = retrieve(extraction)
    summary = summarize(extraction, classification, retrievals)

    return PipelineResponse(
        pipeline_run_id=req.pipeline_run_id,
        deidentified_text=deidentified_text,
        deidentification_log=deid_log,
        extraction=extraction,
        classification=classification,
        retrievals=retrievals,
        summary=summary,
    )


# Individual stage endpoints — useful for debugging / re-running one step without the full chain.
@app.post("/pipeline/deidentify")
def deidentify_endpoint(req: PipelineRequest):
    text, log = deidentify(req.raw_text)
    return {"deidentified_text": text, "deidentification_log": log}


@app.post("/pipeline/extract")
def extract_endpoint(req: PipelineRequest):
    return extract(req.raw_text)
