from typing import List, Optional, Dict, Any

try:
    from pydantic import BaseModel
except ImportError:
    class BaseModel:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)
        def model_dump(self):
            return self.__dict__
        def dict(self):
            return self.__dict__


class PipelineRequest(BaseModel):
    pipeline_run_id: str
    raw_text: str


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
    drugName: Optional[str] = None
    genericName: Optional[str] = None
    brandName: Optional[str] = None
    dosage: Optional[str] = None
    frequency: Optional[str] = None
    route: Optional[str] = None
    duration: Optional[str] = None
    symptoms: List[str] = []
    onsetTimeline: Optional[str] = None
    age: Optional[int] = None
    gender: Optional[str] = None
    comorbidities: List[str] = []
    concomitantDrugs: List[str] = []
    terminology: Optional[Dict[str, Any]] = None
    incomplete: bool = False
    modelVersion: str = "extraction-stub-0.1"
    promptVersion: str = "v1"
    extractionMode: Optional[str] = "regex_baseline"
    model_config = {"protected_namespaces": ()}


class ClassificationResult(BaseModel):
    model_config = {"protected_namespaces": ()}
    severity: str  # mild | moderate | serious | life_threatening
    confidence: float
    model_name: str
    model_version: str
    model_type: Optional[str] = "clinical_safety_rules"  # clinical_safety_rules | experimental
    ich_e2a_criteria: List[str] = []  # death, life_threatening, hospitalization, disability, congenital_anomaly, medically_significant
    is_serious: bool = False
    regulatory_clock_days: int = 15  # 7-day fatal/life-threatening, 15-day serious, 90-day non-serious


class CausalityAssessment(BaseModel):
    naranjo_score: int = 0
    naranjo_category: str = "Possible"  # Definite (>=9), Probable (5-8), Possible (1-4), Doubtful (<=0)
    naranjo_breakdown: Dict[str, int] = {}
    who_umc_category: str = "Possible"  # Certain, Probable, Possible, Unlikely, Conditional, Unassessable
    rationale: str = ""


class RetrievalItem(BaseModel):
    source_collection: str
    source_id: str
    title: str
    snippet: str
    similarity_score: float


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
    claims: List[Dict[str, Any]] = []
    grounded_summary: str = ""


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
