"""
Module 4 — LLM Extraction Engine with Terminology Coding (RxNorm + MedDRA).

Baseline implementation: keyword/regex extraction producing the fixed schema.
Enriches extractions with standardized regulatory ontologies (RxNorm CUI, MedDRA PT/LLT/SOC).
"""

import os
import re

try:
    from google import genai
    from pydantic import TypeAdapter
except ImportError:
    genai = None
    TypeAdapter = None

from app.schemas import ExtractionResult
from .terminology import code_drug_to_rxnorm, code_symptoms_to_meddra

# Comprehensive seed lexicon for pharmacovigilance intake
KNOWN_DRUGS = [
    "ibuprofen", "paracetamol", "acetaminophen", "amoxicillin", "metformin",
    "warfarin", "aspirin", "atorvastatin", "omeprazole", "losartan",
    "insulin", "prednisone", "sertraline", "amlodipine", "clopidogrel",
    "ciprofloxacin", "lisinopril", "penicillin", "levofloxacin", "enalapril", "naproxen"
]

SYMPTOM_KEYWORDS = [
    "rash", "nausea", "vomiting", "dizziness", "headache", "swelling",
    "anaphylaxis", "shortness of breath", "hives", "itching", "fever",
    "diarrhea", "chest pain", "seizure", "liver failure", "bleeding",
    "gastrointestinal bleeding", "acute kidney injury", "tendon rupture",
    "angioedema", "lactic acidosis", "rhabdomyolysis", "myalgia", "cough"
]

ROUTE_KEYWORDS = {"oral": "oral", "iv": "intravenous", "intravenous": "intravenous",
                   "subcutaneous": "subcutaneous", "topical": "topical", "im": "intramuscular"}

client = genai.Client() if (genai is not None and os.environ.get("GEMINI_API_KEY")) else None


def extract(text: str) -> dict:
    if client:
        try:
            prompt = f"Extract adverse drug reaction details from the following report. Return a JSON object strictly matching the schema.\n\nReport:\n{text}"
            response = client.models.generate_content(
                model='gemini-2.5-pro',
                contents=prompt,
                config={
                    'response_mime_type': 'application/json',
                    'response_schema': ExtractionResult,
                },
            )
            result = ExtractionResult.model_validate_json(response.text).model_dump()
            result["modelVersion"] = "gemini-2.5-pro-extraction"
            result["promptVersion"] = "v2"
            result["incomplete"] = not (result.get("drugName") and result.get("symptoms"))
            result["terminology"] = {
                "drug_rxnorm": code_drug_to_rxnorm(result.get("drugName")),
                "meddra_adverse_events": code_symptoms_to_meddra(result.get("symptoms", [])),
            }
            return result
        except Exception as e:
            print(f"LLM extraction failed: {e}. Falling back to baseline.")

    lower = text.lower()

    drug = next((d for d in KNOWN_DRUGS if d in lower), None)
    dosage_match = re.search(r"(\d+(?:\.\d+)?\s?(?:mg|mcg|g|ml|units))", lower)
    frequency_match = re.search(r"(once|twice|three times|four times)\s+(a|per)\s+(day|week)", lower)
    duration_match = re.search(r"for\s+(\d+\s+(?:day|days|week|weeks|month|months))", lower)
    age_match = re.search(r"(\d{1,3})[\s-]*year[s]?[\s-]*old", lower) or re.search(r"age[:\s]+(\d{1,3})", lower)
    gender_match = re.search(r"\b(male|female|man|woman)\b", lower)

    route = next((v for k, v in ROUTE_KEYWORDS.items() if re.search(rf"\b{k}\b", lower)), None)
    symptoms = [s for s in SYMPTOM_KEYWORDS if s in lower]

    result = {
        "drugName": drug,
        "genericName": drug,
        "brandName": None,
        "dosage": dosage_match.group(1) if dosage_match else None,
        "frequency": " ".join(frequency_match.groups()) if frequency_match else None,
        "route": route,
        "duration": duration_match.group(1) if duration_match else None,
        "symptoms": symptoms,
        "onsetTimeline": "within 2 hours" if "hour" in lower else ("within 5 days" if "day" in lower else None),
        "age": int(age_match.group(1)) if age_match else None,
        "gender": gender_match.group(1) if gender_match else None,
        "comorbidities": [],
        "concomitantDrugs": [],
        "modelVersion": "extraction-stub-0.2",
        "promptVersion": "v2",
    }
    # Flag rather than silently drop when core fields are missing
    result["incomplete"] = not (result["drugName"] and result["symptoms"])

    # Standardized regulatory terminology mapping
    result["terminology"] = {
        "drug_rxnorm": code_drug_to_rxnorm(result["drugName"]),
        "meddra_adverse_events": code_symptoms_to_meddra(result["symptoms"]),
    }

    return result
