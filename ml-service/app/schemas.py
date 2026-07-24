from typing import List, Optional
from pydantic import BaseModel


class PipelineRequest(BaseModel):
    pipeline_run_id: str
    raw_text: str


class DeidentificationLogEntry(BaseModel):
    type: str
    span: str


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
    incomplete: bool = False
    modelVersion: str = "extraction-stub-0.1"
    promptVersion: str = "v1"


class ClassificationResult(BaseModel):
    severity: str  # mild | moderate | serious | life_threatening
    confidence: float
    model_name: str
    model_version: str


class RetrievalItem(BaseModel):
    source_collection: str
    source_id: str
    title: str
    snippet: str
    similarity_score: float


class PipelineResponse(BaseModel):
    pipeline_run_id: str
    deidentified_text: str
    deidentification_log: List[DeidentificationLogEntry]
    extraction: ExtractionResult
    classification: ClassificationResult
    retrievals: List[RetrievalItem]
    summary: str
