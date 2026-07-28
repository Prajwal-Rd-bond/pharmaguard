"""
Module 4 — LLM Extraction Engine.

Calls a local Ollama model with a JSON-constrained prompt to extract the fixed ADR schema from
de-identified report text. Per Module 4's AC, malformed/incomplete extractions must be flagged,
not silently dropped: if Ollama is unreachable, times out, or returns something that doesn't
validate against ExtractionResult, we fall back to the keyword/regex baseline and mark the result
`incomplete` rather than failing the whole pipeline run.
"""

import json
import logging
import os
import re

import requests
from pydantic import ValidationError

from ..schemas import ExtractionResult

logger = logging.getLogger(__name__)

OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_TIMEOUT_SECONDS = float(os.getenv("OLLAMA_TIMEOUT_SECONDS", "60"))

LIST_FIELDS = ("symptoms", "comorbidities", "concomitantDrugs")

EXTRACTION_PROMPT = """You are a clinical data extraction assistant for a pharmacovigilance team.
Extract structured adverse drug reaction (ADR) data from the de-identified report text below.

Return ONLY a JSON object with exactly these fields. Use null for anything not stated in the
text — never guess or infer a value that isn't there.

{{
  "drugName": string or null,
  "genericName": string or null,
  "brandName": string or null (ONLY if a brand name distinct from the generic name is stated; otherwise null — do not repeat the generic name here),
  "dosage": string or null,
  "frequency": string or null,
  "route": string or null (one of: oral, intravenous, subcutaneous, topical, intramuscular),
  "duration": string or null,
  "symptoms": array of lowercase strings (adverse reaction symptoms only),
  "onsetTimeline": string or null,
  "age": integer or null,
  "gender": string or null ("male", "female", or null),
  "comorbidities": array of strings,
  "concomitantDrugs": array of strings
}}

Report text:
\"\"\"
{text}
\"\"\"

JSON:"""

# Baseline seed lexicon — used only as a fallback if the LLM call fails or returns invalid output.
KNOWN_DRUGS = [
    "ibuprofen", "paracetamol", "acetaminophen", "amoxicillin", "metformin",
    "warfarin", "aspirin", "atorvastatin", "omeprazole", "losartan",
    "insulin", "prednisone", "sertraline", "amlodipine", "clopidogrel",
]

SYMPTOM_KEYWORDS = [
    "rash", "nausea", "vomiting", "dizziness", "headache", "swelling",
    "anaphylaxis", "shortness of breath", "hives", "itching", "fever",
    "diarrhea", "chest pain", "seizure", "liver failure", "bleeding",
]

ROUTE_KEYWORDS = {"oral": "oral", "iv": "intravenous", "intravenous": "intravenous",
                   "subcutaneous": "subcutaneous", "topical": "topical", "im": "intramuscular"}


def _extract_baseline(text: str) -> dict:
    lower = text.lower()

    drug = next((d for d in KNOWN_DRUGS if d in lower), None)
    dosage_match = re.search(r"(\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|units))", lower)
    frequency_match = re.search(r"(once|twice|three times|four times)\s+(a|per)\s+(day|week)", lower)
    duration_match = re.search(r"for\s+(\d+\s+(?:day|days|week|weeks|month|months))", lower)
    age_match = re.search(r"(\d{1,3})[\s-]*year[s]?[\s-]*old", lower) or re.search(r"age[:\s]+(\d{1,3})", lower)
    gender_match = re.search(r"\b(male|female|man|woman)\b", lower)

    route = next((v for k, v in ROUTE_KEYWORDS.items() if re.search(rf"\b{k}\b", lower)), None)
    symptoms = [s for s in SYMPTOM_KEYWORDS if s in lower]

    return {
        "drugName": drug,
        "genericName": drug,
        "brandName": None,
        "dosage": dosage_match.group(1) if dosage_match else None,
        "frequency": " ".join(frequency_match.groups()) if frequency_match else None,
        "route": route,
        "duration": duration_match.group(1) if duration_match else None,
        "symptoms": symptoms,
        "onsetTimeline": None,
        "age": int(age_match.group(1)) if age_match else None,
        "gender": gender_match.group(1) if gender_match else None,
        "comorbidities": [],
        "concomitantDrugs": [],
    }


def _call_ollama(text: str) -> dict:
    response = requests.post(
        f"{OLLAMA_URL}/api/generate",
        json={
            "model": OLLAMA_MODEL,
            "prompt": EXTRACTION_PROMPT.format(text=text),
            "format": "json",
            "stream": False,
            "options": {"temperature": 0},
        },
        timeout=OLLAMA_TIMEOUT_SECONDS,
    )
    response.raise_for_status()
    raw = response.json()["response"]
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return json.loads(raw.strip().strip("`"))


def extract(text: str) -> dict:
    try:
        payload = _call_ollama(text)
        for field in LIST_FIELDS:
            if payload.get(field) is None:
                payload[field] = []

        validated = ExtractionResult.model_validate({
            **payload,
            "modelVersion": f"ollama:{OLLAMA_MODEL}",
            "promptVersion": "v1-llm",
        })
        result = validated.model_dump()
        result["incomplete"] = not (result["drugName"] and result["symptoms"])
        return result

    except (requests.RequestException, json.JSONDecodeError, ValidationError, KeyError) as exc:
        logger.warning("LLM extraction failed (%s), falling back to baseline extractor", exc)
        result = _extract_baseline(text)
        result["modelVersion"] = "extraction-fallback-baseline-0.1"
        result["promptVersion"] = "v1"
        result["incomplete"] = True  # always flagged: this path only runs when the LLM path failed
        return result
