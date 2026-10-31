from __future__ import annotations

from typing import Any, Dict, List, Optional
from pydantic import BaseModel, ConfigDict, Field


class PipelineRequest(BaseModel):
    pipeline_run_id: str
    raw_text: str
    receipt_date: Optional[str] = None
    unexpected: Optional[bool] = None
    reasonably_related: Optional[bool] = None


class DeidentificationLogEntry(BaseModel):
    type: str
    span: str


class TerminologyCoding(BaseModel):
    meddra_pt: Optional[str] = None
    meddra_soc: Optional[str] = None
    meddra_llt: Optional[str] = None
    rxnorm_cui: Optional[str] = None
    who_atc: Optional[str] = None


class ExtractionResult(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    drugName: Optional[str] = None
    genericName: Optional[str] = None
    brandName: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    route: Optional[str] = None
    duration: Optional[str] = None
    symptoms: List[str] = Field(default_factory=list)
    onsetTimeline: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    comorbidities: List[str] = Field(default_factory=list)
    concomitantDrugs: List[str] = Field(default_factory=list)
    terminology: Optional[Dict[str, Any]] = None
    incomplete: bool = False
    modelVersion: str = "extraction-stub-0.1"
    promptVersion: str = "v1"
    model_config = {"protected_namespaces": ()}


class ClassificationResult(BaseModel):
    model_config = ConfigDict(extra="allow", protected_namespaces=())

    severity: str  # mild | moderate | serious | life_threatening
    confidence: float
    model_name: str
    model_version: str
    ich_e2a_criteria: List[str] = Field(default_factory=list)  # death, life_threatening, hospitalization, disability, congenital_anomaly, medically_significant
    is_serious: bool = False
    regulatory_clock_days: int = 15  # 7-day fatal/life-threatening, 15-day serious, 90-day non-serious
    expedited_clock_label: Optional[str] = "none"  # expedited_7_day | expedited_15_day | none
    periodic_clock_days: Optional[int] = None


class CausalityAssessment(BaseModel):
    naranjo_score: int = 0
    naranjo_category: str = "Possible"  # Definite (>=9), Probable (5-8), Possible (1-4), Doubtful (<=0)
    naranjo_breakdown: Dict[str, int] = Field(default_factory=dict)
    who_umc_category: str = "Possible"  # Certain, Probable, Possible, Unlikely, Conditional, Unassessable
    rationale: str = ""


class RetrievalItem(BaseModel):
    source_collection: str
    source_id: str
    title: str
    snippet: str
    similarity_score: float
    evidence_id: Optional[str] = None
    corpus_origin: Optional[str] = None
    section: Optional[str] = None
    url: Optional[str] = None
    set_id: Optional[str] = None


class CitationCheckItem(BaseModel):
    claim: str
    status: str  # VERIFIED | PARTIAL | UNSUPPORTED
    grounding_score: float
    matched_source_id: Optional[str] = None
    matched_source_title: Optional[str] = None
    citation_index: Optional[int] = None


class CitationVerificationResult(BaseModel):
    overall_grounding_score: float = 1.0
    hallucination_detected: bool = False
    total_claims: int = 0
    verified_claims_count: int = 0
    claims: List[Dict[str, Any]] = Field(default_factory=list)
    grounded_summary: str = ""


class RejectedEvidenceRecord(BaseModel):
    source_id: str
    reason: str = "pii_rejected"


class EvidenceMetadata(BaseModel):
    evidence_status: str = "ok"
    rejected_records: List[RejectedEvidenceRecord] = Field(default_factory=list)


class PipelineResponse(BaseModel):
    pipeline_run_id: str
    deidentified_text: str
    deidentification_log: List[DeidentificationLogEntry]
    extraction: ExtractionResult
    classification: ClassificationResult
    retrievals: List[RetrievalItem]
    summary: str
    citation_verification: Optional[Dict[str, Any]] = None
    causality: Optional[Dict[str, Any]] = None
    normalized_drug: Optional[Dict[str, Any]] = None
    assessment: Optional[Dict[str, Any]] = None
    evidence_status: Optional[str] = "ok"
    rejected_records: List[RejectedEvidenceRecord] = Field(default_factory=list)
    evidence_metadata: Optional[EvidenceMetadata] = None
    assessment_status: Optional[str] = None
    assessment_error: Optional[str] = None
