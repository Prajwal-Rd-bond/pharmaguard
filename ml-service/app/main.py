import asyncio
import concurrent.futures
import logging
import os
from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from typing import Optional

from . import config
from .errors import ConfigError, DeidentificationError
from .privacy import _deid_policy, get_spacy_model as _priv_get_spacy_model
from .schemas import EvidenceMetadata, PipelineRequest, PipelineResponse, RejectedEvidenceRecord
from .pipeline.assess import run_causality_assessment
from .pipeline.deidentify import deidentify, get_spacy_model as _deid_get_spacy_model
from .pipeline.extract import extract
from .pipeline.classify import classify, evaluate_expedited_regulatory_clock
from .pipeline.normalize import normalize_drug
from .pipeline.retrieve import TrustedEvidenceRecord, retrieve, sanitize_and_mark_trusted_evidence
from .pipeline.summarize import summarize
from .pipeline.citation_checker import verify_summary_citations
from .pipeline.causality import evaluate_naranjo_causality
from .analytics.signals import detect_signal_for_pair, get_faers_dashboard_overview
from .analytics.knowledge_graph import explore_drug_graph, get_full_graph

logger = logging.getLogger(__name__)


def _run_coro_sync(coro):
    """Runs an async coroutine from a synchronous FastAPI threadpool route handler."""
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    with concurrent.futures.ThreadPoolExecutor(max_workers=1) as pool:
        return pool.submit(asyncio.run, coro).result()


def _get_active_settings():
    """Returns current Settings, or None if configuration is invalid."""
    try:
        return config.get_settings()
    except ConfigError as exc:
        logger.warning("Settings load failed in pipeline (error_type=%s).", type(exc).__name__)
        return None


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
    require_ner, model_name = _deid_policy()
    if require_ner and (_deid_get_spacy_model(model_name) is None or _priv_get_spacy_model(model_name) is None):
        raise HTTPException(
            status_code=503,
            detail="De-identification NER model is unavailable. Service is configured to require NER (DEID_REQUIRE_NER=true).",
        )
    deid_failed = False
    try:
        deidentified_text, deid_log = deidentify(req.raw_text)
    except Exception:
        deid_failed = True
    if deid_failed:
        raise HTTPException(status_code=500, detail=DeidentificationError.public_message)

    extract_privacy_blocked = False
    try:
        extraction = extract(deidentified_text)
    except DeidentificationError:
        extract_privacy_blocked = True
    if extract_privacy_blocked:
        raise HTTPException(status_code=500, detail=DeidentificationError.public_message)

    classification = classify(
        extraction,
        unexpected=getattr(req, "unexpected", None),
        reasonably_related=getattr(req, "reasonably_related", None),
        receipt_date=getattr(req, "receipt_date", None),
    )
    expedited_eval = evaluate_expedited_regulatory_clock(
        is_serious=bool(classification.get("is_serious")),
        criteria=classification.get("ich_e2a_criteria") or [],
        unexpected=getattr(req, "unexpected", None),
        reasonably_related=getattr(req, "reasonably_related", None),
        receipt_date=getattr(req, "receipt_date", None),
    )
    if bool(classification.get("is_serious")) and getattr(req, "unexpected", None) is True and getattr(req, "reasonably_related", None) is True:
        classification["expedited_clock_label"] = expedited_eval["label"]
        classification["periodic_clock_days"] = None
    else:
        classification["expedited_clock_label"] = "none"
        classification["periodic_clock_days"] = 90
    settings = _get_active_settings()
    retrievals = retrieve(extraction, settings=settings)

    # If a mocked or external retrieval list contains trusted records that have not yet run through
    # sanitize_and_mark_trusted_evidence, apply the contaminated-record policy before downstream stages.
    raw_status = getattr(retrievals, "evidence_status", None)
    raw_rejected = list(getattr(retrievals, "rejected_records", []) or [])
    if isinstance(retrievals, list) and any(isinstance(r, TrustedEvidenceRecord) for r in retrievals) and not raw_rejected:
        base_st = raw_status or ("live_disabled" if (settings is None or not getattr(settings, "enable_live_openfda", False)) else ("ok" if len(retrievals) > 0 else "none_found"))
        retrievals = sanitize_and_mark_trusted_evidence(retrievals, base_status=base_st)
        raw_status = getattr(retrievals, "evidence_status", base_st)
        raw_rejected = list(getattr(retrievals, "rejected_records", []) or [])

    summarize_privacy_blocked = False
    try:
        summary = summarize(extraction, classification, retrievals)
    except DeidentificationError:
        summarize_privacy_blocked = True
    if summarize_privacy_blocked:
        raise HTTPException(status_code=500, detail=DeidentificationError.public_message)

    citation_verification = verify_summary_citations(summary, retrievals)
    causality = evaluate_naranjo_causality(extraction, deidentified_text)

    # Populate retrievals[].evidence_id as E1..En and corpus_origin if missing
    for idx, r in enumerate(retrievals, start=1):
        if not r.get("evidence_id"):
            r["evidence_id"] = f"E{idx}"
        if not r.get("corpus_origin"):
            r["corpus_origin"] = getattr(r, "corpus_origin", None) or (
                "builtin_demo_corpus" if r.get("source_collection") == "drug_labels" else "external_or_vector"
            )

    if raw_status is not None:
        evidence_status = raw_status
    elif settings is None or not getattr(settings, "enable_live_openfda", False):
        evidence_status = "live_disabled"
    else:
        evidence_status = "ok" if len(retrievals) > 0 else "none_found"
    rejected_records = [RejectedEvidenceRecord(**rec) for rec in raw_rejected]

    normalized_drug = None
    assessment = None
    assessment_status = None
    assessment_error = None

    if settings is None or not settings.llm_configured:
        assessment_status = "disabled" if (settings is not None and settings.llm_provider == "disabled") else "unconfigured"
    else:
        primary_drug = (
            extraction.get("drugName")
            or extraction.get("genericName")
            or ""
        )
        normalized_drug = _run_coro_sync(
            normalize_drug(primary_drug, settings=settings, allow_network=False)
        )
        assess_privacy_blocked = False
        assess_error_type = None
        try:
            assessment = _run_coro_sync(
                run_causality_assessment(
                    deidentified_text=deidentified_text,
                    extraction=extraction,
                    retrievals=retrievals,
                    settings=settings,
                )
            )
            assessment_status = "completed" if assessment else "failed"
            if isinstance(assessment, dict):
                assess_ev_status = assessment.get("evidence_status")
                assess_rejected = assessment.get("rejected_records") or []
                if assess_rejected and not rejected_records:
                    rejected_records = [RejectedEvidenceRecord(**rec) for rec in assess_rejected]
                if assess_ev_status in ("partial_pii_rejected", "pii_rejected"):
                    evidence_status = assess_ev_status
        except DeidentificationError:
            assess_privacy_blocked = True
        except Exception as exc:
            assess_error_type = type(exc).__name__
            assessment = None
            assessment_status = "failed"
            assessment_error = assess_error_type
        if assess_privacy_blocked:
            raise HTTPException(status_code=500, detail=DeidentificationError.public_message)
        if assess_error_type is not None:
            logger.warning(
                "Causality assessment failed in pipeline (error_type=%s).",
                assess_error_type,
            )

    evidence_metadata = EvidenceMetadata(
        evidence_status=evidence_status,
        rejected_records=rejected_records,
    )

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
        normalized_drug=normalized_drug,
        assessment=assessment,
        evidence_status=evidence_status,
        rejected_records=rejected_records,
        evidence_metadata=evidence_metadata,
        assessment_status=assessment_status,
        assessment_error=assessment_error,
    )


