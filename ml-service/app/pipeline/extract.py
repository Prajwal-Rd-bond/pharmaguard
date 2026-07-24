"""
Module 4 — LLM Extraction Engine.

Baseline implementation: keyword/regex extraction producing the fixed schema.
Production version should call an LLM (OpenAI / local Ollama running Llama 3 / Qwen / Mistral)
with a structured-output prompt and validate against ExtractionResult — see the TODO below.
"""

import re

# Minimal seed lexicon for the offline baseline. Extend or replace with a real drug database (e.g. RxNorm).
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


def extract(text: str) -> dict:
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
        "onsetTimeline": None,
        "age": int(age_match.group(1)) if age_match else None,
        "gender": gender_match.group(1) if gender_match else None,
        "comorbidities": [],
        "concomitantDrugs": [],
        "modelVersion": "extraction-stub-0.1",
        "promptVersion": "v1",
    }
    # Flag rather than silently drop when core fields are missing (Module 4 requirement).
    result["incomplete"] = not (result["drugName"] and result["symptoms"])

    # TODO(Phase 1 hardening): replace with an LLM call, e.g.:
    #   response = llm_client.extract(prompt=EXTRACTION_PROMPT.format(text=text))
    #   result = ExtractionResult.model_validate_json(response)
    return result