# Stage-specific endpoints
@app.post("/pipeline/deidentify")
def deidentify_endpoint(req: PipelineRequest):
    require_ner, model_name = _deid_policy()
    if require_ner and (_deid_get_spacy_model(model_name) is None or _priv_get_spacy_model(model_name) is None):
        raise HTTPException(
            status_code=503,
            detail="De-identification NER model is unavailable. Service is configured to require NER (DEID_REQUIRE_NER=true).",
        )
    error_type = None
    try:
        text, log = deidentify(req.raw_text)
        return {"deidentified_text": text, "deidentification_log": log}
    except Exception as exc:
        error_type = type(exc).__name__
    logger.error("De-identification endpoint failed (error_type=%s).", error_type)
    raise HTTPException(status_code=500, detail="De-identification failed.")


@app.post("/pipeline/extract")
def extract_endpoint(req: PipelineRequest):
    # Privacy failures return only the generic DeidentificationError message. The HTTPException
    # is raised outside the except block so no original exception is chained or logged.
    deid_failed = False
    try:
        deidentified_text, _ = deidentify(req.raw_text)
    except Exception:
        deid_failed = True
    if deid_failed:
        raise HTTPException(status_code=500, detail=DeidentificationError.public_message)

    privacy_blocked = False
    error_type = None
    try:
        return extract(deidentified_text)
    except DeidentificationError:
        privacy_blocked = True
    except Exception as exc:
        error_type = type(exc).__name__
    if privacy_blocked:
        raise HTTPException(status_code=500, detail=DeidentificationError.public_message)
    logger.error("Extraction endpoint failed (error_type=%s).", error_type)
    raise HTTPException(status_code=500, detail="Extraction failed.")


@app.post("/pipeline/classify")
def classify_endpoint(req: PipelineRequest):
    error_type = None
    try:
        deidentified_text, _ = deidentify(req.raw_text)
        ext = extract(deidentified_text)
        return classify(ext)
    except Exception as exc:
        error_type = type(exc).__name__
    logger.error("Classification endpoint failed (error_type=%s).", error_type)
    raise HTTPException(status_code=500, detail="Classification failed.")


@app.post("/pipeline/causality")
def causality_endpoint(req: PipelineRequest):
    error_type = None
    try:
        deidentified_text, _ = deidentify(req.raw_text)
        ext = extract(deidentified_text)
        return evaluate_naranjo_causality(ext, deidentified_text)
    except Exception as exc:
        error_type = type(exc).__name__
    logger.error("Causality endpoint failed (error_type=%s).", error_type)
    raise HTTPException(status_code=500, detail="Causality assessment failed.")


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
